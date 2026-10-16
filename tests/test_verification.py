"""M2 variant checks: a reading proposes, a human decides, the evidence stays."""

import copy
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_condition_assessment import picture
from test_intake import values
from test_pricing import CARD

from pokeprice.inventory import Store
from pokeprice.inventory_backup import export_data
from pokeprice.verification import (
    language_conflicts,
    propose_variant,
    reading_conflicts,
)
from pokeprice.webapp import create_app


def reading(**fields):
    return {
        "artwork": "holo",
        "background_shine": "not_visible",
        "stamp_text": "",
        "text_language": "en",
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


def test_tcgdex_without_reverse_is_no_proof_when_the_background_is_unclear():
    # Clic 75/114 (Black & White): a confirmed reverse that TCGdex does not list.
    proposal = propose_variant(
        card(), reading(artwork="matte", background_shine="unclear"), ORIGINAL_HOLO
    )
    assert proposal["status"] == "examine" and "prix Foil inconnu" in proposal["reason"]


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


def test_language_conflict_needs_two_known_languages_that_differ():
    assert language_conflicts(card(language="en"), reading(text_language="fr")) == [
        "Le texte imprimé est lu en français ; la fiche indique anglais."
    ]
    assert not language_conflicts(card(language="fr"), reading(text_language="fr"))
    assert not language_conflicts(card(language="en"), reading(text_language="unknown"))
    assert not language_conflicts(card(language="unknown"), reading(text_language="fr"))
    old = reading()
    del old["text_language"]  # card-finish-v1 did not read the text language.
    assert not language_conflicts(card(language="en"), old)
    proposal = propose_variant(
        card(language="en"), reading(text_language="ja"), ORIGINAL_HOLO
    )
    assert proposal["language_conflicts"] and not proposal["conflicts"]


class Reader:
    source, model, protocol = "fake", "fake-model", "card-finish-v2"

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


def test_language_disagreement_enters_review_until_kept_or_corrected(app):
    client, reader = app
    card = photographed(client)  # Recorded in English.
    reader.result = reading(text_language="fr")
    result = check(client, card)
    assert result["proposal"]["language_conflicts"]
    row = client.get("/api/copies").json()["items"][0]
    reasons = [r["code"] for r in row["valuation"]["reasons"]]
    assert "language_reading" in reasons and "variant_reading" not in reasons
    kept = client.post(
        f"/api/copies/{card['id']}/variant-checks/{result['id']}/keep-language",
        json={"expected_version": card["version"], "reason": "Texte anglais vérifié"},
    )
    assert kept.status_code == 200, kept.text
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["variant_checks"][0]["language_kept"]
    event = next(e for e in detail["history"] if e["kind"] == "language-validation")
    assert json.loads(event["after_json"])["verification_id"] == result["id"]
    row = client.get("/api/copies").json()["items"][0]
    assert "language_reading" not in [r["code"] for r in row["valuation"]["reasons"]]
    # A newer reading that still disagrees raises it again; correcting settles it.
    result = check(client, detail)
    row = client.get("/api/copies").json()["items"][0]
    assert "language_reading" in [r["code"] for r in row["valuation"]["reasons"]]
    client.patch(
        f"/api/copies/{card['id']}",
        json={
            "expected_version": detail["version"],
            "reason": "Langue corrigée",
            "language": "fr",
        },
    ).raise_for_status()
    row = client.get("/api/copies").json()["items"][0]
    assert "language_reading" not in [r["code"] for r in row["valuation"]["reasons"]]


def test_replaced_photo_drops_the_language_disagreement(app):
    client, reader = app
    card = photographed(client)
    reader.result = reading(text_language="fr")
    result = check(client, card)
    card = attach(client, card, (200, 30, 30))
    row = client.get("/api/copies").json()["items"][0]
    assert "language_reading" not in [r["code"] for r in row["valuation"]["reasons"]]
    response = client.post(
        f"/api/copies/{card['id']}/variant-checks/{result['id']}/keep-language",
        json={"expected_version": card["version"], "reason": "Texte anglais vérifié"},
    )
    assert response.status_code == 409


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


def schema13(store):
    with sqlite3.connect(store.database) as db:
        db.execute("DROP TABLE verifications")
        db.execute("PRAGMA user_version=13")


def test_migration_keeps_a_copy_of_the_previous_schema(app):
    client, _ = app
    card = photographed(client)
    store = client.app.state.store
    schema13(store)
    Store(store.root)
    backups = list((store.root.parent / "backups").glob("before-schema16-from13-*"))
    assert len(backups) == 1 and backups[0].stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 13
        assert db.execute("SELECT version FROM copies").fetchone()[0] == card["version"]
    with store.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 16
    Store(store.root)  # Already current: no further copy.
    assert len(list((store.root.parent / "backups").glob("before-*"))) == 1


def test_failed_copy_leaves_the_database_unmigrated(app):
    client, _ = app
    store = client.app.state.store
    schema13(store)
    (store.root.parent / "backups").write_text("not a folder")
    with pytest.raises(OSError):
        Store(store.root)
    with sqlite3.connect(store.database) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 13


@pytest.fixture
def auto(tmp_path):
    reader = Reader()
    with TestClient(
        create_app(
            tmp_path / "inventory",
            variant_reader=reader,
            auto_checks=True,
            price_fetch=lambda catalog_id, *_: {**CARD, "id": catalog_id},
        )
    ) as client:
        client.post(
            "/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}
        )
        client.post("/api/albums", json={"name": "Test"})
        yield client, reader


def intake_draft(client, color=(40, 90, 160)):
    response = client.post("/api/intake/photo", content=picture(color))
    assert response.status_code == 201, response.text
    return response.json()["token"]


def history(client, card, kind):
    detail = client.get(f"/api/copies/{card['id']}").json()
    return detail, [
        json.loads(e["after_json"]) for e in detail["history"] if e["kind"] == kind
    ]


def test_new_photographed_copy_is_read_once_after_intake(auto):
    client, reader = auto
    token = intake_draft(client)
    saved = client.post(f"/api/intake/{token}/save", json=values(client))
    assert saved.status_code == 201, saved.text
    card = saved.json()
    detail, events = history(client, card, "verification")
    assert len(reader.sent) == 1 and len(detail["variant_checks"]) == 1
    assert events[0]["trigger"] == "intake"
    assert detail["version"] == card["version"] and detail["finish"] == ""
    # A retried save returns the same copy without paying for a second reading.
    client.post(f"/api/intake/{token}/save", json=values(client)).raise_for_status()
    assert len(reader.sent) == 1


def test_failed_automatic_reading_is_recorded_and_intake_succeeds(auto):
    client, reader = auto

    def broken(photo):
        reader.sent.append(photo)
        raise RuntimeError("Lecture Gemini indisponible ou réponse invalide.")

    client.app.state.variant_checks.reader = broken
    token = intake_draft(client)
    saved = client.post(f"/api/intake/{token}/save", json=values(client))
    assert saved.status_code == 201, saved.text
    detail, failures = history(client, saved.json(), "verification-failed")
    assert detail["variant_checks"] == [] and len(reader.sent) == 1
    assert failures == [
        {
            "kind": "variant",
            "trigger": "intake",
            "error": "Lecture Gemini indisponible ou réponse invalide.",
        }
    ]


def test_no_automatic_reading_without_photo_or_for_an_existing_copy(auto):
    client, reader = auto
    blank = client.post("/api/intake/drafts").json()["token"]
    client.post(
        f"/api/intake/{blank}/save", json=values(client, position=2)
    ).raise_for_status()
    created = photographed(client, position=3)  # Attaching a photo is not intake.
    existing = client.post(f"/api/copies/{created['id']}/intake")
    assert existing.status_code == 201 and existing.json()["has_photo"]
    client.post(
        f"/api/intake/{existing.json()['token']}/save",
        json=values(client, position=3),
    ).raise_for_status()
    assert reader.sent == []


def test_series_capture_reads_the_saved_copy(auto):
    client, reader = auto
    data = values(client)
    data.pop("reason")
    session = client.post(
        "/api/capture-sessions",
        json={"album_id": data["album_id"], "slots": 9, "page": 1, "position": 1},
    ).json()
    session = client.patch(
        "/api/capture-sessions/" + session["id"],
        json={"expected_version": session["version"], "front_token": intake_draft(client)},
    ).json()
    saved = client.post(
        f"/api/capture-sessions/{session['id']}/save",
        json={
            **values(client),
            "token": session["data"]["front_token"],
            "expected_version": session["version"],
        },
    )
    assert saved.status_code == 201, saved.text
    detail, events = history(client, saved.json()["card"], "verification")
    assert len(reader.sent) == 1 and events[0]["trigger"] == "intake"


def test_automatic_reading_is_off_unless_the_server_enables_it(app):
    client, reader = app
    token = intake_draft(client)
    client.post(f"/api/intake/{token}/save", json=values(client)).raise_for_status()
    assert reader.sent == []
