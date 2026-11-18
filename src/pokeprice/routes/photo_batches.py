"""Photo batches: many photos previewed, then applied or undone together."""

from typing import Literal

from fastapi import BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from ..schemas import BatchApply, BatchPreview
from .context import AppContext
from .hooks import Hooks


def register_photo_batches(app, ctx: AppContext, hooks: Hooks):
    """Register the photo-batch routes on ``app``, where ``create_app`` had them."""
    store = ctx.store
    batches = ctx.batches
    editor = ctx.auth.editor
    read_after_intake = hooks.read_after_intake
    review_after_photo = hooks.review_after_photo

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

    @app.post("/api/photo-batches/page", status_code=201)
    async def batch_page_preview(
        request: Request,
        album_id: str = Query(min_length=1, max_length=100),
        page: int = Query(ge=1, le=1000),
        rotation: Literal["auto", "0", "90", "180", "270"] = "auto",
        user=Depends(editor),
    ):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            # Caddy refuses bodies over 9 MB: the same limit as the other photos.
            if len(data) > 8 * 1024 * 1024:
                raise HTTPException(413, "Photo limitée à 8 Mo.")
        # Slicing a 24-megapixel page takes seconds: off the event loop.
        return await run_in_threadpool(
            batches.preview_page,
            user["id"],
            album_id,
            page,
            bytes(data),
            rotation=rotation,
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
        item = next(
            (
                i
                for i in job["data"]["items"]
                if copy_id in (i.get("id"), i.get("key"), str(i.get("position")))
            ),
            None,
        )
        if not item or not item.get(view):
            raise KeyError("Photo absente.")
        return FileResponse(store.photos / item[view], media_type="image/jpeg")

    @app.post("/api/photo-batches/{jid}/apply")
    def batch_apply(
        jid: str, values: BatchApply, tasks: BackgroundTasks, user=Depends(editor)
    ):
        selected = values.positions or values.copy_ids
        result = batches.apply(jid, user["id"], user["username"], selected)
        if result["data"].get("kind") == "page":
            for item in result["data"]["items"]:
                if not item.get("applied_version") or not item.get("id"):
                    continue
                if item.get("action") == "create":
                    read_after_intake(
                        tasks,
                        {"id": item["id"], "photo": item.get("result")},
                        user,
                    )
                elif item.get("action") == "update":
                    review_after_photo(tasks, item["id"])
        return result

    @app.post("/api/photo-batches/{jid}/undo")
    def batch_undo(jid: str, user=Depends(editor)):
        return batches.apply(jid, user["id"], user["username"], [], undo=True)
