"""Storefront listings of the management: publish, read and withdraw."""

from typing import Literal

from fastapi import Depends

from ..inventory import Conflict, cents
from ..schemas import CopyRemoval, ListingCreate, ListingPrice
from .context import AppContext


def register_listings(app, ctx: AppContext):
    """Register the listing routes on ``app``, where ``create_app`` had them."""
    store = ctx.store
    listings = ctx.listings
    staff = ctx.auth.staff
    editor = ctx.auth.editor

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
