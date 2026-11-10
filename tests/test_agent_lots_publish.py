"""Publication routes of the lots tool on the agent API: publish, unpublish, online rotation."""

import pytest
from fastapi.testclient import TestClient
from test_agent_lots_compose import (
    LOTS,
    PASSWORD,
    RECIPE,
    drafts,
    duplicate_ids,
    engine,
    events,
    human_draft,
    no_network,
    put_online,
    sale,
    snapshot,
    tool_draft,
    user_version,
)
from test_pokeprice_lots import add_copy, test_db  # noqa: F401 - fixture

import pokeprice.agent_lots_compose as compose_api
from pokeprice.agent import AgentService
from pokeprice.agent_api import schema
from pokeprice.agent_lots_publish import LotsPublisher
from pokeprice.floor_requests import REQUEST as WAIVER_REQUEST
from pokeprice.inventory import SCHEMA_VERSION
from pokeprice.listings import Listings
from pokeprice.lots import LotsEngine
from pokeprice.lots.settings import DEFAULT_ROTATION_DAYS
from pokeprice.pricing import FLOOR_CENTS, lot_floor_cents, lot_max_margin
from pokeprice.webapp import UserCreate, add_user, create_app

ALL_LOTS = ["lots:read", "lots:compose", "lots:publish"]


@pytest.fixture
def shop(test_db):  # noqa: F811
    """The lots tool base, more duplicates, and a grant that may read, compose and publish."""
    _, store = test_db
    with store.connect(write=True) as db:
        add_user(db, UserCreate(username="owner", password=PASSWORD, role="admin"))
    for position in (10, 11, 12):
        add_copy(store, "b", position, price=150, name="Kabuto", catalog_id="dp5-60", number="60/100")
    for position in range(30, 46):
        add_copy(store, "b", position, price=120, name="Amonita", catalog_id="dp5-61", number="61/100")
    app = create_app(
        store.root,
        intake_reader=no_network,
        intake_lookup=no_network,
        price_fetch=no_network,
        variant_fetch=no_network,
        market_fetch=no_network,
    )
    service = AgentService(store)
    grant = service.issue("Lots", "owner", "a", client="Synthetic lots client", permissions=ALL_LOTS)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + grant["token"]
        yield client, service, grant, app


def publish(client, sale_id, version, *, dry_run=False, key="p1"):
    return client.post(
        f"{LOTS}/{sale_id}/publish",
        json={"expected_version": version, "dry_run": dry_run},
        headers={"Idempotency-Key": key},
    )


def unpublish(client, listing_id, version, reason="Plus d'actualité"):
    return client.post(f"{LOTS}/{listing_id}/unpublish", json={"expected_version": version, "reason": reason})


def rotate(client, key="r1", dry_run=False):
    return client.post(LOTS + "/rotate", json={"dry_run": dry_run}, headers={"Idempotency-Key": key})


def listing(store, listing_id):
    with store.connect() as db:
        return dict(db.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone())


def active_listing(store, copy_id):
    with store.connect() as db:
        return Listings.active(db, copy_id)


def flip_to_review(store, copy_id):
    """A held quote after the last price snapshot puts the copy under review."""
    with store.connect(write=True) as db:
        store.event(db, copy_id, "system:prices", "price-held", "Cote retenue", {}, {"held": {"proposed_cents": 90}})


def waivers(store):
    with store.connect() as db:
        return db.execute("SELECT count(*) FROM events WHERE kind=?", (WAIVER_REQUEST,)).fetchone()[0]


def written(before, store):
    """Dump lines a call added, apart from its journaled refusal."""
    return [
        line for line in snapshot(store)
        if line not in before and "lot-denied" not in line and "sqlite_sequence" not in line
    ]


def floor_of(store, copy_ids):
    with store.connect() as db:
        marks = ",".join("?" for _ in copy_ids)
        total = db.execute(f"SELECT sum(reference_cents) FROM copies WHERE id IN ({marks})", copy_ids).fetchone()[0]
        return max(FLOOR_CENTS, lot_floor_cents(total, lot_max_margin(db)))


def fresh_tool_draft(store, count=3, price=1000, title="Lot outil", skip=0):
    free = duplicate_ids(store)[skip : skip + count]
    sale_id = tool_draft(store, free, price, title=title)
    return sale_id, free, sale(store, sale_id)["version"]


# -- Contract ---------------------------------------------------------------------


def test_the_contract_lists_the_publish_routes_and_nothing_more():
    paths = schema()["paths"]
    assert set(paths[LOTS + "/{sale_id}/publish"]) == {"post"}
    assert set(paths[LOTS + "/{listing_id}/unpublish"]) == {"post"}
    keys = [p for p in paths[LOTS + "/{sale_id}/publish"]["post"]["parameters"] if p["name"] == "Idempotency-Key"]
    assert keys and keys[0]["required"]
    lots_paths = sorted(p for p in paths if p.startswith(LOTS))
    assert lots_paths == sorted(
        LOTS + suffix
        for suffix in (
            "",
            "/pool",
            "/status",
            "/plan",
            "/rotate",
            "/{sale_id}/publication",
            "/{sale_id}/cancel",
            "/{sale_id}/raise",
            "/{sale_id}/publish",
            "/{listing_id}/unpublish",
        )
    )
    assert not [p for p in paths if "publish-all" in p or "grant" in p or "waiver" in p or "floor" in p]


def every_lots_call(sale_id="inconnu", listing_id="inconnue"):
    return [
        ("get", LOTS + "/pool", None, {}),
        ("get", LOTS + "/status", None, {}),
        ("post", LOTS + "/plan", {"recipe": RECIPE}, {}),
        ("get", f"{LOTS}/{sale_id}/publication", None, {}),
        ("post", LOTS, {"recipe": RECIPE, "plan_id": "0" * 64}, {"Idempotency-Key": "a"}),
        ("post", LOTS + "/rotate", {}, {"Idempotency-Key": "b"}),
        ("post", f"{LOTS}/{sale_id}/cancel", {"expected_version": 1, "reason": "Test"}, {}),
        ("post", f"{LOTS}/{sale_id}/raise", {"expected_version": 1, "asking_cents": 500}, {}),
        ("post", f"{LOTS}/{sale_id}/publish", {"expected_version": 1, "dry_run": False}, {"Idempotency-Key": "c"}),
        ("post", f"{LOTS}/{listing_id}/unpublish", {"expected_version": 1, "reason": "Test"}, {}),
    ]


def call(client, method, path, body, headers, token=None):
    if token:
        headers = {"Authorization": "Bearer " + token, **headers}
    if method == "get":
        return client.get(path, headers=headers)
    return client.post(path, json=body, headers=headers)


@pytest.mark.parametrize("permissions", [["lots:read"], ["lots:read", "lots:compose"], ["copies:read"]])
def test_publish_and_unpublish_require_lots_publish(shop, permissions):
    client, service, *_ = shop
    sale_id, free, version = fresh_tool_draft(service.store)
    listing_id = put_online(service.store, tool_draft(service.store, duplicate_ids(service.store)[:3], 1000))
    other = service.issue("Autre", "owner", "a", client="Synthetic", permissions=permissions)
    before = snapshot(service.store)
    for method, path, body, headers in every_lots_call(sale_id, listing_id)[-2:]:
        body = {**body, "expected_version": version if "publish" in path and "un" not in path else 1}
        response = call(client, method, path, body, headers, other["token"])
        assert response.status_code == 403, (path, response.text)
        assert response.json()["code"] == "forbidden"
    assert snapshot(service.store) == before


def test_the_sealed_pilot_grant_is_refused_on_every_lots_route(shop):
    client, service, *_ = shop
    pilot = service.issue(
        "Pilote", "owner", "a", client="Pilot", permissions=["copies:read", "drafts:create", "photos:read"]
    )
    before = snapshot(service.store)
    for method, path, body, headers in every_lots_call():
        response = call(client, method, path, body, headers, pilot["token"])
        assert response.status_code == 403, (path, response.text)
    assert snapshot(service.store) == before


# -- Publish --------------------------------------------------------------------------


def test_publish_defaults_to_a_dry_run_that_writes_nothing(shop):
    client, service, *_ = shop
    sale_id, free, version = fresh_tool_draft(service.store)
    before = snapshot(service.store)
    for body in ({"expected_version": version}, {"expected_version": version, "dry_run": True}):
        response = client.post(f"{LOTS}/{sale_id}/publish", json=body, headers={"Idempotency-Key": "d1"})
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["dry_run"] is True and report["copies_count"] == 3
        assert "published_listing_id" not in report
    assert snapshot(service.store) == before


def test_publish_puts_a_tool_draft_online_in_one_transaction(shop):
    client, service, grant, _ = shop
    store = service.store
    sale_id, free, version = fresh_tool_draft(store)
    unit = Listings(store).publish([free[0]], "owner", price_cents=300)
    response = publish(client, sale_id, version)
    assert response.status_code == 200, response.text
    body = response.json()
    online = listing(store, body["published_listing_id"])
    assert online["state"] == "online" and online["published_by"] == "agent:" + grant["id"]
    assert online["price_cents"] == body["price_cents"] == 1000 and body["raised_to_floor"] is False
    assert [u["id"] for u in body["unpublish_listings"]] == [unit["id"]]
    assert listing(store, unit["id"])["state"] == "offline"
    published = sale(store, sale_id)
    assert published["status"] == "draft" and published["channel"] == "Vitrine"
    assert body["version"] == published["version"]
    (op,) = events(store, "lot-op")
    assert op["actor"] == "agent:" + grant["id"] and op["after"]["op"] == "publish"
    assert op["after"]["published"] == 1 and op["after"]["drafts_created"] == 0
    assert waivers(store) == 0
    assert user_version(store) == SCHEMA_VERSION


def test_a_price_under_the_floor_is_lifted_never_lowered(shop):
    client, service, *_ = shop
    store = service.store
    cheap, cheap_ids, cheap_version = fresh_tool_draft(store, price=60)
    body = publish(client, cheap, cheap_version).json()
    floor = floor_of(store, cheap_ids)
    assert floor > 60
    assert body["price_cents"] == floor and body["previous_price_cents"] == 60 and body["raised_to_floor"]
    assert listing(store, body["published_listing_id"])["price_cents"] == floor
    lifted = sale(store, cheap)
    assert lifted["amount_cents"] == lifted["asking_cents"] == floor
    dear, dear_ids, dear_version = fresh_tool_draft(store, price=9000)
    body = publish(client, dear, dear_version, key="p2").json()
    assert body["price_cents"] == 9000 and body["raised_to_floor"] is False
    # No waiver request is ever queued for an agent.
    assert waivers(store) == 0


def test_a_lot_with_an_unrated_card_is_refused_by_the_api_and_by_listings(shop):
    client, service, *_ = shop
    store = service.store
    free = duplicate_ids(store)[:2]
    unrated = add_copy(store, "b", 70, price=None, name="Sans cote", catalog_id="dp5-70", number="70/100")["id"]
    sale_id = tool_draft(store, [*free, unrated], 1000)
    before = snapshot(store)
    response = publish(client, sale_id, sale(store, sale_id)["version"])
    assert response.status_code == 422 and response.json()["code"] == "not_publishable"
    assert "sans cote" in response.json()["detail"]
    assert written(before, store) == []
    for actor in ("agent:abc", "pokeprice-lots"):
        with pytest.raises(ValueError, match="sans cote"):
            Listings(store).publish([*free, unrated], actor, price_cents=5000, lot=True)
    # A person publishing from the management app is not held to it, as before.
    assert Listings(store).publish([*free, unrated], "owner", price_cents=5000, lot=True)["state"] == "online"


def test_a_card_flipped_to_review_after_compose_is_refused(shop):
    client, service, *_ = shop
    store = service.store
    sale_id, free, version = fresh_tool_draft(store)
    flip_to_review(store, free[1])
    response = publish(client, sale_id, version)
    assert response.status_code == 422 and response.json()["code"] == "not_publishable"
    assert "review_needed" in response.json()["detail"]
    assert active_listing(store, free[0]) is None
    with pytest.raises(ValueError, match="à examiner"):
        Listings(store).publish(free, "agent:abc", price_cents=5000, lot=True)
    assert Listings(store).publish(free, "owner", price_cents=5000, lot=True)["state"] == "online"


def test_a_card_over_the_grant_ceiling_or_in_another_sale_is_refused(shop):
    client, service, *_ = shop
    store = service.store
    sale_id, free, version = fresh_tool_draft(store)
    human_draft(store, [free[2]])
    response = publish(client, sale_id, version)
    assert response.status_code == 422 and "autre vente" in response.json()["detail"]
    low = service.issue("Bas", "owner", "a", client="Synthetic", permissions=ALL_LOTS, value_ceiling_cents=100)
    other, _, other_version = fresh_tool_draft(store, skip=3)
    response = client.post(
        f"{LOTS}/{other}/publish",
        json={"expected_version": other_version, "dry_run": False},
        headers={"Idempotency-Key": "low", "Authorization": "Bearer " + low["token"]},
    )
    assert response.status_code == 422 and "valuable_card" in response.json()["detail"]


def test_a_hand_made_draft_cannot_be_published(shop):
    client, service, *_ = shop
    store = service.store
    human = human_draft(store, duplicate_ids(store)[:3])
    before = snapshot(store)
    response = publish(client, human, sale(store, human)["version"])
    assert response.status_code == 404 and response.json()["code"] == "not_found"
    assert sale(store, human)["channel"] == "Lot" and snapshot(store) != [] and drafts(store)
    assert written(before, store) == []


def test_publish_checks_version_and_refuses_an_online_lot(shop):
    client, service, *_ = shop
    sale_id, free, version = fresh_tool_draft(service.store)
    assert publish(client, sale_id, version + 1).status_code == 409
    assert publish(client, sale_id, version).status_code == 200
    again = publish(client, sale_id, sale(service.store, sale_id)["version"], key="p2")
    assert again.status_code == 409 and again.json()["code"] == "online_lot"


def test_publish_replays_its_key_and_refuses_another_body(shop):
    client, service, *_ = shop
    sale_id, free, version = fresh_tool_draft(service.store)
    first = publish(client, sale_id, version).json()
    assert publish(client, sale_id, version).json() == {**first, "replayed": True}
    conflict = publish(client, sale_id, version + 1)
    assert conflict.status_code == 409 and conflict.json()["code"] == "idempotency_conflict"
    assert len(events(service.store, "lot-op")) == 1


def test_publish_requires_an_idempotency_key(shop):
    client, service, *_ = shop
    sale_id, free, version = fresh_tool_draft(service.store)
    response = client.post(f"{LOTS}/{sale_id}/publish", json={"expected_version": version, "dry_run": False})
    assert response.status_code == 422


def test_the_daily_publish_quota(shop, monkeypatch):
    client, service, *_ = shop
    monkeypatch.setattr(compose_api, "DAILY_PUBLISHES", 1)
    first, _, first_version = fresh_tool_draft(service.store)
    second, _, second_version = fresh_tool_draft(service.store, skip=3)
    assert publish(client, first, first_version).status_code == 200
    refused = publish(client, second, second_version, key="p2")
    assert refused.status_code == 429 and refused.json()["code"] == "publish_quota"


def test_publish_uses_the_heavy_budget(shop):
    client, service, grant, _ = shop
    sale_id, free, version = fresh_tool_draft(service.store)
    for n in range(6):
        assert publish(client, sale_id, version, dry_run=True, key=f"d{n}").status_code == 200
    assert publish(client, sale_id, version, key="p1").status_code == 429


@pytest.mark.parametrize("change", ["revoke", "demote"])
def test_revocation_and_demotion_stop_the_next_call(shop, change):
    client, service, grant, _ = shop
    sale_id, free, version = fresh_tool_draft(service.store)
    if change == "revoke":
        service.revoke(grant["id"])
    else:
        with service.store.connect(write=True) as db:
            db.execute("UPDATE users SET role='editor' WHERE username='owner'")
    response = publish(client, sale_id, version)
    assert response.status_code == (401 if change == "revoke" else 403)
    assert sale(service.store, sale_id)["channel"] == "Lot"


# -- Unpublish ------------------------------------------------------------------------


def test_unpublish_returns_the_cards_to_the_pool(shop):
    client, service, grant, _ = shop
    store = service.store
    sale_id, free, version = fresh_tool_draft(store)
    listing_id = publish(client, sale_id, version).json()["published_listing_id"]
    assert not set(free) & set(duplicate_ids(store))
    response = unpublish(client, listing_id, listing(store, listing_id)["version"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "offline" and body["cancelled"] == [sale_id]
    assert sorted(body["released_copies"]) == sorted(free)
    assert sale(store, sale_id)["status"] == "cancelled"
    assert set(free) <= set(duplicate_ids(store))
    assert all(active_listing(store, c) is None for c in free)


def test_unpublish_never_touches_a_hand_made_or_single_card_listing(shop):
    client, service, *_ = shop
    store = service.store
    free = duplicate_ids(store)
    by_hand = Listings(store).publish(free[:3], "owner", price_cents=1000, lot=True)
    single = Listings(store).publish([free[3]], "agent:other", price_cents=300)
    before = snapshot(store)
    for item in (by_hand, single):
        response = unpublish(client, item["id"], item["version"])
        assert response.status_code == 404 and response.json()["code"] == "not_found"
    assert written(before, store) == []


def test_unpublish_checks_the_version_and_a_hand_made_sale(shop):
    client, service, *_ = shop
    store = service.store
    sale_id, free, version = fresh_tool_draft(store)
    listing_id = publish(client, sale_id, version).json()["published_listing_id"]
    current = listing(store, listing_id)["version"]
    assert unpublish(client, listing_id, current + 1).status_code == 409
    with store.connect(write=True) as db:
        # A person drafted one of its cards in the meantime (a Vinted deal).
        store.create_sale({"title": "Vinted", "channel": "", "amount_cents": 500}, [free[0]], "owner", _db=db)
    response = unpublish(client, listing_id, current)
    assert response.status_code == 409 and response.json()["code"] == "hand_made_sale"
    assert listing(store, listing_id)["state"] == "online"


# -- Online rotation ------------------------------------------------------------------


def another_theme(store):
    """Duplicates of another era, so that two replacement lots can be composed."""
    for position in range(50, 56):
        add_copy(store, "b", position, price=130, name="Salamèche", catalog_id="base1-46", number="46/102")


def online_lot(store, title, days_ago, skip, price=1000):
    free = duplicate_ids(store)[skip : skip + 3] if skip is not None else None
    sale_id = tool_draft(store, free or duplicate_ids(store)[:3], price, title=title)
    return sale_id, put_online(store, sale_id, days_ago=days_ago)


def test_online_rotation_needs_lots_publish(shop):
    client, service, *_ = shop
    store = service.store
    old, old_listing = online_lot(store, "Lot ancien", DEFAULT_ROTATION_DAYS + 1, 0)
    compose_only = service.issue("Compo", "owner", "a", client="Synthetic", permissions=["lots:read", "lots:compose"])
    body = client.post(
        LOTS + "/rotate", json={"dry_run": False},
        headers={"Idempotency-Key": "r1", "Authorization": "Bearer " + compose_only["token"]},
    ).json()
    assert [d["listing_id"] for d in body["due_online"]] == [old_listing]
    assert "online_rotation" not in body
    assert listing(store, old_listing)["state"] == "online"


def test_online_rotation_replaces_only_tool_lots_past_the_age(shop):
    client, service, grant, _ = shop
    store = service.store
    old, old_listing = online_lot(store, "Lot ancien", DEFAULT_ROTATION_DAYS + 1, 0)
    young, young_listing = online_lot(store, "Lot récent", 1, 0)
    by_hand = Listings(store).publish(duplicate_ids(store)[:3], "owner", price_cents=1000, lot=True)
    with store.connect(write=True) as db:
        db.execute("UPDATE listings SET published_at='2020-01-01T00:00:00+00:00' WHERE id=?", (by_hand["id"],))
    before = snapshot(store)
    preview = rotate(client, "dry", dry_run=True).json()
    assert [p["listing_id"] for p in preview["online_rotation"]["planned"]] == [old_listing]
    assert preview["online_rotation"]["planned"][0]["replacement"]["count"] >= 2
    assert snapshot(store) == before
    body = rotate(client).json()
    assert body["online_rotation"]["failed"] == [], body["online_rotation"]
    (done,) = body["online_rotation"]["replaced"]
    assert (done["replaced_sale_id"], done["replaced_listing_id"]) == (old, old_listing)
    assert listing(store, old_listing)["state"] == "offline" and sale(store, old)["status"] == "cancelled"
    fresh = listing(store, done["listing_id"])
    assert fresh["state"] == "online" and fresh["published_by"] == "agent:" + grant["id"]
    assert done["price_cents"] >= FLOOR_CENTS and sale(store, done["sale_id"])["channel"] == "Vitrine"
    with store.connect() as db:
        assert LotsEngine.tool_made(db, done["sale_id"])
    assert listing(store, young_listing)["state"] == "online" and sale(store, young)["status"] == "draft"
    assert listing(store, by_hand["id"])["state"] == "online"
    assert body["due_online"] == []
    op = [e for e in events(store, "lot-op") if e["after"]["op"] == "rotate-online"]
    assert [(e["after"]["drafts_created"], e["after"]["published"]) for e in op] == [(1, 1)]
    assert rotate(client).json() == {**body, "replayed": True}


def test_online_rotation_goes_oldest_first_within_the_quotas(shop, monkeypatch):
    client, service, *_ = shop
    store = service.store
    monkeypatch.setattr(compose_api, "DAILY_PUBLISHES", 1)
    another_theme(store)
    newer, newer_listing = online_lot(store, "Lot moins ancien", DEFAULT_ROTATION_DAYS + 2, 0)
    oldest, oldest_listing = online_lot(store, "Lot le plus ancien", DEFAULT_ROTATION_DAYS + 5, 0)
    report = rotate(client).json()["online_rotation"]
    assert [r["replaced_listing_id"] for r in report["replaced"]] == [oldest_listing]
    assert report["skipped"] == [{"sale_id": newer, "listing_id": newer_listing, "code": "publish_quota"}]
    assert listing(store, newer_listing)["state"] == "online"


def test_a_failed_replacement_leaves_its_lot_online(shop, monkeypatch):
    client, service, *_ = shop
    store = service.store
    another_theme(store)
    first, first_listing = online_lot(store, "Lot A", DEFAULT_ROTATION_DAYS + 5, 0)
    second, second_listing = online_lot(store, "Lot B", DEFAULT_ROTATION_DAYS + 2, 0)
    original = LotsPublisher.plan_online

    def then_flip(self, db, engine, due):
        plans = original(self, db, engine, due)
        paid = [c for c in plans[0]["replacement"]["copies"] if not c.get("bonus")]
        flip_to_review(store, paid[0]["id"])
        return plans

    monkeypatch.setattr(LotsPublisher, "plan_online", then_flip)
    report = rotate(client).json()["online_rotation"]
    assert [(f["listing_id"], f["code"]) for f in report["failed"]] == [(first_listing, "not_publishable")]
    assert listing(store, first_listing)["state"] == "online" and sale(store, first)["status"] == "draft"
    assert [r["replaced_listing_id"] for r in report["replaced"]] == [second_listing]


def test_a_replacement_with_the_same_cards_never_costs_less(shop, monkeypatch):
    client, service, *_ = shop
    store = service.store
    old, old_listing = online_lot(store, "Lot cher", DEFAULT_ROTATION_DAYS + 1, 0, price=4000)
    with store.connect() as db:
        old_ids = [r[0] for r in db.execute("SELECT copy_id FROM sale_items WHERE sale_id=?", (old,))]
        versions = {r[0]: r[1] for r in db.execute("SELECT id, version FROM copies")}
    original = LotsEngine.analyze

    def same_cards(self, db, *args, **kwargs):
        result = original(self, db, *args, **kwargs)
        if not kwargs.get("released"):
            return result  # The draft rotation keeps the real pool.
        result["lots"] = [
            {
                "theme": "test",
                "title": "Lot cher, à nouveau",
                "count": 3,
                "total_reference_cents": 0,
                "asking_cents": 60,
                "copies": [{"id": c, "version": versions[c]} for c in old_ids],
            }
        ]
        return result

    monkeypatch.setattr(LotsEngine, "analyze", same_cards)
    (done,) = rotate(client).json()["online_rotation"]["replaced"]
    assert done["price_cents"] == 4000
    assert listing(store, done["listing_id"])["price_cents"] == 4000


def test_the_engine_still_refuses_for_the_script_without_agent_rules(shop):
    _, service, *_ = shop
    store = service.store
    sale_id, free, _ = fresh_tool_draft(store, price=60)
    with store.connect() as db, pytest.raises(ValueError, match="plancher"):
        engine(store).publication_plan(db, sale_id)
