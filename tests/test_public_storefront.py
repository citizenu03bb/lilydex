import json

import pytest
from fastapi.testclient import TestClient
from test_library import inputs

from pokeprice.inventory import Store
from pokeprice.inventory_import import import_collection
from pokeprice.webapp import create_app

LISTING_KEYS = {"id", "title", "price_cents", "price_date", "items"}
ITEM_KEYS = {
    "index", "name", "set_name", "number", "language", "condition", "finish",
    "stamp", "distribution", "photos",
}


@pytest.fixture
def shop(tmp_path):
    store = Store(tmp_path / "inventory")
    import_collection(store, inputs(tmp_path))
    with TestClient(create_app(store.root)) as admin:
        assert admin.post("/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}).status_code == 200
        cards = [c for c in admin.get("/api/copies", params={"limit": 100}).json()["items"] if c["identification_status"] == "confirmed"]
        first = cards[0]
        noted = admin.patch(
            f"/api/copies/{first['id']}",
            json={"expected_version": first["version"], "notes": "Note privée du vendeur", "reason": "Test"},
        )
        assert noted.status_code == 200, noted.text
        single = admin.put(f"/api/copies/{first['id']}/listing", json={"price_eur": "1.20"}).json()
        lot = admin.post(
            "/api/listings",
            json={"copy_ids": [c["id"] for c in cards[1:3]], "lot": True, "price_eur": "2", "title": "Deux cartes"},
        ).json()[0]
        with TestClient(create_app(store.root)) as visitor:
            yield admin, visitor, store, cards, single, lot


def test_the_storefront_shows_only_whitelisted_fields(shop):
    admin, visitor, store, cards, single, lot = shop
    response = visitor.get("/api/public/listings")
    assert response.status_code == 200 and "pokeprice_session" not in visitor.cookies
    result = response.json()
    assert result["total"] == 2
    for listing in result["items"]:
        assert set(listing) == LISTING_KEYS
        for item in listing["items"]:
            assert set(item) == ITEM_KEYS
            assert item["condition"] is None  # estimated, never confirmed here
    text = json.dumps(result, ensure_ascii=False)
    for secret in [c["id"] for c in cards] + ["Note privée", "Album A", "Album B", "reference_cents", "source", "pat"]:
        assert secret not in text, secret
    by_id = {l["id"]: l for l in result["items"]}
    assert by_id[single["id"]]["price_cents"] == 120 and len(by_id[lot["id"]]["items"]) == 2
    detail = visitor.get(f"/api/public/listings/{lot['id']}").json()
    assert set(detail) == LISTING_KEYS and detail["title"] == "Deux cartes"


def test_search_filters_and_photos(shop):
    admin, visitor, store, cards, single, lot = shop
    name = single["items"][0]["name"]
    found = visitor.get("/api/public/listings", params={"q": name.lower()}).json()
    assert single["id"] in [l["id"] for l in found["items"]]
    assert visitor.get("/api/public/listings", params={"max_eur": "1.5"}).json()["total"] == 1
    assert visitor.get("/api/public/listings", params={"language": "ja"}).json()["total"] == 0
    cheap_first = visitor.get("/api/public/listings", params={"sort": "price"}).json()["items"]
    assert [l["price_cents"] for l in cheap_first] == [120, 200]
    picture = visitor.get(f"/api/public/listings/{single['id']}/photo")
    assert picture.status_code == 200 and picture.headers["content-type"] == "image/jpeg"
    assert visitor.get(f"/api/public/listings/{single['id']}/photo", params={"item": 3}).status_code == 404
    assert visitor.get(f"/api/public/listings/{single['id']}/photo", params={"side": "back"}).status_code == 404


def test_withdrawn_or_reserved_publications_leave_the_storefront(shop):
    admin, visitor, store, cards, single, lot = shop
    admin.delete(f"/api/copies/{single['items'][0]['id']}/listing")
    assert visitor.get(f"/api/public/listings/{single['id']}").status_code == 404
    assert visitor.get(f"/api/public/listings/{single['id']}/photo").status_code == 404
    sale = admin.post("/api/sales", json={"title": "Réservé", "copy_ids": [lot["items"][0]["id"]], "amount_eur": "1"}).json()
    sale = next(s for s in admin.get("/api/sales").json() if s["id"] == sale["id"])
    assert admin.patch(f"/api/sales/{sale['id']}", json={"status": "reserved", "expected_version": sale["version"], "reason": "Test"}).status_code == 200
    assert visitor.get("/api/public/listings").json() == {"items": [], "total": 0}
    assert visitor.get(f"/api/public/listings/{lot['id']}").status_code == 404


def test_the_storefront_page_is_separate_and_not_indexed(shop):
    _, visitor, *_ = shop
    page = visitor.get("/vitrine")
    assert page.status_code == 200 and 'name="robots" content="noindex"' in page.text
    assert "/assets/storefront.js" in page.text and "/assets/app.js" not in page.text
    assert visitor.get("/assets/storefront.js").status_code == 200
    assert visitor.get("/assets/storefront.css").status_code == 200


def test_anonymous_reads_are_rate_limited(shop):
    _, visitor, *_ = shop
    statuses = [visitor.get("/api/public/listings/absent").status_code for _ in range(301)]
    assert set(statuses[:300]) == {404} and statuses[300] == 429
