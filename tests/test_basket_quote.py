"""Accepted basket prices remain authoritative through reservation submission."""

import threading

import pytest
from fastapi.testclient import TestClient
from test_reservations import activate, client_of, shop, signup  # noqa: F401

from pokeprice.listings import Storefront
from pokeprice.reservations import Reservations
from pokeprice.webapp import create_app


def request_body(listing, price=None):
    return {"listing_ids": [listing["id"]],
            "expected_prices": {listing["id"]: listing["price_cents"] if price is None else price}}


def buyer(store, admin):
    signup(store, "acheteur@example.org")
    activate(admin, "acheteur@example.org")
    return client_of(store, "acheteur@example.org")


def test_quote_has_only_public_current_items_and_names_unavailable_ids(shop):
    admin, store, listings = shop
    listing = listings[0]
    with store.connect(write=True) as db:
        db.execute("UPDATE listings SET state='offline',title='Titre privé' WHERE id=?", (listings[1]["id"],))
    with TestClient(create_app(store.root)) as visitor:
        response = visitor.post("/api/public/quote", json={
            "listing_ids": [listing["id"], listings[1]["id"], "inconnu"], "delivery": "hand"})
    assert response.status_code == 200
    quote = response.json()
    assert quote["subtotal_cents"] == quote["total_cents"] == listing["price_cents"]
    assert quote["shipping_cents"] == 0
    assert quote["unavailable"] == [listings[1]["id"], "inconnu"]
    assert quote["items"][0]["id"] == listing["id"] and quote["items"][0]["label"]
    assert set(quote["items"][0]) == {"id", "label", "price_cents", "card_count"}
    assert "Titre privé" not in response.text
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0


@pytest.mark.parametrize("guest", [False, True])
def test_price_changed_after_quote_requires_acceptance_before_insert(shop, guest):
    admin, store, listings = shop
    visitor = TestClient(create_app(store.root)) if guest else buyer(store, admin)
    listing = listings[0]
    quote = visitor.post("/api/public/quote", json={"listing_ids": [listing["id"]]}).json()
    original = quote["items"][0]["price_cents"]
    with store.connect(write=True) as db:
        db.execute("UPDATE listings SET price_cents=? WHERE id=?", (original + 100, listing["id"]))
    endpoint = "/api/public/requests" if guest else "/api/me/requests"
    body = request_body(listing)
    if guest:
        body.update(email="invite@example.org", display_name="Invité", consent=True)
    conflict = visitor.post(endpoint, json=body)
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "basket_changed"
    assert conflict.json()["changed"] == [{"id": listing["id"], "expected_cents": original, "price_cents": original + 100}]
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0
        if guest:
            assert db.execute("SELECT COUNT(*) FROM users WHERE email='invite@example.org'").fetchone()[0] == 0
    body["expected_prices"][listing["id"]] = original + 100
    sent = visitor.post(endpoint, json=body)
    assert sent.status_code == (202 if guest else 201), sent.text
    with store.connect() as db:
        assert [row[0] for row in db.execute("SELECT price_cents FROM request_items")] == [original + 100]


def test_unavailable_article_conflict_identifies_it_and_keeps_request_atomic(shop):
    admin, store, listings = shop
    visitor = buyer(store, admin)
    with store.connect(write=True) as db:
        db.execute("UPDATE listings SET state='offline' WHERE id=?", (listings[1]["id"],))
    response = visitor.post("/api/me/requests", json={
        "listing_ids": [listing["id"] for listing in listings[:2]],
        "expected_prices": {listing["id"]: listing["price_cents"] for listing in listings[:2]}})
    assert response.status_code == 409
    assert response.json()["unavailable"] == [listings[1]["id"]]
    assert [item["id"] for item in response.json()["quote"]["items"]] == [listings[0]["id"]]
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0


@pytest.mark.parametrize("prices", [None, {}, {"autre": 120}, {"VALUE": "120"}, {"VALUE": True}, {"VALUE": -1}])
def test_every_submission_requires_an_exact_explicit_integer_price(shop, prices):
    admin, store, listings = shop
    visitor = buyer(store, admin)
    body = {"listing_ids": [listings[0]["id"]]}
    if prices is not None:
        body["expected_prices"] = {listings[0]["id"] if key == "VALUE" else key: value for key, value in prices.items()}
    for endpoint in ("/api/me/requests", "/api/public/requests"):
        submitted = dict(body)
        if "public" in endpoint:
            submitted.update(email="invite@example.org", display_name="Invité", consent=True)
        response = visitor.post(endpoint, json=submitted)
        assert response.status_code == 422, response.text


@pytest.mark.parametrize("guest", [False, True])
def test_price_comparison_and_insert_share_the_write_lock(shop, monkeypatch, guest):
    admin, store, listings = shop
    visitor = buyer(store, admin)
    client_id = next(client["id"] for client in admin.get("/api/clients").json())
    service = Reservations(store, Storefront(store))
    listing = listings[0]
    original_insert = service.insert
    started, finished = threading.Event(), threading.Event()
    errors = []

    def rival():
        started.set()
        try:
            with store.connect(write=True) as db:
                db.execute("UPDATE listings SET price_cents=999 WHERE id=?", (listing["id"],))
        except Exception as error:
            errors.append(error)
        finally:
            finished.set()

    thread = threading.Thread(target=rival)

    def insert(*args, **kwargs):
        thread.start()
        assert started.wait(1)
        assert not finished.wait(0.1), "The rival changed the price between comparison and insertion"
        return original_insert(*args, **kwargs)

    monkeypatch.setattr(service, "insert", insert)
    try:
        if guest:
            service.guest("invite@example.org", "Invité", [listing["id"]], "", "unusable",
                          expected_prices={listing["id"]: listing["price_cents"]})
        else:
            service.create(client_id, [listing["id"]], "", expected_prices={listing["id"]: listing["price_cents"]})
    finally:
        if thread.ident:
            thread.join(timeout=3)
    assert finished.is_set() and not errors
    with store.connect() as db:
        assert db.execute("SELECT price_cents FROM request_items").fetchone()[0] == listing["price_cents"]
        assert db.execute("SELECT price_cents FROM listings WHERE id=?", (listing["id"],)).fetchone()[0] == 999
