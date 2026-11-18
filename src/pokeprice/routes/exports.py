"""Export of the collection as CSV, JSON or HTML."""

import json
from typing import Literal

from fastapi import Depends, Response

from ..inventory_backup import export_csv, export_data, export_html
from .context import AppContext


def register_exports(app, ctx: AppContext):
    """Register the export route on ``app``, where ``create_app`` had it."""
    store = ctx.store
    staff = ctx.auth.staff

    @app.get("/api/export/{kind}")
    def export(kind: Literal["csv", "json", "html"], user=Depends(staff)):
        body = {
            "csv": export_csv,
            "json": lambda s: json.dumps(export_data(s), ensure_ascii=False, indent=2),
            "html": export_html,
        }[kind](store)
        media = {"csv": "text/csv", "json": "application/json", "html": "text/html"}[
            kind
        ]
        return Response(
            body,
            media_type=media,
            headers={
                "Content-Disposition": f'attachment; filename="pokeprice-collection.{kind}"'
            },
        )
