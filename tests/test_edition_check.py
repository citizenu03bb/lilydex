"""M2 edition check: the image ranks same-name prints, a human settles a doubt."""

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from test_condition_assessment import picture
from test_intake import CANDIDATE, OBSERVATION, values

from pokeprice import edition_check
from pokeprice.edition_check import propose_edition, same_name_gallery
from pokeprice.webapp import create_app

API = "https://api.tcgdex.net/v2"
PRINTS = {
    # Same name, three prints; the English catalogue knows one more.
    "swsh7-077": {"name": "Gourgeist", "set": {"name": "Evolving Skies"}, "localId": "077"},
    "xy4-56": {"name": "Gourgeist", "set": {"name": "Phantom Forces"}, "localId": "56"},
    "sm1-60": {"name": "Gourgeist", "set": {"name": "Sun & Moon"}, "localId": "60"},
}


def tcgdex(url):
    path = url.removeprefix(API + "/")
    language, rest = path.split("/", 1)
    if rest.startswith("cards?"):
        return [
            {"id": i, "name": p["name"], "image": f"https://assets.tcgdex.net/{language}/x/{i}"}
            for i, p in PRINTS.items()
            if language == "en" or i != "sm1-60"
        ]
    card_id = rest.removeprefix("cards/")
    if card_id not in PRINTS:
        return None
    return {"id": card_id, **PRINTS[card_id], "image": f"https://assets.tcgdex.net/{language}/x/{card_id}"}


def png():
    output = io.BytesIO()
    Image.new("RGB", (10, 14), "white").save(output, format="PNG")
    return output.getvalue()


class Reader:
    source, model, protocol = "fake", "fake-dino", "edition-same-name-v1"

    def __init__(self):
        self.scores = {"swsh7-077": 0.91, "xy4-56": 0.62, "sm1-60": 0.55}
        self.calls = []

    def __call__(self, photo, references):
        self.calls.append(sorted(references))
        return {i: self.scores[i] for i in references}, "", {"seconds": 0.1}


def result(**scores):
    return {"scores": scores, "gallery": [{"id": i, "set_name": f"Série {i}"} for i in scores]}


def test_proposal_agrees_doubts_or_disagrees_by_the_similarity_gap():
    card = {"catalog_id": "a"}
    assert propose_edition(card, result(a=0.9, b=0.7))["status"] == "agree"
    undecided = propose_edition(card, result(a=0.80, b=0.81))
    assert undecided["status"] == "undecided" and undecided["conflicts"] == []
    disagree = propose_edition(card, result(a=0.6, b=0.9))
    assert disagree["status"] == "disagree" and disagree["rank"] == 2
    assert "Série b (b)" in disagree["conflicts"][0]
    assert propose_edition(card, result(b=0.9))["status"] == "unavailable"
    assert propose_edition(card, result(a=0.4))["status"] == "agree"


def test_gallery_keeps_the_recorded_print_first_and_adds_english_prints():
    gallery = same_name_gallery({"catalog_id": "xy4-56", "language": "fr"}, tcgdex)
    assert [g["id"] for g in gallery] == ["xy4-56", "swsh7-077", "sm1-60"]
    assert all(g["image"].startswith("https://assets.tcgdex.net/") for g in gallery)


def test_reference_images_only_come_from_catalogue_hosts():
    with pytest.raises(ValueError):
        edition_check.tcgdex_image("https://example.com/card.png")


@pytest.fixture
def app(tmp_path):
    reader = Reader()
    with TestClient(
        create_app(
            tmp_path / "inventory",
            intake_reader=lambda data: (OBSERVATION.copy(), json.dumps(OBSERVATION)),
            intake_lookup=lambda query: {"candidates": [CANDIDATE.copy()], "message": ""},
            variant_reader=lambda photo: (_ for _ in ()).throw(RuntimeError("hors test")),
            edition_reader=reader,
            edition_get_json=tcgdex,
            edition_fetch=lambda url: png(),
            price_fetch=lambda catalog_id, *_: {"id": catalog_id, "variants": {}},
        )
    ) as client:
        client.post(
            "/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}
        )
        client.post("/api/albums", json={"name": "Test"})
        yield client, reader


def confirmed(client, color=(40, 90, 160)):
    token = client.post("/api/intake/photo", content=picture(color)).json()["token"]
    client.post(f"/api/intake/{token}/analyze").raise_for_status()
    saved = client.post(
        f"/api/intake/{token}/save",
        json=values(client, chosen_catalog_id=CANDIDATE["id"], human_confirmed=True),
    )
    assert saved.status_code == 201, saved.text
    return saved.json()


def check(client, card):
    response = client.post(
        f"/api/copies/{card['id']}/edition-checks",
        json={"expected_version": card["version"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def reasons(client):
    row = client.get("/api/copies").json()["items"][0]
    return [r["code"] for r in row["valuation"]["reasons"]]


def test_agreeing_check_is_recorded_without_touching_the_copy(app):
    client, reader = app
    card = confirmed(client)
    result = check(client, card)
    assert reader.calls == [["sm1-60", "swsh7-077", "xy4-56"]]
    assert result["proposal"]["status"] == "agree" and result["source"] == "fake"
    assert {g["id"]: g.get("set_name") for g in result["result"]["gallery"]}[
        "swsh7-077"
    ] == "Evolving Skies 077"
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["version"] == card["version"] and detail["edition_check_available"]
    assert detail["edition_checks"][0]["current_proposal"]["status"] == "agree"
    assert "edition_reading" not in reasons(client)


def test_disagreement_enters_review_until_the_human_keeps_the_edition(app):
    client, reader = app
    card = confirmed(client)
    reader.scores = {"swsh7-077": 0.55, "xy4-56": 0.93, "sm1-60": 0.50}
    result = check(client, card)
    assert result["proposal"]["status"] == "disagree"
    assert "edition_reading" in reasons(client)
    kept = client.post(
        f"/api/copies/{card['id']}/edition-checks/{result['id']}/keep",
        json={"expected_version": card["version"], "reason": "Carte comparée au catalogue"},
    )
    assert kept.status_code == 200, kept.text
    assert "edition_reading" not in reasons(client)
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["edition_checks"][0]["kept"]
    event = next(e for e in detail["history"] if e["kind"] == "edition-validation")
    assert json.loads(event["after_json"])["verification_id"] == result["id"]


def test_a_check_needs_a_confirmed_edition_and_the_vision_option(app):
    client, _ = app
    created = client.post("/api/intake/photo", content=picture((200, 30, 30))).json()
    card = client.post(
        f"/api/intake/{created['token']}/save", json=values(client, position=2)
    ).json()
    response = client.post(
        f"/api/copies/{card['id']}/edition-checks",
        json={"expected_version": card["version"]},
    )
    assert response.status_code == 422 and "Confirmez" in response.json()["detail"]
    client.app.state.edition_checks.reader = None
    response = client.post(
        f"/api/copies/{card['id']}/edition-checks",
        json={"expected_version": card["version"]},
    )
    assert response.status_code == 503 and "vision" in response.json()["detail"]


def test_missing_reference_image_for_the_recorded_print_is_reported(app):
    client, _ = app
    card = confirmed(client)

    def fetch(url):
        if "swsh7" in url:  # Every source, pokemontcg.io included.
            raise OSError("404")
        return png()

    client.app.state.edition_checks.fetch = fetch
    response = client.post(
        f"/api/copies/{card['id']}/edition-checks",
        json={"expected_version": card["version"]},
    )
    assert response.status_code == 502 and "introuvable" in response.json()["detail"]


def test_new_confirmed_copy_is_checked_at_intake(tmp_path):
    reader = Reader()
    with TestClient(
        create_app(
            tmp_path / "inventory",
            intake_reader=lambda data: (OBSERVATION.copy(), json.dumps(OBSERVATION)),
            intake_lookup=lambda query: {"candidates": [CANDIDATE.copy()], "message": ""},
            variant_reader=lambda photo: (_ for _ in ()).throw(RuntimeError("Gemini indisponible.")),
            edition_reader=reader,
            edition_get_json=tcgdex,
            edition_fetch=lambda url: png(),
            price_fetch=lambda catalog_id, *_: {"id": catalog_id, "variants": {}},
            auto_checks=True,
        )
    ) as client:
        client.post(
            "/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}
        )
        client.post("/api/albums", json={"name": "Test"})
        card = confirmed(client)
        detail = client.get(f"/api/copies/{card['id']}").json()
        # The finish reading failed; the edition check ran regardless.
        assert len(reader.calls) == 1 and len(detail["edition_checks"]) == 1
        kinds = [e["kind"] for e in detail["history"]]
        assert "verification-failed" in kinds and "verification" in kinds
