"""Administrator settings: the payment details, the anti-undercut margin and the lot rotation."""

from fastapi import Depends

from ..schemas import FloorMarginSettings, LotRotationSettings, PaymentSettings
from .context import AppContext


def register_settings(app, ctx: AppContext):
    """Register the settings routes on ``app``, where ``create_app`` had them."""
    store = ctx.store
    reservations = ctx.reservations
    admin = ctx.auth.admin

    @app.get("/api/settings/payment")
    def payment_settings(user=Depends(admin)):
        return reservations.payment()

    @app.put("/api/settings/payment")
    def payment_update(values: PaymentSettings, user=Depends(admin)):
        return reservations.set_payment(values.model_dump(), user["username"])

    # Decision 0042: only a signed-in administrator moves the anti-undercut margin.
    @app.get("/api/settings/floor-margin")
    def floor_margin_settings(user=Depends(admin)):
        from ..pricing import lot_margin_history, lot_max_margin

        return {"margin": lot_max_margin(store), "history": lot_margin_history(store)}

    @app.put("/api/settings/floor-margin")
    def floor_margin_update(values: FloorMarginSettings, user=Depends(admin)):
        from ..pricing import set_lot_max_margin

        return set_lot_max_margin(store, values.margin, user["username"])

    # Only a signed-in administrator sets how long an unsold tool-made lot stays online.
    @app.get("/api/settings/lot-rotation")
    def lot_rotation_settings(user=Depends(admin)):
        from ..lots.settings import lot_rotation_days, lot_rotation_history

        return {"days": lot_rotation_days(store), "history": lot_rotation_history(store)}

    @app.put("/api/settings/lot-rotation")
    def lot_rotation_update(values: LotRotationSettings, user=Depends(admin)):
        from ..lots.settings import set_lot_rotation_days

        return set_lot_rotation_days(store, values.days, user["username"])
