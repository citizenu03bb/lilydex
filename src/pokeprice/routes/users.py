"""Management accounts, administered by an administrator."""

import sqlite3

from fastapi import Depends

from ..inventory import Conflict
from ..passwords import add_user
from ..schemas import UserCreate, UserPatch
from .context import AppContext


def register_users(app, ctx: AppContext):
    """Register the account routes on ``app``, where ``create_app`` had them."""
    store = ctx.store
    admin = ctx.auth.admin

    @app.get("/api/users")
    def users(user=Depends(admin)):
        with store.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    # Storefront clients have their own screen (/api/clients).
                    "SELECT id,username,role,disabled,created_at FROM users WHERE role!='client' ORDER BY username"
                )
            ]

    @app.post("/api/users", status_code=201)
    def user_create(values: UserCreate, user=Depends(admin)):
        with store.connect(write=True) as db:
            try:
                return add_user(db, values)
            except sqlite3.IntegrityError:
                raise Conflict("Ce compte existe déjà.")

    @app.patch("/api/users/{user_id}")
    def user_patch(user_id: str, values: UserPatch, user=Depends(admin)):
        with store.connect(write=True) as db:
            row = db.execute(
                "SELECT * FROM users WHERE id=? AND role!='client'", (user_id,)
            ).fetchone()
            if not row:
                raise KeyError("Compte introuvable.")
            if (
                row["role"] == "admin"
                and not row["disabled"]
                and (values.role != "admin" or values.disabled)
            ):
                count = db.execute(
                    "SELECT COUNT(*) FROM users WHERE role='admin' AND disabled=0"
                ).fetchone()[0]
                if count <= 1:
                    raise Conflict("Conservez au moins un administrateur actif.")
            db.execute(
                "UPDATE users SET role=?,disabled=? WHERE id=?",
                (values.role, values.disabled, user_id),
            )
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        return {"ok": True}
