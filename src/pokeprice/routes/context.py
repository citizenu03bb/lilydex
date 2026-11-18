"""The web application's services and settings, built once per application.

``build_services`` runs the start-up in a fixed order: validated public origin,
indexing switch, store, allowed hosts and the exposure check, then each service,
the notifier's thread included. ``AppContext`` hands the route code shared
references, never copies: tests rebind ``.reader``, ``.fetch`` or ``.channels``
on these objects after ``create_app``.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from ..agent_review import AgentReview
from ..audience import Audience
from ..cardmarket_guide import CardmarketGuide
from ..catalogue_image import CatalogueImages
from ..condition_assessment import ConditionService, read_condition
from ..edition_check import EditionCheckService
from ..floor_requests import FloorRequests
from ..intake import IntakeService, catalogue_candidates, read_photo
from ..inventory import Store
from ..listings import Listings, Storefront
from ..market_product import MarketProducts, fetch_tcgdex
from ..notifications import Notifier, WebPush, channels_from_env
from ..pricing import PriceService, fetch_catalogue_card, fetch_card_with_guide
from ..reservations import Reservations
from ..variant_catalogue import VariantCatalogue
from ..verification import VariantCheckService, check_inputs
from ..web_constants import LOCAL_HOSTS, indexing_enabled
from .auth_deps import Auth, build_auth
from .limits import Limits, build_limits
from .pages import Pages, build_pages

if TYPE_CHECKING:  # Imported inside build_services: loaded at start-up, not at import.
    from ..assistant import Assistant
    from ..capture import CaptureService
    from ..move_batches import MoveBatches
    from ..photo_batches import PhotoBatches
    from ..todo import Todo


@dataclass(frozen=True)
class AppContext:
    """What the routes of one application share: settings and services."""

    public_origin: str
    indexing: bool
    allowed_hosts: list[str]
    store: Store
    intake: IntakeService
    conditions: ConditionService
    variant_checks: VariantCheckService
    edition_checks: EditionCheckService
    market: MarketProducts
    pricing: PriceService
    variant_catalogue: VariantCatalogue
    catalogue_images: CatalogueImages
    audience: Audience
    storefront: Storefront
    notifier: Notifier
    web_push: WebPush | None
    reservations: Reservations
    capture: "CaptureService"
    batches: "PhotoBatches"
    moves: "MoveBatches"
    variant_inputs: Callable[..., Any]
    review: AgentReview
    listings: Listings
    floor_requests: FloorRequests
    todo: "Todo"
    assistant: "Assistant"
    pages: Pages
    limits: Limits
    auth: Auth


def build_services(
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
    price_fetch=None,
    variant_fetch=None,
    market_fetch=None,
    indexing=None,
    assistant_model=None,
) -> AppContext:
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
    # Search engines may index the storefront unless the owner switches it off.
    indexing = indexing_enabled(os.environ.get("POKEPRICE_INDEXING", "on") if indexing is None else indexing)
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
    intake = IntakeService(
        store, intake_reader or read_photo, intake_lookup or catalogue_candidates
    )
    conditions = ConditionService(store, condition_reader or read_condition)
    variant_checks = VariantCheckService(store, variant_reader)
    edition_checks = EditionCheckService(
        store, edition_reader, edition_get_json, edition_fetch
    )
    # An injected price source (tests) never reaches TCGdex for neighbours.
    market = MarketProducts(
        store, market_fetch or (fetch_tcgdex if price_fetch is None else None)
    )
    # Tests inject their source; the app completes TCGdex with Cardmarket's guide.
    pricing = PriceService(
        store,
        price_fetch
        or fetch_card_with_guide(CardmarketGuide(store.root / "cardmarket", store)),
        market,
    )
    variant_catalogue = VariantCatalogue(
        store,
        variant_fetch
        or (
            lambda *args: (
                pricing.fetch(*args) if price_fetch else fetch_catalogue_card(*args)
            )
        ),
    )
    catalogue_images = CatalogueImages(store, variant_catalogue.fetch)
    audience = Audience(store.root, allowed_hosts)
    storefront = Storefront(store)
    # Seller alerts: each channel is off until its environment variables are set.
    notifier = Notifier(store, channels_from_env(store=store), public_origin)
    web_push = next((c for c in notifier.channels if isinstance(c, WebPush)), None)
    notifier.start()  # A daemon thread, only when a channel is configured.
    reservations = Reservations(store, storefront, notifier)

    from ..capture import CaptureService
    from ..move_batches import MoveBatches
    from ..photo_batches import PhotoBatches

    capture, batches, moves = (
        CaptureService(store, intake),
        PhotoBatches(store),
        MoveBatches(store),
    )

    def variant_inputs(copy_id, threshold_cents=1000):
        return check_inputs(store, variant_catalogue, copy_id, threshold_cents)

    # The review agent confirms on evidence or asks for a photo (agent_review.py).
    review = AgentReview(store, variant_checks, conditions, edition_checks, variant_inputs)
    listings = Listings(store)

    # Waivers under the anti-undercut floor: asked by agents, decided by a person (0030).
    floor_requests = FloorRequests(store)

    # The management assistant, V0 (todo.py): the brief and the « À toi » queue,
    # floor waivers (decision 0030) included.
    from ..todo import Todo

    todo = Todo(
        store,
        photo_requests=review.photo_requests,
        floor_requests=floor_requests.open,
    )

    from ..assistant import DEFAULT_DAILY_LIMIT, DEFAULT_PER_MINUTE, Assistant
    from ..assistant_model import from_env

    def positive(name, default):
        try:
            return max(1, int(os.environ.get(name, "") or default))
        except ValueError:
            raise ValueError(f"{name} : nombre entier attendu.") from None

    assistant = Assistant(
        store, todo, assistant_model if assistant_model is not None else from_env(),
        daily_limit=positive("POKEPRICE_ASSISTANT_DAILY_LIMIT", DEFAULT_DAILY_LIMIT),
        per_minute=positive("POKEPRICE_ASSISTANT_PER_MINUTE", DEFAULT_PER_MINUTE),
    )

    # V1.1, cost alert (decision 0039): one alert a month on the alert channels once
    # the chat's estimated cost reaches the threshold; 0 switches it off.
    from ..assistant import (COST_ALERT_VARIABLE, DEFAULT_COST_ALERT_EUR, DEFAULT_EUR_PER_USD,
                            RATE_VARIABLE, CostAlert)

    def amount(name, default):
        try:
            value = float((os.environ.get(name, "") or str(default)).replace(",", "."))
        except ValueError:
            raise ValueError(f"{name} : nombre attendu.") from None
        if value < 0:
            raise ValueError(f"{name} : nombre positif attendu.")
        return value

    assistant.cost_alert = CostAlert(
        assistant.journal, notifier.channels, public_origin,
        threshold_eur=amount(COST_ALERT_VARIABLE, DEFAULT_COST_ALERT_EUR),
        eur_per_usd=amount(RATE_VARIABLE, DEFAULT_EUR_PER_USD) or DEFAULT_EUR_PER_USD,
    )
    # Last, as in the original start-up: the pages, which need the notifier for the
    # shipping rates, then the limiters, then the session dependencies.
    pages = build_pages(public_origin, indexing, reservations, notifier)
    limits = build_limits()
    auth = build_auth(store, secure_cookie)
    return AppContext(
        public_origin=public_origin,
        indexing=indexing,
        allowed_hosts=allowed_hosts,
        store=store,
        intake=intake,
        conditions=conditions,
        variant_checks=variant_checks,
        edition_checks=edition_checks,
        market=market,
        pricing=pricing,
        variant_catalogue=variant_catalogue,
        catalogue_images=catalogue_images,
        audience=audience,
        storefront=storefront,
        notifier=notifier,
        web_push=web_push,
        reservations=reservations,
        capture=capture,
        batches=batches,
        moves=moves,
        variant_inputs=variant_inputs,
        review=review,
        listings=listings,
        floor_requests=floor_requests,
        todo=todo,
        assistant=assistant,
        pages=pages,
        limits=limits,
        auth=auth,
    )
