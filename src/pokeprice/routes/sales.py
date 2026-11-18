"""Sales routes of the management: the ledger, a sale's edits and its listing draft."""

from pathlib import Path

from fastapi import Depends
from fastapi.responses import FileResponse

from ..inventory import cents
from ..schemas import SaleCreate, SalePatch
from .context import AppContext


def register_sales(app, ctx: AppContext):
    """Register the sales routes on ``app``, where ``create_app`` had them."""
    store = ctx.store
    staff = ctx.auth.staff
    editor = ctx.auth.editor

    @app.get("/api/sales")
    def sales(user=Depends(staff)):
        return store.sales()

    @app.post("/api/sales", status_code=201)
    def sale_create(values: SaleCreate, user=Depends(editor)):
        data = values.model_dump(
            exclude={
                "copy_ids",
                "amount_eur",
                "asking_eur",
                "target_eur",
                "minimum_eur",
            }
        )
        data["amount_cents"] = cents(values.amount_eur)
        for key in ("asking", "target", "minimum"):
            data[key + "_cents"] = cents(getattr(values, key + "_eur"))
        return {"id": store.create_sale(data, values.copy_ids, user["username"])}

    @app.patch("/api/sales/{sale_id}")
    def sale_patch(sale_id: str, values: SalePatch, user=Depends(editor)):
        changes = values.model_dump(
            exclude_unset=True, exclude={"expected_version", "reason"}
        )
        if any(
            v is None and k not in ("asking_eur", "target_eur", "minimum_eur")
            for k, v in changes.items()
        ):
            raise ValueError("Champ vide non autorisé.")
        for field in list(changes):
            if field.endswith("_eur"):
                changes[field[:-4] + "_cents"] = cents(changes.pop(field))
        return store.update_sale(
            sale_id, changes, values.expected_version, user["username"], values.reason
        )

    @app.get("/api/sales/{sale_id}/listing-package")
    def listing_package(sale_id: str, user=Depends(editor)):
        import shutil
        import tempfile

        from starlette.background import BackgroundTask

        from ..listing_package import package

        folder = Path(tempfile.mkdtemp(prefix="pokeprice-listing-"))
        target = folder / "annonce.zip"
        try:
            package(store, sale_id, target)
        except Exception:
            shutil.rmtree(folder)
            raise
        return FileResponse(
            target,
            filename="pokeprice-brouillon-annonce.zip",
            media_type="application/zip",
            background=BackgroundTask(shutil.rmtree, folder),
        )
