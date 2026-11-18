"""Capture sessions: a binder page entered card by card."""

from fastapi import BackgroundTasks, Depends

from ..schemas import CaptureCreate, CapturePatch, CaptureSave, intake_values
from .context import AppContext
from .hooks import Hooks


def register_capture(app, ctx: AppContext, hooks: Hooks):
    """Register the capture-session routes on ``app``, where ``create_app`` had them."""
    store = ctx.store
    capture = ctx.capture
    editor = ctx.auth.editor
    read_after_intake = hooks.read_after_intake

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
