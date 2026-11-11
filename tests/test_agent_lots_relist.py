"""Cards leaving a tool lot come back as single listings from 1 € up (decision 0045)."""

import pytest
from test_agent_lots_compose import LOTS, engine, events, put_online, sale, snapshot, tool_draft
from test_agent_lots_publish import (  # noqa: F401 - fixtures
    active_listing,
    another_theme,
    flip_to_review,
    listing,
    offer,
    online_lot,
    rotate,
    shop,
    unpublish,
)
from test_pokeprice_lots import add_copy, test_db  # noqa: F401 - fixture

from pokeprice.inventory import Conflict
from pokeprice.listings import Listings
from pokeprice.lots.settings import DEFAULT_ROTATION_DAYS
from pokeprice.pricing import lot_floor_cents, lot_max_margin


def lot_of(store, specs):
    """A tool lot online, one duplicate per ``(name, price)``; the album keeps another copy of each.

    The duplicates are checked NM-EX cards: alone, they take today's trend.
    """
    ids = []
    for index, (name, price) in enumerate(specs):
        catalog = f"sv1-{100 + index}"
        add_copy(store, "a", 60 + index, price=price, name=name, catalog_id=catalog, number=f"{100 + index}/198")
        ids.append(add_copy(store, "b", 60 + index, price=price, name=name, catalog_id=catalog,
                            number=f"{100 + index}/198", condition_confirmed=True)["id"])
    sale_id = tool_draft(store, ids, 2000, title="Lot à retirer")
    return sale_id, ids, put_online(store, sale_id)


def single(store, copy_id):
    found = active_listing(store, copy_id)
    if found is None:
        return None
    with store.connect() as db:
        count = db.execute("SELECT count(*) FROM listing_items WHERE listing_id=? AND active=1", (found["id"],))
        if count.fetchone()[0] > 1:
            return None  # Still in a lot.
    return found


def margin(store):
    with store.connect() as db:
        return lot_max_margin(db)


def test_withdrawal_relists_cards_of_one_euro_or_more_and_no_others(shop):
    client, service, grant, _ = shop
    store = service.store
    sale_id, ids, listing_id = lot_of(
        store,
        [("Haut", 300), ("Bas", 80), ("Sans cote", 300), ("Douteuse", 300), ("À revoir", 300), ("Relevée", 300),
         ("Abîmée", 300)],
    )
    high, low, unpriced, doubtful, review, raised, worn = ids
    outside = add_copy(store, "b", 80, price=250, name="Hors lot", catalog_id="sv1-120", number="120/198")
    with store.connect(write=True) as db:
        # Played: no automatic price alone, the floor alone sets it.
        db.execute("UPDATE copies SET condition='PL' WHERE id=?", (worn,))
        db.execute("UPDATE copies SET reference_cents=NULL WHERE id=?", (unpriced,))
        db.execute(
            "UPDATE copies SET identification_status='unresolved', reference_cents=NULL WHERE id=?", (doubtful,)
        )
        # The stored reference rose above today's displayed price: the floor wins.
        db.execute("UPDATE copies SET reference_cents=500 WHERE id=?", (raised,))
    flip_to_review(store, review)
    response = unpublish(client, listing_id, listing(store, listing_id)["version"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert listing(store, listing_id)["state"] == "offline" and sale(store, sale_id)["status"] == "cancelled"

    relisted = {r["copy_id"]: r for r in body["relisted"]}
    assert set(relisted) == {high, raised, worn}
    floor = lot_floor_cents(500, margin(store))
    assert relisted[raised]["floor_cents"] == floor and relisted[raised]["price_cents"] == floor > 300
    assert relisted[high]["price_cents"] == 300 > relisted[high]["floor_cents"] == lot_floor_cents(300, margin(store))
    assert relisted[worn]["price_cents"] == relisted[worn]["floor_cents"] == lot_floor_cents(300, margin(store))
    assert single(store, high)["price_mode"] == "trend" and single(store, worn)["price_mode"] == "manual"
    for copy_id, entry in relisted.items():
        made = single(store, copy_id)
        assert made["id"] == entry["listing_id"] and made["price_cents"] == entry["price_cents"]
        assert made["published_by"] == "agent:" + grant["id"] and made["state"] == "online"
    codes = {r["copy_id"]: r["code"] for r in body["not_relisted"]}
    assert codes == {
        low: "below_minimum", unpriced: "no_price", doubtful: "identity_unconfirmed", review: "review_needed",
    }
    assert all(single(store, c) is None for c in codes)
    assert single(store, outside["id"]) is None
    # A single listing is not a lot: the daily quota of published lots does not move.
    (op,) = [e for e in events(store, "lot-op") if e["after"]["op"] == "unpublish"]
    assert op["after"]["published"] == 0 and op["actor"] == "agent:" + grant["id"]
    # Replaying the withdrawal lists nothing twice.
    again = unpublish(client, listing_id, listing(store, listing_id)["version"])
    assert again.status_code == 409
    assert [single(store, c)["id"] for c in relisted] == [r["listing_id"] for r in relisted.values()]


def test_a_failed_relist_rolls_the_whole_withdrawal_back(shop, monkeypatch):
    client, service, *_ = shop
    store = service.store
    sale_id, ids, listing_id = lot_of(store, [("Une", 300), ("Deux", 400)])
    original = Listings.publish
    calls = []

    def second_breaks(self, copy_ids, actor, **kwargs):
        calls.append(copy_ids)
        if len(calls) == 2:
            raise RuntimeError("Panne simulée")
        return original(self, copy_ids, actor, **kwargs)

    monkeypatch.setattr(Listings, "publish", second_breaks)
    before = snapshot(store)
    with pytest.raises(RuntimeError):
        unpublish(client, listing_id, listing(store, listing_id)["version"])
    assert len(calls) == 2
    assert listing(store, listing_id)["state"] == "online" and sale(store, sale_id)["status"] == "draft"
    assert all(single(store, c) is None for c in ids)
    assert [line for line in snapshot(store) if line not in before and "lot-denied" not in line] == []


def test_a_refused_card_leaves_no_partial_listing(shop, monkeypatch):
    client, service, *_ = shop
    store = service.store
    sale_id, ids, listing_id = lot_of(store, [("Une", 300), ("Deux", 400)])
    original = Listings.publish

    def insert_then_conflict(self, copy_ids, actor, **kwargs):
        made = original(self, copy_ids, actor, **kwargs)
        if copy_ids == [ids[0]]:
            raise Conflict("Un exemplaire a été réservé entre-temps.")
        return made

    monkeypatch.setattr(Listings, "publish", insert_then_conflict)
    body = unpublish(client, listing_id, listing(store, listing_id)["version"]).json()
    assert [r["copy_id"] for r in body["relisted"]] == [ids[1]]
    assert [(r["copy_id"], r["code"]) for r in body["not_relisted"]] == [(ids[0], "refused")]
    assert single(store, ids[0]) is None
    with store.connect() as db:
        rows = db.execute(
            "SELECT count(*) FROM listing_items WHERE copy_id=? AND listing_id != ?", (ids[0], listing_id)
        ).fetchone()[0]
    assert rows == 0 and sale(store, sale_id)["status"] == "cancelled"


def test_without_lots_publish_nothing_is_withdrawn_nor_relisted(shop):
    client, service, *_ = shop
    store = service.store
    _, ids, listing_id = lot_of(store, [("Une", 300), ("Deux", 400)])
    compose_only = service.issue("Compo", "owner", "a", client="Synthetic", permissions=["lots:read", "lots:compose"])
    response = client.post(
        f"{LOTS}/{listing_id}/unpublish",
        json={"expected_version": listing(store, listing_id)["version"], "reason": "Test"},
        headers={"Authorization": "Bearer " + compose_only["token"]},
    )
    assert response.status_code == 403
    assert listing(store, listing_id)["state"] == "online"
    assert all(single(store, c) is None for c in ids)


def test_rotation_relists_only_the_cards_the_replacement_leaves_out(shop, monkeypatch):
    client, service, grant, _ = shop
    store = service.store
    old, old_listing = online_lot(store, "Lot", DEFAULT_ROTATION_DAYS + 1, 0)
    old_ids, free = offer(
        monkeypatch, store, old, lambda old_ids, free: [("En partie", [old_ids[0], *free[:2]])]
    )
    with store.connect(write=True) as db:
        # Checked condition: alone, the cards take today's trend (1 € and up).
        db.executemany("UPDATE copies SET condition_confirmed=1 WHERE id=?", [(c,) for c in old_ids])
    body = rotate(client).json()
    (done,) = body["online_rotation"]["replaced"]
    assert done["replaced_listing_id"] == old_listing
    assert {r["copy_id"] for r in done["relisted"]} == set(old_ids[1:]), done
    assert done["not_relisted"] == [{"copy_id": old_ids[0], "code": "in_replacement"}], done
    assert active_listing(store, old_ids[0])["id"] == done["listing_id"]
    for entry in done["relisted"]:
        made = single(store, entry["copy_id"])
        assert made["id"] == entry["listing_id"] and made["published_by"] == "agent:" + grant["id"]
        assert made["price_cents"] == entry["price_cents"] >= max(100, entry["floor_cents"])
    op = [e for e in events(store, "lot-op") if e["after"]["op"] == "rotate-online"]
    assert [(e["after"]["drafts_created"], e["after"]["published"]) for e in op] == [(1, 1)]
    # The same key replays the stored answer and lists nothing twice.
    listed = sorted(single(store, c)["id"] for c in old_ids[1:])
    assert rotate(client).json() == {**body, "replayed": True}
    assert sorted(single(store, c)["id"] for c in old_ids[1:]) == listed
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM listings WHERE state='online'").fetchone()[0] == 1 + len(listed)


def test_a_card_already_listed_alone_keeps_its_listing(shop):
    client, service, *_ = shop
    store = service.store
    _, ids, listing_id = lot_of(store, [("Une", 300), ("Deux", 400)])
    body = unpublish(client, listing_id, listing(store, listing_id)["version"]).json()
    assert len(body["relisted"]) == 2
    # Running the engine again on the same cards finds them listed and leaves them.
    with store.connect(write=True) as db:
        again = engine(store).relist_released(db, ids, "agent:x")
    assert again["relisted"] == []
    assert {r["code"] for r in again["not_relisted"]} == {"already_listed"}


@pytest.mark.parametrize("price", [90, 60])
def test_under_one_euro_after_the_floor_stays_unlisted(shop, price):
    client, service, *_ = shop
    store = service.store
    _, ids, listing_id = lot_of(store, [("Une", price), ("Deux", 300)])
    body = unpublish(client, listing_id, listing(store, listing_id)["version"]).json()
    assert [r["copy_id"] for r in body["relisted"]] == [ids[1]]
    assert body["not_relisted"][0]["copy_id"] == ids[0] and body["not_relisted"][0]["code"] == "below_minimum"
    assert single(store, ids[0]) is None
