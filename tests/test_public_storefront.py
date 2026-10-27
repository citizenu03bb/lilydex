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


def test_the_language_filter_lists_languages_on_sale(shop):
    admin, visitor, store, cards, single, lot = shop
    with store.connect() as db:
        db.execute("UPDATE copies SET language='ja' WHERE id=?", (cards[0]["id"],))
    result = visitor.get("/api/public/listings", params={"language": "fr"}).json()
    # Whatever the current filter, every language on sale stays offered.
    assert "ja" in result["languages"] and "de" not in result["languages"]


def test_a_bulk_publication_reads_in_name_order(shop):
    admin, visitor, store, cards, single, lot = shop
    names = {single["id"]: single["items"][0]["name"], lot["id"]: "Deux cartes"}
    expected = sorted(names, key=lambda i: names[i].lower())
    with store.connect() as db:
        db.execute("UPDATE listings SET price_cents=50")
        # Published in name order, seconds apart: newest first would reverse it.
        for second, listing_id in enumerate(expected):
            db.execute(
                "UPDATE listings SET published_at=? WHERE id=?",
                (f"2026-10-16T21:10:0{second}+00:00", listing_id),
            )
    for sort in ("recent", "price", "price_desc", "name"):
        items = visitor.get("/api/public/listings", params={"sort": sort}).json()["items"]
        assert [l["id"] for l in items] == expected, sort
    pages = [visitor.get("/api/public/listings", params={"limit": 1, "offset": o}).json()["items"][0]["id"] for o in (0, 1)]
    assert pages == expected


def test_search_knows_other_languages_and_forgives_one_slip(shop):
    admin, visitor, store, cards, single, lot = shop
    with store.connect() as db:
        db.execute("UPDATE copies SET name='Évoli', catalog_id='base2-51' WHERE id=?", (cards[0]["id"],))
        db.execute(
            "INSERT INTO catalog_names VALUES('base2-51','en','Eevee','test','2026-10-27')"
        )
    search = lambda q: visitor.get("/api/public/listings", params={"q": q}).json()
    found = search("eevee")
    assert [l["id"] for l in found["items"]] == [single["id"]] and "approximate" not in found
    assert search("evoli")["total"] == 1
    slipped = search("eeveee")
    assert [l["id"] for l in slipped["items"]] == [single["id"]] and slipped["approximate"]
    assert search("evloi")["approximate"]  # two letters swapped
    assert search("eevxx")["total"] == 0
    assert search("evol")["total"] == 1 and "approximate" not in search("evol")
    # Short words need an exact match: one slip in three letters is another word.
    assert search("evx")["total"] == 0


def test_withdrawn_or_reserved_publications_leave_the_storefront(shop):
    admin, visitor, store, cards, single, lot = shop
    admin.delete(f"/api/copies/{single['items'][0]['id']}/listing")
    assert visitor.get(f"/api/public/listings/{single['id']}").status_code == 404
    assert visitor.get(f"/api/public/listings/{single['id']}/photo").status_code == 404
    sale = admin.post("/api/sales", json={"title": "Réservé", "copy_ids": [lot["items"][0]["id"]], "amount_eur": "1"}).json()
    sale = next(s for s in admin.get("/api/sales").json() if s["id"] == sale["id"])
    assert admin.patch(f"/api/sales/{sale['id']}", json={"status": "reserved", "expected_version": sale["version"], "reason": "Test"}).status_code == 200
    assert visitor.get("/api/public/listings").json() == {"items": [], "total": 0, "languages": []}
    assert visitor.get(f"/api/public/listings/{lot['id']}").status_code == 404


def test_the_storefront_page_is_separate_and_not_indexed(shop):
    _, visitor, *_ = shop
    page = visitor.get("/")
    assert page.status_code == 200 and 'name="robots" content="noindex"' in page.text
    assert "/assets/storefront.js" in page.text and "/assets/app.js" not in page.text
    assert "/assets/themes.css" in page.text and "/assets/components.js" in page.text
    assert visitor.get("/assets/storefront.js").status_code == 200
    assert visitor.get("/assets/storefront.css").status_code == 200
    assert visitor.get("/assets/themes.css").status_code == 200
    assert visitor.get("/assets/components.js").status_code == 200


def test_every_page_shows_the_logo_and_its_tab_icon(shop):
    _, visitor, *_ = shop
    for path in ("/", "/a-propos", "/gestion"):
        page = visitor.get(path).text
        assert 'rel="icon" href="/favicon.ico"' in page and 'src="/assets/logo.png"' in page
    icon = visitor.get("/favicon.ico")
    assert icon.status_code == 200 and icon.headers["content-type"] == "image/x-icon"
    assert icon.content[:4] == b"\x00\x00\x01\x00"  # ICO header
    assert 'src="/assets/mascotte.png"' in visitor.get("/a-propos").text
    for name in ("logo.png", "apple-touch-icon.png", "mascotte.png"):
        image = visitor.get(f"/assets/{name}")
        assert image.status_code == 200 and image.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_anonymous_reads_are_rate_limited(shop):
    _, visitor, *_ = shop
    statuses = [visitor.get("/api/public/listings/absent").status_code for _ in range(301)]
    assert set(statuses[:300]) == {404} and statuses[300] == 429


def test_the_storefront_is_home_and_management_has_its_own_address(shop):
    _, visitor, *_ = shop
    assert "/assets/app.js" in visitor.get("/gestion").text
    assert 'href="/gestion"' in visitor.get("/").text  # discreet seller link
    old_link = visitor.get("/?view=sales&q=Zarbi", follow_redirects=False)
    assert old_link.status_code == 301 and old_link.headers["location"] == "/gestion?view=sales&q=Zarbi"
    former = visitor.get("/vitrine", follow_redirects=False)
    assert former.status_code == 301 and former.headers["location"] == "/"


def test_a_card_has_its_own_address(shop):
    admin, visitor, store, cards, single, lot = shop
    page = visitor.get(f"/carte/{single['id']}")
    assert page.status_code == 200 and "/assets/storefront.js" in page.text
    gone = visitor.get("/carte/absente")
    # Still the storefront, which says the card is no longer for sale.
    assert gone.status_code == 404 and "/assets/storefront.js" in gone.text
    assert admin.delete(f"/api/copies/{single['items'][0]['id']}/listing").status_code == 200
    assert visitor.get(f"/carte/{single['id']}").status_code == 404


def test_https_deployments_ask_browsers_to_stay_on_https(shop):
    admin, visitor, store, *_ = shop
    assert "strict-transport-security" not in visitor.get("/health").headers
    with TestClient(create_app(store.root, secure_cookie=True), base_url="https://testserver") as secure:
        assert secure.get("/health").headers["strict-transport-security"] == "max-age=31536000"


def test_about_page_shows_the_configured_contact_only(shop, monkeypatch):
    _, visitor, store, *_ = shop
    page = visitor.get("/a-propos")
    assert page.status_code == 200 and "non officiel" in page.text.lower() and "mailto:" not in page.text
    monkeypatch.setenv("POKEPRICE_CONTACT_EMAIL", "vendeur@example.org")
    with TestClient(create_app(store.root)) as other:
        assert 'href="mailto:vendeur@example.org"' in other.get("/a-propos").text
    monkeypatch.setenv("POKEPRICE_CONTACT_EMAIL", '"><script>alert(1)</script>@x.org')
    with TestClient(create_app(store.root)) as other:
        text = other.get("/a-propos").text
        assert "<script>" not in text and "mailto:" not in text


def test_only_the_storefront_may_be_indexed(shop):
    _, visitor, *_ = shop
    assert "x-robots-tag" not in visitor.get("/").headers
    assert visitor.get("/gestion").headers["x-robots-tag"] == "noindex, nofollow"
    assert visitor.get("/api/public/listings").headers["x-robots-tag"] == "noindex, nofollow"
    assert "Site personnel et non officiel" in visitor.get("/").text
    assert "Lilydex" in visitor.get("/gestion").text and "Poképrice" not in visitor.get("/gestion").text
