"""Intake drafts: a photo or a stored copy identified, then saved."""

import json

from fastapi import BackgroundTasks, Depends, HTTPException, Request, Response

from ..intake import normalize_photo
from ..inventory import Conflict
from ..photo_processing import parse_guide
from ..schemas import (
    IntakeEntry,
    IntakeQuery,
    IntakeSave,
    PhotoAttachment,
    PhotoOptions,
    intake_values,
)
from .context import AppContext
from .hooks import Hooks


def register_intake(app, ctx: AppContext, hooks: Hooks):
    """Register the intake routes on ``app``, where ``create_app`` had them."""
    store = ctx.store
    intake = ctx.intake
    staff = ctx.auth.staff
    editor = ctx.auth.editor
    read_after_intake = hooks.read_after_intake
    review_after_photo = hooks.review_after_photo

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
        copy_id: str, values: PhotoAttachment, tasks: BackgroundTasks, user=Depends(editor)
    ):
        review_after_photo(tasks, copy_id)
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
