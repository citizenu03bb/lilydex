"""The storefront's public API: search, sign-up, quote, guest requests, listings and photos."""

import secrets
from decimal import Decimal
from typing import Literal

from fastapi import Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse

from ..inventory import cents
from ..passwords import password_hash
from ..reservations import shipping_config
from ..schemas import BasketQuote, GuestRequest, PasswordSet, Signup
from .context import AppContext


def register_public_search(app, ctx: AppContext):
    """Register the storefront search, where ``create_app`` had them."""
    storefront = ctx.storefront
    public_rate = ctx.limits.public_rate

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


def register_public_signup(app, ctx: AppContext):
    """Register the sign-up and the basket quote, where ``create_app`` had them."""
    reservations = ctx.reservations
    signups = ctx.limits.signups
    client_of = ctx.limits.client_of
    public_rate = ctx.limits.public_rate

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


def register_public_requests(app, ctx: AppContext):
    """Register guest requests, the shipping rates and the password link, where ``create_app`` had them."""
    store = ctx.store
    notifier = ctx.notifier
    reservations = ctx.reservations
    guests = ctx.limits.guests
    client_of = ctx.limits.client_of
    public_rate = ctx.limits.public_rate
    issue_session = ctx.auth.issue_session

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


def register_public_listing(app, ctx: AppContext, count_visit):
    """Register a published listing and its photos, where ``create_app`` had them."""
    storefront = ctx.storefront
    public_rate = ctx.limits.public_rate

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
        size: Literal["full", "thumb", "grid1", "grid2", "grid3", "view", "view2"] = "thumb",
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
