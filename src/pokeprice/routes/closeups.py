"""Close-up shots in series (decision 0048): administrators only.

The queue is the review agent's verdict in simulation on the cards in scope; a
shot goes through the copy's photo path, then the card is read again and the
agent decides on it after the response.
"""

from typing import Literal

from fastapi import BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from ..closeups import Closeups, side_of
from ..schemas import CloseupScope
from .context import AppContext
from .copies import read_photo_body, save_copy_photo
from .hooks import Hooks


class CreaseAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: Literal["non", "pli", "enfoncement", "doute"]


def register_closeups(app, ctx: AppContext, hooks: Hooks):
    """Register the close-up series routes on ``app``."""
    store = ctx.store
    admin = ctx.auth.admin
    imports = getattr(app.state, "binder_imports", None)
    closeups = Closeups(store, ctx.review, grids=imports.grids if imports else None)
    app.state.closeups = closeups

    def scope(values: CloseupScope):
        return {
            "import_id": values.import_id or None,
            "album": values.album or None,
            "copy_ids": values.copy_ids or None,
        }

    @app.post("/api/closeups/queue")
    def closeup_queue(values: CloseupScope, tasks: BackgroundTasks, user=Depends(admin)):
        try:
            result = closeups.queue(**scope(values))
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        # A shot whose reading was lost (a restart) is read again now.
        for copy_id in result["resumed"]:
            hooks.in_background(tasks, closeups.after_shot, copy_id)
        return result

    @app.post("/api/closeups/results")
    def closeup_results(values: CloseupScope, user=Depends(admin)):
        return closeups.results(**scope(values))

    @app.put("/api/closeups/{copy_id}/shot")
    async def closeup_shot(
        copy_id: str,
        request: Request,
        tasks: BackgroundTasks,
        version: int = Query(ge=1),
        view: Literal["front", "back", "holo", "corner"] = "front",
        user=Depends(admin),
    ):
        data = await read_photo_body(request)
        result = save_copy_photo(
            store, copy_id, data, version, side_of(view), view == "holo", user["username"]
        )
        side = "photo" if side_of(view) == "front" else "back_photo"
        closeups.record_shot(copy_id, view, result[side], user["username"])
        hooks.in_background(tasks, closeups.after_shot, copy_id)
        return {"copy_id": copy_id, "version": result["version"], "view": view}

    @app.post("/api/closeups/{copy_id}/crease")
    def closeup_crease(copy_id: str, values: CreaseAnswer, tasks: BackgroundTasks, user=Depends(admin)):
        try:
            closeups.record_crease(copy_id, values.answer, user["username"])
        except KeyError as error:
            raise HTTPException(404, "Exemplaire introuvable.") from error
        # The agent decides again on the card with the answer.
        hooks.in_background(tasks, closeups.after_crease, copy_id)
        return {"copy_id": copy_id, "answer": values.answer}
