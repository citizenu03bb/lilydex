import sys

import pytest
from fastapi.testclient import TestClient

from pokeprice.manage import main


@pytest.mark.parametrize("host", ["127.0.0.1", "192.0.2.10"])
def test_serve_accepts_same_origin_registration_on_selected_interface(
    tmp_path, monkeypatch, host
):
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
    origin = "http://" + host + ":3820"
    with TestClient(captured["app"], base_url=origin) as client:
        assert client.get("/api/setup").json() == {"required": True}
        response = client.post(
            "/api/setup",
            headers={"Origin": origin},
            json={"username": "registration-test", "password": "Collection-test-2026!"},
        )
        assert response.status_code == 200 and response.json()["role"] == "admin"
        assert client.get("/api/session").json()["username"] == "registration-test"
        assert client.get("/api/setup").json() == {"required": False}
        assert client.get("/", headers={"Host": "outside.example"}).status_code == 400
