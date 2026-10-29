"""Private FastAPI inventory API and a dependency-free French web interface."""

import hashlib
import hmac
import html
import io
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
import warnings
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .audience import Audience, counted
from .brand import SITE_NAME, site_slug, site_wordmark
from .condition_assessment import ConditionService, assessment_rows, read_condition
from .intake import IntakeService, catalogue_candidates, normalize_photo, read_photo
from .inventory import Conflict, Store, cents, now
from .inventory_backup import backup, export_csv, export_data, export_html
from .photo_processing import parse_guide
from .quote_ledger import select_transcription
from .market_product import MarketProducts, cached_set_code, fetch_tcgdex
from .pricing import (
    PriceService,
    binding_market_url,
    cardmarket_search_url,
    cardmarket_url,
    fetch_card,
    fetch_card_with_guide,
    fetch_catalogue_card,
)
from .cardmarket_guide import CardmarketGuide
from .listings import Listings, Storefront
from .privacy import Privacy
from .reservations import Reservations, valid_email
from .variant_catalogue import VariantCatalogue
from .catalogue_image import CatalogueImages
from .variant_pricing import category
from .edition_check import EditionCheckService, propose_edition
from .verification import (
    VariantCheckService,
    check_inputs,
    check_rows,
    propose_variant,
)

# A page's text, as written in the HTML: {{t:filters.title}}.
TEXT_KEY = re.compile(r"\{\{t:([\w.]+)\}\}")
# The storefront's languages: dictionary, <html lang> and home address. French is the
# reference; another language lives under its prefix (docs/decisions/0020).
LANGUAGES = {"fr": ("fr", "/"), "en": ("en-GB", "/en/")}
# The errors a storefront visitor can meet, by their French detail. The answer adds
# the code; the storefront shows web/messages' "error.<code>" in its own language.
ERROR_CODES = {
    "Origine interdite.": "origin_forbidden",
    "Trop de requêtes. Réessayez dans une minute.": "too_many_requests",
    "Trop d’inscriptions depuis cette adresse. Réessayez plus tard.": "too_many_signups",
    "Trop de demandes depuis cette adresse. Réessayez plus tard.": "too_many_guest_requests",
    "Trop de tentatives. Réessayez dans cinq minutes.": "too_many_attempts",
    "Connectez-vous pour consulter la collection.": "login_required",
    "Espace réservé aux comptes clients.": "clients_only",
    "Identifiants incorrects.": "wrong_credentials",
    "Compte en attente de validation.": "account_pending",
    "Mot de passe incorrect.": "wrong_password",
    "Adresse e-mail invalide.": "invalid_email",
    "Cette adresse est déjà utilisée par un autre compte.": "email_taken",
    "Ce lien n’est plus valable : demandez-en un autre au vendeur.": "link_expired",
    "La boutique n’est pas encore ouverte aux inscriptions.": "signup_closed",
    "La boutique n’est pas encore ouverte aux réservations.": "requests_closed",
    "Carte absente de la vitrine.": "card_not_found",
    "Choisissez des cartes distinctes.": "duplicate_cards",
    "Une carte n’est plus disponible : actualisez la vitrine.": "card_unavailable",
    "Trop de demandes en attente : attendez une réponse du vendeur.": "too_many_pending",
    "Demande introuvable.": "request_not_found",
    "La demande a changé. Actualisez la page.": "request_changed",
    "Seule une demande en attente peut être annulée.": "request_not_pending",
    "Format d’image indisponible.": "photo_format_unavailable",
}


def error_response(detail, status_code, headers=None):
    body = {"detail": detail}
    if detail in ERROR_CODES:
        body["code"] = ERROR_CODES[detail]
    return Response(
        json.dumps(body), status_code=status_code, headers=headers, media_type="application/json"
    )


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PhotoOptions(Model):
    crop: StrictBool = True
    balance: StrictBool = True
    perspective: StrictBool = True


class PhotoAttachment(Model):
    token: str = Field(min_length=20, max_length=100)
    expected_version: int = Field(ge=1)
    side: Literal["front", "back"] = "front"


class ConditionRequest(Model):
    expected_version: int = Field(ge=1)


class MarketVerdict(Model):
    expected_version: int = Field(ge=1)
    verdict: Literal["wrong", "verified", ""]
    reason: str = Field(min_length=1, max_length=1000)


class BoundQuote(Model):
    expected_version: int = Field(ge=1)
    metrics: dict[str, Decimal]
    observed_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    capture_sha256: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    reason: str = Field(min_length=1, max_length=1000)


class OffersPaste(Model):
    text: str = Field(min_length=1, max_length=200_000)


class ConditionConfirmation(ConditionRequest):
    condition: Literal["NM", "EX", "GD", "LP", "PL", "PO", "NM/EX"]
    human_confirmed: Literal[True]
    reason: str = Field(min_length=1, max_length=1000)


class VariantDecision(ConditionRequest):
    finish: Literal["non_holo", "holo", "holo_border", "reverse", "special"]
    stamp_state: Literal["unobserved", "absent", "present"]
    stamp: str = Field(default="", max_length=120)
    variant_confirmed: bool
    reason: str = Field(min_length=1, max_length=1000)


class KeepRecorded(ConditionRequest):
    reason: str = Field(min_length=1, max_length=1000)


class Credentials(Model):
    # E-mail addresses serve as client usernames, "+" included.
    username: str = Field(min_length=1, max_length=254, pattern=r"^[\w.@+-]+$")
    password: str = Field(min_length=10, max_length=256)


class UserCreate(Credentials):
    role: Literal["admin", "editor", "reader"] = "reader"


class UserPatch(Model):
    role: Literal["admin", "editor", "reader"]
    disabled: bool = False


class CardFields(Model):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    set_name: str | None = Field(default=None, max_length=256)
    number: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, pattern=r"^(?:[a-z]{2,3}|unknown)$")
    catalog_id: str | None = Field(default=None, max_length=120)
    hp: int | None = Field(default=None, ge=0, le=5000)
    identification_status: (
        Literal["confirmed", "review", "unresolved", "failed"] | None
    ) = None
    condition: Literal["", "NM", "EX", "GD", "LP", "PL", "PO", "NM/EX"] | None = None
    condition_confirmed: bool | None = None
    foil: bool | None = None
    finish: (
        Literal["", "non_holo", "holo", "holo_border", "reverse", "special"] | None
    ) = None
    variant_confirmed: bool | None = None
    variant_observation: str | None = Field(default=None, max_length=1000)
    stamp: str | None = Field(default=None, max_length=120)
    stamp_state: Literal["unobserved", "absent", "present"] | None = None
    distribution: str | None = Field(default=None, max_length=120)
    distribution_state: Literal["unobserved", "absent", "present"] | None = None
    album_id: str | None = Field(default=None, min_length=1, max_length=120)
    page: int | None = Field(default=None, ge=1, le=1000)
    position: int | None = Field(default=None, ge=1, le=100)
    notes: str | None = Field(default=None, max_length=8000)


class CardPatch(CardFields):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)
    reference_price_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    price_source: str | None = Field(default=None, max_length=256)


class CardCreate(CardFields):
    name: str = Field(min_length=1, max_length=256)
    album_id: str = Field(min_length=1, max_length=120)
    page: int = Field(ge=1, le=1000)
    position: int = Field(ge=1, le=100)
    set_name: str = Field(default="", max_length=256)
    number: str = Field(default="", max_length=80)
    language: str = Field(default="fr", pattern=r"^(?:[a-z]{2,3}|unknown)$")
    reason: str = Field(min_length=1, max_length=1000)
    duplicate_acknowledgments: list[str] = Field(default_factory=list, max_length=200)


class CopyRemoval(Model):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class ReferenceDispute(CopyRemoval):
    active: bool
    affects: Literal["print", "market", "both"] = "both"


class AlbumCreate(Model):
    name: str = Field(min_length=1, max_length=120)


class IntakeQuery(Model):
    name: str = Field(min_length=1, max_length=256)
    number: str = Field(default="", max_length=80)
    language: str = Field(default="unknown", pattern=r"^(?:[a-z]{2,3}|unknown)$")
    hp: int | None = Field(default=None, ge=0, le=5000)


class IntakeEntry(Model):
    """The entry as shown when a reading starts: fallback for unread fields."""

    name: str = Field(default="", max_length=256)
    number: str = Field(default="", max_length=80)
    language: str = Field(default="unknown", pattern=r"^(?:[a-z]{2,3}|unknown)$")
    hp: int | None = Field(default=None, ge=0, le=5000)


class IntakeSave(CardCreate):
    chosen_catalog_id: str | None = Field(default=None, max_length=120)
    human_confirmed: bool = False


class CaptureCreate(Model):
    album_id: str = Field(min_length=1, max_length=120)
    slots: int = Field(default=9, ge=1, le=100)
    page: int = Field(default=1, ge=1, le=1000)
    position: int = Field(default=1, ge=1, le=100)


class CaptureFields(CardFields):
    reason: str = Field(default="", max_length=1000)
    chosen_catalog_id: str | None = Field(default=None, max_length=120)
    human_confirmed: bool = False


class CapturePatch(Model):
    expected_version: int = Field(ge=1)
    page: int | None = Field(default=None, ge=1, le=1000)
    position: int | None = Field(default=None, ge=1, le=100)
    fields: CaptureFields | None = None
    front_token: str | None = Field(default=None, min_length=20, max_length=100)
    back_token: str | None = Field(default=None, min_length=20, max_length=100)
    status: Literal["active", "paused", "closed"] | None = None


class CaptureSave(IntakeSave):
    expected_version: int = Field(ge=1)
    token: str = Field(min_length=20, max_length=100)


class BatchCopy(Model):
    id: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)


class BatchPreview(Model):
    copies: list[BatchCopy] = Field(min_length=1, max_length=20)
    side: Literal["front", "back"] = "front"
    options: PhotoOptions = Field(default_factory=PhotoOptions)


class BatchApply(Model):
    copy_ids: list[str] = Field(min_length=1, max_length=20)


def intake_values(values):
    data = values.model_dump(
        exclude_unset=True,
        exclude={
            "expected_version",
            "token",
            "duplicate_acknowledgments",
            "chosen_catalog_id",
            "human_confirmed",
            "catalog_id",
            "identification_status",
            "condition",
            "condition_confirmed",
            "foil",
        },
    )
    if any(v is None and k != "hp" for k, v in data.items()):
        raise ValueError("Champ vide non autorisé.")
    for key in ("name", "number", "set_name", "language", "reason"):
        data[key] = getattr(values, key)
    return data


class Signup(Model):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=256)
    # Acknowledges the data notice; the legal basis is the reservation itself,
    # not consent. Its date stays in users.consent_at.
    consent: Literal[True]


class RequestCreate(Model):
    listing_ids: list[str] = Field(min_length=1, max_length=50)
    message: str = Field(default="", max_length=1000)


class GuestRequest(RequestCreate):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=80)
    # The same notice as at signup: the reservation itself is the legal basis.
    consent: Literal[True]


class PasswordSet(Model):
    token: str = Field(min_length=20, max_length=100)
    password: str = Field(min_length=10, max_length=256)


class RequestVersion(Model):
    expected_version: int = Field(ge=1)


class RequestAccept(RequestVersion):
    listing_ids: list[str] = Field(min_length=1, max_length=50)


class Profile(Model):
    display_name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class PasswordCheck(Model):
    password: str = Field(min_length=1, max_length=256)


class PaymentSettings(Model):
    # Each method is optional; an empty value means it is not offered.
    wero: str = Field("", max_length=254)
    iban: str = Field("", max_length=64)
    holder: str = Field("", max_length=70)
    paypal: str = Field("", max_length=254)


class ClientPatch(Model):
    status: Literal["active", "refused"]
    disabled: bool = False


class ListingPrice(Model):
    # Without a price, the copy takes its computed storefront price.
    price_eur: Decimal | None = Field(default=None, ge=0, le=10000000, decimal_places=2)


class ListingCreate(ListingPrice):
    copy_ids: list[str] = Field(min_length=1, max_length=401)
    lot: bool = False
    title: str = Field(default="", max_length=256)


class SaleCreate(Model):
    title: str = Field(min_length=1, max_length=256)
    copy_ids: list[str] = Field(min_length=1, max_length=401)
    amount_eur: Decimal = Field(ge=0, le=10000000, decimal_places=2)
    asking_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    target_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    minimum_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    channel: str = Field(default="", max_length=120)
    listing_url: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=8000)


class SalePatch(Model):
    expected_version: int = Field(ge=1)
    asking_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    target_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    minimum_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    reason: str = Field(min_length=1, max_length=1000)
    status: (
        Literal[
            "draft", "reserved", "sold", "shipped", "completed", "cancelled", "returned"
        ]
        | None
    ) = None
    amount_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    fees_eur: Decimal | None = Field(default=None, ge=0, le=10000000, decimal_places=2)
    shipping_charged_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    shipping_cost_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    packing_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    refund_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    paid: bool | None = None
    channel: str | None = Field(default=None, max_length=120)
    listing_url: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=8000)


# OWASP scrypt minimum in its low-memory form (16 MiB per hash, five passes):
# the small server stays usable when several logins arrive at once.
SCRYPT = {"n": 2**14, "r": 8, "p": 5}
# Bare "salt:key" hashes written before October 2026, upgraded at login.
LEGACY_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def scrypt_key(password, salt, n, r, p):
    return hashlib.scrypt(
        password.encode(), salt=salt, n=n, r=r, p=p, maxmem=256 * r * n, dklen=32
    )


def password_hash(password):
    salt = secrets.token_bytes(16)
    params = ",".join(f"{k}={v}" for k, v in SCRYPT.items())
    return f"scrypt${params}${salt.hex()}${scrypt_key(password, salt, **SCRYPT).hex()}"


def hash_parts(encoded):
    if "$" not in encoded:
        salt, key = encoded.split(":")
        return LEGACY_SCRYPT, salt, key
    algorithm, params, salt, key = encoded.split("$")
    if algorithm != "scrypt":
        raise ValueError("Format de mot de passe inconnu.")
    cost = {k: int(v) for k, v in (item.split("=") for item in params.split(","))}
    return cost, salt, key


def password_valid(password, encoded):
    params, salt, key = hash_parts(encoded)
    actual = scrypt_key(password, bytes.fromhex(salt), **params)
    return hmac.compare_digest(actual, bytes.fromhex(key))


def password_outdated(encoded):
    return hash_parts(encoded)[0] != SCRYPT


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "testserver"}


def has_admin(db):
    return bool(db.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone())


def add_user(db, values):
    import uuid

    user = {"id": str(uuid.uuid4()), "username": values.username, "role": values.role}
    db.execute(
        "INSERT INTO users(id,username,password_hash,role,created_at) VALUES(?,?,?,?,?)",
        (
            user["id"],
            user["username"],
            password_hash(values.password),
            user["role"],
            now(),
        ),
    )
    return user


def create_app(
    directory="data/inventory",
    *,
    secure_cookie=False,
    allowed_hosts=None,
    public_origin=None,
    intake_reader=None,
    intake_lookup=None,
    condition_reader=None,
    variant_reader=None,
    edition_reader=None,
    edition_get_json=None,
    edition_fetch=None,
    auto_checks=False,
    price_fetch=None,
    variant_fetch=None,
    market_fetch=None,
    agent_enabled=True,
):
    # Preview URLs come from explicit deployment configuration, never Host or forwarding headers.
    public_origin = os.environ.get("POKEPRICE_PUBLIC_ORIGIN", "") if public_origin is None else public_origin
    public_origin = public_origin.strip()
    if public_origin:
        origin = urlsplit(public_origin)
        try:
            origin.port  # Reject malformed ports before serving any public metadata.
        except ValueError as exc:
            raise ValueError("Origine publique invalide.") from exc
        if (
            not origin.hostname or origin.username is not None or origin.password is not None
            or origin.path not in ("", "/") or origin.query or origin.fragment
            or any(c.isspace() or ord(c) < 32 or c in "?#\\" for c in public_origin)
            or (origin.scheme != "https" and not (
                origin.scheme == "http" and origin.hostname in {"localhost", "127.0.0.1", "::1", "testserver"}
            ))
        ):
            raise ValueError("L’origine publique est une URL HTTPS sans chemin, identifiants ni paramètres.")
        public_origin = public_origin.rstrip("/")
    store = Store(directory)
    allowed_hosts = allowed_hosts or ["127.0.0.1", "localhost", "testserver"]
    # Web setup is for a private first run: once others can reach the server,
    # the first visitor must not become admin, so the admin is made locally.
    exposed = secure_cookie or set(allowed_hosts) - LOCAL_HOSTS
    if exposed:
        with store.connect() as db:
            if not db.execute(
                "SELECT 1 FROM users WHERE role='admin' AND disabled=0 LIMIT 1"
            ).fetchone():
                raise ValueError(
                    "Créez un administrateur local (commande user) avant le "
                    "démarrage HTTPS ou l’ouverture au réseau."
                )
    app = FastAPI(
        title="Poképrice — collection privée",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store
    intake = IntakeService(
        store, intake_reader or read_photo, intake_lookup or catalogue_candidates
    )
    app.state.intake = intake
    conditions = ConditionService(store, condition_reader or read_condition)
    app.state.conditions = conditions
    variant_checks = VariantCheckService(store, variant_reader)
    app.state.variant_checks = variant_checks
    edition_checks = EditionCheckService(
        store, edition_reader, edition_get_json, edition_fetch
    )
    app.state.edition_checks = edition_checks
    # An injected price source (tests) never reaches TCGdex for neighbours.
    market = MarketProducts(
        store, market_fetch or (fetch_tcgdex if price_fetch is None else None)
    )
    app.state.market = market
    # Tests inject their source; the app completes TCGdex with Cardmarket's guide.
    pricing = PriceService(
        store,
        price_fetch
        or fetch_card_with_guide(CardmarketGuide(store.root / "cardmarket", store)),
        market,
    )
    app.state.pricing = pricing
    variant_catalogue = VariantCatalogue(
        store,
        variant_fetch
        or (
            lambda *args: (
                pricing.fetch(*args) if price_fetch else fetch_catalogue_card(*args)
            )
        ),
    )
    app.state.variant_catalogue = variant_catalogue
    catalogue_images = CatalogueImages(store, variant_catalogue.fetch)
    # The public name, plus loopback: commands run on the server itself (the agent
    # client's default URL) reach the app without going out through Caddy.
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(dict.fromkeys([*allowed_hosts, "127.0.0.1", "localhost"])),
    )
    static = Path(__file__).with_name("web")

    small, large = site_wordmark()
    wordmark = (f"<span>{html.escape(small)}</span>" if small else "") + f"<em>{html.escape(large)}</em>"

    # The interface texts, one dictionary per language (docs/decisions/0020).
    dictionaries = {
        code: json.loads(static.joinpath("messages", f"{code}.json").read_text())
        for code in LANGUAGES
    }

    def public_head(language, rest, listing=None):
        words = dictionaries[language]
        generic_title = f"{SITE_NAME} · {words['meta.title']}"
        title = generic_title
        description = words.get("meta.description", words["hero.intro"])
        image = None
        first = None
        if listing:
            first = listing["items"][0]
            name = listing["title"] or first["name"]
            title = f"{name} · {SITE_NAME}"
            price = f"{listing['price_cents'] / 100:,.2f}"
            price = price.replace(",", "\u202f").replace(".", ",") + "\u00a0€" if language == "fr" else "€" + price
            fields = {
                "name": first["name"], "title": name, "extension": first["set_name"],
                "number": first["number"], "price": price, "count": len(listing["items"]),
                "condition": words["item.condition"].format(condition=first["condition"])
                if first["condition"] else words["item.condition_unconfirmed"],
            }
            template = words["share.lot_description"] if len(listing["items"]) > 1 else words["share.card_description"]
            description = template.format(**fields)
            photo = first.get("media", {}).get("front")
            if photo:
                variants = [v for v in photo["variants"] if v["format"] == "jpeg"]
                # A public consultation derivative, never the private capture original.
                if variants:
                    image = max(variants, key=lambda v: v["width"] * v["height"])

        def tag(key, value, *, property=False):
            attr = "property" if property else "name"
            return f'<meta {attr}="{key}" content="{html.escape(str(value), quote=True)}" />'

        tags = [tag("description", description), tag("og:type", "website", property=True),
                tag("og:site_name", SITE_NAME, property=True), tag("og:title", title, property=True),
                tag("og:description", description, property=True), tag("twitter:card", "summary"),
                tag("twitter:title", title), tag("twitter:description", description)]
        if public_origin:
            tags.append(tag("og:url", public_origin + LANGUAGES[language][1] + rest, property=True))
            if image:
                image_url = public_origin + image["url"]
                alt = words.get("share.image_alt", "{name}").format(name=first["name"])
                tags.extend([
                    tag("og:image", image_url, property=True), tag("og:image:type", "image/jpeg", property=True),
                    tag("og:image:width", image["width"], property=True),
                    tag("og:image:height", image["height"], property=True),
                    tag("og:image:alt", alt, property=True), tag("twitter:image", image_url),
                    tag("twitter:image:alt", alt),
                ])
        return generic_title, title, "\n    ".join(tags)

    def page(name: str, language: str = "fr", rest: str = "", *, listing=None) -> str:
        """A page as served: its texts come from the dictionary, the site's name from `brand`.

        `rest` is the address after the language's home, so the link to the other
        language leads to the same card.
        """
        words = dictionaries[language]
        lang, home = LANGUAGES[language]
        other = words["footer.language.code"]

        def word(match: re.Match) -> str:
            # A key ending in _html is trusted markup from the dictionary; the rest is text.
            key = match.group(1)
            return words[key] if key.endswith("_html") else html.escape(words[key])

        # A data block, not a script: the CSP lets it through, and "<" cannot close it.
        block = (
            '<script id="messages" type="application/json">'
            + json.dumps(words, ensure_ascii=False).replace("<", "\\u003c")
            + "</script>"
        )
        rendered = (
            TEXT_KEY.sub(word, static.joinpath(name).read_text())
            .replace("{{lang}}", lang)
            .replace("{{home}}", home)
            .replace("{{other_home}}", LANGUAGES[other][1])
            .replace("{{other_page}}", html.escape(LANGUAGES[other][1] + rest))
            .replace("{{messages}}", block)
            .replace("{{site_name}}", html.escape(SITE_NAME))
            .replace("{{site_wordmark}}", wordmark)
        )
        if name == "storefront.html":
            generic, title, metadata = public_head(language, rest if listing else "", listing)
            rendered = re.sub(r"<title>.*?</title>", lambda _: f"<title>{html.escape(title)}</title>", rendered, count=1)
            rendered = re.sub(r"(<html\b[^>]*)(>)", lambda match:
                              match[1] + f' data-page-title="{html.escape(generic, quote=True)}">', rendered, count=1)
            rendered = rendered.replace("</head>", metadata + "\n  </head>", 1)
        return rendered

    failures = {}
    login_lock = threading.Lock()
    dummy_hash = password_hash("not-a-valid-user-password")

    @app.middleware("http")
    async def protect(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            base = urlsplit(str(request.base_url))
            if origin and origin != f"{base.scheme}://{base.netloc}":
                return error_response("Origine interdite.", 403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return error_response("Origine interdite.", 403)
        if (
            request.method == "GET"
            and request.url.path == "/api/copies"
            and "text/html" in request.headers.get("accept", "")
            and request.headers.get("sec-fetch-dest", "") in ("", "document")
        ):
            response = RedirectResponse("/gestion?" + request.url.query, status_code=303)
        else:
            response = await call_next(request)
        if secure_cookie:
            # Behind HTTPS only: browsers then refuse plain HTTP for a year.
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path.startswith(("/gestion", "/api/")):
            # The seller's login and data never belong in a search engine.
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        cache_policy = "no-store"
        if response.status_code in (200, 304):
            if request.url.path == "/favicon.ico":
                cache_policy = "public, max-age=86400"
            elif request.url.path.startswith("/assets/"):
                cache_policy = "public, no-cache"
        response.headers["Cache-Control"] = cache_policy
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://assets.tcgdex.net; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(HTTPException)
    async def refused(request, exc):
        if isinstance(exc.detail, str):
            return error_response(exc.detail, exc.status_code, exc.headers)
        return await http_exception_handler(request, exc)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return error_response(str(exc), 409)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return error_response(str(exc.args[0]), 404)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return error_response(str(exc), 422)

    def current_user(request: Request):
        token = request.cookies.get("pokeprice_session", "")
        hashed = hashlib.sha256(token.encode()).hexdigest()
        with store.connect() as db:
            row = db.execute(
                "SELECT u.id,u.username,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.disabled=0 AND u.status='active'",
                (hashed, int(time.time())),
            ).fetchone()
        if not row:
            raise HTTPException(401, "Connectez-vous pour consulter la collection.")
        return dict(row)

    def staff(user=Depends(current_user)):
        # Storefront clients never reach the management routes, even read-only ones.
        if user["role"] not in ("admin", "editor", "reader"):
            raise HTTPException(403, "Ce compte n'a pas accès à la gestion.")
        return user

    def client(user=Depends(current_user)):
        if user["role"] != "client":
            raise HTTPException(403, "Espace réservé aux comptes clients.")
        return user

    def editor(user=Depends(staff)):
        if user["role"] not in ("admin", "editor"):
            raise HTTPException(403, "Ce compte permet uniquement la consultation.")
        return user

    def admin(user=Depends(staff)):
        if user["role"] != "admin":
            raise HTTPException(403, "Administration requise.")
        return user

    def issue_session(db, user, response):
        token = secrets.token_urlsafe(32)
        db.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?)",
            (
                hashlib.sha256(token.encode()).hexdigest(),
                user["id"],
                int(time.time()) + 43200,
            ),
        )
        response.set_cookie(
            "pokeprice_session",
            token,
            max_age=43200,
            httponly=True,
            secure=secure_cookie,
            samesite="strict",
            path="/",
        )

    audience = Audience(store.root, allowed_hosts)

    def count_visit(request, kind, key):
        """Count a storefront visit; the seller's team is not an audience."""
        headers = request.headers
        if request.method != "GET" or not counted(headers.get("user-agent", ""), headers):
            return
        if request.cookies.get("pokeprice_session"):
            try:
                if current_user(request)["role"] != "client":
                    return
            except HTTPException:
                pass
        try:
            audience.record(
                kind, key, request.client.host if request.client else "local",
                headers["user-agent"], headers.get("referer", ""),
            )
        except sqlite3.Error as error:
            # A lost count never costs a visitor the page, but it shows in the journal.
            logging.getLogger("uvicorn.error").warning("Visite non comptée : %s", error)

    # The public storefront is the home page; management lives at /gestion.
    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        if request.url.query:
            # Former management links (/?view=sales, filters) keep working.
            return RedirectResponse("/gestion?" + request.url.query, status_code=301)
        count_visit(request, "page", "accueil")
        return page("storefront.html")

    @app.get("/en", include_in_schema=False)
    def home_en_slash():
        return RedirectResponse("/en/", status_code=301)

    # The same storefront in English; the visit counts with the French one.
    @app.get("/en/", response_class=HTMLResponse)
    def home_en(request: Request):
        count_visit(request, "page", "accueil")
        return page("storefront.html", "en")

    # The seller's contact comes from the server's environment, never from the
    # public repository.
    contact_email = os.environ.get("POKEPRICE_CONTACT_EMAIL", "").strip()
    if not re.fullmatch(r"[^@\s<>\"']+@[^@\s<>\"']+\.[a-z]{2,}", contact_email, re.I):
        contact_email = ""
    # The data controller, a private individual, is named by the server too.
    controller_name = os.environ.get("POKEPRICE_CONTROLLER_NAME", "").strip()[:120]

    @app.get("/a-propos", response_class=HTMLResponse)
    def about(request: Request):
        count_visit(request, "page", "a-propos")
        return about_page("fr")

    # The English page translates the French one, which prevails.
    @app.get("/en/a-propos", response_class=HTMLResponse)
    def about_en(request: Request):
        count_visit(request, "page", "a-propos")
        return about_page("en")

    def about_page(language):
        en = language == "en"
        contact = (
            f'<a href="mailto:{html.escape(contact_email)}">{html.escape(contact_email)}</a>'
            if contact_email
            else "The contact address will be given here soon." if en
            else "L’adresse de contact sera bientôt indiquée ici."
        )
        who = html.escape(controller_name) if controller_name else ""
        if en:
            controller = (
                f"Data controller: {who or 'the seller'}, as a private individual, "
                "reachable at the contact address below."
            )
        else:
            controller = (
                f"Responsable du traitement : {who or 'le vendeur'}, à titre "
                "personnel, joignable à l’adresse de contact ci-dessous."
            )
        if en:
            methods = reservations.payment_methods(
                {"wero": "Wero", "iban": "bank transfer", "paypal": "PayPal (goods and services)"}
            )
            payment = (
                "Payment by " + ", ".join(methods[:-1]) + (" or " if len(methods) > 1 else "")
                + methods[-1] + ": the seller sends you the amount, the lot’s reference "
                "and their payment details by email; with an account, you also find "
                "them in “My requests” while the lot awaits payment."
                if methods
                else "The seller tells you in their reply how to pay."
            )
        else:
            methods = reservations.payment_methods()
            payment = (
                "Paiement par " + ", ".join(methods[:-1]) + (" ou " if len(methods) > 1 else "")
                + methods[-1] + " : le vendeur vous envoie le montant, la référence du lot "
                "et ses coordonnées par e-mail ; avec un compte, vous les retrouvez aussi "
                "dans « Mes demandes » tant que le lot attend son paiement."
                if methods
                else "Le vendeur vous indique dans sa réponse comment payer."
            )
        return (
            page("about.en.html" if en else "about.html", language)
            .replace("{{contact}}", contact)
            .replace("{{controller}}", controller)
            .replace("{{payment}}", html.escape(payment))
        )

    @app.get("/gestion", response_class=HTMLResponse)
    def index():
        return page("index.html")

    @app.get("/assets/{name}")
    def assets(
        request: Request,
        name: Literal[
            "app.js", "media.js", "workflows.js", "gallery.js", "style.css",
            "storefront.js", "storefront.css", "themes.css", "components.js",
            "photo-zoom.js", "photo-zoom.css",
            "logo.png", "apple-touch-icon.png", "mascotte.png",
        ],
    ):
        path = static / name
        etag = '"' + hashlib.sha256(path.read_bytes()).hexdigest() + '"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return FileResponse(path, headers={"ETag": etag})

    # Browsers ask for /favicon.ico on their own, before reading any page.
    @app.get("/favicon.ico", include_in_schema=False)
    def favicon(request: Request):
        path = static / "favicon.ico"
        etag = '"' + hashlib.sha256(path.read_bytes()).hexdigest() + '"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return FileResponse(path, media_type="image/x-icon", headers={"ETag": etag})

    storefront = Storefront(store)
    public_hits = {}
    public_lock = threading.Lock()

    def public_rate(request: Request):
        """Anonymous storefront reads: at most 300 requests a minute per address."""
        host = request.client.host if request.client else "local"
        key = (host, "photo" if request.url.path.endswith("/photo") else "api")
        timestamp = time.monotonic()
        with public_lock:
            recent = [t for t in public_hits.get(key, []) if timestamp - t < 60]
            if len(recent) >= 300:
                raise HTTPException(429, "Trop de requêtes. Réessayez dans une minute.", headers={"Retry-After": "60"})
            public_hits[key] = recent + [timestamp]
            if len(public_hits) > 10000:  # Forget idle addresses.
                for address in [a for a, hits in public_hits.items() if timestamp - hits[-1] >= 60]:
                    del public_hits[address]

    @app.get("/vitrine")
    def storefront_page():
        return RedirectResponse("/", status_code=301)

    # A card's own address, to share it: the storefront opens on its fiche.
    @app.get("/carte/{listing_id}", response_class=HTMLResponse)
    def card_page(listing_id: str, request: Request, _=Depends(public_rate)):
        return card(listing_id, request, "fr")

    @app.get("/en/carte/{listing_id}", response_class=HTMLResponse)
    def card_page_en(listing_id: str, request: Request, _=Depends(public_rate)):
        return card(listing_id, request, "en")

    def card(listing_id, request, language):
        try:
            listing = storefront.get(listing_id)
        except KeyError:
            # The page still loads and says the card is no longer for sale.
            return HTMLResponse(page("storefront.html", language, "carte/" + quote(listing_id, safe="")), status_code=404)
        count_visit(request, "page", "carte")
        return page("storefront.html", language, "carte/" + quote(listing_id, safe=""), listing=listing)

    @app.get("/api/public/listings")
    def public_listings(
        q: str = Query(default="", max_length=200),
        language: str = Query(default="", pattern=r"^(?:[a-z]{2,3})?$"),
        extension: str = Query(default="", max_length=200),
        finish: Literal["", "non_holo", "holo", "holo_border", "reverse", "special"] = "",
        condition: Literal["", "MT", "NM", "NM/EX", "EX", "GD", "LP", "PL", "PO", "unknown"] = "",
        max_eur: Decimal | None = Query(default=None, ge=0, le=10000000),
        sort: Literal["recent", "price", "price_desc", "name"] = "recent",
        limit: int = Query(default=48, ge=1, le=96),
        offset: int = Query(default=0, ge=0, le=100000),
        _=Depends(public_rate),
    ):
        return storefront.search(
            q, language, cents(max_eur), sort, limit, offset,
            extension=extension, finish=finish, condition=condition,
        )

    reservations = Reservations(store, storefront)
    signups = {}

    @app.post("/api/public/signup", status_code=202)
    def signup(values: Signup, request: Request, _=Depends(public_rate)):
        key = request.client.host if request.client else "local"
        timestamp = time.monotonic()
        with public_lock:
            recent = [t for t in signups.get(key, []) if timestamp - t < 3600]
            if len(recent) >= 5:
                raise HTTPException(429, "Trop d’inscriptions depuis cette adresse. Réessayez plus tard.")
            signups[key] = recent + [timestamp]
        # Same answer and same hashing cost whether the address is known or not.
        reservations.signup(values.email, values.display_name, password_hash(values.password))
        return {
            "detail": "Inscription enregistrée. Le vendeur valide chaque compte : "
            "vous pourrez vous connecter une fois le vôtre activé."
        }

    guests = {}

    @app.post("/api/public/requests", status_code=202)
    def guest_request(values: GuestRequest, request: Request, _=Depends(public_rate)):
        key = request.client.host if request.client else "local"
        timestamp = time.monotonic()
        with public_lock:
            recent = [t for t in guests.get(key, []) if timestamp - t < 3600]
            if len(recent) >= 5:
                raise HTTPException(429, "Trop de demandes depuis cette adresse. Réessayez plus tard.")
            guests[key] = recent + [timestamp]
        # Hashed whether or not the address is known: the delay tells nothing either.
        unusable = password_hash(secrets.token_urlsafe(32))
        reservations.guest(
            values.email, values.display_name, values.listing_ids, values.message, unusable
        )
        return {
            "detail": "Demande envoyée. Rien n’est bloqué tant que le vendeur ne l’a pas "
            f"acceptée : il vous répond à {values.email.strip()} pour le paiement et l’envoi."
        }

    @app.post("/api/public/password")
    def password_set(values: PasswordSet, response: Response, _=Depends(public_rate)):
        hashed = password_hash(values.password)
        with store.connect(write=True) as db:
            user = reservations.use_link(db, values.token, hashed)
            issue_session(db, user, response)
        return {"ok": True}

    @app.get("/api/me")
    def me(user=Depends(client)):
        with store.connect() as db:
            row = db.execute(
                "SELECT email,display_name FROM users WHERE id=?", (user["id"],)
            ).fetchone()
        return dict(row)

    def own_password(db, user, password):
        """Changing or deleting one's account asks for the password again."""
        row = db.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
        if not password_valid(password, row["password_hash"]):
            raise HTTPException(403, "Mot de passe incorrect.")

    @app.patch("/api/me")
    def me_update(values: Profile, user=Depends(client)):
        email = valid_email(values.email)
        with store.connect(write=True) as db:
            own_password(db, user, values.password)
            taken = db.execute(
                "SELECT 1 FROM users WHERE (email=? OR username=?) AND id<>?",
                (email, email, user["id"]),
            ).fetchone()
            if taken:
                raise Conflict("Cette adresse est déjà utilisée par un autre compte.")
            # The e-mail is also the login name.
            db.execute(
                "UPDATE users SET email=?,username=?,display_name=? WHERE id=?",
                (email, email, values.display_name.strip(), user["id"]),
            )
            row = db.execute(
                "SELECT email,display_name FROM users WHERE id=?", (user["id"],)
            ).fetchone()
        return dict(row)

    @app.get("/api/me/export")
    def me_export(user=Depends(client)):
        """Everything kept about the client, in a portable format (articles 15 and 20)."""
        with store.connect() as db:
            account = dict(
                db.execute(
                    "SELECT email,display_name,status,created_at,consent_at FROM users WHERE id=?",
                    (user["id"],),
                ).fetchone()
            )
        body = {"exported_at": now(), "account": account, "requests": reservations.mine(user["id"])}
        return Response(
            json.dumps(body, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{site_slug()}-mes-donnees.json"'},
        )

    @app.post("/api/me/delete")
    def me_delete(values: PasswordCheck, response: Response, user=Depends(client)):
        with store.connect() as db:
            own_password(db, user, values.password)
        Privacy(store).forget(user["id"], "Suppression par la personne")
        response.delete_cookie("pokeprice_session", path="/")
        return {"ok": True}

    @app.get("/api/me/requests")
    def my_requests(user=Depends(client)):
        return reservations.mine(user["id"])

    @app.post("/api/me/requests", status_code=201)
    def request_create(values: RequestCreate, user=Depends(client)):
        return reservations.create(user["id"], values.listing_ids, values.message)

    @app.post("/api/me/requests/{request_id}/cancel")
    def request_cancel(request_id: str, values: RequestVersion, user=Depends(client)):
        return reservations.cancel(user["id"], request_id, values.expected_version)

    @app.get("/api/clients")
    def client_index(user=Depends(admin)):
        return reservations.clients()

    @app.patch("/api/clients/{client_id}")
    def client_patch(client_id: str, values: ClientPatch, user=Depends(admin)):
        return reservations.set_client(client_id, values.status, values.disabled)

    @app.post("/api/clients/{client_id}/password-link", status_code=201)
    def client_password_link(client_id: str, user=Depends(admin)):
        return reservations.password_link(client_id, user["username"])

    @app.get("/api/settings/payment")
    def payment_settings(user=Depends(admin)):
        return reservations.payment()

    @app.put("/api/settings/payment")
    def payment_update(values: PaymentSettings, user=Depends(admin)):
        return reservations.set_payment(values.model_dump(), user["username"])

    @app.get("/api/requests")
    def request_index(user=Depends(staff)):
        return reservations.all()

    @app.post("/api/requests/{request_id}/accept")
    def request_accept(request_id: str, values: RequestAccept, user=Depends(editor)):
        return reservations.accept(
            request_id, values.expected_version, values.listing_ids, user["username"]
        )

    @app.post("/api/requests/{request_id}/refuse")
    def request_refuse(request_id: str, values: CopyRemoval, user=Depends(editor)):
        return reservations.refuse(
            request_id, values.expected_version, user["username"], values.reason
        )

    @app.get("/api/public/listings/{listing_id}")
    def public_listing(listing_id: str, request: Request, view: bool = False, _=Depends(public_rate)):
        listing = storefront.get(listing_id)
        if view:
            count_visit(request, "listing", listing_id)
        return listing

    @app.get("/api/public/listings/{listing_id}/photo")
    def public_photo(
        listing_id: str,
        item: int = Query(default=0, ge=0, le=500),
        side: Literal["front", "back"] = "front",
        size: Literal["full", "thumb", "grid2", "grid3", "view", "view2"] = "thumb",
        format: Literal["jpeg", "webp"] = "jpeg",
        request: Request = None,
        _=Depends(public_rate),
    ):
        try:
            if size in ("full", "thumb"):
                if format != "jpeg":
                    raise HTTPException(422, "Format d’image indisponible.")
                path = storefront.photo(listing_id, item, side, size)
            else:
                # Availability is checked before even considering an already generated derivative.
                source = storefront.photo(listing_id, item, side, "full")
                if format not in storefront.media.formats:
                    raise HTTPException(422, "Format d’image indisponible.")
                path = storefront.media.render(source, size, format)
        except OSError as exc:
            raise KeyError("Photo absente.") from exc
        if not path.is_file():
            raise KeyError("Photo absente.")
        return FileResponse(path, media_type="image/webp" if format == "webp" else "image/jpeg")

    @app.get("/api/audience")
    def audience_report(
        days: int = Query(default=30, ge=7, le=365), user=Depends(admin)
    ):
        report = audience.report(days)
        for row in report["listings"]:
            try:
                listing = storefront.get(row["id"])
                row["title"] = listing["title"] or " · ".join(
                    i["name"] for i in listing["items"]
                )
            except KeyError:
                row["title"] = ""  # Sold or withdrawn since.
        start = report["from"]
        with store.connect() as db:
            report["signups"] = db.execute(
                "SELECT COUNT(*) FROM users WHERE role='client' AND created_at>=?", (start,)
            ).fetchone()[0]
            report["requests"] = db.execute(
                "SELECT COUNT(*) FROM requests WHERE created_at>=?", (start,)
            ).fetchone()[0]
        return report

    @app.get("/api/setup")
    def setup_state():
        with store.connect() as db:
            return {"required": not has_admin(db)}

    @app.get("/health")
    def health():
        with store.connect() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.post("/api/setup")
    def setup(values: Credentials, response: Response):
        with store.connect(write=True) as db:
            # Client sign-ups do not count: only an admin closes the setup.
            if has_admin(db):
                raise Conflict("Le compte initial existe déjà.")
            user = add_user(db, UserCreate(**values.model_dump(), role="admin"))
            issue_session(db, user, response)
            return user

    @app.post("/api/login")
    def login(values: Credentials, request: Request, response: Response):
        key = request.client.host if request.client else "local"
        target = values.username.casefold()
        timestamp = time.monotonic()
        with login_lock:
            attempts = [a for a in failures.get(key, []) if timestamp - a[0] < 300]
            if len(attempts) >= 5:
                raise HTTPException(
                    429, "Trop de tentatives. Réessayez dans cinq minutes."
                )
            # Reserve the attempt before hashing to account for simultaneous requests.
            failures[key] = attempts + [(timestamp, target)]
        with store.connect(write=True) as db:
            row = db.execute(
                "SELECT * FROM users WHERE username=?", (values.username,)
            ).fetchone()
            valid = password_valid(
                values.password, row["password_hash"] if row else dummy_hash
            )
            if not valid or not row or row["disabled"] or row["status"] == "refused":
                raise HTTPException(401, "Identifiants incorrects.")
            if row["status"] == "pending":
                # Only said after a correct password: it reveals nothing to a guesser.
                raise HTTPException(403, "Compte en attente de validation.")
            if password_outdated(row["password_hash"]):
                # The password is only known here: strengthen old hashes as owners log in.
                db.execute(
                    "UPDATE users SET password_hash=? WHERE id=?",
                    (password_hash(values.password), row["id"]),
                )
            user = {k: row[k] for k in ("id", "username", "role")}
            issue_session(db, user, response)
        with login_lock:
            # Forgive only this account's typos: logging into one's own account
            # must not reset guesses aimed at another one from the same address.
            remaining = [a for a in failures.get(key, []) if a[1] != target]
            if remaining:
                failures[key] = remaining
            else:
                failures.pop(key, None)
        return user

    @app.get("/api/session")
    def session(user=Depends(current_user)):
        return user

    @app.post("/api/logout")
    def logout(request: Request, response: Response, user=Depends(current_user)):
        with store.connect(write=True) as db:
            db.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (
                    hashlib.sha256(
                        request.cookies["pokeprice_session"].encode()
                    ).hexdigest(),
                ),
            )
        response.delete_cookie("pokeprice_session", path="/")
        return {"ok": True}

    @app.get("/api/users")
    def users(user=Depends(admin)):
        with store.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    # Storefront clients have their own screen (/api/clients).
                    "SELECT id,username,role,disabled,created_at FROM users WHERE role!='client' ORDER BY username"
                )
            ]

    @app.post("/api/users", status_code=201)
    def user_create(values: UserCreate, user=Depends(admin)):
        with store.connect(write=True) as db:
            try:
                return add_user(db, values)
            except sqlite3.IntegrityError:
                raise Conflict("Ce compte existe déjà.")

    @app.patch("/api/users/{user_id}")
    def user_patch(user_id: str, values: UserPatch, user=Depends(admin)):
        with store.connect(write=True) as db:
            row = db.execute(
                "SELECT * FROM users WHERE id=? AND role!='client'", (user_id,)
            ).fetchone()
            if not row:
                raise KeyError("Compte introuvable.")
            if (
                row["role"] == "admin"
                and not row["disabled"]
                and (values.role != "admin" or values.disabled)
            ):
                count = db.execute(
                    "SELECT COUNT(*) FROM users WHERE role='admin' AND disabled=0"
                ).fetchone()[0]
                if count <= 1:
                    raise Conflict("Conservez au moins un administrateur actif.")
            db.execute(
                "UPDATE users SET role=?,disabled=? WHERE id=?",
                (values.role, values.disabled, user_id),
            )
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        return {"ok": True}

    @app.get("/api/summary")
    def summary(
        threshold: float = Query(default=10, ge=0.01, le=10000),
        user=Depends(staff),
    ):
        return store.summary(threshold_cents=cents(threshold))

    @app.post("/api/albums", status_code=201)
    def album_create(values: AlbumCreate, user=Depends(editor)):
        import uuid

        album = {"id": str(uuid.uuid4()), "name": values.name}
        with store.connect(write=True) as db:
            db.execute("INSERT INTO albums VALUES(?,?)", (album["id"], album["name"]))
        return album

    @app.get("/api/copies")
    def copies(
        q: str = Query(default="", max_length=300),
        album: str = "",
        stock: str = "",
        status: str = "",
        variant: Literal["", "standard", "foil", "check", "unverified", "stamped"] = "",
        sort: Literal["name", "binder", "price", "price_asc"] = "name",
        review: Literal["", "needed", "coverage"] = "",
        threshold: float = Query(default=10, ge=0.01, le=10000),
        limit: int = Query(default=60, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        user=Depends(staff),
    ):
        if stock == "deleted" and user["role"] != "admin":
            raise HTTPException(403, "La corbeille est réservée à l’administration.")
        return store.listing(
            q,
            album,
            stock,
            status,
            limit,
            offset,
            variant=variant,
            sort=sort,
            review=review,
            threshold_cents=cents(threshold),
        )

    @app.delete("/api/copies/{copy_id}")
    def copy_remove(copy_id: str, values: CopyRemoval, user=Depends(admin)):
        return store.set_deleted(
            copy_id, True, values.expected_version, user["username"], values.reason
        )

    @app.post("/api/copies/{copy_id}/restore")
    def copy_restore(copy_id: str, values: CopyRemoval, user=Depends(admin)):
        return store.set_deleted(
            copy_id, False, values.expected_version, user["username"], values.reason
        )

    @app.get("/api/copies/{copy_id}")
    def detail(
        copy_id: str,
        threshold: float = Query(default=10, ge=0.01, le=10000),
        user=Depends(staff),
    ):
        with store.connect() as db:
            card = store.get(db, copy_id)
            source = db.execute(
                "SELECT raw_json,sha256,imported_at FROM sources WHERE copy_id=?",
                (copy_id,),
            ).fetchone()
            card["source"] = (
                {
                    "data": json.loads(source["raw_json"]),
                    "sha256": source["sha256"],
                    "imported_at": source["imported_at"],
                }
                if source
                else None
            )
            card["history"] = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM events WHERE copy_id=? ORDER BY id DESC", (copy_id,)
                )
            ]
            card["prices"] = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM prices WHERE copy_id=? ORDER BY id DESC", (copy_id,)
                )
            ]
            card["condition_assessments"] = assessment_rows(store, db, card)
            snapshot = pricing.latest(db, copy_id)
            card["price_snapshot"] = snapshot
            card["price_category"] = category(card, store.category_snapshot(db, card))
            card["reference_resolution"] = store.reference.decision_for(
                db, card, store.category_snapshot(db, card)
            )
            card["bound_quotes"] = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload_json FROM reference_quotes WHERE copy_id=? ORDER BY rowid DESC",
                    (copy_id,),
                )
            ]
            card["sale_estimate"] = pricing.latest(db, copy_id, "sale-estimate")
            card["valuation"] = store.valuation(
                card,
                store.valuation_context(db),
                card["source"]["data"] if card["source"] else None,
                threshold_cents=cents(threshold),
            )
            card["variant_checks"] = check_rows(db, card)
            if card["variant_checks"] and not card["variant_checks"][0]["stale"]:
                latest = card["variant_checks"][0]
                # The reading is fixed; the proposal follows the current copy.
                latest["current_proposal"] = propose_variant(
                    card,
                    latest["result"],
                    store.category_snapshot(db, card),
                    card["valuation"],
                )
                latest["language_kept"] = any(
                    json.loads(e[0]).get("verification_id") == latest["id"]
                    for e in db.execute(
                        "SELECT after_json FROM events WHERE copy_id=? AND kind='language-validation'",
                        (copy_id,),
                    )
                )
            card["edition_checks"] = check_rows(db, card, "edition")
            card["edition_check_available"] = edition_checks.available
            if card["edition_checks"] and not card["edition_checks"][0]["stale"]:
                latest = card["edition_checks"][0]
                latest["current_proposal"] = propose_edition(card, latest["result"])
                latest["kept"] = any(
                    json.loads(e[0]).get("verification_id") == latest["id"]
                    for e in db.execute(
                        "SELECT after_json FROM events WHERE copy_id=? AND kind='edition-validation'",
                        (copy_id,),
                    )
                )
            card["sale_estimate_stale"] = bool(
                card["sale_estimate"]
                and card["valuation"]["sale_estimate_cents"] is None
            )
            card["cardmarket_url"] = cardmarket_url(
                (snapshot or {}).get("id_product"),
                card["language"],
                card["condition"],
                card["price_category"]["foil"]
                if card["price_category"]["mode"] == "automatic"
                else card["foil"],
            )
            card["reference_binding"] = store.reference.selected_binding(
                card["reference_resolution"]
            )
            bound_quote = card["reference_resolution"]["price_selection"]["quote"] or {}
            if bound_quote.get("binding_key"):
                card["cardmarket_url"] = binding_market_url(bound_quote["binding"])
            market_state = card["valuation"].get("market_product") or {}
            if market_state.get("verdict") == "wrong":
                card["cardmarket_url"] = None  # That product is another card.
            card["cardmarket_search_url"] = None
            if card["catalog_id"] and (
                not card["cardmarket_url"] or market_state.get("shared_with")
            ):
                english = db.execute(
                    "SELECT name FROM catalog_names WHERE catalog_id=? AND language='en'",
                    (card["catalog_id"],),
                ).fetchone()
                card["cardmarket_search_url"] = cardmarket_search_url(
                    english[0] if english else card["name"],
                    card["catalog_id"],
                    cached_set_code(db, card["catalog_id"]),
                )
            return card

    @app.post("/api/copies/{copy_id}/variant-preview")
    def variant_preview(copy_id: str, values: CardFields, user=Depends(staff)):
        with store.connect() as db:
            before = store.get(db, copy_id)
            card = {**before, **values.model_dump(exclude_unset=True)}
            if any(
                card.get(k) != before.get(k)
                for k in (
                    "finish",
                    "stamp",
                    "stamp_state",
                    "distribution",
                    "distribution_state",
                    "catalog_id",
                    "language",
                    "number",
                    "identification_status",
                )
            ):
                card["variant_confirmed"] = False
            if (
                any(card[k] != before[k] for k in ("number", "set_name", "language"))
                and card["catalog_id"] == before["catalog_id"]
            ):
                card["catalog_id"] = None
        variant_catalogue.ensure(card)
        with store.connect() as db:
            snapshot = store.category_snapshot(db, card)
            return {
                **category(card, snapshot),
                "reference_resolution": store.reference.decision_for(
                    db, card, snapshot
                ),
            }

    @app.get("/api/reference-audit")
    def reference_audit(user=Depends(staff)):
        return store.reference.audit()

    @app.post("/api/copies/{copy_id}/reference-decision", status_code=201)
    def reference_decision(copy_id: str, values: CopyRemoval, user=Depends(editor)):
        return store.reference.record(
            copy_id, values.expected_version, user["username"], values.reason
        )

    @app.get("/api/reference-decisions/{decision_id}/replay")
    def reference_replay(decision_id: int, user=Depends(staff)):
        return store.reference.replay(decision_id)

    @app.post("/api/copies/{copy_id}/reference-dispute")
    def reference_dispute(copy_id: str, values: ReferenceDispute, user=Depends(editor)):
        return store.reference.dispute(
            copy_id,
            values.expected_version,
            values.active,
            values.affects,
            user["username"],
            values.reason,
        )

    @app.post("/api/copies/{copy_id}/market-product")
    def market_product(copy_id: str, values: MarketVerdict, user=Depends(editor)):
        return market.judge(
            copy_id,
            values.expected_version,
            values.verdict,
            user["username"],
            values.reason,
        )

    @app.post("/api/copies/{copy_id}/bound-quote", status_code=201)
    def bound_quote(copy_id: str, values: BoundQuote, user=Depends(editor)):
        if any(v < 0 or v > 10000000 for v in values.metrics.values()):
            raise ValueError("Montant hors limites.")
        return select_transcription(
            store,
            copy_id,
            values.expected_version,
            values.metrics,
            values.observed_on,
            user["username"],
            values.reason,
            values.capture_sha256,
        )

    @app.post("/api/copies/{copy_id}/sale-estimate", status_code=201)
    def sale_estimate(copy_id: str, values: OffersPaste, user=Depends(editor)):
        return pricing.estimate(copy_id, values.text, user["username"])

    @app.post("/api/copies/{copy_id}/price-refresh")
    def price_refresh(copy_id: str, values: ConditionRequest, user=Depends(editor)):
        try:
            return pricing.refresh(copy_id, values.expected_version, user["username"])
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from None

    @app.patch("/api/copies/{copy_id}")
    def correct(copy_id: str, values: CardPatch, user=Depends(editor)):
        changes = values.model_dump(
            exclude_unset=True, exclude={"reason", "expected_version"}
        )
        if any(
            v is None and k not in ("catalog_id", "hp", "reference_price_eur")
            for k, v in changes.items()
        ):
            raise ValueError("Champ vide non autorisé.")
        if "reference_price_eur" in changes:
            changes["reference_cents"] = cents(changes.pop("reference_price_eur"))
            if changes["reference_cents"] is not None:
                if not changes.get("price_source"):
                    raise ValueError("Précisez la source du prix.")
                changes["price_date"] = now()
            else:
                changes.update(price_source="", price_date="")
        # Network metadata lookup happens before the write transaction. It may
        # fail; saving a physical observation must remain possible offline.
        with store.connect() as db:
            before = store.get(db, copy_id)
        if before["version"] != values.expected_version:
            raise Conflict("La fiche a changé. Rechargez-la avant de modifier.")
        observed = {**before, **changes}
        if (
            any(observed[k] != before[k] for k in ("number", "set_name", "language"))
            and observed["catalog_id"] == before["catalog_id"]
        ):
            observed["catalog_id"] = None
        variant_catalogue.ensure(observed)
        return store.patch(
            copy_id, changes, values.expected_version, user["username"], values.reason
        )

    @app.post("/api/copies", status_code=201)
    def copy_create(values: CardCreate, user=Depends(editor)):
        changes = values.model_dump(
            exclude_unset=True, exclude={"reason", "duplicate_acknowledgments"}
        )
        if any(v is None and k not in ("catalog_id", "hp") for k, v in changes.items()):
            raise ValueError("Champ vide non autorisé.")
        for key in (
            "name",
            "album_id",
            "page",
            "position",
            "set_name",
            "number",
            "language",
        ):
            changes[key] = getattr(values, key)
        variant_catalogue.ensure(changes)
        return store.create_copy(
            changes,
            user["username"],
            values.reason,
            duplicate_acknowledgments=values.duplicate_acknowledgments,
        )

    @app.get("/api/editions")
    def editions(
        q: str = Query(default="", max_length=300),
        album: str = "",
        stock: str = "",
        status: str = "",
        variant: Literal["", "standard", "foil", "check", "unverified", "stamped"] = "",
        sort: Literal["name", "binder", "price", "price_asc"] = "name",
        review: Literal["", "needed", "coverage"] = "",
        threshold: float = Query(default=10, ge=0.01, le=10000),
        limit: int = Query(default=40, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        user=Depends(staff),
    ):
        if stock == "deleted" and user["role"] != "admin":
            raise HTTPException(403, "La corbeille est réservée à l’administration.")
        return store.grouped(
            q,
            album,
            stock,
            status,
            limit,
            offset,
            variant=variant,
            sort=sort,
            review=review,
            threshold_cents=cents(threshold),
        )

    from .capture import CaptureService
    from .photo_batches import PhotoBatches

    capture, batches = CaptureService(store, intake), PhotoBatches(store)

    @app.get("/api/capture-sessions")
    def capture_list(user=Depends(editor)):
        return capture.listing(user["id"])

    @app.post("/api/capture-sessions", status_code=201)
    def capture_create(values: CaptureCreate, user=Depends(editor)):
        return capture.create(user["id"], values.model_dump())

    @app.get("/api/capture-sessions/{sid}")
    def capture_get(sid: str, user=Depends(editor)):
        with store.connect() as db:
            return capture.get(db, sid, user["id"])

    @app.patch("/api/capture-sessions/{sid}")
    def capture_patch(sid: str, values: CapturePatch, user=Depends(editor)):
        changes = values.model_dump(exclude_unset=True, exclude={"expected_version"})
        if any(
            changes.get(k) is None
            for k in ("fields", "status", "page", "position")
            if k in changes
        ):
            raise ValueError("Champ vide non autorisé.")
        return capture.patch(sid, user["id"], values.expected_version, changes)

    @app.post("/api/capture-sessions/{sid}/save", status_code=201)
    def capture_save(
        sid: str, values: CaptureSave, tasks: BackgroundTasks, user=Depends(editor)
    ):
        result = capture.save(
            sid,
            user["id"],
            user["username"],
            values.expected_version,
            values.token,
            intake_values(values),
            values.chosen_catalog_id,
            values.human_confirmed,
            values.duplicate_acknowledgments,
        )
        read_after_intake(tasks, result["card"], user)
        return result

    @app.post("/api/photo-batches", status_code=201)
    def batch_preview(values: BatchPreview, user=Depends(editor)):
        if len({c.id for c in values.copies}) != len(values.copies):
            raise ValueError("Exemplaires répétés.")
        return batches.preview(
            user["id"],
            [c.model_dump() for c in values.copies],
            values.side,
            values.options.model_dump(),
        )

    @app.get("/api/photo-batches")
    def batch_list(user=Depends(editor)):
        with store.connect() as db:
            return [
                batches.get(db, r[0], user["id"])
                for r in db.execute(
                    "SELECT id FROM photo_batches WHERE owner_id=? ORDER BY created_at DESC LIMIT 20",
                    (user["id"],),
                )
            ]

    @app.get("/api/photo-batches/{jid}")
    def batch_get(jid: str, user=Depends(editor)):
        with store.connect() as db:
            return batches.get(db, jid, user["id"])

    @app.get("/api/photo-batches/{jid}/photo/{copy_id}/{view}")
    def batch_photo(
        jid: str, copy_id: str, view: Literal["before", "result"], user=Depends(editor)
    ):
        with store.connect() as db:
            job = batches.get(db, jid, user["id"])
        item = next((i for i in job["data"]["items"] if i["id"] == copy_id), None)
        if not item or not item.get(view):
            raise KeyError("Photo absente.")
        return FileResponse(store.photos / item[view], media_type="image/jpeg")

    @app.post("/api/photo-batches/{jid}/apply")
    def batch_apply(jid: str, values: BatchApply, user=Depends(editor)):
        return batches.apply(jid, user["id"], user["username"], values.copy_ids)

    @app.post("/api/photo-batches/{jid}/undo")
    def batch_undo(jid: str, user=Depends(editor)):
        return batches.apply(jid, user["id"], user["username"], [], undo=True)

    @app.post("/api/intake/drafts", status_code=201)
    def intake_draft(user=Depends(editor)):
        return intake.new(user["id"])

    @app.post("/api/intake/photo", status_code=201)
    async def intake_photo(request: Request, user=Depends(editor)):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 8 * 1024 * 1024:
                raise HTTPException(413, "Photo limitée à 8 Mo.")
        guide = request.headers.get("x-card-guide")
        return intake.new(
            user["id"],
            normalize_photo(data),
            guide=parse_guide(guide) if guide else None,
        )

    @app.post("/api/copies/{copy_id}/intake", status_code=201)
    def intake_existing(copy_id: str, user=Depends(editor)):
        with store.connect() as db:
            card = store.get(db, copy_id)
        data = (store.photos / card["photo"]).read_bytes() if card["photo"] else None
        return {
            **intake.new(
                user["id"],
                data,
                {
                    "id": copy_id,
                    "version": card["version"],
                    **{k: card[k] for k in ("name", "number", "language", "hp")},
                },
            ),
            "card": card,
        }

    @app.get("/api/intake/{token}")
    def intake_metadata(token: str, user=Depends(editor)):
        draft = intake.draft(token, user["id"])
        return {
            "token": token,
            "has_photo": draft["photo"] is not None,
            "photo_processing": draft["photo_processing"],
            "searches": draft["searches"],
            "observation": draft["observation"],
        }

    @app.get("/api/intake/{token}/photo")
    def intake_preview(token: str, user=Depends(staff)):
        draft = intake.draft(token, user["id"])
        if draft["photo"] is None:
            raise HTTPException(404, "Photo absente.")
        return Response(draft["photo"], media_type="image/jpeg")

    @app.post("/api/intake/{token}/photo-options")
    def intake_photo_options(token: str, values: PhotoOptions, user=Depends(editor)):
        return intake.photo_options(token, user["id"], values.model_dump())

    @app.post("/api/copies/{copy_id}/photo-from-intake")
    def attach_prepared_photo(
        copy_id: str, values: PhotoAttachment, user=Depends(editor)
    ):
        return intake.attach_photo(
            values.token,
            user["id"],
            copy_id,
            values.expected_version,
            user["username"],
            values.side,
        )

    @app.delete("/api/intake/{token}")
    def intake_discard(token: str, user=Depends(editor)):
        with intake.lock:
            intake.draft(token, user["id"])
            with store.connect() as db:
                for row in db.execute(
                    "SELECT data_json FROM capture_sessions WHERE owner_id=? AND status!='closed'",
                    (user["id"],),
                ):
                    data = json.loads(row[0])
                    if token in (data.get("front_token"), data.get("back_token")):
                        raise Conflict(
                            "Cette photo est conservée pour une série en cours."
                        )
            del intake.drafts[token]
            with store.connect(write=True) as db:
                db.execute(
                    "DELETE FROM intake_drafts WHERE token=? AND owner_id=?",
                    (token, user["id"]),
                )
        return {"discarded": True}

    @app.post("/api/intake/{token}/analyze")
    def intake_analyze(
        token: str, entry: IntakeEntry | None = None, user=Depends(editor)
    ):
        try:
            return intake.analyze(
                token, user["id"], entry.model_dump() if entry else None
            )
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from None

    @app.post("/api/intake/{token}/catalogue")
    def intake_catalogue(token: str, values: IntakeQuery, user=Depends(editor)):
        return intake.search(token, user["id"], values.model_dump())

    def read_after_intake(tasks, card, user):
        """A new photographed copy is checked once, after the response."""
        if auto_checks and card.get("photo"):
            tasks.add_task(
                variant_checks.evaluate_new_copy,
                card["id"],
                user["username"],
                variant_inputs,
            )
            if edition_checks.available:
                tasks.add_task(
                    edition_checks.evaluate_new_copy, card["id"], user["username"]
                )

    @app.post("/api/intake/{token}/save", status_code=201)
    def intake_save(
        token: str, values: IntakeSave, tasks: BackgroundTasks, user=Depends(editor)
    ):
        data = intake_values(values)
        existing = intake.draft(token, user["id"])["existing"]
        result = intake.save(
            token,
            user["id"],
            user["username"],
            data,
            values.chosen_catalog_id,
            values.human_confirmed,
            duplicate_acknowledgments=values.duplicate_acknowledgments,
        )
        if not existing:  # Identifying a stored copy does not change its photo.
            read_after_intake(tasks, result, user)
        return result

    @app.post("/api/intake/{token}/duplicates")
    def intake_duplicates(token: str, values: IntakeSave, user=Depends(editor)):
        draft = intake.draft(token, user["id"])
        data = {
            **intake_values(values),
            "photo": store.save_photo(draft["photo"]) if draft["photo"] else None,
            "photo_original": store.save_photo(draft["original_photo"])
            if draft["original_photo"]
            else None,
        }
        with store.connect() as db:
            return store.duplicates(
                db,
                data,
                draft["existing"]["id"] if draft["existing"] else draft["copy_id"],
            )

    @app.get("/api/copies/{copy_id}/catalogue")
    def catalogue(copy_id: str, user=Depends(staff)):
        with store.connect() as db:
            card = store.get(db, copy_id)
        return catalogue_images.get(card)

    @app.get("/api/copies/{copy_id}/photo")
    def photo(
        copy_id: str,
        side: Literal["front", "back"] = "front",
        size: Literal["full", "thumb"] = "full",
        user=Depends(staff),
    ):
        with store.connect() as db:
            card = store.get(db, copy_id)
        name = card["photo" if side == "front" else "back_photo"]
        if not name:
            raise HTTPException(404, "Photo absente.")
        path = store.thumbnail(name) if size == "thumb" else store.photos / name
        return FileResponse(path, media_type="image/jpeg")

    @app.put("/api/copies/{copy_id}/photo")
    async def upload(
        copy_id: str,
        request: Request,
        version: int = Query(ge=1),
        side: Literal["front", "back"] = "front",
        user=Depends(editor),
    ):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 8 * 1024 * 1024:
                raise HTTPException(413, "Photo limitée à 8 Mo.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    if (
                        image.format not in ("JPEG", "PNG", "WEBP")
                        or image.width * image.height > 24000000
                    ):
                        raise ValueError("Format ou dimensions non pris en charge.")
                    image = ImageOps.exif_transpose(image).convert("RGB")
                    image.thumbnail((1600, 1600))
                    output = io.BytesIO()
                    image.save(output, format="JPEG", quality=90)
        except (
            OSError,
            ValueError,
            Image.DecompressionBombWarning,
            Image.DecompressionBombError,
        ):
            raise HTTPException(
                422, "Photo JPEG, PNG ou WebP valide requise (24 mégapixels maximum)."
            )
        name = store.save_photo(output.getvalue())
        return store.patch(
            copy_id,
            {
                "photo" if side == "front" else "back_photo": name,
                "photo_original" if side == "front" else "back_photo_original": name,
                "condition_confirmed": False,
            },
            version,
            user["username"],
            "Ajout ou remplacement de la photo du "
            + ("recto" if side == "front" else "verso"),
        )

    @app.post("/api/copies/{copy_id}/condition-assessments", status_code=201)
    def assess_condition(copy_id: str, values: ConditionRequest, user=Depends(editor)):
        try:
            return conditions.evaluate(
                copy_id, values.expected_version, user["username"]
            )
        except RuntimeError as error:
            raise HTTPException(502, str(error)) from None

    @app.post("/api/copies/{copy_id}/condition-assessments/{assessment_id}/confirm")
    def confirm_condition(
        copy_id: str,
        assessment_id: str,
        values: ConditionConfirmation,
        user=Depends(editor),
    ):
        return conditions.confirm(
            copy_id,
            assessment_id,
            values.expected_version,
            values.condition,
            user["username"],
            values.reason,
        )

    def variant_inputs(copy_id, threshold_cents=1000):
        return check_inputs(store, variant_catalogue, copy_id, threshold_cents)

    @app.post("/api/copies/{copy_id}/variant-checks", status_code=201)
    def check_variant(
        copy_id: str,
        values: ConditionRequest,
        threshold: float = Query(default=10, ge=0.01, le=10000),
        user=Depends(editor),
    ):
        snapshot, valuation = variant_inputs(copy_id, cents(threshold))
        try:
            return variant_checks.evaluate(
                copy_id,
                values.expected_version,
                user["username"],
                snapshot=snapshot,
                valuation=valuation,
            )
        except RuntimeError as error:
            raise HTTPException(502, str(error)) from None

    @app.post("/api/copies/{copy_id}/variant-checks/{check_id}/confirm")
    def confirm_variant(
        copy_id: str,
        check_id: str,
        values: VariantDecision,
        threshold: float = Query(default=10, ge=0.01, le=10000),
        user=Depends(editor),
    ):
        snapshot, valuation = variant_inputs(copy_id, cents(threshold))
        with store.connect() as db:
            card = store.get(db, copy_id)
            row = next((r for r in check_rows(db, card) if r["id"] == check_id), None)
        proposal = (
            propose_variant(card, row["result"], snapshot, valuation) if row else None
        )
        return variant_checks.confirm(
            copy_id,
            check_id,
            values.expected_version,
            values.model_dump(exclude={"expected_version", "reason"}),
            user["username"],
            values.reason,
            proposal,
        )

    @app.post("/api/copies/{copy_id}/variant-checks/{check_id}/keep-language")
    def keep_language(
        copy_id: str, check_id: str, values: KeepRecorded, user=Depends(editor)
    ):
        return variant_checks.keep_language(
            copy_id, check_id, values.expected_version, user["username"], values.reason
        )

    @app.post("/api/copies/{copy_id}/edition-checks", status_code=201)
    def check_edition(copy_id: str, values: ConditionRequest, user=Depends(editor)):
        if not edition_checks.available:
            raise HTTPException(
                503,
                "Contrôle d’édition indisponible : installez l’option vision (uv sync --extra vision).",
            )
        try:
            return edition_checks.evaluate(
                copy_id, values.expected_version, user["username"]
            )
        except RuntimeError as error:
            raise HTTPException(502, str(error)) from None

    @app.post("/api/copies/{copy_id}/edition-checks/{check_id}/keep")
    def keep_edition(
        copy_id: str, check_id: str, values: KeepRecorded, user=Depends(editor)
    ):
        return edition_checks.keep(
            copy_id, check_id, values.expected_version, user["username"], values.reason
        )

    listings = Listings(store)

    @app.get("/api/listings")
    def listing_index(
        state: Literal["online", "offline", ""] = "online", user=Depends(staff)
    ):
        return listings.all(state)

    @app.post("/api/listings", status_code=201)
    def listing_create(values: ListingCreate, user=Depends(editor)):
        price = cents(values.price_eur)
        if values.lot:
            return [
                listings.publish(
                    values.copy_ids, user["username"], price_cents=price,
                    title=values.title, lot=True,
                )
            ]
        # A selection: each card is published alone, at its own price.
        published, refused = [], []
        for copy_id in values.copy_ids:
            try:
                published.append(
                    listings.publish([copy_id], user["username"], price_cents=price)
                )
            except (ValueError, Conflict) as error:
                refused.append({"copy_id": copy_id, "reason": str(error)})
        return {"published": published, "refused": refused}

    @app.get("/api/copies/{copy_id}/listing")
    def copy_listing(copy_id: str, user=Depends(staff)):
        with store.connect() as db:
            current = listings.active(db, copy_id)
            current = listings.get(db, current["id"]) if current else None
        return {"listing": current, "proposal": listings.proposal(copy_id)}

    @app.put("/api/copies/{copy_id}/listing")
    def copy_publish(copy_id: str, values: ListingPrice, user=Depends(editor)):
        return listings.publish(
            [copy_id], user["username"], price_cents=cents(values.price_eur)
        )

    @app.delete("/api/copies/{copy_id}/listing")
    def copy_unpublish(copy_id: str, user=Depends(editor)):
        with store.connect() as db:
            current = listings.active(db, copy_id)
        if not current:
            raise KeyError("Cet exemplaire n’est pas publié.")
        return listings.unpublish(
            current["id"], current["version"], user["username"], "Retrait de la vitrine"
        )

    @app.post("/api/listings/{listing_id}/unpublish")
    def listing_unpublish(listing_id: str, values: CopyRemoval, user=Depends(editor)):
        return listings.unpublish(
            listing_id, values.expected_version, user["username"], values.reason
        )

    @app.get("/api/sales")
    def sales(user=Depends(staff)):
        return store.sales()

    @app.post("/api/sales", status_code=201)
    def sale_create(values: SaleCreate, user=Depends(editor)):
        data = values.model_dump(
            exclude={
                "copy_ids",
                "amount_eur",
                "asking_eur",
                "target_eur",
                "minimum_eur",
            }
        )
        data["amount_cents"] = cents(values.amount_eur)
        for key in ("asking", "target", "minimum"):
            data[key + "_cents"] = cents(getattr(values, key + "_eur"))
        return {"id": store.create_sale(data, values.copy_ids, user["username"])}

    @app.patch("/api/sales/{sale_id}")
    def sale_patch(sale_id: str, values: SalePatch, user=Depends(editor)):
        changes = values.model_dump(
            exclude_unset=True, exclude={"expected_version", "reason"}
        )
        if any(
            v is None and k not in ("asking_eur", "target_eur", "minimum_eur")
            for k, v in changes.items()
        ):
            raise ValueError("Champ vide non autorisé.")
        for field in list(changes):
            if field.endswith("_eur"):
                changes[field[:-4] + "_cents"] = cents(changes.pop(field))
        return store.update_sale(
            sale_id, changes, values.expected_version, user["username"], values.reason
        )

    @app.get("/api/sales/{sale_id}/listing-package")
    def listing_package(sale_id: str, user=Depends(editor)):
        import shutil
        import tempfile

        from starlette.background import BackgroundTask

        from .listing_package import package

        folder = Path(tempfile.mkdtemp(prefix="pokeprice-listing-"))
        target = folder / "annonce.zip"
        try:
            package(store, sale_id, target)
        except Exception:
            shutil.rmtree(folder)
            raise
        return FileResponse(
            target,
            filename="pokeprice-brouillon-annonce.zip",
            media_type="application/zip",
            background=BackgroundTask(shutil.rmtree, folder),
        )

    @app.get("/api/export/{kind}")
    def export(kind: Literal["csv", "json", "html"], user=Depends(staff)):
        body = {
            "csv": export_csv,
            "json": lambda s: json.dumps(export_data(s), ensure_ascii=False, indent=2),
            "html": export_html,
        }[kind](store)
        media = {"csv": "text/csv", "json": "application/json", "html": "text/html"}[
            kind
        ]
        return Response(
            body,
            media_type=media,
            headers={
                "Content-Disposition": f'attachment; filename="pokeprice-collection.{kind}"'
            },
        )

    @app.get("/api/backup/status")
    def backup_status(user=Depends(admin)):
        from .daily_backup import public_status

        return public_status(store)

    @app.post("/api/backup/daily")
    def backup_daily(user=Depends(admin)):
        from .daily_backup import daily, public_status

        daily(store, force=True)
        return public_status(store)

    @app.get("/api/backup")
    def download_backup(user=Depends(admin)):
        import tempfile

        from starlette.background import BackgroundTask

        folder = Path(tempfile.mkdtemp(prefix="pokeprice-backup-"))
        target = folder / "collection.zip"
        try:
            backup(store, target)
        except Exception:
            import shutil

            shutil.rmtree(folder)
            raise
        import shutil

        return FileResponse(
            target,
            filename="pokeprice-backup.zip",
            media_type="application/zip",
            background=BackgroundTask(shutil.rmtree, folder),
        )

    if agent_enabled:
        from .agent_api import install

        install(app, store)
    return app
