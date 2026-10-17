import sys

import pytest
from fastapi.testclient import TestClient

from pokeprice.inventory import Store
from pokeprice.manage import main
from pokeprice.webapp import UserCreate, add_user


CREDENTIALS = {"username": "registration-test", "password": "Collection-test-2026!"}


def serve(tmp_path, monkeypatch, host):
    uvicorn = pytest.importorskip("uvicorn")
    captured = {}
    monkeypatch.setattr(
        uvicorn, "run", lambda app, **options: captured.update(app=app, **options)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["pokeprice-manage", "--data", str(tmp_path), "serve", "--host", host],
    )
    main()
    assert captured["host"] == host and captured["port"] == 3820
    return captured["app"]


def test_serve_accepts_same_origin_registration_on_loopback(tmp_path, monkeypatch):
    origin = "http://127.0.0.1:3820"
    with TestClient(serve(tmp_path, monkeypatch, "127.0.0.1"), base_url=origin) as client:
        assert client.get("/api/setup").json() == {"required": True}
        response = client.post("/api/setup", headers={"Origin": origin}, json=CREDENTIALS)
        assert response.status_code == 200 and response.json()["role"] == "admin"
        assert client.get("/api/session").json()["username"] == "registration-test"
        assert client.get("/api/setup").json() == {"required": False}
        assert client.get("/", headers={"Host": "outside.example"}).status_code == 400


def test_serve_on_a_network_interface_needs_a_local_admin(tmp_path, monkeypatch):
    # Otherwise the first visitor on the network would become admin.
    with pytest.raises(ValueError, match="administrateur"):
        serve(tmp_path, monkeypatch, "192.0.2.10")
    with Store(tmp_path).connect(write=True) as db:
        add_user(db, UserCreate(**CREDENTIALS, role="admin"))
    origin = "http://192.0.2.10:3820"
    with TestClient(serve(tmp_path, monkeypatch, "192.0.2.10"), base_url=origin) as client:
        assert client.get("/api/setup").json() == {"required": False}
        response = client.post("/api/login", headers={"Origin": origin}, json=CREDENTIALS)
        assert response.status_code == 200 and response.json()["role"] == "admin"
        assert client.get("/", headers={"Host": "outside.example"}).status_code == 400
