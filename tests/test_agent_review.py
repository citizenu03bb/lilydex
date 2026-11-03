"""The review agent confirms on concordant evidence, or asks for one more photo."""

import copy
import json

import pytest
from fastapi.testclient import TestClient
from test_condition_assessment import picture
from test_edition_check import Reader as EditionReader
from test_edition_check import png, tcgdex
from test_intake import values
from test_pricing import CARD
from test_verification import Reader as FinishReader
from test_verification import reading

from pokeprice.agent_review import ACTOR, AgentReview
from pokeprice.condition_assessment import auto_condition_decision
from pokeprice.inventory import Conflict
from pokeprice.pricing import display_price
from pokeprice.webapp import create_app

ORIGINAL_HOLO = {
    "catalog_id": "swsh7-077",
    "variants": {"holo": True, "normal": False, "reverse": False},
}
MATTE_WITH_REVERSE = {
    "catalog_id": "swsh7-077",
    "variants": {"holo": False, "normal": True, "reverse": True},
}


class ConditionReader:
    def __init__(self):
        self.grade, self.quality, self.calls = "EX", "adequate", 0

    def __call__(self, photos):
        self.calls += 1
        result = {
            "suggested_condition": self.grade,
            "front_usable": "front" in photos,
            "back_usable": "back" in photos,
            "quality": self.quality,
            "flaws_front": "Légère usure d’un coin.",
            "flaws_back": "",
            "explanation": "Usure légère, surface propre.",
            "limits": [],
        }
        return result, json.dumps(result)


class Stakes:
    """The value at stake, set by each test; the catalogue snapshot too."""

    def __init__(self):
        self.risk, self.snapshot, self.foil = 300, ORIGINAL_HOLO, None

    def __call__(self, copy_id, threshold):
        hypotheses = [{"foil": False, "prudent_cents": self.risk}]
        if self.foil is not None:
            hypotheses.append({"foil": True, "prudent_cents": self.foil})
        return self.snapshot, {
            "risk_cents": self.risk,
            "threshold_cents": threshold,
            "hypotheses": hypotheses,
        }


def make_app(tmp_path, auto_checks=False):
    catalogue = copy.deepcopy(CARD)
    catalogue["variants"] = ORIGINAL_HOLO["variants"]
    readers = {
        "finish": FinishReader(),
        "condition": ConditionReader(),
        "edition": EditionReader(),
    }
    app = create_app(
        tmp_path / "inventory",
        variant_reader=readers["finish"],
        condition_reader=readers["condition"],
        edition_reader=readers["edition"],
        edition_get_json=tcgdex,
        edition_fetch=lambda url: png(),
        auto_checks=auto_checks,
        price_fetch=lambda catalog_id, *_: {**catalogue, "id": catalog_id},
    )
    return app, readers


@pytest.fixture
def env(tmp_path):
    app, readers = make_app(tmp_path)
    with TestClient(app) as client:
        client.post(
            "/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}
        )
        client.post("/api/albums", json={"name": "Test"})
        stakes = Stakes()
        state = app.state
        review = AgentReview(
            state.store,
            state.variant_checks,
            state.conditions,
            state.edition_checks,
            stakes,
        )
        # The server's own agent shares the test's stakes.
        state.agent_review.inputs = stakes
        yield client, review, readers, stakes


def attach(client, card, color=(40, 90, 160), side="front"):
    draft = client.post("/api/intake/photo", content=picture(color)).json()
    response = client.post(
        f"/api/copies/{card['id']}/photo-from-intake",
        json={"token": draft["token"], "expected_version": card["version"], "side": side},
    )
    assert response.status_code == 200, response.text
    return response.json()


def photographed(client, page=1, position=1, color=(40, 90, 160)):
    created = client.post(
        "/api/copies",
        json=values(
            client,
            catalog_id=CARD["id"],
            identification_status="confirmed",
            page=page,
            position=position,
            condition="EX",
        ),
    )
    assert created.status_code == 201, created.text
    return attach(client, created.json(), color)


def card_of(client, card):
    return client.get(f"/api/copies/{card['id']}").json()


def evidence(detail, kind):
    return [json.loads(e["after_json"]) for e in detail["history"] if e["kind"] == kind]


def test_agent_confirms_both_halves_through_the_human_path(env):
    client, review, _, _ = env
    card = photographed(client)
    report = review.run(apply=True, read=True)
    assert [c["copy_id"] for c in report["confirmed"]] == [card["id"]]
    assert report["human_decisions_saved"] == 2
    assert report["photo_requests"] == [] and report["skipped"] == []
    detail = card_of(client, card)
    assert detail["variant_confirmed"] and detail["finish"] == "holo"
    assert detail["variant_verified_by"] == ACTOR
    assert detail["condition"] == "EX" and detail["condition_confirmed"]
    variant = evidence(detail, "variant-validation")[0]
    assert variant["decided_by"] == "agent" and variant["run_id"] == report["run_id"]
    assert variant["score"]["edition_margin"] >= 0.05
    condition = evidence(detail, "condition-validation")[0]
    assert condition["decided_by"] == "agent" and condition["human_condition"] == "EX"
    labels = [e["reason"] for e in detail["history"] if e["kind"] == "variant-validation"]
    assert "confirmée par l’agent" in labels[0]
    provenance = json.loads(detail["observation_provenance"])
    assert provenance["finish"]["origin"] == "agent"


def test_price_gate_opens_without_touching_pricing(env):
    client, review, _, _ = env
    card = photographed(client)
    valuation = {"trend_cents": 300}
    before = display_price(card_of(client, card), valuation)
    assert before["price_cents"] is None
    review.run(apply=True, read=True)
    after = display_price(card_of(client, card), valuation)
    assert after["price_cents"] == 300 and after["mode"] == "trend"


def test_simulation_reads_and_writes_nothing(env):
    client, review, readers, _ = env
    card = photographed(client)
    report = review.run(read=True)
    assert report["run_id"] is None
    assert report["skipped"][0]["reason"].startswith("Pas de lecture")
    assert readers["finish"].sent == [] and readers["condition"].calls == 0
    detail = card_of(client, card)
    assert detail["version"] == card["version"] and not detail["variant_confirmed"]
    assert review.runs() == []


def test_valuable_copy_needs_a_back_then_the_new_photo_is_read_again(env):
    client, review, readers, stakes = env
    stakes.risk = 5000
    card = photographed(client)
    report = review.run(apply=True, read=True)
    assert report["confirmed"] == []
    assert report["photo_requests"][0]["views"][0]["view"] == "back"
    listed = client.get("/api/photo-requests").json()
    assert [(r["copy_id"], r["view"], r["side"]) for r in listed] == [
        (card["id"], "back", "back")
    ]
    assert "verso" in listed[0]["reason"]
    # The same request is not asked twice while it is open.
    again = review.run(apply=True, read=True)
    assert again["photo_requests"] == [] and len(client.get("/api/photo-requests").json()) == 1
    attach(client, card_of(client, card), (200, 200, 200), side="back")
    assert client.get("/api/photo-requests").json() == []
    report = review.after_photo(card["id"])
    assert report["trigger"] == "photo" and len(report["confirmed"]) == 1
    detail = card_of(client, card)
    assert detail["variant_confirmed"] and detail["condition_confirmed"]
    assert evidence(detail, "variant-validation")[0]["high_value"] is True


def test_requests_follow_the_binder_order_and_name_the_view(env):
    client, review, readers, _ = env
    second = photographed(client, page=2, position=1)
    first = photographed(client, page=1, position=3)
    readers["finish"].result = reading(photo_quality="limited")
    readers["condition"].quality = "limited"
    review.run(apply=True, read=True)
    listed = client.get("/api/photo-requests").json()
    # One photo of the front answers both doubts: the close-up is asked.
    assert [(r["copy_id"], r["view"]) for r in listed] == [
        (first["id"], "corner"),
        (second["id"], "corner"),
    ]
    assert all(r["reason"].endswith(".") for r in listed)
    assert not card_of(client, first)["variant_confirmed"]


def test_a_possible_reverse_asks_for_a_holo_glint_once(env):
    client, review, readers, stakes = env
    stakes.snapshot, stakes.foil = MATTE_WITH_REVERSE, 4300
    readers["finish"].result = reading(artwork="matte")
    card = photographed(client)
    report = review.run(apply=True, read=True)
    assert report["photo_requests"][0]["views"][0]["view"] == "holo"
    attach(client, card_of(client, card), (90, 40, 160))
    # Still matte under the lamp: decision 0008 keeps the reverse to a human.
    report = review.run(apply=True, read=True)
    assert report["photo_requests"] == [] and report["confirmed"] == []
    assert "examen en main" in report["skipped"][0]["reason"]
    assert not card_of(client, card)["variant_confirmed"]


def test_disagreement_is_left_aside_and_a_close_edition_asks_a_front(env):
    client, review, readers, _ = env
    card = photographed(client)
    readers["edition"].scores = {"swsh7-077": 0.80, "xy4-56": 0.78, "sm1-60": 0.5}
    report = review.run(apply=True, read=True)
    assert report["photo_requests"][0]["views"][0]["view"] == "front"
    other = photographed(client, position=2, color=(10, 160, 90))
    readers["edition"].scores = {"swsh7-077": 0.5, "xy4-56": 0.9, "sm1-60": 0.4}
    report = review.run(apply=True, read=True, copy_ids=[other["id"]])
    assert report["skipped"][0]["copy_id"] == other["id"]
    assert "À examiner" in report["skipped"][0]["reason"]
    assert not card_of(client, card)["variant_confirmed"]


def test_a_whole_run_is_undone_except_copies_changed_since(env):
    client, review, _, stakes = env
    kept = photographed(client, position=1)
    restored = photographed(client, position=2, color=(10, 160, 90))
    asked = photographed(client, position=3, color=(160, 10, 90))
    report = review.run(apply=True, read=True, copy_ids=[kept["id"], restored["id"]])
    assert len(report["confirmed"]) == 2
    stakes.risk = 5000
    review.run(apply=True, read=True, copy_ids=[asked["id"]])
    runs = review.runs()
    assert [r["confirmed"] for r in runs] == [0, 2]
    # A person changes one copy after the run: the undo leaves it alone.
    changed = card_of(client, kept)
    response = client.patch(
        f"/api/copies/{kept['id']}",
        json={"expected_version": changed["version"], "notes": "Vue", "reason": "Note"},
    )
    assert response.status_code == 200, response.text
    result = review.undo(report["run_id"], "pat")
    assert result["restored"] == [restored["id"]]
    assert [k["copy_id"] for k in result["kept"]] == [kept["id"]]
    back = card_of(client, restored)
    assert not back["variant_confirmed"] and not back["condition_confirmed"]
    assert back["finish"] == "" and card_of(client, kept)["variant_confirmed"]
    with pytest.raises(Conflict):
        review.undo(report["run_id"], "pat")
    # Undoing the run that asked a photo withdraws its request.
    assert len(client.get("/api/photo-requests").json()) == 1
    review.undo(runs[0]["run_id"], "pat")
    assert client.get("/api/photo-requests").json() == []
    assert [r["undone"] for r in review.runs()] == [True, True]


def test_a_new_photo_answering_a_request_starts_the_analysis_on_the_server(tmp_path):
    app, readers = make_app(tmp_path, auto_checks=True)
    with TestClient(app) as client:
        client.post(
            "/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}
        )
        client.post("/api/albums", json={"name": "Test"})
        stakes = Stakes()
        app.state.agent_review.inputs = stakes
        readers["finish"].result = reading(photo_quality="limited")
        card = photographed(client)
        app.state.agent_review.run(apply=True, read=True)
        listed = client.get("/api/photo-requests").json()
        assert [r["view"] for r in listed] == ["front"]
        readers["finish"].result = reading()
        current = card_of(client, card)
        response = client.put(
            f"/api/copies/{card['id']}/photo?version={current['version']}&side=front",
            content=picture((70, 70, 200)),
        )
        assert response.status_code == 200, response.text
        detail = card_of(client, card)
        assert detail["variant_confirmed"] and detail["condition_confirmed"]
        assert client.get("/api/photo-requests").json() == []
        assert [r["trigger"] for r in app.state.agent_review.runs()] == ["photo", "batch"]


def test_photo_requests_are_for_staff_only(env):
    client, *_ = env
    client.post("/api/logout")
    assert client.get("/api/photo-requests").status_code == 401


@pytest.mark.parametrize(
    ("result", "high_value", "action", "view"),
    [
        ({"quality": "adequate", "front_usable": True, "back_usable": False, "suggested_condition": "EX"}, False, "confirm", None),
        ({"quality": "adequate", "front_usable": True, "back_usable": False, "suggested_condition": "EX"}, True, "photo", "back"),
        ({"quality": "limited", "front_usable": True, "back_usable": True, "suggested_condition": "EX"}, False, "photo", "corner"),
        ({"quality": "unusable", "front_usable": False, "back_usable": False, "suggested_condition": ""}, False, "photo", "front"),
        ({"quality": "adequate", "front_usable": True, "back_usable": True, "suggested_condition": ""}, False, "skip", None),
    ],
)
def test_condition_rule(result, high_value, action, view):
    assessment = {"stale": False, "result": {**result, "explanation": "x"}}
    decision = auto_condition_decision({}, assessment, high_value=high_value)
    assert decision["action"] == action and decision.get("view") == view
