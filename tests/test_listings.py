import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient
from test_library import inputs

from pokeprice.inventory import SCHEMA_VERSION, Store
from pokeprice.inventory_import import import_collection
from pokeprice.pricing import FLOOR_CENTS, display_price
from pokeprice.webapp import create_app, password_hash

CHECKED = {
    "identification_status": "confirmed",
    "condition": "NM",
    "condition_confirmed": True,
    "variant_confirmed": True,
    "stock_state": "available",
    "deleted_at": "",
    "price_date": "2026-10-16T08:00:00+00:00",
}
VALUATION = {
    "trend_cents": 123,
    "price_variant_issue": None,
    "manual_price": None,
    "sale_estimate_cents": None,
}


def test_trend_is_rounded_up_to_the_next_tenth_for_checked_cards():
    price = display_price(CHECKED, VALUATION)
    assert price["publishable"] and price["price_cents"] == 130 and price["mode"] == "trend"
    assert display_price(CHECKED, {**VALUATION, "trend_cents": 150})["price_cents"] == 150
    assert display_price({**CHECKED, "condition": "EX"}, VALUATION)["publishable"]


def test_below_the_floor_a_card_goes_into_a_lot():
    price = display_price(CHECKED, {**VALUATION, "trend_cents": 41})
    assert not price["publishable"] and price["suggestion"] == "lot"
    assert "0,41 €" in price["reasons"][0] and FLOOR_CENTS == 50
    assert display_price(CHECKED, {**VALUATION, "trend_cents": 50})["publishable"]
    assert not display_price(CHECKED, VALUATION, {"amount_cents": 30})["publishable"]


@pytest.mark.parametrize(
    "card, valuation, words",
    [
        ({**CHECKED, "identification_status": "review"}, VALUATION, "Identité"),
        ({**CHECKED, "stock_state": "reserved"}, VALUATION, "réservé"),
        ({**CHECKED, "deleted_at": "2026-10-16"}, VALUATION, "supprimé"),
        ({**CHECKED, "condition_confirmed": False}, VALUATION, "État à confirmer"),
        ({**CHECKED, "variant_confirmed": False}, VALUATION, "Variante"),
        (CHECKED, {**VALUATION, "price_variant_issue": "Catégorie incohérente"}, "Variante"),
        ({**CHECKED, "condition": "PL"}, VALUATION, "État PL"),
        (CHECKED, {**VALUATION, "trend_cents": None}, "Aucune tendance"),
        (CHECKED, {**VALUATION, "trend_cents": 1000}, "10 €"),
    ],
)
def test_no_automatic_price_without_checks(card, valuation, words):
    price = display_price(card, valuation)
    assert not price["publishable"] and price["price_cents"] is None
    assert words in " ".join(price["reasons"])


def test_manual_prices_and_offers_come_first_without_condition_discount():
    damaged = {**CHECKED, "condition": "PL", "variant_confirmed": False}
    manual = display_price(damaged, VALUATION, {"amount_cents": 250, "source": "Vente entre amis"})
    assert manual["publishable"] and manual["price_cents"] == 250 and manual["mode"] == "manual"
    assert manual["source"] == "Vente entre amis"
    offers = display_price({**CHECKED, "condition": "PL"}, {**VALUATION, "sale_estimate_cents": 1234})
    assert offers["mode"] == "offers" and offers["price_cents"] == 1240
    typed = display_price(
        CHECKED,
        {**VALUATION, "trend_cents": 90, "manual_price": {"amount_cents": 90, "source": "Cardmarket relevé", "observed_at": "2026-10-13"}},
    )
    assert typed["mode"] == "manual" and typed["source"] == "Cardmarket relevé" and typed["price_cents"] == 90


@pytest.fixture
def shop(tmp_path):
    store = Store(tmp_path / "inventory")
    import_collection(store, inputs(tmp_path))
    with TestClient(create_app(store.root)) as client:
        assert client.post("/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}).status_code == 200
        cards = {c["id"]: c for c in client.get("/api/copies", params={"limit": 100}).json()["items"]}
        yield client, store, cards


def confirmed(cards):
    return sorted(c["id"] for c in cards.values() if c["identification_status"] == "confirmed")


def test_publishing_a_card_a_price_update_and_its_withdrawal(shop):
    client, store, cards = shop
    copy_id = confirmed(cards)[0]
    refused = client.get(f"/api/copies/{copy_id}/listing").json()
    assert refused["listing"] is None and not refused["proposal"]["publishable"]
    assert client.put(f"/api/copies/{copy_id}/listing", json={}).status_code == 422
    listing = client.put(f"/api/copies/{copy_id}/listing", json={"price_eur": "1.20"}).json()
    assert listing["price_cents"] == 120 and listing["price_mode"] == "manual" and listing["available"]
    assert [i["id"] for i in listing["items"]] == [copy_id] and listing["id"] != copy_id
    again = client.put(f"/api/copies/{copy_id}/listing", json={"price_eur": "1.50"}).json()
    assert again["id"] == listing["id"] and again["price_cents"] == 150 and again["version"] == 2
    assert [l["id"] for l in client.get("/api/listings").json()] == [listing["id"]]
    shown = client.get("/api/copies", params={"stock": "published"}).json()["items"]
    assert [c["id"] for c in shown] == [copy_id] and shown[0]["published"]
    kinds = [e["kind"] for e in client.get(f"/api/copies/{copy_id}").json()["history"]]
    assert kinds.count("listing") == 2
    stale = client.post(f"/api/listings/{listing['id']}/unpublish", json={"expected_version": 1, "reason": "Test"})
    assert stale.status_code == 409
    removed = client.delete(f"/api/copies/{copy_id}/listing").json()
    assert removed["state"] == "offline" and not removed["available"]
    assert client.get("/api/listings").json() == []
    assert client.get("/api/copies", params={"stock": "published"}).json()["items"] == []
    assert [l["id"] for l in client.get("/api/listings", params={"state": "offline"}).json()] == [listing["id"]]
    republished = client.put(f"/api/copies/{copy_id}/listing", json={"price_eur": "2"}).json()
    assert republished["id"] != listing["id"] and republished["version"] == 1


def test_a_lot_has_one_price_and_the_floor_applies_to_the_whole(shop):
    client, _, cards = shop
    ids = confirmed(cards)[:3]  # 3 × 1.00 € reference -> floor = 2.55 €
    assert client.post("/api/listings", json={"copy_ids": ids, "lot": True}).status_code == 422
    assert client.post("/api/listings", json={"copy_ids": ids, "lot": True, "price_eur": "0.40"}).status_code == 422
    below = client.post("/api/listings", json={"copy_ids": ids, "lot": True, "price_eur": "2.54"})
    assert below.status_code == 422 and "2,55 €" in below.json()["detail"]
    lot = client.post("/api/listings", json={"copy_ids": ids, "lot": True, "price_eur": "2.55", "title": "Zarbi"}).json()[0]
    assert lot["price_cents"] == 255 and sorted(i["id"] for i in lot["items"]) == ids and lot["title"] == "Zarbi"
    # A copy already in an online publication cannot be published a second time.
    twice = client.put(f"/api/copies/{ids[0]}/listing", json={"price_eur": "3"})
    assert twice.status_code == 409


def test_a_selection_publishes_each_card_and_reports_refusals(shop):
    client, _, cards = shop
    unresolved = [c["id"] for c in cards.values() if c["identification_status"] != "confirmed"]
    ids = confirmed(cards)[:2] + unresolved
    result = client.post("/api/listings", json={"copy_ids": ids, "price_eur": "0.85"}).json()
    assert len(result["published"]) == 2 and [r["copy_id"] for r in result["refused"]] == unresolved
    assert "Identité" in result["refused"][0]["reason"]


def test_a_reserved_card_leaves_the_storefront_and_cannot_be_published(shop):
    client, _, cards = shop
    first, second = confirmed(cards)[:2]
    client.put(f"/api/copies/{first}/listing", json={"price_eur": "1"})
    sale = client.post("/api/sales", json={"title": "Lot", "copy_ids": [first, second], "amount_eur": "5"}).json()
    sale = next(s for s in client.get("/api/sales").json() if s["id"] == sale["id"])
    reserved = client.patch(f"/api/sales/{sale['id']}", json={"status": "reserved", "expected_version": sale["version"], "reason": "Réservé"})
    assert reserved.status_code == 200
    assert client.get("/api/listings").json()[0]["available"] is False
    refused = client.put(f"/api/copies/{second}/listing", json={"price_eur": "1"})
    assert refused.status_code == 422 and "réservé" in refused.json()["detail"]


def test_readers_and_clients_cannot_publish(shop):
    client, store, cards = shop
    copy_id = confirmed(cards)[0]
    client.post("/api/users", json={"username": "lecteur", "password": "Lecture-test-2026!", "role": "reader"})
    with store.connect(write=True) as db:
        db.execute(
            "INSERT INTO users(id,username,password_hash,role,created_at,status) VALUES(?,?,?,?,?,?)",
            (str(uuid.uuid4()), "client", password_hash("Client-test-2026!"), "client", "2026-10-16", "active"),
        )
    for username, password, reading in (("lecteur", "Lecture-test-2026!", 200), ("client", "Client-test-2026!", 403)):
        with TestClient(create_app(store.root)) as visitor:
            assert visitor.post("/api/login", json={"username": username, "password": password}).status_code == 200
            assert visitor.get("/api/listings").status_code == reading
            assert visitor.put(f"/api/copies/{copy_id}/listing", json={"price_eur": "1"}).status_code == 403
            assert visitor.post("/api/listings", json={"copy_ids": [copy_id], "price_eur": "1"}).status_code == 403
            assert visitor.delete(f"/api/copies/{copy_id}/listing").status_code == 403


def test_schema_16_adds_listings_without_touching_the_collection(tmp_path):
    store = Store(tmp_path / "inventory")
    import_collection(store, inputs(tmp_path))
    with sqlite3.connect(store.database) as db:
        db.executescript("DROP TABLE listing_items; DROP TABLE listings; PRAGMA user_version=15;")
        before = db.execute("SELECT id,version FROM copies ORDER BY id").fetchall()
    Store(store.root)
    with sqlite3.connect(store.database) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION >= 16
        assert db.execute("SELECT id,version FROM copies ORDER BY id").fetchall() == before
        db.execute("INSERT INTO listings(id,price_cents,price_mode,published_at,published_by,updated_at) VALUES('a',60,'manual','t','pat','t')")
        db.execute("INSERT INTO listings(id,price_cents,price_mode,published_at,published_by,updated_at) VALUES('b',60,'manual','t','pat','t')")
        db.execute("INSERT INTO listing_items(listing_id,copy_id) VALUES('a',?)", before[0][:1])
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO listing_items(listing_id,copy_id) VALUES('b',?)", before[0][:1])
    assert list((tmp_path / "backups").glob("before-schema*-from15-*.sqlite3"))


def test_an_imposed_price_keeps_its_source_for_a_later_review(shop):
    _, store, cards = shop
    from pokeprice.listings import Listings

    copy_id = confirmed(cards)[0]
    listing = Listings(store).publish(
        [copy_id], "claude", price_cents=85, price_mode="trend",
        price_source="À réviser : état à confirmer",
    )
    assert (listing["price_mode"], listing["price_source"], listing["price_cents"]) == (
        "trend", "À réviser : état à confirmer", 85,
    )


def test_manual_unit_and_lot_prices_enforce_reference_floor_and_margin_bounds(shop, monkeypatch):
    client, store, cards = shop
    from pokeprice.pricing import LOT_MAX_MARGIN_ENV

    first, second, third = confirmed(cards)[:3]
    with store.connect(write=True) as db:
        db.execute("UPDATE copies SET reference_cents=200 WHERE id=?", (first,))
        db.execute("UPDATE copies SET reference_cents=123 WHERE id=?", (second,))

    # Single card: reference 2.00 €, default 15 % margin -> floor 1.70 € (170 cents).
    info = client.get(f"/api/copies/{first}/listing").json()
    assert info["proposal"]["floor_cents"] == 170
    refused = client.put(f"/api/copies/{first}/listing", json={"price_eur": "1.69"})
    assert refused.status_code == 422
    assert "1,70 €" in refused.json()["detail"] and "2,00 €" in refused.json()["detail"]
    accepted = client.put(f"/api/copies/{first}/listing", json={"price_eur": "1.70"})
    assert accepted.status_code == 200 and accepted.json()["price_cents"] == 170
    client.delete(f"/api/copies/{first}/listing")

    # Margin 0 %: floor equals the exact reference (2.00 €).
    monkeypatch.setenv(LOT_MAX_MARGIN_ENV, "0")
    assert client.get("/api/summary").json()["lot_max_margin"] == 0
    assert client.get(f"/api/copies/{first}/listing").json()["proposal"]["floor_cents"] == 200
    assert client.put(f"/api/copies/{first}/listing", json={"price_eur": "1.99"}).status_code == 422
    exact = client.put(f"/api/copies/{first}/listing", json={"price_eur": "2.00"})
    assert exact.status_code == 200 and exact.json()["price_cents"] == 200
    client.delete(f"/api/copies/{first}/listing")

    # Invalid environment variable is rejected with a clear error.
    monkeypatch.setenv(LOT_MAX_MARGIN_ENV, "quinze")
    bad_env = client.put(f"/api/copies/{first}/listing", json={"price_eur": "2.00"})
    assert bad_env.status_code == 422 and LOT_MAX_MARGIN_ENV in bad_env.json()["detail"]
    monkeypatch.delenv(LOT_MAX_MARGIN_ENV, raising=False)

    # Card without reference (None) or with reference 0 keeps FLOOR_CENTS = 50 and says so.
    for empty_ref in (None, 0):
        with store.connect(write=True) as db:
            db.execute("UPDATE copies SET reference_cents=? WHERE id=?", (empty_ref, third))
        assert client.get(f"/api/copies/{third}/listing").json()["proposal"]["floor_cents"] == FLOOR_CENTS
        low = client.put(f"/api/copies/{third}/listing", json={"price_eur": "0.49"})
        assert low.status_code == 422 and "sans référence" in low.json()["detail"] and "0,50 €" in low.json()["detail"]
        ok = client.put(f"/api/copies/{third}/listing", json={"price_eur": "0.50"})
        assert ok.status_code == 200 and ok.json()["price_cents"] == FLOOR_CENTS
        client.delete(f"/api/copies/{third}/listing")

    # Lot with referenced cards (2.00 € + 1.23 € = 3.23 € -> floor ceil(323 * 0.85) = 275 cents)
    # plus one unreferenced card (0): floor is still 2.75 € and refusal mentions the unreferenced card.
    lot_low = client.post("/api/listings", json={"copy_ids": [first, second, third], "lot": True, "price_eur": "2.74"})
    assert lot_low.status_code == 422
    assert "2,75 €" in lot_low.json()["detail"] and "1 sans référence" in lot_low.json()["detail"]
    lot_ok = client.post("/api/listings", json={"copy_ids": [first, second, third], "lot": True, "price_eur": "2.75"})
    assert lot_ok.status_code == 201 and lot_ok.json()[0]["price_cents"] == 275
    client.post(
        f"/api/listings/{lot_ok.json()[0]['id']}/unpublish",
        json={"expected_version": 1, "reason": "Test"},
    )

    # Lot where no card has a reference: keeps FLOOR_CENTS = 50 and says so.
    with store.connect(write=True) as db:
        db.execute("UPDATE copies SET reference_cents=NULL WHERE id IN (?,?)", (first, second))
    unrated_low = client.post("/api/listings", json={"copy_ids": [first, second], "lot": True, "price_eur": "0.49"})
    assert unrated_low.status_code == 422 and "aucune carte du lot n’a de référence" in unrated_low.json()["detail"]
    unrated_ok = client.post("/api/listings", json={"copy_ids": [first, second], "lot": True, "price_eur": "0.50"})
    assert unrated_ok.status_code == 201 and unrated_ok.json()[0]["price_cents"] == FLOOR_CENTS
