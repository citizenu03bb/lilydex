"""The edition's catalogue image beside the copy's photo in the form."""

from fastapi.testclient import TestClient
from test_intake import values

from pokeprice.webapp import create_app

IMAGE = "https://assets.tcgdex.net/en/swsh/swsh7/77"


def client_with(tmp_path, fetch):
    client = TestClient(create_app(tmp_path / "inventory", variant_fetch=fetch))
    client.post(
        "/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}
    )
    client.post("/api/albums", json={"name": "Test"})
    return client


def create(client, **fields):
    response = client.post("/api/copies", json=values(client, **fields))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_image_and_links_are_fetched_once_then_cached(tmp_path):
    calls = []

    def fetch(catalog_id, language):
        calls.append((catalog_id, language))
        return {
            "id": catalog_id,
            "image": IMAGE,
            "_acquisition": {"served_language": "en"},
        }

    with client_with(tmp_path, fetch) as client:
        copy_id = create(client, catalog_id="swsh7-77")
        first = client.get(f"/api/copies/{copy_id}/catalogue").json()
        second = client.get(f"/api/copies/{copy_id}/catalogue").json()
    assert first == second == {
        "catalog_id": "swsh7-77",
        "image": IMAGE + "/high.webp",
        "served_language": "en",
        "tcgdex_url": "https://api.tcgdex.net/v2/en/cards/swsh7-77",
    }
    assert calls == [("swsh7-77", "en")]


def test_image_from_another_host_is_not_shown(tmp_path):
    def fetch(catalog_id, language):
        return {"id": catalog_id, "image": "https://example.com/swsh7/77"}

    with client_with(tmp_path, fetch) as client:
        copy_id = create(client, catalog_id="swsh7-77")
        info = client.get(f"/api/copies/{copy_id}/catalogue").json()
    assert info["image"] == "" and info["tcgdex_url"].endswith("/en/cards/swsh7-77")


def test_network_failure_is_not_cached_and_form_still_gets_links(tmp_path):
    attempts = []

    def fetch(catalog_id, language):
        attempts.append(catalog_id)
        raise OSError("offline")

    with client_with(tmp_path, fetch) as client:
        copy_id = create(client, catalog_id="swsh7-77")
        info = client.get(f"/api/copies/{copy_id}/catalogue").json()
        client.get(f"/api/copies/{copy_id}/catalogue")
        with client.app.state.store.connect() as db:
            cached = db.execute(
                "SELECT count(*) FROM catalog_lookups WHERE key LIKE 'image:%'"
            ).fetchone()[0]
    assert info["image"] == "" and info["tcgdex_url"]
    assert attempts == ["swsh7-77"] and cached == 0


def test_copy_without_edition_has_no_catalogue(tmp_path):
    def fetch(*_):
        raise AssertionError("no edition, no request")

    with client_with(tmp_path, fetch) as client:
        copy_id = create(client)
        response = client.get(f"/api/copies/{copy_id}/catalogue")
    assert response.status_code == 200 and response.json() is None


def test_catalogue_needs_a_staff_session(tmp_path):
    with client_with(tmp_path, lambda *_: {}) as client:
        copy_id = create(client, catalog_id="swsh7-77")
        client.cookies.clear()
        response = client.get(f"/api/copies/{copy_id}/catalogue")
    assert response.status_code == 401


def test_print_without_a_french_scan_shows_the_english_one(tmp_path):
    def fetch(catalog_id, language):
        if language == "en":
            return {"id": catalog_id, "image": "https://assets.tcgdex.net/en/dp/dp6/89"}
        return {"id": catalog_id, "_acquisition": {"served_language": "fr"}}

    with client_with(tmp_path, fetch) as client:
        copy_id = create(client, catalog_id="dp6-89", language="fr")
        info = client.get(f"/api/copies/{copy_id}/catalogue").json()
    assert info["image"] == "https://assets.tcgdex.net/en/dp/dp6/89/high.webp"
    assert info["served_language"] == "en"
