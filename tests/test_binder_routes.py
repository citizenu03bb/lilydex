"""The binder import routes: administrators only, uploads by chunks, no reading.

The worker's steps are run here by a test service on the same store.
"""

import hashlib

import pytest
from fastapi.testclient import TestClient
from test_binder_import import page_photo, service

from pokeprice.webapp import create_app

PASSWORD = "Collection-test-2026!"


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "inventory", auto_checks=False)) as client:
        client.post("/api/setup", json={"username": "pat", "password": PASSWORD})
        yield client


def send(client, import_id, page, data, position=0, chunk=200_000, drop_after=None):
    sha = hashlib.sha256(data).hexdigest()
    begin = {"page": page, "position": position, "size": len(data), "sha256": sha}
    state = client.post(f"/api/binder-imports/{import_id}/uploads", json=begin).json()
    sent = 0
    while not state["done"]:
        if drop_after is not None and sent == drop_after:
            # The phone drops: it announces the photo again and resumes there.
            state = client.post(f"/api/binder-imports/{import_id}/uploads", json=begin).json()
            drop_after = None
        offset = state["received"]
        response = client.put(
            f"/api/binder-uploads/{state['id']}?offset={offset}",
            content=data[offset:offset + chunk],
        )
        assert response.status_code == 200, response.text
        state = response.json()
        sent += 1
    return state


def test_admin_imports_a_page_and_the_worker_does_the_rest(client):
    assert client.post("/api/binder-imports", json={"album_name": "Vide"}).json()["budget_eur"] == 3.0
    created = client.post("/api/binder-imports", json={"album_name": "Classeur vert", "budget_eur": 50})
    assert created.status_code == 201
    item = created.json()
    assert item["grid"] == "3x3" and item["status"] == "active"
    state = send(client, item["id"], 1, page_photo(), drop_after=2)
    assert state["done"]
    assert client.get(f"/api/binder-imports/{item['id']}").json()["pages"][0]["status"] == "received"
    # The web process read nothing; the worker does.
    worker = service(client.app.state.binder_imports.store)
    worker.run_until_idle()
    result = client.get(f"/api/binder-imports/{item['id']}").json()
    assert result["progress"] == {"pockets": 9, "settled": 9, "pages_done": 1}
    assert result["cost"]["calls"] == 9
    assert item["id"] in [i["id"] for i in client.get("/api/binder-imports").json()]
    report = client.get(f"/api/binder-imports/{item['id']}/report?threshold=10").json()
    assert report["threshold_cents"] == 1000 and report["tally"]["copies"] == 9
    copies = client.get("/api/copies?status=review").json()
    assert len(copies["items"] if isinstance(copies, dict) else copies) == 9


def test_budget_pause_is_lifted_by_an_admin(client):
    item = client.post("/api/binder-imports", json={"album_name": "A", "budget_eur": 1}).json()
    send(client, item["id"], 1, page_photo())
    service(client.app.state.binder_imports.store, default_budget_eur=1.0).run_until_idle()
    paused = client.get(f"/api/binder-imports/{item['id']}").json()
    assert paused["status"] == "paused_budget"
    resumed = client.post(f"/api/binder-imports/{item['id']}/continue").json()
    assert resumed["status"] == "active" and resumed["budget_eur"] == 2
    assert client.post(f"/api/binder-imports/{item['id']}/continue").status_code == 409


def test_only_admins_reach_the_import(client):
    client.post("/api/users", json={"username": "lily", "password": PASSWORD, "role": "editor"})
    item = client.post("/api/binder-imports", json={"album_name": "A"}).json()
    client.post("/api/logout")
    client.post("/api/login", json={"username": "lily", "password": PASSWORD})
    assert client.get("/api/binder-imports").status_code == 403
    assert client.post("/api/binder-imports", json={"album_name": "B"}).status_code == 403
    begin = {"page": 1, "size": 10, "sha256": "a" * 64}
    assert client.post(f"/api/binder-imports/{item['id']}/uploads", json=begin).status_code == 403
    assert client.put("/api/binder-uploads/x?offset=0", content=b"x").status_code == 403
    assert client.get("/api/settings/agent-review-apply").status_code == 403


def test_review_apply_switch(client):
    closed = {"identity": False, "variant": False, "condition": False}
    assert client.get("/api/settings/agent-review-apply").json() == {
        "apply": False, "facets": closed}
    refused = client.put("/api/settings/agent-review-apply", json={"apply": True})
    assert refused.status_code in (400, 422)
    switched = client.put(
        "/api/settings/agent-review-apply",
        json={"apply": True, "reason": "Échantillon de 60 : aucune variante fausse."},
    )
    assert switched.json() == {
        "apply": True, "previous": False,
        "facets": {"identity": True, "variant": True, "condition": False}}
    bad = client.put("/api/settings/agent-review-apply", json={"apply": False, "facets": ["prix"]})
    assert bad.status_code == 422
    variant_off = client.put(
        "/api/settings/agent-review-apply", json={"apply": False, "facets": ["variant"]})
    assert variant_off.json()["facets"] == {**closed, "identity": True}


def test_bad_uploads_are_refused(client):
    item = client.post("/api/binder-imports", json={"album_name": "A"}).json()
    url = f"/api/binder-imports/{item['id']}/uploads"
    assert client.post(url, json={"page": 1, "size": 10, "sha256": "xyz"}).status_code == 422
    assert client.post(url, json={"page": 1, "size": 16 * 1024 * 1024, "sha256": "a" * 64}).status_code == 422
    state = client.post(url, json={"page": 1, "size": 4, "sha256": "a" * 64}).json()
    big = client.put(f"/api/binder-uploads/{state['id']}?offset=0", content=b"x" * (2 * 1024 * 1024))
    assert big.status_code == 413
    assert client.post("/api/binder-imports", json={"album_name": "A", "grid": "9x9"}).status_code == 422
