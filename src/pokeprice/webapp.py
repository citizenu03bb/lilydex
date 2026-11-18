"""Private FastAPI inventory API and a dependency-free French web interface."""

import hashlib
import html
import io
import json
import logging
import secrets
import sqlite3
import warnings
from decimal import Decimal
from typing import Literal
from urllib.parse import quote

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

from .audience import counted
from .brand import SITE_NAME, site_slug
from .condition_assessment import assessment_rows
from .inventory import Conflict, cents, now
from .quote_ledger import select_transcription
from .market_product import cached_set_code
from .pricing import (
    binding_market_url,
    cardmarket_search_url,
    cardmarket_url,
    fetch_card,
)
from .privacy import Privacy
from .reservations import shipping_config, valid_email
from .variant_pricing import category
from .edition_check import propose_edition
from .verification import (
    check_rows,
    propose_variant,
)
from .web_constants import (
    APP_SHELL,
    LANGUAGES,
    MANAGEMENT_QUERY,
    TEXT_KEY,
    indexing_enabled,
    interface_version,
)
from .schemas import (
    AlbumCreate,
    BasketQuote,
    BoundQuote,
    CardCreate,
    CardFields,
    CardPatch,
    ClientPatch,
    ConditionRequest,
    CopyRemoval,
    GuestRequest,
    MarketVerdict,
    OffersPaste,
    PasswordCheck,
    PasswordSet,
    Profile,
    ReferenceDispute,
    RequestCreate,
    RequestVersion,
    Signup,
    UserCreate,
)
from .errors import ERROR_CODES, install_handlers
from .passwords import add_user, password_hash, password_valid
from .routes.auth import register_auth, register_logout
from .routes.backup import register_backup
from .routes.capture import register_capture
from .routes.checks import register_checks, register_conditions
from .routes.client_requests import register_client_requests
from .routes.context import build_services
from .routes.exports import register_exports
from .routes.floor_requests import register_floor_requests
from .routes.hooks import build_hooks
from .routes.intake import register_intake
from .routes.listings import register_listings
from .routes.move_batches import register_move_batches
from .routes.photo_batches import register_photo_batches
from .routes.push import register_push
from .routes.sales import register_sales
from .routes.settings import register_settings
from .routes.statistics import register_statistics
from .routes.users import register_users
from .security import install_security


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
    indexing=None,
    assistant_model=None,
):
    ctx = build_services(
        directory,
        secure_cookie=secure_cookie,
        allowed_hosts=allowed_hosts,
        public_origin=public_origin,
        intake_reader=intake_reader,
        intake_lookup=intake_lookup,
        condition_reader=condition_reader,
        variant_reader=variant_reader,
        edition_reader=edition_reader,
        edition_get_json=edition_get_json,
        edition_fetch=edition_fetch,
        price_fetch=price_fetch,
        variant_fetch=variant_fetch,
        market_fetch=market_fetch,
        indexing=indexing,
        assistant_model=assistant_model,
    )
    public_origin = ctx.public_origin
    indexing = ctx.indexing
    allowed_hosts = ctx.allowed_hosts
    store = ctx.store
    intake = ctx.intake
    conditions = ctx.conditions
    variant_checks = ctx.variant_checks
    edition_checks = ctx.edition_checks
    market = ctx.market
    pricing = ctx.pricing
    variant_catalogue = ctx.variant_catalogue
    catalogue_images = ctx.catalogue_images
    audience = ctx.audience
    storefront = ctx.storefront
    notifier = ctx.notifier
    web_push = ctx.web_push
    reservations = ctx.reservations
    capture = ctx.capture
    batches = ctx.batches
    moves = ctx.moves
    variant_inputs = ctx.variant_inputs
    review = ctx.review
    listings = ctx.listings
    floor_requests = ctx.floor_requests
    todo = ctx.todo
    assistant = ctx.assistant
    failures = ctx.limits.failures
    public_hits = ctx.limits.public_hits
    signups = ctx.limits.signups
    guests = ctx.limits.guests
    client_of = ctx.limits.client_of
    public_rate = ctx.limits.public_rate
    dummy_hash = ctx.auth.dummy_hash
    current_user = ctx.auth.current_user
    staff = ctx.auth.staff
    client = ctx.auth.client
    editor = ctx.auth.editor
    admin = ctx.auth.admin
    issue_session = ctx.auth.issue_session
    static = ctx.pages.static
    dictionaries = ctx.pages.dictionaries
    page = ctx.pages.page
    about_page = ctx.pages.about_page
    conditions_page = ctx.pages.conditions_page
    app = FastAPI(
        title="Poképrice — collection privée",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store
    app.state.intake = intake
    app.state.conditions = conditions
    app.state.variant_checks = variant_checks
    app.state.edition_checks = edition_checks
    app.state.market = market
    app.state.pricing = pricing
    app.state.variant_catalogue = variant_catalogue
    install_security(app, allowed_hosts=allowed_hosts, secure_cookie=secure_cookie, indexing=indexing)
    install_handlers(app)

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
        if MANAGEMENT_QUERY & set(request.query_params.keys()):
            # Former management links (/?view=sales, filters) keep working; a
            # shared link's fbclid, utm_* or gclid stays on the storefront.
            return RedirectResponse("/gestion?" + request.url.query, status_code=301)
        count_visit(request, "page", "accueil")
        return page("storefront.html", public="")

    @app.get("/en", include_in_schema=False)
    def home_en_slash():
        return RedirectResponse("/en/", status_code=301)

    # The same storefront in English; the visit counts with the French one.
    @app.get("/en/", response_class=HTMLResponse)
    def home_en(request: Request):
        count_visit(request, "page", "accueil")
        return page("storefront.html", "en", public="")

    @app.get("/a-propos", response_class=HTMLResponse)
    def about(request: Request):
        count_visit(request, "page", "a-propos")
        return about_page("fr")

    # The English page translates the French one, which prevails.
    @app.get("/en/a-propos", response_class=HTMLResponse)
    def about_en(request: Request):
        count_visit(request, "page", "a-propos")
        return about_page("en")

    @app.get("/conditions", response_class=HTMLResponse)
    def conditions_fr(request: Request):
        count_visit(request, "page", "conditions")
        return conditions_page("fr")

    @app.get("/en/conditions", response_class=HTMLResponse)
    def conditions_en(request: Request):
        count_visit(request, "page", "conditions")
        return conditions_page("en")

    @app.get("/gestion", response_class=HTMLResponse)
    def index():
        return page("index.html")

    # The management app is installable (docs/APP.md): manifest, service
    # worker and offline page, all public and free of any collection data.
    @app.get("/gestion/manifest.webmanifest", include_in_schema=False)
    def app_manifest():
        words = dictionaries["fr"]
        icons = [
            {"src": "/assets/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/assets/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/assets/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ]
        manifest = {
            "id": "/gestion",
            "name": SITE_NAME,
            "short_name": "Cartes Lily",
            "description": words["install.description"],
            "lang": "fr",
            "dir": "ltr",
            "start_url": "/gestion",
            "scope": "/gestion",
            "display": "standalone",
            # Herbier theme (themes.css): --surface-1 for the bar, --surface-0 behind.
            "theme_color": "#ffffff",
            "background_color": "#f6f5f0",
            "icons": icons,
        }
        return Response(
            json.dumps(manifest, ensure_ascii=False),
            media_type="application/manifest+json",
        )

    @app.get("/gestion/sw.js", include_in_schema=False)
    def service_worker():
        script = (
            static.joinpath("sw.js").read_text()
            .replace("{{version}}", interface_version(static))
            .replace("{{precache}}", json.dumps(list(APP_SHELL)))
        )
        # Its own folder would cap its reach at /gestion/; the page is /gestion.
        return Response(
            script,
            media_type="text/javascript",
            headers={"Service-Worker-Allowed": "/gestion"},
        )

    @app.get("/gestion/hors-ligne", response_class=HTMLResponse, include_in_schema=False)
    def offline_page():
        return page("offline.html")

    @app.get("/assets/{name}")
    def assets(
        request: Request,
        name: Literal[
            "app.js", "media.js", "workflows.js", "gallery.js", "style.css",
            "storefront.js", "storefront.css", "themes.css", "components.js",
            "photo-zoom.js", "photo-zoom.css", "pwa.js", "assistant.js",
            "logo.png", "apple-touch-icon.png", "mascotte.png",
            "icon-192.png", "icon-512.png", "icon-maskable-512.png",
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

    app.state.rate_limits = {"public": public_hits, "login": failures}

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
        rest = "carte/" + quote(listing_id, safe="")
        return page("storefront.html", language, rest, listing=listing, public=rest)

    def online_listings():
        """The publications on sale, newest first, for the sitemap."""
        with store.connect() as db:
            rows = [r for r in storefront.rows(db) if storefront.cards(db, r["id"])]
        return sorted(rows, key=lambda r: r["published_at"] or "", reverse=True)

    if indexing:
        @app.get("/robots.txt", include_in_schema=False)
        def robots():
            lines = [
                "User-agent: *",
                "Allow: /api/public/listings/*/photo",
                "Disallow: /gestion",
                "Disallow: /api/",
            ]
            if public_origin:
                lines.append(f"Sitemap: {public_origin}/sitemap.xml")
            return Response("\n".join(lines) + "\n", media_type="text/plain")

        @app.get("/sitemap.xml", include_in_schema=False)
        def sitemap():
            if not public_origin:
                # Absolute addresses come from configuration, never from Host.
                raise HTTPException(404, "Plan du site indisponible sans origine publique.")
            entries = [("", None), ("a-propos", None), ("conditions", None)] + [
                ("carte/" + quote(r["id"], safe=""), (r["price_date"] or r["published_at"])[:10])
                for r in online_listings()
            ]
            urls = []
            for rest, modified in entries:
                alternates = "".join(
                    f'<xhtml:link rel="alternate" hreflang="{code}" href="{html.escape(public_origin + home + rest)}"/>'
                    for code, (_, home) in LANGUAGES.items()
                ) + f'<xhtml:link rel="alternate" hreflang="x-default" href="{html.escape(public_origin + "/" + rest)}"/>'
                for _, home in LANGUAGES.values():
                    lastmod = f"<lastmod>{html.escape(modified)}</lastmod>" if modified else ""
                    urls.append(f"<url><loc>{html.escape(public_origin + home + rest)}</loc>{lastmod}{alternates}</url>")
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(urls) + "\n</urlset>\n"
            )
            return Response(body, media_type="application/xml")

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

    app.state.notifier = notifier
    app.state.rate_limits["signup"] = signups

    @app.post("/api/public/signup", status_code=202)
    def signup(values: Signup, request: Request, _=Depends(public_rate)):
        if not signups.hit(client_of(request)):
            raise HTTPException(429, "Trop d’inscriptions depuis cette adresse. Réessayez plus tard.")
        # Same answer and same hashing cost whether the address is known or not.
        reservations.signup(values.email, values.display_name, password_hash(values.password))
        return {
            "detail": "Inscription enregistrée. Le vendeur valide chaque compte : "
            "vous pourrez vous connecter une fois le vôtre activé."
        }

    @app.post("/api/public/quote")
    def basket_quote(values: BasketQuote, _=Depends(public_rate)):
        return reservations.quote(values.listing_ids, values.delivery)

    app.state.rate_limits["guest"] = guests

    @app.post("/api/public/requests", status_code=202)
    def guest_request(values: GuestRequest, request: Request, _=Depends(public_rate)):
        if not guests.hit(client_of(request)):
            raise HTTPException(429, "Trop de demandes depuis cette adresse. Réessayez plus tard.")
        # Hashed whether or not the address is known: the delay tells nothing either.
        unusable = password_hash(secrets.token_urlsafe(32))
        reservations.guest(
            values.email,
            values.display_name,
            values.listing_ids,
            values.message,
            unusable,
            delivery=values.delivery,
            registered=values.registered,
            expected_prices=values.expected_prices,
        )
        return {
            "detail": "Demande envoyée. Rien n’est bloqué tant que le vendeur ne l’a pas "
            f"acceptée : il vous répond à {values.email.strip()} pour le paiement et l’envoi."
        }

    @app.get("/api/public/shipping")
    def public_shipping():
        return shipping_config(notifier)

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
                "SELECT email,display_name,pending_email FROM users WHERE id=?", (user["id"],)
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
            current = db.execute("SELECT email,pending_email FROM users WHERE id=?", (user["id"],)).fetchone()
            pending = email if email.casefold() != current["email"].casefold() else ""
            if pending != current["pending_email"]:
                db.execute("DELETE FROM password_links WHERE user_id=?", (user["id"],))
            # The requested mailbox becomes the login only after proof by link.
            db.execute(
                "UPDATE users SET pending_email=?,display_name=? WHERE id=?",
                (pending, values.display_name.strip(), user["id"]),
            )
            row = db.execute(
                "SELECT email,display_name,pending_email FROM users WHERE id=?", (user["id"],)
            ).fetchone()
        return dict(row)

    @app.get("/api/me/export")
    def me_export(user=Depends(client)):
        """Everything kept about the client, in a portable format (articles 15 and 20)."""
        with store.connect() as db:
            account = dict(
                db.execute(
                    "SELECT email,display_name,pending_email,email_verified_at,status,created_at,consent_at FROM users WHERE id=?",
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
        result = Privacy(store).forget(user["id"], "Suppression par la personne", preserve_unverified=True)
        response.delete_cookie("pokeprice_session", path="/")
        return {"ok": True, **({"unverified_requests": result["unverified_requests"]} if result.get("unverified_requests") else {})}

    @app.get("/api/me/requests")
    def my_requests(user=Depends(client)):
        return reservations.mine(user["id"])

    @app.post("/api/me/requests", status_code=201)
    def request_create(values: RequestCreate, user=Depends(client)):
        return reservations.create(
            user["id"],
            values.listing_ids,
            values.message,
            delivery=values.delivery,
            registered=values.registered,
            expected_prices=values.expected_prices,
        )

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

    register_settings(app, ctx)
    register_client_requests(app, ctx)

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

    register_statistics(app, ctx)


    register_auth(app, ctx)

    register_push(app, ctx)

    register_logout(app, ctx)
    register_users(app, ctx)

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

    app.state.moves = moves

    hooks = build_hooks(ctx, auto_checks)
    review_after_photo = hooks.review_after_photo
    register_capture(app, ctx, hooks)
    register_photo_batches(app, ctx, hooks)
    register_move_batches(app, ctx)

    register_intake(app, ctx, hooks)

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
        tasks: BackgroundTasks,
        version: int = Query(ge=1),
        side: Literal["front", "back"] = "front",
        user=Depends(editor),
    ):
        review_after_photo(tasks, copy_id)
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

    register_conditions(app, ctx)

    app.state.agent_review = review

    register_checks(app, ctx)


    register_listings(app, ctx)
    register_floor_requests(app, ctx)

    register_sales(app, ctx)
    register_exports(app, ctx)
    register_backup(app, ctx)

    from .todo import default_since, parse_since

    app.state.todo = todo

    @app.get("/api/todo")
    def todo_index(since: str = "", user=Depends(editor)):
        try:
            moment = parse_since(since) if since else default_since()
        except ValueError:
            raise ValueError("Date invalide : utilisez AAAA-MM-JJ.") from None
        return todo.brief(moment)

    # The management chat, V1 (assistant.py, decisions 0029 and 0034): it reads
    # through the closed tools and writes nothing. Off without its own key.
    from .routes.assistant import register_assistant

    app.state.assistant = assistant
    register_assistant(app, ctx)

    if agent_enabled:
        from .agent_api import install

        install(app, store)
    return app
