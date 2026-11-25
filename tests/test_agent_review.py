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


def test_a_failed_condition_takes_the_variant_back_and_keeps_the_copy_waiting(env, monkeypatch):
    client, review, _, _ = env
    card = photographed(client)

    def failing(*args, **kwargs):
        raise Conflict("Évaluation périmée.")

    monkeypatch.setattr(review.conditions, "confirm", failing)
    report = review.run(apply=True, read=True)
    assert report["confirmed"] == [] and report["interrupted"] == []
    assert [s["copy_id"] for s in report["skipped"]] == [card["id"]]
    assert "variante remise en attente" in report["skipped"][0]["reason"]
    detail = card_of(client, card)
    assert not detail["variant_confirmed"] and not detail["condition_confirmed"]
    assert detail["finish"] == ""
    # Still waiting: a later pass with a working service decides it.
    monkeypatch.undo()
    again = review.run(apply=True, read=True)
    assert [c["copy_id"] for c in again["confirmed"]] == [card["id"]]


def test_a_failed_take_back_is_recorded_for_the_undo(env, monkeypatch):
    client, review, _, _ = env
    card = photographed(client)

    def failing(*args, **kwargs):
        raise Conflict("Évaluation périmée.")

    monkeypatch.setattr(review.conditions, "confirm", failing)

    real_patch = review.store.patch

    def stuck(copy_id, changes, *args, **kwargs):
        if not changes.get("variant_confirmed", True):
            raise Conflict("Fiche modifiée.")
        return real_patch(copy_id, changes, *args, **kwargs)

    monkeypatch.setattr(review.store, "patch", stuck)
    report = review.run(apply=True, read=True)
    assert [i["copy_id"] for i in report["interrupted"]] == [card["id"]]
    assert "agent-review-undo" in report["skipped"][0]["reason"]
    assert card_of(client, card)["variant_confirmed"]
    monkeypatch.undo()
    result = review.undo(report["run_id"], "pat")
    assert result["restored"] == [card["id"]]
    detail = card_of(client, card)
    assert not detail["variant_confirmed"] and detail["finish"] == ""


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


def test_valuable_copy_waits_for_its_back_at_the_sale_then_is_read_again(env):
    client, review, readers, stakes = env
    stakes.risk = 5000
    card = photographed(client)
    report = review.run(apply=True, read=True)
    # Decision 0049: no request takes the card out of the binder for its back.
    assert report["confirmed"] == [] and report["photo_requests"] == []
    assert [k["copy_id"] for k in report["kept"]] == [card["id"]]
    assert "mise en vente" in report["kept"][0]["reason"]
    assert client.get("/api/photo-requests").json() == []
    assert not card_of(client, card)["condition_confirmed"]
    # The back photographed for the sale settles it on the next pass.
    attach(client, card_of(client, card), (200, 200, 200), side="back")
    report = review.run(apply=True, read=True)
    assert len(report["confirmed"]) == 1
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
    # Still matte under the lamp: the card stays as recorded (decision 0049).
    report = review.run(apply=True, read=True)
    assert report["photo_requests"] == [] and report["confirmed"] == []
    assert "reste en l’état" in report["kept"][0]["reason"]
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
    client, review, readers, stakes = env
    kept = photographed(client, position=1)
    restored = photographed(client, position=2, color=(10, 160, 90))
    asked = photographed(client, position=3, color=(160, 10, 90))
    report = review.run(apply=True, read=True, copy_ids=[kept["id"], restored["id"]])
    assert len(report["confirmed"]) == 2
    readers["condition"].quality = "limited"  # Corners unreadable: a photo is asked.
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
        # Decision 0049: a copy of value is never taken out for its back.
        ({"quality": "adequate", "front_usable": True, "back_usable": False, "suggested_condition": "EX"}, True, "keep", None),
        ({"quality": "adequate", "front_usable": True, "back_usable": True, "suggested_condition": "EX"}, True, "confirm", None),
        ({"quality": "adequate", "front_usable": True, "back_usable": False, "suggested_condition": "NM"}, False, "confirm", None),
        ({"quality": "adequate", "front_usable": True, "back_usable": False, "suggested_condition": ""}, False, "keep", None),
        ({"quality": "limited", "front_usable": True, "back_usable": True, "suggested_condition": "EX"}, False, "photo", "corner"),
        ({"quality": "unusable", "front_usable": False, "back_usable": False, "suggested_condition": ""}, False, "photo", "front"),
        ({"quality": "adequate", "front_usable": True, "back_usable": True, "suggested_condition": ""}, False, "keep", None),
        (None, False, "skip", None),
    ],
)
def test_condition_rule(result, high_value, action, view):
    assessment = result and {"stale": False, "result": {**result, "explanation": "x"}}
    decision = auto_condition_decision({}, assessment, high_value=high_value)
    assert decision["action"] == action and decision.get("view") == view


# -- Imported copies (decision 0047) ------------------------------------------------


def imported(client, *, exact=True, language="en", position=1, color=(40, 90, 160)):
    """A copy the binder import created « à vérifier », with its reading."""
    store = client.app.state.store
    data = values(client, catalog_id=CARD["id"], page=3, position=position)
    data.pop("reason")
    card = store.create_copy(
        {**data, "identification_status": "review",
         "source_key": f"binder:imp:3:{position}"},
        "system:import",
        "Import du classeur",
        evidence={
            "type": "binder-import",
            "exact_catalogue_match": exact,
            "chosen_catalog_id": CARD["id"] if exact else None,
            "observation": {"name": "Gourgeist", "language": language},
        },
    )
    return attach(client, card, color)


def open_gate(client):
    from pokeprice.agent_review import set_review_apply

    set_review_apply(client.app.state.store, True, "pat", "Porte passée (essai).")


def test_agent_confirms_the_identity_of_an_easy_imported_card(env):
    client, review, _, _ = env
    open_gate(client)
    card = imported(client)
    simulated = review.run(read=False)
    assert simulated["run_id"] is None and simulated["confirmed"] == []
    report = review.run(apply=True, read=True)
    assert [c["copy_id"] for c in report["confirmed"]] == [card["id"]]
    assert report["human_decisions_saved"] == 3
    detail = card_of(client, card)
    assert detail["identification_status"] == "confirmed"
    assert detail["variant_confirmed"] and detail["condition_confirmed"]
    identity = evidence(detail, "identification")[-1]
    assert identity["type"] == "identity-validation" and identity["decided_by"] == "agent"
    assert identity["score"]["edition_margin"] >= 0.05
    labels = [e["reason"] for e in detail["history"] if e["kind"] == "identification"]
    assert "confirmée par l’agent" in labels[-1]
    # The whole run is undone, identity included.
    undone = review.undo(report["run_id"], "pat")
    assert undone["restored"] == [card["id"]]
    assert card_of(client, card)["identification_status"] == "review"


def test_simulation_says_what_it_would_confirm_on_imported_copies(env):
    client, review, _, _ = env
    card = imported(client)
    # The import's checks, as the worker runs them; then the agent in simulation.
    state = client.app.state
    state.variant_checks.evaluate_new_copy(
        card["id"], "pat", lambda copy_id: review.inputs(copy_id, 1000))
    state.edition_checks.evaluate_new_copy(card["id"], "pat")
    state.conditions.evaluate(card["id"], card_of(client, card)["version"], "pat")
    report = review.run()
    assert [c["copy_id"] for c in report["confirmed"]] == [card["id"]]
    assert card_of(client, card)["identification_status"] == "review"


def test_without_the_gate_no_caller_writes_an_imported_identity(env, monkeypatch, capsys):
    import sys

    from pokeprice import manage

    client, review, _, _ = env
    card = imported(client)
    # Readings done, setting off: the agent would confirm, and writes nothing.
    report = review.run(apply=True, read=True)
    assert report["confirmed"] == []
    assert "agent_review_apply" in report["skipped"][0]["reason"]
    assert review.run()["confirmed"][0]["copy_id"] == card["id"]
    # The command line, with --apply, goes through the same gate.
    root = str(client.app.state.store.root)
    monkeypatch.setattr(sys, "argv", ["pokeprice-manage", "--data", root, "agent-review", "--apply"])
    manage.main()
    assert '"confirmed": 0' in capsys.readouterr().out
    assert card_of(client, card)["identification_status"] == "review"
    open_gate(client)
    assert review.run(apply=True)["confirmed"][0]["copy_id"] == card["id"]
    assert card_of(client, card)["identification_status"] == "confirmed"


@pytest.mark.parametrize(
    "case, reason",
    [
        ({"exact": False}, "une seule édition exacte"),
        ({"language": "fr"}, "langue lue"),
    ],
)
def test_imported_identity_stays_with_a_person_without_concordant_evidence(env, case, reason):
    client, review, _, _ = env
    card = imported(client, **case)
    report = review.run(apply=True, read=True)
    assert report["confirmed"] == []
    assert reason in report["skipped"][0]["reason"]
    assert card_of(client, card)["identification_status"] == "review"


def test_imported_card_of_value_keeps_its_identity_for_a_person(env):
    client, review, _, stakes = env
    stakes.risk = 2500
    card = imported(client)
    report = review.run(apply=True, read=True)
    assert report["confirmed"] == []
    assert card_of(client, card)["identification_status"] == "review"


def test_an_unidentified_or_manual_copy_is_not_the_agents(env):
    client, review, _, _ = env
    store = client.app.state.store
    data = values(client, catalog_id=CARD["id"])
    data.pop("reason")
    manual = store.create_copy({**data, "identification_status": "review"}, "pat", "Saisie")
    with store.connect() as db:
        assert manual["id"] not in review.candidates(db)


# -- The glint shot (decision 0047) ---------------------------------------------------


def glint(client, card, color=(90, 40, 160)):
    current = card_of(client, card)
    response = client.put(
        f"/api/copies/{card['id']}/photo?version={current['version']}&side=front&view=glint",
        content=picture(color),
        headers={"Content-Type": "image/jpeg"},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "shine, finish, foil",
    [("not_visible", "non_holo", False), ("visible", "reverse", True)],
)
def test_a_good_glint_shot_settles_a_valuable_reverse(env, shine, finish, foil):
    client, review, readers, stakes = env
    stakes.snapshot, stakes.foil = MATTE_WITH_REVERSE, 4300
    readers["finish"].result = reading(artwork="matte")
    card = photographed(client)
    report = review.run(apply=True, read=True)
    assert report["photo_requests"][0]["views"][0]["view"] == "holo"
    glint(client, card)
    readers["finish"].result = reading(artwork="matte", background_shine=shine)
    report = review.run(apply=True, read=True)
    assert [c["copy_id"] for c in report["confirmed"]] == [card["id"]]
    detail = card_of(client, card)
    assert detail["finish"] == finish and bool(detail["foil"]) is foil and detail["variant_confirmed"]
    assert any(e["kind"] == "glint-photo" for e in detail["history"])


def test_a_poor_glint_shot_or_a_flat_photo_settles_nothing(env):
    client, review, readers, stakes = env
    stakes.snapshot, stakes.foil = MATTE_WITH_REVERSE, 4300
    card = photographed(client)
    glint(client, card)
    readers["finish"].result = reading(artwork="matte", photo_quality="limited")
    report = review.run(apply=True, read=True)
    assert report["confirmed"] == []
    assert not card_of(client, card)["variant_confirmed"]


def test_glint_is_for_the_front_only(env):
    client, _, _, _ = env
    card = photographed(client)
    response = client.put(
        f"/api/copies/{card['id']}/photo?version={card['version']}&side=back&view=glint",
        content=picture((1, 2, 3)),
        headers={"Content-Type": "image/jpeg"},
    )
    assert response.status_code == 422


def test_an_assessment_under_an_older_protocol_is_read_again(env):
    client, review, readers, _ = env
    card = photographed(client)
    review.run(apply=False, read=False)
    review.read_missing(card["id"], 1000)
    assert readers["condition"].calls == 1
    with review.store.connect(write=True) as db:
        db.execute("UPDATE condition_assessments SET protocol='card-condition-v1'")
    # Decision 0049: the front-only protocol replaces the old reading.
    assert review.evidence(card["id"], 1000)["assessment"] is None
    review.read_missing(card["id"], 1000)
    assert readers["condition"].calls == 2
    assert review.evidence(card["id"], 1000)["assessment"] is not None


# -- One facet at a time (decision 0050) --------------------------------------------


def test_identity_is_written_while_the_corners_are_asked(env):
    client, review, readers, _ = env
    open_gate(client)
    card = imported(client)
    readers["condition"].quality = "limited"  # Corners unreadable: a photo is asked.
    report = review.run(apply=True, read=True)
    assert [c["copy_id"] for c in report["confirmed"]] == [card["id"]]
    assert report["confirmed"][0]["partial"] and report["human_decisions_saved"] == 1
    assert [v["view"] for v in report["photo_requests"][0]["views"]] == ["corner"]
    detail = card_of(client, card)
    # The identity survives a new front; the variant and the condition would not.
    assert detail["identification_status"] == "confirmed"
    assert not detail["variant_confirmed"] and not detail["condition_confirmed"]
    assert [r["view"] for r in client.get("/api/photo-requests").json()] == ["corner"]
    # The run is undone as a whole: identity and request.
    review.undo(report["run_id"], "pat")
    assert card_of(client, card)["identification_status"] == "review"
    assert client.get("/api/photo-requests").json() == []


def test_variant_is_written_when_the_condition_stays_as_recorded(env):
    client, review, readers, _ = env
    card = photographed(client)
    readers["condition"].grade = None  # The front does not settle the grade.
    report = review.run(apply=True, read=True)
    assert report["confirmed"][0]["partial"] and report["photo_requests"] == []
    assert [k["copy_id"] for k in report["kept"]] == [card["id"]]
    assert "undo" not in report["kept"][0]
    detail = card_of(client, card)
    assert detail["variant_confirmed"] and detail["finish"] == "holo"
    assert detail["condition"] == "EX" and not detail["condition_confirmed"]


def test_a_lone_identity_waits_for_the_gate_and_the_photo_is_still_asked(env):
    client, review, readers, _ = env
    card = imported(client)
    readers["condition"].quality = "limited"
    assert review.run(read=False)["confirmed"] == []  # No readings yet.
    report = review.run(apply=True, read=True)
    assert report["confirmed"] == []
    assert [p["copy_id"] for p in report["photo_requests"]] == [card["id"]]
    assert card_of(client, card)["identification_status"] == "review"
    # The simulation still says what it would write.
    assert review.run()["confirmed"][0]["partial"]
