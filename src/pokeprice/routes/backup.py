"""Backup routes of the management: daily status, a forced run and the download."""

from pathlib import Path

from fastapi import Depends
from fastapi.responses import FileResponse

from ..inventory_backup import backup
from .context import AppContext


def register_backup(app, ctx: AppContext):
    """Register the backup routes on ``app``, where ``create_app`` had them."""
    store = ctx.store
    admin = ctx.auth.admin

    @app.get("/api/backup/status")
    def backup_status(user=Depends(admin)):
        from ..daily_backup import public_status

        return public_status(store)

    @app.post("/api/backup/daily")
    def backup_daily(user=Depends(admin)):
        from ..daily_backup import daily, public_status

        daily(store, force=True)
        return public_status(store)

    @app.get("/api/backup")
    def download_backup(user=Depends(admin)):
        import tempfile

        from starlette.background import BackgroundTask

        folder = Path(tempfile.mkdtemp(prefix="pokeprice-backup-"))
        target = folder / "collection.zip"
        try:
            backup(store, target)
        except Exception:
            import shutil

            shutil.rmtree(folder)
            raise
        import shutil

        return FileResponse(
            target,
            filename="pokeprice-backup.zip",
            media_type="application/zip",
            background=BackgroundTask(shutil.rmtree, folder),
        )
