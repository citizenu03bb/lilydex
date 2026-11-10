"""Waivers under the anti-undercut floor: asked by agents, decided by a person (0030)."""

import json
import sys

import pytest
from fastapi.testclient import TestClient
from test_pokeprice_lots import add_copy, draft_with_unit_listings, lot_listings
from test_pokeprice_lots import test_db  # noqa: F401 - fixture

from pokeprice.agent import AgentService
from pokeprice.floor_requests import FloorRequests, HumanOnly, open_floor_requests
from pokeprice.listings import NO_REFERENCE_FOR_AGENT, FloorRefusal, Listings
from pokeprice.webapp import create_app

from pokeprice_lots import LotsEngine

PASSWORD = "Collection-test-2026!"


@pytest.fixture
def human(test_db):  # noqa: F811
    _, store = test_db
    with TestClient(create_app(store.root)) as client:
        assert client.post("/api/setup", json={"username": "pat", "password": PASSWORD}).status_code == 200
        yield client


@pytest.fixture(autouse=True)
def loosened_environment(monkeypatch):
    # Every floor below is the stored 15 %: the variable no longer loosens anything.
    monkeypatch.setenv("POKEPRICE_LOT_MAX_MARGIN", "50")


def undercut_lot(store, first_position, price_cents=200):
    """Three cards at 1,00 € each (floor 2,55 €) offered together at ``price_cents``."""
    cards = [add_copy(store, "b", first_position + i, price=100)["id"] for i in range(3)]
    sale_id, units = draft_with_unit_listings(store, cards, title=f"Lot {first_position}")
    with store.connect(write=True) as db:
        db.execute(
            "UPDATE sales SET amount_cents=?, asking_cents=? WHERE id=?", (price_cents, price_cents, sale_id)
        )
    return sale_id, cards, units


def floor_events(store):
    with store.connect() as db:
        return [
            (r["kind"], r["actor"], json.loads(r["after_json"]))
            for r in db.execute(
                "SELECT kind,actor,after_json FROM events WHERE kind LIKE 'floor-request%' ORDER BY id"
            )
        ]


def test_an_undercut_lot_from_the_lots_tool_becomes_a_request_a_person_accepts(test_db, human):  # noqa: F811
    db_path, store = test_db
    sale_id, cards, units = undercut_lot(store, 10)
    with pytest.raises(FloorRefusal, match="plancher anti-bradage") as refused:
        LotsEngine(db_path).publish_to_storefront(sale_id)
    request_id = refused.value.request_id
    assert request_id and not lot_listings(store)

    # Retrying asks nothing new: one open request per selection and price.
    with pytest.raises(FloorRefusal):
        LotsEngine(db_path).publish_to_storefront(sale_id)
    assert [e[0] for e in floor_events(store)] == ["floor-request"]

    listed = human.get("/api/floor-requests").json()
    assert listed == open_floor_requests(store)
    (request,) = listed
    assert request["id"] == request_id and request["origin"] == "publish"
    assert request["requested_by"] == "pokeprice-lots" and request["sale_id"] == sale_id
    assert request["lot"] and request["price_cents"] == 200 and request["floor_cents"] == 255
    assert request["current_floor_cents"] == 255 and request["total_reference_cents"] == 300
    assert sorted(i["copy_id"] for i in request["items"]) == sorted(cards)
    assert {i["reference_cents"] for i in request["items"]} == {100}
    assert request["reason"] and "2,55 €" in request["refusal"]

    accepted = human.post(f"/api/floor-requests/{request_id}/accept", json={})
    assert accepted.status_code == 200, accepted.text
    accepted = accepted.json()
    listing = accepted["listing"]
    assert accepted["decision"] == "accepted"
    assert listing["price_cents"] == 200 and listing["price_source"] == "Dérogation accordée par pat"
    assert sorted(i["id"] for i in listing["items"]) == sorted(cards)
    with store.connect() as db:
        online_units = db.execute(
            f"SELECT COUNT(*) FROM listings WHERE state='online' AND id IN ({','.join('?' * len(units))})", units
        ).fetchone()[0]
        reasons = [r[0] for r in db.execute("SELECT reason FROM events WHERE kind='listing' AND copy_id=?", (cards[0],))]
        sale = db.execute("SELECT channel FROM sales WHERE id=?", (sale_id,)).fetchone()
    assert online_units == 0 and sale["channel"] == "Vitrine"
    assert any("dérogation accordée par pat" in r for r in reasons)
    assert human.get("/api/floor-requests").json() == []
    assert floor_events(store)[-1][:2] == ("floor-request-decision", "pat")


def test_dry_run_and_human_publications_record_no_request(test_db, human):  # noqa: F811
    db_path, store = test_db
    sale_id, cards, _ = undercut_lot(store, 20)
    with pytest.raises(FloorRefusal) as dry:
        LotsEngine(db_path).publish_to_storefront(sale_id, dry_run=True)
    assert dry.value.request_id is None
    with pytest.raises(FloorRefusal) as manual:
        LotsEngine(db_path).publish_to_storefront(sale_id, actor="pat")
    assert manual.value.request_id is None
    refused = human.post("/api/listings", json={"copy_ids": cards, "lot": True, "price_eur": "2.00"})
    assert refused.status_code == 422 and "2,55 €" in refused.json()["detail"]
    assert floor_events(store) == []


def test_publish_all_reports_the_request_of_a_refused_lot(test_db):  # noqa: F811
    db_path, store = test_db
    sale_id, _, _ = undercut_lot(store, 25)
    report = LotsEngine(db_path).publish_all()
    (refused,) = [r for r in report["refused"] if r["sale_id"] == sale_id]
    assert refused["floor_request_id"] == floor_events(store)[0][2]["id"]


def test_an_agent_key_never_decides_a_waiver(test_db, human):  # noqa: F811
    db_path, store = test_db
    sale_id, _, _ = undercut_lot(store, 30)
    with pytest.raises(FloorRefusal) as refused:
        LotsEngine(db_path).publish_to_storefront(sale_id)
    request_id = refused.value.request_id
    with store.connect(write=True) as db:
        db.execute("INSERT INTO albums VALUES('c','Album C')")
    grant = AgentService(store).issue(
        "Assistant", "pat", "b", client="Synthetic HTTP client",
        permissions=["copies:read", "drafts:create", "photos:read"],
    )
    with TestClient(human.app) as agent:
        agent.headers["Authorization"] = "Bearer " + grant["token"]
        assert agent.get("/api/floor-requests").status_code == 401
        for action in ("accept", "raise", "refuse"):
            assert agent.post(f"/api/floor-requests/{request_id}/{action}", json={}).status_code == 401
    # The service refuses an agent account too, whatever route calls it.
    service = FloorRequests(store)
    for decide in (service.accept, service.raise_to_floor, service.refuse):
        with pytest.raises(HumanOnly):
            decide(request_id, "agent:" + grant["id"])
        with pytest.raises(HumanOnly):
            decide(request_id, "pokeprice-lots")
    assert [r["id"] for r in human.get("/api/floor-requests").json()] == [request_id]
    assert not lot_listings(store)


def test_an_agent_key_never_loosens_the_floor(test_db, human):  # noqa: F811
    from pokeprice.pricing import lot_max_margin, set_lot_max_margin

    db_path, store = test_db
    with store.connect(write=True) as db:
        db.execute("INSERT INTO albums VALUES('c','Album C')")
    grant = AgentService(store).issue(
        "Assistant", "pat", "b", client="Synthetic HTTP client",
        permissions=["copies:read", "drafts:create", "photos:read"],
    )
    with TestClient(human.app) as agent:
        agent.headers["Authorization"] = "Bearer " + grant["token"]
        assert agent.get("/api/settings/floor-margin").status_code == 401
        assert agent.put("/api/settings/floor-margin", json={"margin": 50}).status_code == 401
    for actor in ("agent:" + grant["id"], "pokeprice-lots"):
        with pytest.raises(HumanOnly):
            set_lot_max_margin(store, 50, actor)
    assert lot_max_margin(store) == 15
    # The lot the agent's tool tries to sell at half its reference is still refused.
    sale_id, _, _ = undercut_lot(store, 60, price_cents=150)
    with pytest.raises(FloorRefusal, match="moins 15 %"):
        LotsEngine(db_path).publish_to_storefront(sale_id)
    # A person tightens the floor; the tool follows at once.
    assert human.put("/api/settings/floor-margin", json={"margin": 0}).status_code == 200
    tight, _, _ = undercut_lot(store, 70, price_cents=299)
    with pytest.raises(FloorRefusal, match="moins 0 %"):
        LotsEngine(db_path).publish_to_storefront(tight)


def test_a_person_refuses_or_raises_to_the_floor(test_db, human):  # noqa: F811
    db_path, store = test_db
    first, _, _ = undercut_lot(store, 40)
    second, cards, _ = undercut_lot(store, 50)
    ids = {}
    for sale_id in (first, second):
        with pytest.raises(FloorRefusal) as refused:
            LotsEngine(db_path).publish_to_storefront(sale_id)
        ids[sale_id] = refused.value.request_id
    closed = human.post(f"/api/floor-requests/{ids[first]}/refuse", json={"reason": "Trop bas"}).json()
    assert closed["decision"] == "refused" and closed["listing"] is None
    assert human.post(f"/api/floor-requests/{ids[first]}/accept", json={}).status_code == 404
    raised = human.post(f"/api/floor-requests/{ids[second]}/raise", json={}).json()
    assert raised["listing"]["price_cents"] == 255
    assert sorted(i["id"] for i in raised["listing"]["items"]) == sorted(cards)
    assert human.get("/api/floor-requests").json() == []
    decisions = [e[2]["decision"] for e in floor_events(store) if e[0] == "floor-request-decision"]
    assert decisions == ["refused", "raised"]


def test_an_agent_never_publishes_alone_a_card_without_reference(test_db):  # noqa: F811
    _, store = test_db
    listings = Listings(store)
    unrated = add_copy(store, "b", 60, price=None, condition_confirmed=True)["id"]
    other = add_copy(store, "b", 61, price=None, condition_confirmed=True)["id"]
    for actor in ("agent:abc", "pokeprice-lots"):
        with pytest.raises(ValueError, match="relevez d’abord son prix") as alone:
            listings.publish([unrated], actor, price_cents=500)
        assert NO_REFERENCE_FOR_AGENT in str(alone.value) and not isinstance(alone.value, FloorRefusal)
        with pytest.raises(ValueError, match="lot avec des cartes cotées"):
            listings.publish([unrated, other], actor, price_cents=500, lot=True)
    assert floor_events(store) == []
    # A person keeps the 0,50 € floor of decision 0026.
    assert listings.publish([unrated], "pat", price_cents=50)["price_cents"] == 50


def test_an_agent_unit_price_under_the_floor_is_asked_not_applied(test_db, human):  # noqa: F811
    _, store = test_db
    card = add_copy(store, "b", 70, price=200)["id"]  # floor 1,70 €
    listings = Listings(store)
    with pytest.raises(FloorRefusal, match="1,70 €") as refused:
        listings.publish([card], "agent:abc", price_cents=150, reason="Carte abîmée au dos")
    with pytest.raises(FloorRefusal) as by_person:
        listings.publish([card], "pat", price_cents=150)
    assert by_person.value.request_id is None
    (request,) = open_floor_requests(store)
    assert request["id"] == refused.value.request_id and not request["lot"]
    assert request["reason"] == "Carte abîmée au dos" and request["requested_by"] == "agent:abc"
    listing = human.post(f"/api/floor-requests/{request['id']}/accept", json={}).json()["listing"]
    assert listing["price_cents"] == 150 and listing["price_source"] == "Dérogation accordée par pat"
    # Below 0,50 € no waiver exists: the absolute floor stays.
    with pytest.raises(ValueError, match="0,50 €"):
        listings.publish([card], "pat", price_cents=40, waiver_by="pat")


def test_floor_audit_lists_online_prices_a_rising_quote_left_under_the_floor(test_db, human, monkeypatch, capsys):  # noqa: F811
    _, store = test_db
    cheap = add_copy(store, "b", 80, price=100)["id"]
    kept = add_copy(store, "b", 81, price=100)["id"]
    fine = add_copy(store, "b", 82, price=100)["id"]
    listings = Listings(store)
    for copy_id in (cheap, kept, fine):
        listings.publish([copy_id], "pat", price_cents=100)
    with store.connect(write=True) as db:
        db.execute("UPDATE copies SET reference_cents=200 WHERE id IN (?,?)", (cheap, kept))

    from pokeprice import manage

    def audit(*extra):
        monkeypatch.setattr(sys, "argv", ["pokeprice-manage", "--data", str(store.root), "floor-audit", *extra])
        manage.main()
        return json.loads(capsys.readouterr().out)

    report = audit()
    assert report["count"] == 2 and not report["recorded"]
    assert {e["copy_ids"][0] for e in report["below_floor"]} == {cheap, kept}
    entry = report["below_floor"][0]
    assert entry["price_cents"] == 100 and entry["floor_cents"] == entry["raise_to_cents"] == 170
    assert entry["request_id"] is None and floor_events(store) == []  # read only

    recorded = audit("--record")
    assert all(e["request_id"] for e in recorded["below_floor"])
    assert audit("--record")["below_floor"][0]["request_id"] == recorded["below_floor"][0]["request_id"]
    requests = {r["items"][0]["copy_id"]: r for r in human.get("/api/floor-requests").json()}
    assert set(requests) == {cheap, kept} and requests[cheap]["origin"] == "audit"
    with store.connect() as db:
        unchanged = {r[0] for r in db.execute("SELECT price_cents FROM listings WHERE state='online'")}
    assert unchanged == {100}  # nothing republished

    raised = human.post(f"/api/floor-requests/{requests[cheap]['id']}/raise", json={}).json()["listing"]
    assert raised["price_cents"] == 170 and raised["state"] == "online"
    waived = human.post(f"/api/floor-requests/{requests[kept]['id']}/accept", json={}).json()["listing"]
    assert waived["price_cents"] == 100 and waived["price_source"] == "Dérogation accordée par pat"
    assert human.get("/api/floor-requests").json() == []
    assert audit()["count"] == 0  # a kept price is not asked again


def test_an_open_waiver_waits_in_the_queue_until_decided(test_db, human):  # noqa: F811
    db_path, store = test_db
    sale_id, cards, units = undercut_lot(store, 40)
    with pytest.raises(FloorRefusal) as refused:
        LotsEngine(db_path).publish_to_storefront(sale_id)
    request_id = refused.value.request_id
    waiting = human.get("/api/todo").json()["waiting"]
    floor = [i for i in waiting if i["kind"] == "floor"]
    assert [i["action"]["target"] for i in floor] == [f"floor-request-{request_id}"]
    assert human.post(f"/api/floor-requests/{request_id}/refuse", json={"reason": "Non."}).status_code == 200
    assert not [i for i in human.get("/api/todo").json()["waiting"] if i["kind"] == "floor"]
