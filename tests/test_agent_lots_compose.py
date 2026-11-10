"""Write routes of the lots tool on the agent API: compose, rotate, cancel, raise."""

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from test_pokeprice_lots import add_copy, test_db  # noqa: F401 - fixture

import pokeprice.agent_lots_compose as compose_api
from pokeprice.agent import AgentService
from pokeprice.agent_api import PREFIX, schema
from pokeprice.floor_requests import HumanOnly
from pokeprice.inventory import SCHEMA_VERSION
from pokeprice.lots import DEFAULT_ACTOR, LotsEngine
from pokeprice.lots.settings import DEFAULT_ROTATION_DAYS, lot_rotation_days, set_lot_rotation_days
from pokeprice.webapp import UserCreate, add_user, create_app

PASSWORD = "Lots-api-test-password!"
LOTS = PREFIX + "/lots"
RECIPE = {
    "title": "Doublons Duels au Sommet",
    "summary": "Les doublons de la série.",
    "bundle_rules": {"target_count": 3, "diversity": "any"},
}


def no_network(*args, **kwargs):
    raise AssertionError("A lots write must never call a model or a catalogue")


@pytest.fixture
def lots(test_db):  # noqa: F811
    """The lots tool base, more duplicates, and a grant that may read and compose."""
    _, store = test_db
    with store.connect(write=True) as db:
        user = add_user(db, UserCreate(username="owner", password=PASSWORD, role="admin"))
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
    grant = service.issue(
        "Lots", "owner", "a", client="Synthetic lots client", permissions=["lots:read", "lots:compose"]
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + grant["token"]
        yield client, service, grant, user, app


def engine(store):
    return LotsEngine(store, value_ceiling_cents=1000)


def snapshot(store):
    with store.connect() as db:
        return list(db.iterdump())


def duplicate_ids(store):
    with store.connect() as db:
        return [c["id"] for c in engine(store).classify_pool(db)["duplicates"]]


def retained_ids(store):
    with store.connect() as db:
        return {c["id"] for c in engine(store).classify_pool(db)["retained"]}


def tool_draft(store, copy_ids, price_cents, title="Lot outil"):
    lot = {
        "title": title,
        "summary": "Lot de test",
        "total_reference_cents": 0,
        "asking_cents": price_cents,
        "copies": [{"id": c} for c in copy_ids],
    }
    with store.connect(write=True) as db:
        return engine(store).create_draft(db, lot, DEFAULT_ACTOR)


def human_draft(store, copy_ids, title="Vinted pour une amie"):
    with store.connect(write=True) as db:
        return store.create_sale(
            {"title": title, "channel": "Lot", "amount_cents": 500, "asking_cents": 500}, copy_ids, "owner", _db=db
        )


def sale(store, sale_id):
    with store.connect() as db:
        return dict(db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone())


def drafts(store):
    with store.connect() as db:
        return [dict(r) for r in db.execute("SELECT id, status, title FROM sales WHERE status='draft'")]


def drafted_copies(store):
    with store.connect() as db:
        return [
            r[0]
            for r in db.execute(
                "SELECT si.copy_id FROM sale_items si JOIN sales s ON s.id=si.sale_id WHERE s.status='draft'"
            )
        ]


def put_online(store, sale_id, days_ago=0):
    with store.connect(write=True) as db:
        report = engine(store).publish_lot(db, sale_id, DEFAULT_ACTOR)
        stamp = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        db.execute("UPDATE listings SET published_at=? WHERE id=?", (stamp, report["published_listing_id"]))
    return report["published_listing_id"]


def plan(client, recipe=RECIPE):
    response = client.post(LOTS + "/plan", json={"recipe": recipe})
    assert response.status_code == 200, response.text
    return response.json()


def compose(client, body, key="k1", **headers):
    return client.post(LOTS, json=body, headers={"Idempotency-Key": key, **headers})


def events(store, kind):
    with store.connect() as db:
        return [
            {**dict(r), "after": json.loads(r["after_json"])}
            for r in db.execute("SELECT actor, after_json, created_at FROM events WHERE kind=? ORDER BY id", (kind,))
        ]


def user_version(store):
    with store.connect() as db:
        return db.execute("PRAGMA user_version").fetchone()[0]


# -- Contract ---------------------------------------------------------------------


def test_the_contract_lists_the_compose_routes():
    paths = schema()["paths"]
    assert set(paths[LOTS]) == {"post"}
    assert set(paths[LOTS + "/rotate"]) == {"post"}
    assert set(paths[LOTS + "/{sale_id}/cancel"]) == {"post"}
    assert set(paths[LOTS + "/{sale_id}/raise"]) == {"post"}
    keys = [p for p in paths[LOTS]["post"]["parameters"] if p["name"] == "Idempotency-Key"]
    assert keys and keys[0]["required"]


def write_calls(sale_id="inconnu"):
    return [
        ("post", LOTS, {"recipe": RECIPE, "plan_id": "0" * 64}, {"Idempotency-Key": "a"}),
        ("post", LOTS + "/rotate", {}, {"Idempotency-Key": "b"}),
        ("post", f"{LOTS}/{sale_id}/cancel", {"expected_version": 1, "reason": "Test"}, {}),
        ("post", f"{LOTS}/{sale_id}/raise", {"expected_version": 1, "asking_cents": 500}, {}),
    ]


@pytest.mark.parametrize("permissions", [["lots:read"], ["lots:publish"], ["copies:read"]])
def test_every_write_requires_lots_compose(lots, permissions):
    client, service, *_ = lots
    other = service.issue("Autre", "owner", "a", client="Synthetic", permissions=permissions)
    before = snapshot(service.store)
    for method, path, body, headers in write_calls():
        response = getattr(client, method)(
            path, json=body, headers={"Authorization": "Bearer " + other["token"], **headers}
        )
        assert response.status_code == 403, (path, response.text)
        assert response.json()["code"] == "forbidden"
    assert snapshot(service.store) == before


# -- Compose ------------------------------------------------------------------------


def test_compose_creates_the_planned_tool_draft(lots):
    client, service, grant, *_ = lots
    planned = plan(client)
    response = compose(client, {"recipe": RECIPE, "plan_id": planned["plan_id"]})
    assert response.status_code == 201, response.text
    body = response.json()
    created = sale(service.store, body["sale_id"])
    assert created["status"] == "draft" and created["channel"] == "Lot"
    assert body["asking_cents"] == created["asking_cents"] == created["amount_cents"]
    assert body["asking_cents"] == planned["lot"]["asking_cents"] >= body["floor_cents"]
    assert body["raised_to_floor"] is False and body["version"] == created["version"]
    assert [c["id"] for c in body["copies"]] == [c["id"] for c in planned["lot"]["copies"]]
    with service.store.connect() as db:
        assert LotsEngine.tool_made(db, body["sale_id"])
        actor = db.execute(
            "SELECT actor FROM sale_events WHERE sale_id=? ORDER BY id LIMIT 1", (body["sale_id"],)
        ).fetchone()[0]
    assert actor == "agent:" + grant["id"]
    assert user_version(service.store) == SCHEMA_VERSION


@pytest.mark.parametrize(
    "extra",
    [
        {"copies": [{"id": "x", "version": 1}]},
        {"bonus": []},
        {"actor": "owner"},
        {"scope": "all"},
        {"max_drafts": 10},
        {"margin": 50},
    ],
)
def test_a_client_cannot_choose_copies_bonus_actor_scope_or_cap(lots, extra):
    client, service, *_ = lots
    planned = plan(client)
    before = snapshot(service.store)
    response = compose(client, {"recipe": RECIPE, "plan_id": planned["plan_id"], **extra})
    assert response.status_code == 422
    assert set(response.json()) == {"code", "detail", "request_id"}
    assert snapshot(service.store) == before


def test_compose_requires_an_idempotency_key(lots):
    client, *_ = lots
    planned = plan(client)
    response = client.post(LOTS, json={"recipe": RECIPE, "plan_id": planned["plan_id"]})
    assert response.status_code == 422
    assert compose(client, {"recipe": RECIPE, "plan_id": planned["plan_id"]}, key="espace interdite").status_code == 422


def test_a_stale_plan_is_refused(lots):
    client, service, *_ = lots
    planned = plan(client)
    assert compose(client, {"recipe": RECIPE, "plan_id": "f" * 64}).json()["code"] == "stale_plan"
    with service.store.connect(write=True) as db:
        db.execute("UPDATE copies SET version=version+1 WHERE id=?", (planned["lot"]["copies"][0]["id"],))
    before = drafts(service.store)
    response = compose(client, {"recipe": RECIPE, "plan_id": planned["plan_id"]}, key="k2")
    assert response.status_code == 409 and response.json()["code"] == "stale_plan"
    assert drafts(service.store) == before


def test_a_copy_taken_after_the_plan_makes_it_stale(lots):
    client, service, *_ = lots
    planned = plan(client)
    human_draft(service.store, [planned["lot"]["copies"][0]["id"]])
    response = compose(client, {"recipe": RECIPE, "plan_id": planned["plan_id"]})
    assert response.status_code == 409 and response.json()["code"] == "stale_plan"


def test_album_copies_cannot_be_pulled_in(lots):
    client, service, *_ = lots
    album = retained_ids(service.store)
    # Every Kabuto: the album keeps the best one, the recipe may only take the two others.
    recipe = {**RECIPE, "filters": {"pokemon_names": ["Kabuto"]}, "bundle_rules": {"target_count": 10, "diversity": "any"}}
    planned = plan(client, recipe)
    body = compose(client, {"recipe": recipe, "plan_id": planned["plan_id"]}).json()
    chosen = {c["id"] for c in body["copies"] + body["bonus"]}
    assert len(body["copies"]) == 2 and not chosen & album


def test_asking_may_only_raise_the_computed_price(lots):
    client, service, *_ = lots
    planned = plan(client)
    computed = planned["lot"]["asking_cents"]
    low = compose(client, {"recipe": RECIPE, "plan_id": planned["plan_id"], "asking_cents": computed - 1})
    assert low.status_code == 422 and low.json()["code"] == "price_lowered"
    high = compose(client, {"recipe": RECIPE, "plan_id": planned["plan_id"], "asking_cents": computed + 300}, key="k2")
    assert high.status_code == 201 and high.json()["asking_cents"] == computed + 300


def test_a_price_under_the_floor_is_raised_to_it(lots, monkeypatch):
    client, service, *_ = lots
    original = LotsEngine.compose_from_recipe

    def cheap(self, db, recipe, **kwargs):
        # A composition priced below the floor, the same for the plan and the compose.
        result = original(self, db, recipe, **kwargs)
        result["lot"]["asking_cents"] = 60
        return result

    monkeypatch.setattr(LotsEngine, "compose_from_recipe", cheap)
    planned = plan(client)
    body = compose(client, {"recipe": RECIPE, "plan_id": planned["plan_id"]}).json()
    assert body["computed_asking_cents"] == 60 and body["raised_to_floor"] is True
    assert body["asking_cents"] == body["floor_cents"] == planned["lot"]["floor_cents"] > 60
    assert sale(service.store, body["sale_id"])["asking_cents"] == body["floor_cents"]
    assert events(service.store, "floor-request") == []


def test_two_concurrent_composes_never_book_the_same_copy(lots):
    client, service, *_ = lots
    planned = plan(client)
    body = {"recipe": RECIPE, "plan_id": planned["plan_id"]}
    barrier = threading.Barrier(2)
    results = []

    def attempt(key):
        barrier.wait()
        results.append(compose(client, body, key=key))

    threads = [threading.Thread(target=attempt, args=(key,)) for key in ("left", "right")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(r.status_code for r in results) == [201, 409]
    assert [r.json()["code"] for r in results if r.status_code == 409] == ["stale_plan"]
    booked = drafted_copies(service.store)
    assert len(booked) == len(set(booked))


def test_the_draft_cap_is_checked_inside_the_transaction(lots):
    client, service, *_ = lots
    planned = plan(client)
    planned_ids = {c["id"] for c in planned["lot"]["copies"] + planned["lot"]["bonus"]}
    # Five drafts appear between the plan and the compose, on other duplicates:
    # the plan itself does not change.
    others = [c for c in duplicate_ids(service.store) if c not in planned_ids]
    for n in range(5):
        tool_draft(service.store, others[n : n + 1], 400, title=f"Lot {n}")
    assert plan(client)["plan_id"] == planned["plan_id"]
    response = compose(client, {"recipe": RECIPE, "plan_id": planned["plan_id"]})
    assert response.status_code == 409 and response.json()["code"] == "draft_cap"
    assert len(drafts(service.store)) == 5


# -- Idempotency and quotas -------------------------------------------------------------


def test_the_same_key_replays_and_a_different_body_conflicts(lots):
    client, service, *_ = lots
    planned = plan(client)
    body = {"recipe": RECIPE, "plan_id": planned["plan_id"]}
    first = compose(client, body)
    again = compose(client, body)
    assert first.status_code == again.status_code == 201
    assert again.json() == {**first.json(), "replayed": True}
    assert len(drafts(service.store)) == 1
    other = compose(client, {**body, "asking_cents": 9000})
    assert other.status_code == 409 and other.json()["code"] == "idempotency_conflict"
    assert len(drafts(service.store)) == 1
    # Replayed before validation: the plan is stale by now, the answer is still the stored one.
    assert compose(client, body).json()["sale_id"] == first.json()["sale_id"]


def test_two_grants_may_use_the_same_key(lots):
    client, service, *_ = lots
    other = service.issue("Autre", "owner", "a", client="Synthetic", permissions=["lots:read", "lots:compose"])
    first = compose(client, {"recipe": RECIPE, "plan_id": plan(client)["plan_id"]}, key="same-key")
    planned = plan(client)
    second = compose(
        client, {"recipe": RECIPE, "plan_id": planned["plan_id"]}, key="same-key", Authorization="Bearer " + other["token"]
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["sale_id"] != second.json()["sale_id"]


def test_the_daily_draft_quota(lots, monkeypatch):
    client, service, *_ = lots
    monkeypatch.setattr(compose_api, "DAILY_DRAFTS", 1)
    assert compose(client, {"recipe": RECIPE, "plan_id": plan(client)["plan_id"]}).status_code == 201
    response = compose(client, {"recipe": RECIPE, "plan_id": plan(client)["plan_id"]}, key="k2")
    assert response.status_code == 429 and response.json()["code"] == "draft_quota"


def test_refusals_are_journaled_once_a_minute_and_capped(lots, monkeypatch):
    client, service, grant, *_ = lots
    monkeypatch.setattr(compose_api, "DAILY_REFUSALS", 2)
    for key in ("a", "b"):
        assert compose(client, {"recipe": RECIPE, "plan_id": "f" * 64}, key=key).json()["code"] == "stale_plan"
    denied = events(service.store, "lot-denied")
    assert [(e["actor"], e["after"]["op"], e["after"]["code"]) for e in denied] == [
        ("agent:" + grant["id"], "compose", "stale_plan")
    ]
    assert client.post(f"{LOTS}/inconnu/cancel", json={"expected_version": 1, "reason": "x"}).status_code == 404
    assert len(events(service.store, "lot-denied")) == 2
    blocked = compose(client, {"recipe": RECIPE, "plan_id": plan(client)["plan_id"]}, key="c")
    assert blocked.status_code == 429 and blocked.json()["code"] == "refusal_quota"
    assert len(events(service.store, "lot-denied")) == 2 and drafts(service.store) == []


def test_every_write_is_journaled_without_a_copy(lots):
    client, service, grant, *_ = lots
    body = compose(client, {"recipe": RECIPE, "plan_id": plan(client)["plan_id"]}).json()
    journal = events(service.store, "lot-op")
    assert len(journal) == 1 and journal[0]["actor"] == "agent:" + grant["id"]
    after = journal[0]["after"]
    assert after["key"] == "k1" and after["op"] == "compose" and after["drafts_created"] == 1
    assert len(after["request_sha256"]) == 64 and after["response"]["sale_id"] == body["sale_id"]
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM events WHERE kind='lot-op' AND copy_id IS NOT NULL").fetchone()[0] == 0


# -- Cancel and raise -------------------------------------------------------------------


def test_cancel_a_tool_draft(lots):
    client, service, *_ = lots
    sale_id = tool_draft(service.store, duplicate_ids(service.store)[:2], 400)
    version = sale(service.store, sale_id)["version"]
    stale = client.post(f"{LOTS}/{sale_id}/cancel", json={"expected_version": version + 1, "reason": "Doublon"})
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    response = client.post(f"{LOTS}/{sale_id}/cancel", json={"expected_version": version, "reason": "Doublon"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == sale(service.store, sale_id)["status"] == "cancelled"
    again = client.post(f"{LOTS}/{sale_id}/cancel", json={"expected_version": response.json()["version"], "reason": "x"})
    assert again.status_code == 409 and again.json()["code"] == "not_draft"


def test_a_hand_made_draft_cannot_be_cancelled_or_raised(lots):
    client, service, *_ = lots
    theirs = human_draft(service.store, duplicate_ids(service.store)[:2])
    for path, body in (("cancel", {"expected_version": 1, "reason": "x"}), ("raise", {"expected_version": 1, "asking_cents": 900})):
        response = client.post(f"{LOTS}/{theirs}/{path}", json=body)
        assert response.status_code == 404 and "Vinted" not in response.text
    assert sale(service.store, theirs)["status"] == "draft" and sale(service.store, theirs)["asking_cents"] == 500


def test_a_draft_with_an_online_lot_cannot_be_cancelled(lots):
    client, service, *_ = lots
    sale_id = tool_draft(service.store, duplicate_ids(service.store)[:3], 1000)
    put_online(service.store, sale_id)
    version = sale(service.store, sale_id)["version"]
    response = client.post(f"{LOTS}/{sale_id}/cancel", json={"expected_version": version, "reason": "x"})
    assert response.status_code == 409 and response.json()["code"] == "online_lot"
    assert sale(service.store, sale_id)["status"] == "draft"


def test_raise_never_lowers_and_lifts_to_the_floor(lots):
    client, service, *_ = lots
    sale_id = tool_draft(service.store, duplicate_ids(service.store)[:3], 60, title="Lot bradé")
    current = sale(service.store, sale_id)
    lower = client.post(f"{LOTS}/{sale_id}/raise", json={"expected_version": current["version"], "asking_cents": 50})
    assert lower.status_code == 422 and lower.json()["code"] == "price_lowered"
    body = client.post(f"{LOTS}/{sale_id}/raise", json={"expected_version": current["version"], "asking_cents": 60}).json()
    assert body["previous_cents"] == 60 and body["raised_to_floor"] is True
    assert body["asking_cents"] == body["floor_cents"] > 60
    after = sale(service.store, sale_id)
    assert after["asking_cents"] == after["amount_cents"] == body["floor_cents"]
    higher = client.post(f"{LOTS}/{sale_id}/raise", json={"expected_version": after["version"], "asking_cents": 5000}).json()
    assert higher["asking_cents"] == 5000 and higher["raised_to_floor"] is False
    published = client.get(f"{LOTS}/{sale_id}/publication").json()
    assert published["publishable"] is True and published["price_cents"] == 5000


# -- Rotate -----------------------------------------------------------------------------


def test_rotate_defaults_to_a_dry_run_that_writes_nothing(lots):
    client, service, *_ = lots
    before = snapshot(service.store)
    response = client.post(LOTS + "/rotate", json={}, headers={"Idempotency-Key": "r1"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is True and body["lots_to_create"] and body["rotation_days"] == DEFAULT_ROTATION_DAYS
    assert all(line["asking_cents"] >= line["floor_cents"] for line in body["lots_to_create"])
    assert snapshot(service.store) == before
    assert client.post(LOTS + "/rotate", json={}).status_code == 422


@pytest.mark.parametrize("extra", [{"max_drafts": 10}, {"actor": "owner"}, {"lots_to_add": []}, {"limit": 6}, {"limit": -1}])
def test_rotate_takes_no_cap_actor_or_lots_from_the_request(lots, extra):
    client, *_ = lots
    response = client.post(LOTS + "/rotate", json=extra, headers={"Idempotency-Key": "r1"})
    assert response.status_code == 422


def test_rotate_creates_tool_drafts_and_only_cancels_its_own(lots):
    client, service, *_ = lots
    free = duplicate_ids(service.store)
    theirs = [human_draft(service.store, free[n : n + 1], title=f"Vinted {n}") for n in range(3)]
    mine = tool_draft(service.store, free[3:5], 400, title="Vieux lot")
    # Five drafts: one slot is the tool's, the hand-made ones are never cancelled.
    tool_draft(service.store, free[5:7], 400, title="Lot récent")
    body = client.post(LOTS + "/rotate", json={"dry_run": False}, headers={"Idempotency-Key": "r1"}).json()
    assert body["dry_run"] is False
    assert body["cancelled"] == [mine] and len(body["created"]) == 1
    assert all(sale(service.store, s)["status"] == "draft" for s in theirs)
    assert sale(service.store, mine)["status"] == "cancelled"
    assert len(drafts(service.store)) == 5
    with service.store.connect() as db:
        assert all(LotsEngine.tool_made(db, c["sale_id"]) for c in body["created"])
    booked = drafted_copies(service.store)
    assert len(booked) == len(set(booked))
    assert events(service.store, "lot-op")[0]["after"]["drafts_created"] == 1


def test_rotate_with_only_hand_made_drafts_creates_nothing(lots):
    client, service, *_ = lots
    free = duplicate_ids(service.store)
    theirs = [human_draft(service.store, free[n : n + 1], title=f"Vinted {n}") for n in range(5)]
    body = client.post(LOTS + "/rotate", json={"dry_run": False}, headers={"Idempotency-Key": "r1"}).json()
    assert body["cancelled"] == [] and body["created"] == []
    assert all(sale(service.store, s)["status"] == "draft" for s in theirs)


def test_rotate_limit_only_lowers(lots):
    client, service, *_ = lots
    body = client.post(LOTS + "/rotate", json={"dry_run": False, "limit": 1}, headers={"Idempotency-Key": "r1"}).json()
    assert len(body["created"]) == 1


def test_rotate_floors_every_created_price(lots, monkeypatch):
    client, service, *_ = lots
    original = LotsEngine.analyze

    def cheap(self, db, **kwargs):
        result = original(self, db, **kwargs)
        for lot in result["lots"]:
            lot["asking_cents"] = 60
        return result

    monkeypatch.setattr(LotsEngine, "analyze", cheap)
    body = client.post(LOTS + "/rotate", json={"dry_run": False}, headers={"Idempotency-Key": "r1"}).json()
    assert body["created"]
    for line in body["created"]:
        created = sale(service.store, line["sale_id"])
        assert created["asking_cents"] == line["asking_cents"] > 60


def test_revocation_between_plan_and_apply_stops_the_rotation(lots, monkeypatch):
    client, service, grant, *_ = lots
    original = LotsEngine.plan_rotation

    def then_revoke(self, db, **kwargs):
        result = original(self, db, **kwargs)
        service.revoke(grant["id"])
        return result

    monkeypatch.setattr(LotsEngine, "plan_rotation", then_revoke)
    before = drafts(service.store)
    response = client.post(LOTS + "/rotate", json={"dry_run": False}, headers={"Idempotency-Key": "r1"})
    assert response.status_code == 401
    assert drafts(service.store) == before and events(service.store, "lot-op") == []


def test_a_draft_taken_between_plan_and_apply_makes_the_rotation_stale(lots, monkeypatch):
    client, service, *_ = lots
    original = LotsEngine.plan_rotation

    def then_take(self, db, **kwargs):
        result = original(self, db, **kwargs)
        human_draft(service.store, [result.create[0]["copies"][0]["id"]])
        return result

    monkeypatch.setattr(LotsEngine, "plan_rotation", then_take)
    response = client.post(LOTS + "/rotate", json={"dry_run": False}, headers={"Idempotency-Key": "r1"})
    assert response.status_code == 409 and response.json()["code"] == "stale_plan"
    assert len(drafts(service.store)) == 1


def test_rotate_reports_due_online_lots_and_leaves_them_alone(lots):
    client, service, *_ = lots
    free = duplicate_ids(service.store)
    old = tool_draft(service.store, free[:3], 1000, title="Lot ancien")
    old_listing = put_online(service.store, old, days_ago=DEFAULT_ROTATION_DAYS + 1)
    young = tool_draft(service.store, free[3:6], 1000, title="Lot récent")
    put_online(service.store, young, days_ago=1)
    for dry_run in (True, False):
        body = client.post(LOTS + "/rotate", json={"dry_run": dry_run}, headers={"Idempotency-Key": f"r{dry_run}"}).json()
        assert [(d["sale_id"], d["listing_id"]) for d in body["due_online"]] == [(old, old_listing)]
        assert body["due_online"][0]["age_days"] == DEFAULT_ROTATION_DAYS + 1
        assert old not in body.get("cancelled", [])
    with service.store.connect() as db:
        assert db.execute("SELECT state FROM listings WHERE id=?", (old_listing,)).fetchone()[0] == "online"
    assert sale(service.store, old)["status"] == "draft"
    set_lot_rotation_days(service.store, 30, "owner")
    body = client.post(LOTS + "/rotate", json={}, headers={"Idempotency-Key": "r3"}).json()
    assert body["due_online"] == [] and body["rotation_days"] == 30


def test_rotate_replays_its_key(lots):
    client, service, *_ = lots
    first = client.post(LOTS + "/rotate", json={"dry_run": False}, headers={"Idempotency-Key": "r1"}).json()
    again = client.post(LOTS + "/rotate", json={"dry_run": False}, headers={"Idempotency-Key": "r1"}).json()
    assert again == {**first, "replayed": True}
    conflict = client.post(LOTS + "/rotate", json={"dry_run": False, "limit": 1}, headers={"Idempotency-Key": "r1"})
    assert conflict.status_code == 409 and conflict.json()["code"] == "idempotency_conflict"


# -- Rotation age setting ---------------------------------------------------------------


def test_the_rotation_age_is_admin_only_and_journaled(lots):
    _, service, _, _, app = lots
    store = service.store
    with TestClient(app) as admin:
        assert admin.post("/api/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
        assert admin.get("/api/settings/lot-rotation").json() == {"days": 14, "history": []}
        for bad in (2, 91, 7.5, "20", True, None):
            assert admin.put("/api/settings/lot-rotation", json={"days": bad}).status_code == 422
        assert admin.put("/api/settings/lot-rotation", json={"days": 21}).json() == {"days": 21, "previous": 14}
        history = admin.get("/api/settings/lot-rotation").json()["history"]
        assert [(h["actor"], h["previous"], h["days"]) for h in history] == [("owner", 14, 21)]
        assert admin.post("/api/users", json={"username": "vendeuse", "password": PASSWORD, "role": "editor"}).status_code == 201
    with TestClient(app) as editor:
        assert editor.post("/api/login", json={"username": "vendeuse", "password": PASSWORD}).status_code == 200
        assert editor.get("/api/settings/lot-rotation").status_code == 403
        assert editor.put("/api/settings/lot-rotation", json={"days": 3}).status_code == 403
    with TestClient(app) as anonymous:
        assert anonymous.put("/api/settings/lot-rotation", json={"days": 3}).status_code == 401
    for actor in ("vendeuse", "agent:abc", DEFAULT_ACTOR, ""):
        with pytest.raises(HumanOnly):
            set_lot_rotation_days(store, 3, actor)
    assert lot_rotation_days(store) == 21
    with store.connect() as db:
        row = db.execute("SELECT value_json, updated_by FROM settings WHERE key='lot_rotation_days'").fetchone()
        journal = db.execute("SELECT count(*) FROM events WHERE kind='lot-rotation-age' AND copy_id IS NULL").fetchone()[0]
    assert (row["value_json"], row["updated_by"], journal) == ("21", "owner", 1)
    assert user_version(store) == SCHEMA_VERSION


def test_no_agent_route_touches_a_setting():
    assert not [p for p in schema()["paths"] if "setting" in p or "rotation-age" in p or "margin" in p]
