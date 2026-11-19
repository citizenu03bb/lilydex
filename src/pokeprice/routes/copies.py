"""The stored copies: summary, lists, detail, corrections, references, prices, photos."""

import io
import json
import warnings
from typing import Literal

from fastapi import BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from PIL import Image, ImageOps

from ..condition_assessment import assessment_rows
from ..edition_check import propose_edition
from ..inventory import Conflict, cents, now
from ..market_product import cached_set_code
from ..pricing import binding_market_url, cardmarket_search_url, cardmarket_url
from ..quote_ledger import select_transcription
from ..schemas import (
    AlbumCreate,
    BoundQuote,
    CardCreate,
    CardFields,
    CardPatch,
    ConditionRequest,
    CopyRemoval,
    MarketVerdict,
    OffersPaste,
    ReferenceDispute,
)
from ..variant_pricing import category
from ..verification import check_rows, propose_variant
from .context import AppContext
from .hooks import Hooks


def register_copies(app, ctx: AppContext):
    """Register the copy routes from the summary to the editions, where ``create_app`` had them."""
    store = ctx.store
    edition_checks = ctx.edition_checks
    market = ctx.market
    pricing = ctx.pricing
    variant_catalogue = ctx.variant_catalogue
    staff = ctx.auth.staff
    editor = ctx.auth.editor
    admin = ctx.auth.admin

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


def register_copy_images(app, ctx: AppContext, hooks: Hooks):
    """Register a copy's catalogue image and photo routes, where ``create_app`` had them."""
    store = ctx.store
    catalogue_images = ctx.catalogue_images
    staff = ctx.auth.staff
    editor = ctx.auth.editor
    review_after_photo = hooks.review_after_photo

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
