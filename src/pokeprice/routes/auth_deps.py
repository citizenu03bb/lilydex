"""The web application's authentication dependencies, built once per application.

``current_user`` reads the session cookie; ``staff``, ``client``, ``editor`` and
``admin`` narrow it by role. Their names are part of the route table: FastAPI
records each route's dependencies by function name.
"""

import hashlib
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request

from ..inventory import Store
from ..passwords import password_hash


@dataclass(frozen=True)
class Auth:
    """The session dependencies and helpers the routes share."""

    dummy_hash: str
    current_user: Callable[..., Any]
    staff: Callable[..., Any]
    client: Callable[..., Any]
    editor: Callable[..., Any]
    admin: Callable[..., Any]
    issue_session: Callable[..., Any]


def build_auth(store: Store, secure_cookie: bool) -> Auth:
    dummy_hash = password_hash("not-a-valid-user-password")

    def current_user(request: Request):
        token = request.cookies.get("pokeprice_session", "")
        hashed = hashlib.sha256(token.encode()).hexdigest()
        with store.connect() as db:
            row = db.execute(
                "SELECT u.id,u.username,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.disabled=0 AND u.status='active'",
                (hashed, int(time.time())),
            ).fetchone()
        if not row:
            raise HTTPException(401, "Connectez-vous pour consulter la collection.")
        return dict(row)

    def staff(user=Depends(current_user)):
        # Storefront clients never reach the management routes, even read-only ones.
        if user["role"] not in ("admin", "editor", "reader"):
            raise HTTPException(403, "Ce compte n'a pas accès à la gestion.")
        return user

    def client(user=Depends(current_user)):
        if user["role"] != "client":
            raise HTTPException(403, "Espace réservé aux comptes clients.")
        return user

    def editor(user=Depends(staff)):
        if user["role"] not in ("admin", "editor"):
            raise HTTPException(403, "Ce compte permet uniquement la consultation.")
        return user

    def admin(user=Depends(staff)):
        if user["role"] != "admin":
            raise HTTPException(403, "Administration requise.")
        return user

    def issue_session(db, user, response):
        token = secrets.token_urlsafe(32)
        db.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?)",
            (
                hashlib.sha256(token.encode()).hexdigest(),
                user["id"],
                int(time.time()) + 43200,
            ),
        )
        response.set_cookie(
            "pokeprice_session",
            token,
            max_age=43200,
            httponly=True,
            secure=secure_cookie,
            samesite="strict",
            path="/",
        )
    return Auth(
        dummy_hash=dummy_hash,
        current_user=current_user,
        staff=staff,
        client=client,
        editor=editor,
        admin=admin,
        issue_session=issue_session,
    )
