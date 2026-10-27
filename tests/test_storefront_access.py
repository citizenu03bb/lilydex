import sqlite3
import uuid

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from pokeprice.inventory import SCHEMA_VERSION, Store
from pokeprice.webapp import create_app, password_hash

# Routes reachable without a management account. Any new route outside this list
# and outside the storefront prefixes must depend on `staff`.
PUBLIC = {
    ("GET", "/"),
    ("GET", "/assets/{name}"),
    ("GET", "/favicon.ico"),
    ("GET", "/vitrine"),
    ("GET", "/carte/{listing_id}"),
    ("GET", "/en"),
    ("GET", "/en/"),
    ("GET", "/en/carte/{listing_id}"),
    ("GET", "/en/a-propos"),
    ("GET", "/gestion"),
    ("GET", "/a-propos"),
    ("GET", "/health"),
    ("GET", "/api/setup"),
    ("POST", "/api/setup"),
    ("POST", "/api/login"),
    ("GET", "/api/session"),
    ("POST", "/api/logout"),
}
STOREFRONT = ("/api/public/", "/api/me/", "/api/me")
PASSWORD = "Collection-client-2026!"


def dependencies(dependant):
    for dependency in dependant.dependencies:
        yield dependency.call.__name__
        yield from dependencies(dependency)


def api_routes(routes):
    # Newer FastAPI keeps included routers lazy; never silently skip a branch.
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        else:
            nested = getattr(route, "original_router", None)
            assert nested is not None, f"Unexamined route type: {type(route)}"
            yield from api_routes(nested.routes)


def add_account(store, username, role, status):
    with store.connect(write=True) as db:
        db.execute(
            "INSERT INTO users(id,username,password_hash,role,created_at,status) "
            "VALUES(?,?,?,?,?,?)",
            (str(uuid.uuid4()), username, password_hash(PASSWORD), role, "2026-10-16T00:00:00+00:00", status),
        )


def test_every_management_route_requires_staff(tmp_path):
    app = create_app(tmp_path / "inventory")
    assert app.openapi_url is None and app.docs_url is None and app.redoc_url is None
    routes = list(api_routes(app.routes))
    unguarded = [
        (method, route.path)
        for route in routes
        for method in route.methods
        if not (
            "agent_principal" in set(dependencies(route.dependant))
            if route.path.startswith("/api/agent/v1/")
            else "staff" in set(dependencies(route.dependant))
        )
        and (method, route.path) not in PUBLIC
        and not route.path.startswith(STOREFRONT)
    ]
    assert unguarded == []


def test_client_accounts_never_reach_management(tmp_path):
    store = Store(tmp_path / "inventory")
    with TestClient(create_app(store.root)) as admin:
        assert admin.post("/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}).status_code == 200
    add_account(store, "client", "client", "active")
    add_account(store, "waiting", "client", "pending")
    add_account(store, "refused", "client", "refused")
    with TestClient(create_app(store.root)) as visitor:
        login = visitor.post("/api/login", json={"username": "client", "password": PASSWORD})
        assert login.status_code == 200 and login.json()["role"] == "client"
        assert visitor.get("/api/session").json()["role"] == "client"
        for path in ("/api/copies", "/api/summary", "/api/sales", "/api/users", "/api/export/json"):
            assert visitor.get(path).status_code == 403, path
        assert visitor.post("/api/logout").status_code == 200
    with TestClient(create_app(store.root)) as visitor:
        pending = visitor.post("/api/login", json={"username": "waiting", "password": PASSWORD})
        assert pending.status_code == 403 and "attente" in pending.json()["detail"]
        assert "pokeprice_session" not in visitor.cookies
        assert visitor.post("/api/login", json={"username": "waiting", "password": "Mauvais-mot-2026!"}).status_code == 401
        assert visitor.post("/api/login", json={"username": "refused", "password": PASSWORD}).status_code == 401
        assert visitor.get("/api/session").status_code == 401


def test_a_session_ends_when_the_account_is_no_longer_active(tmp_path):
    store = Store(tmp_path / "inventory")
    add_account(store, "client", "client", "active")
    with TestClient(create_app(store.root)) as visitor:
        assert visitor.post("/api/login", json={"username": "client", "password": PASSWORD}).status_code == 200
        with store.connect(write=True) as db:
            db.execute("UPDATE users SET status='refused' WHERE username='client'")
        assert visitor.get("/api/session").status_code == 401


def downgrade_users_to_schema14(store):
    """Rebuild the users table as schema 14 had it, to replay the migration."""
    with sqlite3.connect(store.database) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.executescript(
            """
            CREATE TABLE users_v14(id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','editor','reader')),
                created_at TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0);
            INSERT INTO users_v14 SELECT id,username,password_hash,role,created_at,disabled FROM users;
            DROP TABLE users;
            ALTER TABLE users_v14 RENAME TO users;
            PRAGMA user_version=14;
            """
        )


def test_schema_15_keeps_accounts_sessions_and_adds_clients(tmp_path):
    store = Store(tmp_path / "inventory")
    with TestClient(create_app(store.root)) as admin:
        assert admin.post("/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}).status_code == 200
        assert admin.post("/api/users", json={"username": "lily", "password": "Collection-lily-2026!", "role": "editor"}).status_code == 201
    downgrade_users_to_schema14(store)
    with sqlite3.connect(store.database) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO users(id,username,password_hash,role,created_at) VALUES('x','c','h','client','t')")
        before = db.execute("SELECT id,username,password_hash,role,created_at,disabled FROM users ORDER BY username").fetchall()
        sessions = db.execute("SELECT token_hash,user_id FROM sessions").fetchall()
    assert len(before) == 2 and sessions

    migrated = Store(store.root)
    with migrated.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION >= 15
        after = db.execute("SELECT id,username,password_hash,role,created_at,disabled FROM users ORDER BY username").fetchall()
        assert [tuple(r) for r in after] == before
        assert {r[0] for r in db.execute("SELECT status FROM users")} == {"active"}
        assert [tuple(r) for r in db.execute("SELECT token_hash,user_id FROM sessions")] == sessions
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert list((tmp_path / "backups").glob("before-schema*-from14-*.sqlite3"))
    add_account(migrated, "client", "client", "pending")
    add_account(migrated, "second", "client", "pending")  # several accounts without e-mail
    with migrated.connect(write=True) as db:
        db.execute("UPDATE users SET email='Client@Example.org' WHERE username='client'")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE users SET email='client@example.org' WHERE username='second'")
