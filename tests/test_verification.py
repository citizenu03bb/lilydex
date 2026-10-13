"""M2 variant checks: a reading proposes, a human decides, the evidence stays."""

import copy
import json

import pytest
from fastapi.testclient import TestClient
from test_condition_assessment import picture
from test_intake import values
from test_pricing import CARD

from pokeprice.inventory_backup import export_data
from pokeprice.verification import propose_variant, reading_conflicts
from pokeprice.webapp import create_app


def reading(**fields):
    return {
        "artwork": "holo",
        "background_shine": "not_visible",
        "stamp_text": "",
        "photo_quality": "adequate",
        "notes": "Motif holographique visible dans l’illustration.",
        **fields,
    }


def card(**fields):
    return {
        "catalog_id": "base1-4",
        "identification_status": "confirmed",
        "finish": "",
        "foil": False,
        "stamp": "",
        "stamp_state": "unobserved",
        **fields,
    }


ORIGINAL_HOLO = {
    "catalog_id": "base1-4",
    "variants": {"holo": True, "normal": False, "reverse": False},
}
MATTE_WITH_REVERSE = {
    "catalog_id": "base1-4",
    "variants": {"holo": False, "normal": True, "reverse": True},
}


def stakes(foil_cents, threshold=1000):
    return {
        "threshold_cents": threshold,
        "hypotheses": [
            {"foil": False, "prudent_cents": 150},
            {"foil": True, "prudent_cents": foil_cents},
        ],
    }


def test_holo_artwork_on_an_original_holo_edition_proposes_standard():
    proposal = propose_variant(card(), reading(), ORIGINAL_HOLO)
    assert proposal["status"] == "proposed"
    assert proposal["finish"] == "holo" and proposal["foil"] is False
    assert "holo d’origine" in proposal["reason"]


def test_holo_artwork_with_holon_stamp_proposes_stamped_foil():
    # Pikachu 78/110: the set-stamped holo is the parallel foil, not Standard.
    proposal = propose_variant(
        card(catalog_id="ex13-78"),
        reading(stamp_text="EX Fantômes Holon"),
        {"catalog_id": "ex13-78", "variants": {}},
    )
    assert proposal["status"] == "proposed" and proposal["foil"] is True
    assert proposal["stamp"] == "EX Fantômes Holon"
    assert "tampon" in proposal["reason"]


def test_human_stamp_observation_wins_over_the_reading():
    proposal = propose_variant(
        card(catalog_id="ex13-78", stamp_state="absent"),
        reading(stamp_text="EX Fantômes Holon"),
        {"catalog_id": "ex13-78", "variants": {}},
    )
    assert proposal["stamp"] == "" and proposal["foil"] is not True
    assert any("tampon" in c for c in proposal["conflicts"])


def test_matte_artwork_with_a_valuable_reverse_requires_physical_examination():
    proposal = propose_variant(
        card(), reading(artwork="matte"), MATTE_WITH_REVERSE, stakes(4300)
    )
    assert proposal["status"] == "examine"
    assert "43,00 €" in proposal["reason"] and "éclairage rasant" in proposal["reason"]


def test_matte_artwork_with_unknown_foil_price_is_not_called_standard():
    proposal = propose_variant(card(), reading(artwork="matte"), None, None)
    assert proposal["status"] == "examine" and "prix Foil inconnu" in proposal["reason"]


@pytest.mark.parametrize(
    ("snapshot", "valuation", "text"),
    [
        (MATTE_WITH_REVERSE, stakes(200), "prime est faible"),
        (ORIGINAL_HOLO, None, "ne connaît pas de reverse"),
    ],
)
def test_matte_artwork_without_stakes_proposes_standard(snapshot, valuation, text):
    proposal = propose_variant(card(), reading(artwork="matte"), snapshot, valuation)
    assert proposal["status"] == "proposed" and proposal["foil"] is False
    assert proposal["finish"] == "non_holo" and text in proposal["reason"]


def test_unclear_or_unusable_photo_proposes_nothing():
    for fields in ({"artwork": "unclear"}, {"photo_quality": "unusable"}):
        proposal = propose_variant(card(), reading(**fields), ORIGINAL_HOLO)
        assert proposal["status"] == "unreadable" and proposal["finish"] == ""


def test_visible_background_shine_is_a_reverse_to_examine_not_a_decision():
    proposal = propose_variant(
        card(), reading(artwork="matte", background_shine="visible"), ORIGINAL_HOLO
    )
    assert proposal["status"] == "examine" and proposal["finish"] == "reverse"


def test_conflicts_compare_the_reading_with_recorded_observations():
    assert reading_conflicts(card(finish="holo"), reading(artwork="matte"))
    assert reading_conflicts(card(finish="reverse"), reading())
    assert not reading_conflicts(card(finish="holo_border"), reading())
    assert not reading_conflicts(card(), reading(artwork="matte"))
    assert reading_conflicts(
        card(stamp_state="present", stamp="Fantômes Holon"), reading()
    )
    assert not reading_conflicts(
        card(stamp_state="present", stamp="Fantômes Holon"),
        reading(stamp_text="FANTOMES HOLON"),
    )


class Reader:
    source, model, protocol = "fake", "fake-model", "card-finish-v1"

    def __init__(self):
        self.result, self.sent = reading(), []

    def __call__(self, photo):
        self.sent.append(photo)
        return (
            self.result,
            json.dumps(self.result),
            {"input_tokens": 1290, "output_tokens": 80, "total_tokens": 1370},
        )


@pytest.fixture
def app(tmp_path):
    catalogue = copy.deepcopy(CARD)
    catalogue["variants"] = {"holo": True, "normal": False, "reverse": False}
    reader = Reader()
    with TestClient(
        create_app(
            tmp_path / "inventory",
            variant_reader=reader,
            price_fetch=lambda catalog_id, *_: {**catalogue, "id": catalog_id},
        )
    ) as client:
        client.post(
            "/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}
        )
        client.post("/api/albums", json={"name": "Test"})
        yield client, reader


def photographed(client, **fields):
    created = client.post(
        "/api/copies",
        json=values(
            client,
            catalog_id=CARD["id"],
            identification_status="confirmed",
            **fields,
        ),
    )
    assert created.status_code == 201, created.text
    return attach(client, created.json(), (40, 90, 160))


def attach(client, card, color):
    draft = client.post("/api/intake/photo", content=picture(color)).json()
    response = client.post(
        f"/api/copies/{card['id']}/photo-from-intake",
        json={"token": draft["token"], "expected_version": card["version"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def check(client, card):
    response = client.post(
        f"/api/copies/{card['id']}/variant-checks",
        json={"expected_version": card["version"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_reading_is_recorded_with_evidence_and_leaves_the_copy_unchanged(app):
    client, reader = app
    card = photographed(client)
    result = check(client, card)
    assert reader.sent and result["source"] == "fake" and not result["stale"]
    assert result["usage"]["total_tokens"] == 1370
    assert result["proposal"]["status"] == "proposed"
    assert result["proposal"]["foil"] is False  # original holo edition
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["version"] == card["version"] and detail["finish"] == ""
    assert detail["variant_checks"][0]["current_proposal"]["finish"] == "holo"
    event = next(e for e in detail["history"] if e["kind"] == "verification")
    assert json.loads(event["after_json"])["verification_id"] == result["id"]
    exported = export_data(client.app.state.store)["tables"]["verifications"]
    assert [row["id"] for row in exported] == [result["id"]]


def test_human_decision_is_applied_with_the_reading_as_evidence(app):
    client, _ = app
    card = photographed(client)
    result = check(client, card)
    response = client.post(
        f"/api/copies/{card['id']}/variant-checks/{result['id']}/confirm",
        json={
            "expected_version": card["version"],
            "finish": "holo",
            "stamp_state": "absent",
            "stamp": "",
            "variant_confirmed": True,
            "reason": "Carte examinée sous éclairage rasant",
        },
    )
    assert response.status_code == 200, response.text
    changed = response.json()
    assert changed["finish"] == "holo" and not changed["foil"]
    assert changed["variant_confirmed"] and changed["variant_verified_by"] == "pat"
    detail = client.get(f"/api/copies/{card['id']}").json()
    evidence = json.loads(
        next(e for e in detail["history"] if e["kind"] == "variant-validation")[
            "after_json"
        ]
    )
    assert evidence["verification_id"] == result["id"]
    assert evidence["reading"]["artwork"] == "holo"
    assert evidence["proposal"]["foil"] is False


def test_replaced_front_photo_makes_the_reading_stale(app):
    client, _ = app
    card = photographed(client)
    result = check(client, card)
    card = attach(client, card, (200, 30, 30))
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["variant_checks"][0]["stale"]
    assert "current_proposal" not in detail["variant_checks"][0]
    response = client.post(
        f"/api/copies/{card['id']}/variant-checks/{result['id']}/confirm",
        json={
            "expected_version": card["version"],
            "finish": "holo",
            "stamp_state": "unobserved",
            "variant_confirmed": False,
            "reason": "Proposition acceptée",
        },
    )
    assert response.status_code == 409


def test_disagreement_enters_the_review_queue_until_a_later_confirmation(app):
    client, reader = app
    card = photographed(client, finish="holo")
    reader.result = reading(artwork="matte")
    result = check(client, card)
    row = client.get("/api/copies").json()["items"][0]
    reasons = [r["code"] for r in row["valuation"]["reasons"]]
    assert "variant_reading" in reasons and row["valuation"]["needs_review"]
    card = client.get(f"/api/copies/{card['id']}").json()
    client.post(
        f"/api/copies/{card['id']}/variant-checks/{result['id']}/confirm",
        json={
            "expected_version": card["version"],
            "finish": "holo",
            "stamp_state": "absent",
            "variant_confirmed": True,
            "reason": "Holo vérifiée à la main : la photo était voilée",
        },
    ).raise_for_status()
    row = client.get("/api/copies").json()["items"][0]
    assert "variant_reading" not in [r["code"] for r in row["valuation"]["reasons"]]


def test_reader_role_cannot_request_a_reading(app):
    client, reader = app
    card = photographed(client)
    client.post(
        "/api/users",
        json={
            "username": "lecteur",
            "password": "Lecture-test-2026!",
            "role": "reader",
        },
    )
    client.post("/api/logout")
    client.post(
        "/api/login", json={"username": "lecteur", "password": "Lecture-test-2026!"}
    )
    response = client.post(
        f"/api/copies/{card['id']}/variant-checks",
        json={"expected_version": card["version"]},
    )
    assert response.status_code == 403 and not reader.sent
