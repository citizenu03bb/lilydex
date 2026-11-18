"""Move batches: copies moved between binder slots, previewed, applied or undone."""

from fastapi import Body, Depends

from ..schemas import MoveApply, MovePreview, MoveUndo
from .context import AppContext


def register_move_batches(app, ctx: AppContext):
    """Register the move-batch routes on ``app``, where ``create_app`` had them."""
    store = ctx.store
    moves = ctx.moves
    editor = ctx.auth.editor

    @app.post("/api/move-batches", status_code=201)
    def move_batch_preview(values: MovePreview, user=Depends(editor)):
        if len({c.id for c in values.copies}) != len(values.copies):
            raise ValueError("Exemplaires répétés.")
        return moves.preview(
            user["id"],
            [c.model_dump() for c in values.copies],
            values.album_id,
            mode=values.mode,
            start_page=values.start_page,
            start_position=values.start_position,
            slots=values.slots,
            reason=values.reason,
        )

    @app.get("/api/move-batches")
    def move_batch_list(user=Depends(editor)):
        with store.connect() as db:
            return [
                moves.get(db, r[0], user["id"])
                for r in db.execute(
                    "SELECT id FROM move_batches WHERE owner_id=? ORDER BY created_at DESC LIMIT 20",
                    (user["id"],),
                )
            ]

    @app.get("/api/move-batches/{jid}")
    def move_batch_get(jid: str, user=Depends(editor)):
        with store.connect() as db:
            return moves.get(db, jid, user["id"])

    @app.post("/api/move-batches/{jid}/apply")
    def move_batch_apply(
        jid: str,
        values: MoveApply | None = Body(default=None),
        user=Depends(editor),
    ):
        return moves.apply(
            jid,
            user["id"],
            user["username"],
            reason=values.reason if values else None,
            allow_collisions=bool(values and values.allow_collisions),
        )

    @app.post("/api/move-batches/{jid}/undo")
    def move_batch_undo(
        jid: str,
        values: MoveUndo | None = Body(default=None),
        user=Depends(editor),
    ):
        return moves.undo(
            jid,
            user["id"],
            user["username"],
            reason=values.reason if values else None,
        )
