"""Private FastAPI inventory API and a dependency-free French web interface."""

import hashlib
import hmac
import io
import json
import secrets
import sqlite3
import threading
import time
import warnings
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.middleware.trustedhost import TrustedHostMiddleware

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
    fetch_catalogue_card,
)
from .listings import Listings, Storefront
from .reservations import Reservations
from .variant_catalogue import VariantCatalogue
from .variant_pricing import category
from .edition_check import EditionCheckService, propose_edition
from .verification import (
    VariantCheckService,
    check_inputs,
    check_rows,
    propose_variant,
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
    consent: Literal[True]


class RequestCreate(Model):
    listing_ids: list[str] = Field(min_length=1, max_length=50)
    message: str = Field(default="", max_length=1000)


class RequestVersion(Model):
    expected_version: int = Field(ge=1)


class RequestAccept(RequestVersion):
    listing_ids: list[str] = Field(min_length=1, max_length=50)


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


def password_hash(password):
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return salt.hex() + ":" + key.hex()


def password_valid(password, encoded):
    salt, key = encoded.split(":")
    actual = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32
    )
    return hmac.compare_digest(actual, bytes.fromhex(key))


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
):
    store = Store(directory)
    if secure_cookie:
        with store.connect() as db:
            if not db.execute(
                "SELECT 1 FROM users WHERE role='admin' AND disabled=0 LIMIT 1"
            ).fetchone():
                raise ValueError(
                    "Créez un administrateur local avant le démarrage HTTPS."
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
    pricing = PriceService(store, price_fetch or fetch_card, market)
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
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=allowed_hosts or ["127.0.0.1", "localhost", "testserver"],
    )
    static = Path(__file__).with_name("web")
    failures = {}
    login_lock = threading.Lock()
    dummy_hash = password_hash("not-a-valid-user-password")

    @app.middleware("http")
    async def protect(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            base = urlsplit(str(request.base_url))
            if origin and origin != f"{base.scheme}://{base.netloc}":
                return Response("Origine interdite.", status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return Response("Origine interdite.", status_code=403)
        if (
            request.method == "GET"
            and request.url.path == "/api/copies"
            and "text/html" in request.headers.get("accept", "")
            and request.headers.get("sec-fetch-dest", "") in ("", "document")
        ):
            response = RedirectResponse("/?" + request.url.query, status_code=303)
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://assets.tcgdex.net; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return Response(
            json.dumps({"detail": str(exc)}),
            status_code=409,
            media_type="application/json",
        )

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return Response(
            json.dumps({"detail": str(exc.args[0])}),
            status_code=404,
            media_type="application/json",
        )

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return Response(
            json.dumps({"detail": str(exc)}),
            status_code=422,
            media_type="application/json",
        )

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

    @app.get("/", response_class=HTMLResponse)
    def index():
        return static.joinpath("index.html").read_text()

    @app.get("/assets/{name}")
    def assets(
        name: Literal[
            "app.js", "media.js", "workflows.js", "gallery.js", "style.css",
            "storefront.js", "storefront.css",
        ],
    ):
        return FileResponse(static / name)

    storefront = Storefront(store)
    public_hits = {}
    public_lock = threading.Lock()

    def public_rate(request: Request):
        """Anonymous storefront reads: at most 300 requests a minute per address."""
        key = request.client.host if request.client else "local"
        timestamp = time.monotonic()
        with public_lock:
            recent = [t for t in public_hits.get(key, []) if timestamp - t < 60]
            if len(recent) >= 300:
                raise HTTPException(429, "Trop de requêtes. Réessayez dans une minute.")
            public_hits[key] = recent + [timestamp]
            if len(public_hits) > 10000:  # Forget idle addresses.
                for address in [a for a, hits in public_hits.items() if timestamp - hits[-1] >= 60]:
                    del public_hits[address]

    @app.get("/vitrine", response_class=HTMLResponse)
    def storefront_page():
        return static.joinpath("storefront.html").read_text()

    @app.get("/api/public/listings")
    def public_listings(
        q: str = Query(default="", max_length=200),
        language: str = Query(default="", pattern=r"^(?:[a-z]{2,3})?$"),
        max_eur: Decimal | None = Query(default=None, ge=0, le=10000000),
        sort: Literal["recent", "price", "price_desc", "name"] = "recent",
        limit: int = Query(default=48, ge=1, le=96),
        offset: int = Query(default=0, ge=0, le=100000),
        _=Depends(public_rate),
    ):
        return storefront.search(q, language, cents(max_eur), sort, limit, offset)

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

    @app.get("/api/me")
    def me(user=Depends(client)):
        with store.connect() as db:
            row = db.execute(
                "SELECT email,display_name FROM users WHERE id=?", (user["id"],)
            ).fetchone()
        return dict(row)

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
    def public_listing(listing_id: str, _=Depends(public_rate)):
        return storefront.get(listing_id)

    @app.get("/api/public/listings/{listing_id}/photo")
    def public_photo(
        listing_id: str,
        item: int = Query(default=0, ge=0, le=500),
        side: Literal["front", "back"] = "front",
        size: Literal["full", "thumb"] = "thumb",
        _=Depends(public_rate),
    ):
        return FileResponse(
            storefront.photo(listing_id, item, side, size), media_type="image/jpeg"
        )

    @app.get("/api/setup")
    def setup_state():
        with store.connect() as db:
            return {
                "required": not bool(
                    db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
                )
            }

    @app.get("/health")
    def health():
        with store.connect() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.post("/api/setup")
    def setup(values: Credentials, response: Response):
        with store.connect(write=True) as db:
            if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise Conflict("Le compte initial existe déjà.")
            user = add_user(db, UserCreate(**values.model_dump(), role="admin"))
            issue_session(db, user, response)
            return user

    @app.post("/api/login")
    def login(values: Credentials, request: Request, response: Response):
        key = request.client.host if request.client else "local"
        timestamp = time.monotonic()
        with login_lock:
            attempts = [t for t in failures.get(key, []) if timestamp - t < 300]
            if len(attempts) >= 5:
                raise HTTPException(
                    429, "Trop de tentatives. Réessayez dans cinq minutes."
                )
            # Reserve the attempt before hashing to account for simultaneous requests.
            failures[key] = attempts + [timestamp]
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
            user = {k: row[k] for k in ("id", "username", "role")}
            issue_session(db, user, response)
        with login_lock:
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
            **intake.new(user["id"], data, {"id": copy_id, "version": card["version"]}),
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
    def intake_analyze(token: str, user=Depends(editor)):
        try:
            return intake.analyze(token, user["id"])
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

    return app
