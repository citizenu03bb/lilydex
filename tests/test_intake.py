import io
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pokeprice.intake import (
    IntakeService,
    Observation,
    catalogue_candidates,
    normalize_photo,
)
from pokeprice.inventory import Store
from pokeprice.inventory_backup import backup, restore_backup
from pokeprice.webapp import create_app

CANDIDATE = {
    "id": "swsh7-077",
    "name": "Gourgeist",
    "set_name": "Evolving Skies",
    "number": "077/203",
    "hp": 120,
    "language": "en",
    "image": "",
    "source": "https://api.tcgdex.net/v2/en/cards/swsh7-077",
}
OBSERVATION = {
    "name": "Gourgeist",
    "number": "077/203",
    "language": "en",
    "hp": 120,
    "readable_front": True,
    "flaws": "Pliure visible",
    "notes": "",
}


def photo():
    output = io.BytesIO()
    Image.new("RGB", (50, 80), "purple").save(output, format="JPEG")
    return output.getvalue()


def lookup(query):
    return {"candidates": [CANDIDATE.copy()], "message": "Comparez la carte."}


@pytest.fixture
def client(tmp_path):
    store = Store(tmp_path / "inventory")
    with TestClient(
        create_app(
            store.root,
            intake_reader=lambda data: (OBSERVATION.copy(), json.dumps(OBSERVATION)),
            intake_lookup=lookup,
        )
    ) as client:
        client.post(
            "/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}
        )
        client.post("/api/albums", json={"name": "Test"})
        yield client


def values(client, **overrides):
    album = client.get("/api/summary").json()["albums"][0]["id"]
    return {
        "name": "Gourgeist",
        "number": "077/203",
        "set_name": "Evolving Skies",
        "language": "en",
        "hp": 120,
        "album_id": album,
        "page": 1,
        "position": 1,
        "reason": "Confirmation photo",
        **overrides,
    }


def draft(client):
    response = client.post("/api/intake/photo", content=photo())
    assert response.status_code == 201
    return response.json()["token"]


def test_photo_intake_is_not_stock_and_confirmation_keeps_evidence(client):
    token = draft(client)
    assert client.get("/api/summary").json()["copies"] == 0
    assert client.get(f"/api/intake/{token}/photo").status_code == 200
    result = client.post(f"/api/intake/{token}/analyze").json()
    assert result["observation"]["number"] == "077/203"
    response = client.post(
        f"/api/intake/{token}/save",
        json=values(client, chosen_catalog_id=CANDIDATE["id"], human_confirmed=True),
    )
    assert response.status_code == 201
    card = response.json()
    assert (
        card["identification_status"] == "confirmed"
        and card["catalog_id"] == CANDIDATE["id"]
    )
    assert (
        card["reference_cents"] is None
        and card["condition"] == ""
        and not card["condition_confirmed"]
    )
    assert card["stock_state"] == "available"
    assert client.get(f"/api/copies/{card['id']}/photo").status_code == 200
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["source"]["data"]["raw_response"] == json.dumps(OBSERVATION)
    assert detail["source"]["data"]["human_confirmed"] is True
    repeated = client.post(f"/api/intake/{token}/save", json=values(client))
    assert repeated.json()["id"] == card["id"]
    assert client.get("/api/summary").json()["copies"] == 1


def test_manual_intake_without_photo_or_catalogue_remains_review(client):
    token = client.post("/api/intake/drafts").json()["token"]
    response = client.post(
        f"/api/intake/{token}/save", json=values(client, set_name="", hp=None)
    )
    assert response.status_code == 201
    assert (
        response.json()["photo"] is None
        and response.json()["identification_status"] == "review"
    )
    assert response.json()["catalog_id"] is None


def test_photo_settings_invalidate_ocr_and_confirmation_without_destroying_original(
    client,
):
    token = draft(client)
    service = client.app.state.intake
    original = service.drafts[token]["original_photo"]
    client.post(f"/api/intake/{token}/analyze")
    assert service.drafts[token]["observation"]
    response = client.post(
        f"/api/intake/{token}/photo-options",
        json={"crop": False, "balance": False, "perspective": False},
    )
    assert response.status_code == 200
    assert client.get(f"/api/intake/{token}/photo").content == original
    assert service.drafts[token]["observation"] is None
    assert not service.drafts[token]["searches"]
    assert (
        client.post(
            f"/api/intake/{token}/save",
            json=values(
                client, human_confirmed=True, chosen_catalog_id=CANDIDATE["id"]
            ),
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/intake/{token}/photo-options", json={"crop": "false"}
        ).status_code
        == 422
    )


def test_prepared_replacement_is_explicit_versioned_and_original_is_restorable(
    client, tmp_path
):
    from PIL import ImageDraw

    scene = Image.new("RGB", (420, 540), (30, 32, 30))
    ImageDraw.Draw(scene).rectangle((100, 70, 310, 365), fill=(235, 224, 197))
    output = io.BytesIO()
    scene.save(output, "JPEG", quality=95)
    card = client.post(
        "/api/copies", json=values(client, notes="À conserver", condition="PL")
    ).json()
    uploaded = client.post("/api/intake/photo", content=output.getvalue()).json()
    token = uploaded["token"]
    assert uploaded["photo_processing"]["perspective_quad"]
    assert client.get(f"/api/copies/{card['id']}").json()["photo"] is None
    body = {"token": token, "expected_version": 1}
    response = client.post(f"/api/copies/{card['id']}/photo-from-intake", json=body)
    assert response.status_code == 200
    changed = response.json()
    assert changed["notes"] == "À conserver" and changed["condition"] == "PL"
    assert changed["version"] == 2 and changed["stock_state"] == "available"
    assert (
        client.post(f"/api/copies/{card['id']}/photo-from-intake", json=body).json()[
            "version"
        ]
        == 2
    )
    assert client.post(f"/api/intake/{token}/photo-options", json={}).status_code == 422
    assert (
        client.post(f"/api/intake/{token}/save", json=values(client)).status_code == 422
    )
    detail = client.get(f"/api/copies/{card['id']}").json()
    evidence = json.loads(
        next(e for e in detail["history"] if e["kind"] == "photo-preparation")[
            "after_json"
        ]
    )
    assert evidence["original_photo"] != evidence["prepared_photo"] == changed["photo"]
    store = client.app.state.store
    archive = tmp_path / "prepared.zip"
    backup(store, archive)
    recovered = tmp_path / "restored"
    assert restore_backup(archive, recovered)["copies"] == 1
    for key in ["original_photo", "prepared_photo"]:
        assert (recovered / "photos" / evidence[key]).read_bytes() == (
            store.photos / evidence[key]
        ).read_bytes()


def test_photo_replacement_rejects_stale_version_and_other_owner(client):
    card = client.post("/api/copies", json=values(client)).json()
    token = draft(client)
    client.patch(
        f"/api/copies/{card['id']}",
        json={"expected_version": 1, "reason": "Autre correction", "notes": "Autre"},
    )
    assert (
        client.post(
            f"/api/copies/{card['id']}/photo-from-intake",
            json={"token": token, "expected_version": 1},
        ).status_code
        == 409
    )
    assert client.get(f"/api/copies/{card['id']}").json()["photo"] is None
    client.post(
        "/api/users",
        json={
            "username": "other",
            "password": "Collection-other-2026!",
            "role": "editor",
        },
    )
    client.post("/api/logout")
    client.post(
        "/api/login", json={"username": "other", "password": "Collection-other-2026!"}
    )
    assert client.post(f"/api/intake/{token}/photo-options", json={}).status_code == 404
    assert (
        client.post(
            f"/api/copies/{card['id']}/photo-from-intake",
            json={"token": token, "expected_version": 2},
        ).status_code
        == 404
    )


def test_stale_or_forged_confirmation_is_rejected(client):
    token = draft(client)
    assert (
        client.post(
            f"/api/intake/{token}/save",
            json=values(client, human_confirmed=True, chosen_catalog_id="invented"),
        ).status_code
        == 422
    )
    client.post(f"/api/intake/{token}/analyze")
    for changed in [
        {"number": "78/203"},
        {"name": "Pikachu"},
        {"language": "fr"},
        {"hp": 110},
    ]:
        response = client.post(
            f"/api/intake/{token}/save",
            json=values(
                client,
                human_confirmed=True,
                chosen_catalog_id=CANDIDATE["id"],
                **changed,
            ),
        )
        assert response.status_code == 422
    assert client.get("/api/summary").json()["copies"] == 0


def test_existing_intake_preserves_copy_stock_and_original_source(client):
    original = client.post(
        "/api/copies",
        json=values(
            client,
            set_name="",
            notes="Mes notes",
            condition="PL",
            condition_confirmed=True,
        ),
    ).json()
    store = client.app.state.store
    with store.connect(write=True) as db:
        db.execute(
            "INSERT INTO sources VALUES(?,?,?,?)",
            (
                original["id"],
                '{"original":"source conservée"}',
                "original-test",
                "2026-10-05",
            ),
        )
    client.put(f"/api/copies/{original['id']}/photo?version=1", content=photo())
    token = client.post(f"/api/copies/{original['id']}/intake").json()["token"]
    client.post(f"/api/intake/{token}/analyze")
    response = client.post(
        f"/api/intake/{token}/save",
        json=values(client, human_confirmed=True, chosen_catalog_id=CANDIDATE["id"]),
    )
    assert response.status_code == 201
    changed = response.json()
    assert (
        changed["id"] == original["id"]
        and changed["notes"] == "Mes notes"
        and changed["condition"] == "PL"
    )
    assert changed["photo"] and changed["stock_state"] == "available"
    assert client.get("/api/summary").json()["copies"] == 1
    events = client.get(f"/api/copies/{original['id']}").json()["history"]
    evidence = next(event for event in events if event["kind"] == "identification")
    assert json.loads(evidence["after_json"])["raw_response"] == json.dumps(OBSERVATION)
    assert client.get(f"/api/copies/{original['id']}").json()["source"]["data"] == {
        "original": "source conservée"
    }


def test_existing_intake_detects_concurrent_correction(client):
    original = client.post("/api/copies", json=values(client)).json()
    token = client.post(f"/api/copies/{original['id']}/intake").json()["token"]
    client.patch(
        f"/api/copies/{original['id']}",
        json={
            "expected_version": 1,
            "reason": "Autre modification",
            "notes": "À conserver",
        },
    )
    assert (
        client.post(f"/api/intake/{token}/save", json=values(client)).status_code == 409
    )
    assert client.get(f"/api/copies/{original['id']}").json()["notes"] == "À conserver"


def test_photo_is_private_to_its_author_and_readers_cannot_scan(client):
    token = draft(client)
    client.post(
        "/api/users",
        json={
            "username": "other",
            "password": "Collection-other-2026!",
            "role": "editor",
        },
    )
    client.post(
        "/api/users",
        json={
            "username": "reader",
            "password": "Collection-reader-2026!",
            "role": "reader",
        },
    )
    client.post("/api/logout")
    assert client.get(f"/api/intake/{token}/photo").status_code == 401
    assert client.post(f"/api/intake/{token}/analyze").status_code == 401
    client.post(
        "/api/login", json={"username": "other", "password": "Collection-other-2026!"}
    )
    assert client.get(f"/api/intake/{token}/photo").status_code == 404
    assert (
        client.post(f"/api/intake/{token}/save", json=values(client)).status_code == 404
    )
    client.post("/api/logout")
    client.post(
        "/api/login", json={"username": "reader", "password": "Collection-reader-2026!"}
    )
    assert client.post("/api/intake/drafts").status_code == 403
    assert client.post("/api/intake/photo", content=photo()).status_code == 403


def test_upload_validation_and_cross_origin_precede_provider(client):
    assert client.post("/api/intake/photo", content=b"invalid").status_code == 422
    assert (
        client.post(
            "/api/intake/photo", content=b"x" * (8 * 1024 * 1024 + 1)
        ).status_code
        == 413
    )
    token = draft(client)
    assert (
        client.post(
            f"/api/intake/{token}/analyze",
            headers={"Origin": "https://outside.example"},
        ).status_code
        == 403
    )
    assert client.delete(f"/api/intake/{token}").status_code == 200
    assert client.get(f"/api/intake/{token}/photo").status_code == 404


def test_provider_failure_still_allows_manual_save(client):
    service = client.app.state.intake

    def fail(data):
        raise RuntimeError("Lecture indisponible")

    service.reader = fail
    token = draft(client)
    assert client.post(f"/api/intake/{token}/analyze").status_code == 502
    response = client.post(
        f"/api/intake/{token}/save", json=values(client, set_name="")
    )
    assert response.status_code == 201 and response.json()["photo"]
    assert response.json()["identification_status"] == "review"


def test_reader_result_is_cached_and_concurrent_save_is_single_copy(tmp_path):
    store = Store(tmp_path)
    album = {"id": "test"}
    with store.connect(write=True) as db:
        db.execute("INSERT INTO albums(id,name) VALUES(?,?)", ("test", "Test"))
    calls = []

    def reader(data):
        calls.append(1)
        return OBSERVATION.copy(), json.dumps(OBSERVATION)

    service = IntakeService(store, reader, lookup)
    with store.connect(write=True) as db:
        db.execute(
            "INSERT INTO users(id,username,password_hash,role,created_at) VALUES('owner','owner','unused','editor','test')"
        )
    token = service.new("owner", photo())["token"]
    assert service.analyze(token, "owner") == service.analyze(token, "owner")
    assert len(calls) == 1
    data = {k: CANDIDATE[k] for k in ("name", "number", "set_name", "language", "hp")}
    data.update(album_id=album["id"], page=1, position=1, reason="Essai")

    def save(_):
        return service.save(token, "owner", "pat", data, CANDIDATE["id"], True)["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(save, range(2)))) == 1
    assert store.summary()["copies"] == 1
    service.drafts[token]["expires"] = time.time() - 1
    with pytest.raises(KeyError):
        service.draft(token, "owner")


def test_catalogue_requires_language_name_number_denominator_and_hp():
    details = [
        {
            "id": "swsh7-077",
            "name": "Gourgeist",
            "localId": "077",
            "hp": 120,
            "set": {"name": "Evolving Skies", "cardCount": {"official": 203}},
            "image": "https://assets.tcgdex.net/en/swsh7/077",
        },
        {
            "id": "wrong-77",
            "name": "Gourgeist",
            "localId": "77",
            "hp": 120,
            "set": {"name": "Wrong", "cardCount": {"official": 100}},
        },
        {"id": "decoy-77", "name": "Different name", "localId": "77"},
    ]

    def get(url):
        assert "/en/" in url
        if "?" in url:
            return details
        return next(c for c in details if url.endswith("/" + c["id"]))

    query = {"name": "Gourgeist", "number": "077/203", "language": "en", "hp": 120}
    result = catalogue_candidates(query, get)
    assert [c["id"] for c in result["candidates"]] == ["swsh7-077"]
    assert not catalogue_candidates({**query, "number": "78/203"}, get)["candidates"]
    assert not catalogue_candidates({**query, "hp": 110}, get)["candidates"]
    assert not catalogue_candidates({**query, "language": "unknown"}, get)["candidates"]
    # Incomplete references expose multiple choices instead of guessing.
    assert len(catalogue_candidates({**query, "number": "77"}, get)["candidates"]) == 2


def test_invalid_observation_and_photo_are_not_silent_empty_cards():
    with pytest.raises(ValueError):
        Observation.model_validate_json("{}")
    with pytest.raises(ValueError):
        normalize_photo(b"not an image")


def test_capture_guide_is_kept_for_photo_options_and_validated(client):
    headers = {"X-Card-Guide": "0.2000,0.1000,0.6000,0.8000"}
    uploaded = client.post("/api/intake/photo", content=photo(), headers=headers)
    assert uploaded.status_code == 201
    processing = uploaded.json()["photo_processing"]
    assert processing["crop_source"] == "guide"
    assert processing["guide"] == [0.2, 0.1, 0.6, 0.8]
    token = uploaded.json()["token"]
    service = client.app.state.intake
    service.drafts.clear()  # Reload the draft from SQLite, as after a restart.
    options = client.post(
        f"/api/intake/{token}/photo-options",
        json={"crop": True, "balance": False, "perspective": True},
    ).json()
    assert options["crop_source"] == "guide"
    bad = client.post(
        "/api/intake/photo", content=photo(), headers={"X-Card-Guide": "1,1,1,1"}
    )
    assert bad.status_code == 422
