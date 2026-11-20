"""Binder imports (decision 0047): administrators only, the work done elsewhere.

The web process records imports and resumable uploads; the background worker
(``pokeprice-import.service``) cuts, reads and creates the copies. Nothing here
calls Gemini or the catalogue.
"""

from fastapi import Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from ..binder_import import CHUNK_BYTES, BinderImports, budget_from_env
from ..schemas import BinderImportCreate, BinderUpload, ReviewApplySettings
from .context import AppContext


def no_reading(*_args):
    raise RuntimeError("Le service web ne lit aucune carte : le processus de fond s'en charge.")


def register_binder_imports(app, ctx: AppContext):
    """Register the binder import routes on ``app``."""
    import os

    store = ctx.store
    admin = ctx.auth.admin
    imports = BinderImports(
        store, reader=no_reading, lookup=no_reading,
        default_budget_eur=budget_from_env(os.environ),
    )
    app.state.binder_imports = imports

    @app.get("/api/binder-imports")
    def binder_import_list(user=Depends(admin)):
        return imports.listing()

    @app.post("/api/binder-imports", status_code=201)
    def binder_import_create(values: BinderImportCreate, user=Depends(admin)):
        return imports.create(
            user["username"], album_id=values.album_id, album_name=values.album_name,
            grid=values.grid, budget_eur=values.budget_eur,
        )

    @app.get("/api/binder-imports/{import_id}")
    def binder_import_get(import_id: str, user=Depends(admin)):
        return imports.get(import_id)

    @app.post("/api/binder-imports/{import_id}/uploads", status_code=201)
    def binder_upload_begin(import_id: str, values: BinderUpload, user=Depends(admin)):
        return imports.begin_upload(
            import_id, values.page, values.position, values.size, values.sha256
        )

    @app.put("/api/binder-uploads/{upload_id}")
    async def binder_upload_chunk(
        upload_id: str,
        request: Request,
        offset: int = Query(ge=0, le=16 * 1024 * 1024),
        user=Depends(admin),
    ):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > CHUNK_BYTES * 2:
                raise HTTPException(413, "Morceau trop gros.")
        # The last chunk checks the fingerprint and writes the photo: off the loop.
        return await run_in_threadpool(imports.put_chunk, upload_id, offset, bytes(data))

    @app.post("/api/binder-imports/{import_id}/continue")
    def binder_import_continue(import_id: str, user=Depends(admin)):
        return imports.continue_budget(import_id, user["username"])

    @app.post("/api/binder-imports/{import_id}/close")
    def binder_import_close(import_id: str, user=Depends(admin)):
        return imports.close(import_id, user["username"])

    @app.post("/api/binder-imports/{import_id}/pages/{page}/pockets/{position}/empty")
    def binder_pocket_empty(import_id: str, page: int, position: int, user=Depends(admin)):
        return imports.mark_empty(import_id, page, position, user["username"])

    @app.get("/api/binder-imports/{import_id}/pages/{page}/pockets/{position}/photo")
    def binder_pocket_photo(import_id: str, page: int, position: int, user=Depends(admin)):
        from fastapi.responses import FileResponse

        with imports.connect() as db:
            found = db.execute(
                "SELECT photo FROM pockets WHERE import_id=? AND page=? AND position=?",
                (import_id, page, position),
            ).fetchone()
        if not found:
            raise KeyError("Pochette inconnue.")
        return FileResponse(
            store.photos / found[0], media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    # The review agent writes on imported pages only once the blind check passed.
    @app.get("/api/settings/agent-review-apply")
    def review_apply_settings(user=Depends(admin)):
        from ..agent_review import review_apply

        return {"apply": review_apply(store)}

    @app.put("/api/settings/agent-review-apply")
    def review_apply_update(values: ReviewApplySettings, user=Depends(admin)):
        from ..agent_review import set_review_apply

        return set_review_apply(store, values.apply, user["username"], values.reason)
