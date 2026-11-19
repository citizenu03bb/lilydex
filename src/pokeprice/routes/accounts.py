"""A client's own account and requests, and the administration of client accounts."""

import json

from fastapi import Depends, HTTPException, Response

from ..brand import site_slug
from ..inventory import Conflict, now
from ..passwords import password_valid
from ..privacy import Privacy
from ..reservations import valid_email
from ..schemas import ClientPatch, PasswordCheck, Profile, RequestCreate, RequestVersion
from .context import AppContext


def register_accounts(app, ctx: AppContext):
    """Register a client's own account and requests, and the client administration, where ``create_app`` had them."""
    store = ctx.store
    reservations = ctx.reservations
    client = ctx.auth.client
    admin = ctx.auth.admin

    @app.get("/api/me")
    def me(user=Depends(client)):
        with store.connect() as db:
            row = db.execute(
                "SELECT email,display_name,pending_email FROM users WHERE id=?", (user["id"],)
            ).fetchone()
        return dict(row)

    def own_password(db, user, password):
        """Changing or deleting one's account asks for the password again."""
        row = db.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
        if not password_valid(password, row["password_hash"]):
            raise HTTPException(403, "Mot de passe incorrect.")

    @app.patch("/api/me")
    def me_update(values: Profile, user=Depends(client)):
        email = valid_email(values.email)
        with store.connect(write=True) as db:
            own_password(db, user, values.password)
            taken = db.execute(
                "SELECT 1 FROM users WHERE (email=? OR username=?) AND id<>?",
                (email, email, user["id"]),
            ).fetchone()
            if taken:
                raise Conflict("Cette adresse est déjà utilisée par un autre compte.")
            current = db.execute("SELECT email,pending_email FROM users WHERE id=?", (user["id"],)).fetchone()
            pending = email if email.casefold() != current["email"].casefold() else ""
            if pending != current["pending_email"]:
                db.execute("DELETE FROM password_links WHERE user_id=?", (user["id"],))
            # The requested mailbox becomes the login only after proof by link.
            db.execute(
                "UPDATE users SET pending_email=?,display_name=? WHERE id=?",
                (pending, values.display_name.strip(), user["id"]),
            )
            row = db.execute(
                "SELECT email,display_name,pending_email FROM users WHERE id=?", (user["id"],)
            ).fetchone()
        return dict(row)

    @app.get("/api/me/export")
    def me_export(user=Depends(client)):
        """Everything kept about the client, in a portable format (articles 15 and 20)."""
        with store.connect() as db:
            account = dict(
                db.execute(
                    "SELECT email,display_name,pending_email,email_verified_at,status,created_at,consent_at FROM users WHERE id=?",
                    (user["id"],),
                ).fetchone()
            )
        body = {"exported_at": now(), "account": account, "requests": reservations.mine(user["id"])}
        return Response(
            json.dumps(body, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{site_slug()}-mes-donnees.json"'},
        )

    @app.post("/api/me/delete")
    def me_delete(values: PasswordCheck, response: Response, user=Depends(client)):
        with store.connect() as db:
            own_password(db, user, values.password)
        result = Privacy(store).forget(user["id"], "Suppression par la personne", preserve_unverified=True)
        response.delete_cookie("pokeprice_session", path="/")
        return {"ok": True, **({"unverified_requests": result["unverified_requests"]} if result.get("unverified_requests") else {})}

    @app.get("/api/me/requests")
    def my_requests(user=Depends(client)):
        return reservations.mine(user["id"])

    @app.post("/api/me/requests", status_code=201)
    def request_create(values: RequestCreate, user=Depends(client)):
        return reservations.create(
            user["id"],
            values.listing_ids,
            values.message,
            delivery=values.delivery,
            registered=values.registered,
            expected_prices=values.expected_prices,
        )

    @app.post("/api/me/requests/{request_id}/cancel")
    def request_cancel(request_id: str, values: RequestVersion, user=Depends(client)):
        return reservations.cancel(user["id"], request_id, values.expected_version)

    @app.get("/api/clients")
    def client_index(user=Depends(admin)):
        return reservations.clients()

    @app.patch("/api/clients/{client_id}")
    def client_patch(client_id: str, values: ClientPatch, user=Depends(admin)):
        return reservations.set_client(client_id, values.status, values.disabled)

    @app.post("/api/clients/{client_id}/password-link", status_code=201)
    def client_password_link(client_id: str, user=Depends(admin)):
        return reservations.password_link(client_id, user["username"])
