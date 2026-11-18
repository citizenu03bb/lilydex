"""Web Push routes of the management: the public key and each phone's subscription."""

from fastapi import Depends, HTTPException

from ..notifications import subscribe, subscribed, unsubscribe
from ..schemas import PushEndpoint, PushSubscription
from .context import AppContext


def register_push(app, ctx: AppContext):
    """Register the push routes on ``app``, where ``create_app`` had them."""
    store = ctx.store
    web_push = ctx.web_push
    staff = ctx.auth.staff

    # Web Push of the management (decision 0033): the public key, then one
    # subscription per phone, owned by the account that took it.
    @app.get("/api/push")
    def push_settings(user=Depends(staff)):
        return {"enabled": web_push is not None,
                "public_key": web_push.public_key if web_push else None}

    @app.post("/api/push/subscriptions", status_code=201)
    def push_subscribe(values: PushSubscription, user=Depends(staff)):
        if web_push is None:
            raise HTTPException(409, "Notifications non configurées sur le serveur.")
        subscribe(store, user["id"], values.endpoint, values.keys.p256dh, values.keys.auth)
        return {"subscribed": True}

    @app.post("/api/push/subscriptions/check")
    def push_check(values: PushEndpoint, user=Depends(staff)):
        return {"subscribed": subscribed(store, user["id"], values.endpoint)}

    @app.delete("/api/push/subscriptions")
    def push_unsubscribe(values: PushEndpoint, user=Depends(staff)):
        return {"removed": unsubscribe(store, user["id"], values.endpoint)}
