"""Read side of the stored copies: summary, lists, detail, reference audit, images."""

import json
from typing import Literal

from fastapi import Depends, HTTPException, Query
from fastapi.responses import FileResponse

from ..condition_assessment import assessment_rows
from ..edition_check import propose_edition
from ..inventory import cents
from ..market_product import cached_set_code
from ..pricing import binding_market_url, cardmarket_search_url, cardmarket_url
from ..variant_pricing import category
from ..verification import check_rows, propose_variant
from .context import AppContext


def register_summary(app, ctx: AppContext):
    """Register the summary, where ``create_app`` had it."""
    store = ctx.store
    staff = ctx.auth.staff

    @app.get("/api/summary")
    def summary(
        threshold: float = Query(default=10, ge=0.01, le=10000),
        user=Depends(staff),
    ):
        return store.summary(threshold_cents=cents(threshold))


def register_copy_list(app, ctx: AppContext):
    """Register the copy list, where ``create_app`` had it."""
    store = ctx.store
    staff = ctx.auth.staff

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


def register_copy_detail(app, ctx: AppContext):
    """Register a copy's detail, where ``create_app`` had it."""
    store = ctx.store
    edition_checks = ctx.edition_checks
    pricing = ctx.pricing
    staff = ctx.auth.staff

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


def register_reference_audit(app, ctx: AppContext):
    """Register the reference audit, where ``create_app`` had it."""
    store = ctx.store
    staff = ctx.auth.staff

    @app.get("/api/reference-audit")
    def reference_audit(user=Depends(staff)):
        return store.reference.audit()


def register_reference_replay(app, ctx: AppContext):
    """Register the replay of a reference decision, where ``create_app`` had it."""
    store = ctx.store
    staff = ctx.auth.staff

    @app.get("/api/reference-decisions/{decision_id}/replay")
    def reference_replay(decision_id: int, user=Depends(staff)):
        return store.reference.replay(decision_id)


def register_editions(app, ctx: AppContext):
    """Register the grouped editions, where ``create_app`` had it."""
    store = ctx.store
    staff = ctx.auth.staff

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


def register_copy_images(app, ctx: AppContext):
    """Register a copy's catalogue image and photo reads, where ``create_app`` had it."""
    store = ctx.store
    catalogue_images = ctx.catalogue_images
    staff = ctx.auth.staff

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
