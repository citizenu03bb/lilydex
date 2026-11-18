"""Signing in and out: first-run setup, login, session and logout.

The health probe registers here too: it has always sat between the two setup
routes, and the route table keeps that order.
"""

import hashlib

from fastapi import Depends, HTTPException, Request, Response

from ..inventory import Conflict
from ..passwords import add_user, has_admin, password_hash, password_outdated, password_valid
from ..schemas import Credentials, UserCreate
from .context import AppContext


def register_auth(app, ctx: AppContext):
    """Register setup, health, login and session routes on ``app``, where ``create_app`` had them."""
    store = ctx.store
    failures = ctx.limits.failures
    client_of = ctx.limits.client_of
    dummy_hash = ctx.auth.dummy_hash
    current_user = ctx.auth.current_user
    issue_session = ctx.auth.issue_session

    @app.get("/api/setup")
    def setup_state():
        with store.connect() as db:
            return {"required": not has_admin(db)}

    @app.get("/health")
    def health():
        with store.connect() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.post("/api/setup")
    def setup(values: Credentials, response: Response):
        with store.connect(write=True) as db:
            # Client sign-ups do not count: only an admin closes the setup.
            if has_admin(db):
                raise Conflict("Le compte initial existe déjà.")
            user = add_user(db, UserCreate(**values.model_dump(), role="admin"))
            issue_session(db, user, response)
            return user

    @app.post("/api/login")
    def login(values: Credentials, request: Request, response: Response):
        key = client_of(request)
        target = values.username.casefold()
        # Reserve the attempt before hashing to account for simultaneous requests.
        if not failures.hit(key, target):
            raise HTTPException(
                429, "Trop de tentatives. Réessayez dans cinq minutes."
            )
        with store.connect(write=True) as db:
            row = db.execute(
                "SELECT * FROM users WHERE username=?", (values.username,)
            ).fetchone()
            valid = password_valid(
                values.password, row["password_hash"] if row else dummy_hash
            )
            if not valid or not row or row["disabled"] or row["status"] == "refused":
                raise HTTPException(401, "Identifiants incorrects.")
            if row["status"] == "pending":
                # Only said after a correct password: it reveals nothing to a guesser.
                raise HTTPException(403, "Compte en attente de validation.")
            if password_outdated(row["password_hash"]):
                # The password is only known here: strengthen old hashes as owners log in.
                db.execute(
                    "UPDATE users SET password_hash=? WHERE id=?",
                    (password_hash(values.password), row["id"]),
                )
            user = {k: row[k] for k in ("id", "username", "role")}
            issue_session(db, user, response)
        # Forgive only this account's typos: logging into one's own account
        # must not reset guesses aimed at another one from the same address.
        failures.forgive(key, target)
        return user

    @app.get("/api/session")
    def session(user=Depends(current_user)):
        return user


def register_logout(app, ctx: AppContext):
    """Register the logout route on ``app``, where ``create_app`` had it."""
    store = ctx.store
    current_user = ctx.auth.current_user

    @app.post("/api/logout")
    def logout(request: Request, response: Response, user=Depends(current_user)):
        with store.connect(write=True) as db:
            db.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (
                    hashlib.sha256(
                        request.cookies["pokeprice_session"].encode()
                    ).hexdigest(),
                ),
            )
        response.delete_cookie("pokeprice_session", path="/")
        return {"ok": True}
