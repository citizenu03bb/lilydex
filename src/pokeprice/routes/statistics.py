"""The audience statistics of the management (Statistiques): visits, sign-ups, requests."""

from fastapi import Depends, Query

from .context import AppContext


def register_statistics(app, ctx: AppContext):
    """Register the audience report on ``app``, where ``create_app`` had it."""
    store = ctx.store
    audience = ctx.audience
    storefront = ctx.storefront
    admin = ctx.auth.admin

    @app.get("/api/audience")
    def audience_report(
        days: int = Query(default=30, ge=7, le=365), user=Depends(admin)
    ):
        report = audience.report(days)
        for row in report["listings"]:
            try:
                listing = storefront.get(row["id"])
                row["title"] = listing["title"] or " · ".join(
                    i["name"] for i in listing["items"]
                )
            except KeyError:
                row["title"] = ""  # Sold or withdrawn since.
        start = report["from"]
        with store.connect() as db:
            report["signups"] = db.execute(
                "SELECT COUNT(*) FROM users WHERE role='client' AND created_at>=?", (start,)
            ).fetchone()[0]
            report["requests"] = db.execute(
                "SELECT COUNT(*) FROM requests WHERE created_at>=?", (start,)
            ).fetchone()[0]
        return report
