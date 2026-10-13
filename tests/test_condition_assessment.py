import io
import json
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from pokeprice.condition_assessment import ConditionService, read_condition
from pokeprice.inventory import Conflict, Store
from pokeprice.inventory_backup import backup, export_data, export_html, restore_backup
from pokeprice.webapp import create_app


def picture(color):
    image = Image.new("RGB", (420, 540), color)
    draw = ImageDraw.Draw(image)
    draw.polygon([(95, 80), (290, 105), (322, 390), (72, 405)], fill=(235, 224, 197))
    output = io.BytesIO()
    image.save(output, "JPEG", quality=95)
    return output.getvalue()


def observed(photos, grade="GD"):
    return {
        "suggested_condition": grade,
        "front_usable": "front" in photos,
        "back_usable": "back" in photos,
        "quality": "adequate",
        "flaws_front": "Usure visible au coin supérieur.",
        "flaws_back": "Légère usure des bords." if "back" in photos else "",
        "explanation": "Usure visible à contrôler sur la carte.",
        "limits": [],
    }


@pytest.fixture
def collection(tmp_path):
    sent = []

    def reader(photos):
        sent.append(photos)
        result = observed(photos)
        return result, json.dumps(result)

    app = create_app(tmp_path / "inventory", condition_reader=reader)
    with TestClient(app) as client:
        client.post(
            "/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}
        )
        album = client.post("/api/albums", json={"name": "Test"}).json()
        card = client.post(
            "/api/copies",
            json={
                "name": "Gourgeist",
                "album_id": album["id"],
                "page": 1,
                "position": 1,
                "reason": "Ajout manuel",
                "condition": "EX",
                "condition_confirmed": True,
            },
        ).json()
        yield client, app, card, sent


def attach(client, card, side, color):
    draft = client.post("/api/intake/photo", content=picture(color)).json()
    response = client.post(
        f"/api/copies/{card['id']}/photo-from-intake",
        json={
            "token": draft["token"],
            "side": side,
            "expected_version": card["version"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json(), draft["token"]


def evaluate(client, card):
    return client.post(
        f"/api/copies/{card['id']}/condition-assessments",
        json={"expected_version": card["version"]},
    )


def test_verso_and_originals_are_private_separate_and_not_stock(collection):
    client, app, card, _ = collection
    card, _ = attach(client, card, "front", "gray")
    front = card["photo"]
    card, token = attach(client, card, "back", "blue")
    assert card["photo"] == front and card["back_photo"] != front
    assert card["condition"] == "EX" and not card["condition_confirmed"]
    assert client.get("/api/summary").json()["copies"] == 1
    assert (
        client.get(f"/api/copies/{card['id']}/photo?side=back").content
        == (app.state.store.photos / card["back_photo"]).read_bytes()
    )
    assert (
        client.post(
            f"/api/copies/{card['id']}/photo-from-intake",
            json={"token": token, "side": "front", "expected_version": card["version"]},
        ).status_code
        == 422
    )
    client.post("/api/logout")
    assert client.get(f"/api/copies/{card['id']}/photo?side=back").status_code == 401
    assert evaluate(client, card).status_code == 401


def test_assessment_uses_originals_preserves_state_and_requires_human_confirmation(
    collection,
):
    client, app, card, sent = collection
    card = client.patch(
        f"/api/copies/{card['id']}",
        json={
            "expected_version": card["version"],
            "reason": "Référence de test",
            "identification_status": "confirmed",
            "reference_price_eur": "12.34",
            "price_source": "Source de test",
        },
    ).json()
    card, _ = attach(client, card, "front", "gray")
    card, _ = attach(client, card, "back", "blue")
    response = evaluate(client, card)
    assert response.status_code == 201, response.text
    assessment = response.json()
    assert (
        sent[0]["front"]
        == (app.state.store.photos / card["photo_original"]).read_bytes()
    )
    assert (
        sent[0]["back"]
        == (app.state.store.photos / card["back_photo_original"]).read_bytes()
    )
    assert card["photo_original"] != card["photo"]  # perspective preparation differs
    current = client.get(f"/api/copies/{card['id']}").json()
    for key in (
        "condition",
        "condition_confirmed",
        "reference_cents",
        "stock_state",
        "version",
    ):
        assert current[key] == card[key]
    endpoint = (
        f"/api/copies/{card['id']}/condition-assessments/{assessment['id']}/confirm"
    )
    values = {
        "expected_version": card["version"],
        "condition": "LP",
        "human_confirmed": False,
        "reason": "Examen recto et verso",
    }
    assert client.post(endpoint, json=values).status_code == 422
    changed = client.post(endpoint, json={**values, "human_confirmed": True}).json()
    assert changed["condition"] == "LP" and changed["condition_confirmed"]
    assert (
        changed["stock_state"] == card["stock_state"]
        and changed["reference_cents"] == card["reference_cents"]
    )
    detail = client.get(f"/api/copies/{card['id']}").json()
    evidence = next(e for e in detail["history"] if e["kind"] == "condition-validation")
    assert json.loads(evidence["after_json"])["assessment_id"] == assessment["id"]
    assert detail["condition_assessments"][0]["result"]["suggested_condition"] == "GD"
    assert changed["reference_cents"] == 1234


def test_replaced_photos_make_assessment_stale_and_cannot_be_confirmed(collection):
    client, _, card, _ = collection
    card, _ = attach(client, card, "front", "gray")
    assessment = evaluate(client, card).json()
    card, _ = attach(client, card, "back", "blue")
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["condition_assessments"][0]["stale"]
    response = client.post(
        f"/api/copies/{card['id']}/condition-assessments/{assessment['id']}/confirm",
        json={
            "expected_version": card["version"],
            "condition": "GD",
            "human_confirmed": True,
            "reason": "Examen",
        },
    )
    assert response.status_code == 409


def test_partial_unclear_and_provider_errors_do_not_invent_states(collection):
    client, app, card, _ = collection
    assert evaluate(client, card).status_code == 422
    card, _ = attach(client, card, "front", "gray")
    app.state.conditions.reader = lambda photos: (observed(photos, "NM"), "raw NM")
    result = evaluate(client, card).json()["result"]
    assert result["suggested_condition"] == "" and not result["back_usable"]
    assert any("verso" in text for text in result["limits"])
    app.state.conditions.reader = lambda photos: (
        {**observed(photos), "quality": "unusable"},
        "raw",
    )
    assert evaluate(client, card).json()["result"]["suggested_condition"] == ""
    app.state.conditions.reader = lambda photos: ({"bad": "response"}, "raw")
    assert evaluate(client, card).status_code == 502

    def unavailable(photos):
        raise RuntimeError("Évaluation indisponible.")

    app.state.conditions.reader = unavailable
    assert evaluate(client, card).status_code == 502
    current = client.get(f"/api/copies/{card['id']}").json()
    assert current["condition"] == "EX" and current["version"] == card["version"]


def test_photo_change_during_analysis_and_duplicate_requests_are_rejected(collection):
    _, app, card, _ = collection
    store = app.state.store
    name = store.save_photo(picture("red"))
    card = store.patch(
        card["id"],
        {"photo": name, "photo_original": name},
        card["version"],
        "pat",
        "Photo",
    )
    started, release = Event(), Event()

    def slow(photos):
        started.set()
        assert release.wait(5)
        return observed(photos), "raw"

    service = ConditionService(store, slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(service.evaluate, card["id"], card["version"], "pat")
        assert started.wait(3)
        with pytest.raises(Conflict):
            service.evaluate(card["id"], card["version"], "pat")
        store.patch(
            card["id"], {"notes": "Concurrent"}, card["version"], "pat", "Modification"
        )
        release.set()
        with pytest.raises(Conflict):
            running.result()
    with store.connect() as db:
        assert (
            db.execute("SELECT count(*) FROM condition_assessments").fetchone()[0] == 0
        )


def test_reader_role_cannot_evaluate_and_injected_state_is_rejected(collection):
    client, _, card, _ = collection
    client.post(
        "/api/users",
        json={
            "username": "reader",
            "password": "Collection-reader-2026!",
            "role": "reader",
        },
    )
    client.post("/api/logout")
    client.post(
        "/api/login", json={"username": "reader", "password": "Collection-reader-2026!"}
    )
    assert evaluate(client, card).status_code == 403
    assert (
        client.put(
            f"/api/copies/{card['id']}/photo?side=back&version=1",
            content=picture("blue"),
        ).status_code
        == 403
    )


def test_backup_restore_and_offline_export_keep_both_faces_and_evidence(
    collection, tmp_path
):
    client, app, card, _ = collection
    card, _ = attach(client, card, "front", "gray")
    card, _ = attach(client, card, "back", "blue")
    assessment = evaluate(client, card).json()
    archive = tmp_path / "backup.zip"
    backup(app.state.store, archive)
    target = tmp_path / "restored"
    assert restore_backup(archive, target)["copies"] == 1
    restored = Store(target)
    assert export_data(restored)["tables"] == export_data(app.state.store)["tables"]
    exported = export_html(restored)
    assert "back_image" in exported and "Verso de" in exported
    assert (
        export_data(restored)["tables"]["condition_assessments"][0]["id"]
        == assessment["id"]
    )
    # A backup missing an original face must fail restoration even if its manifest matches.
    broken = tmp_path / "missing.zip"
    with (
        zipfile.ZipFile(archive) as source,
        zipfile.ZipFile(broken, "w") as destination,
    ):
        manifest = json.loads(source.read("manifest.json"))
        missing = "photos/" + card["back_photo_original"]
        manifest["files"].pop(missing)
        for name in source.namelist():
            if name not in (missing, "manifest.json"):
                destination.writestr(name, source.read(name))
        destination.writestr("manifest.json", json.dumps(manifest))
    with pytest.raises(ValueError, match="Photo référencée absente"):
        restore_backup(broken, tmp_path / "broken-restore")


def test_schema4_migration_preserves_existing_copy(collection):
    _, app, card, _ = collection
    with sqlite3.connect(app.state.store.database) as db:
        db.execute("DROP TABLE condition_assessments")
        for table in ("catalog_names", "catalog_lookups"):
            db.execute("DROP TABLE " + table)
        for table in ("intake_drafts", "capture_sessions", "photo_batches"):
            db.execute("DROP TABLE " + table)
        for column in (
            "photo_original",
            "back_photo",
            "back_photo_original",
            "deleted_at",
            "stamp",
            "finish",
            "variant_confirmed",
            "variant_verified_at",
            "variant_verified_by",
            "variant_observation",
            "stamp_state",
            "distribution",
            "distribution_state",
            "observation_provenance",
        ):
            db.execute("ALTER TABLE copies DROP COLUMN " + column)
        db.execute("DROP TABLE reference_quote_events")
        db.execute("DROP TABLE reference_quotes")
        db.execute("DROP TABLE reference_decisions")
        db.execute("DROP TABLE reference_rulesets")
        db.execute("DROP TABLE reference_engines")
        db.execute("PRAGMA user_version=4")
    migrated = Store(app.state.store.root)
    with migrated.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 13
        new = migrated.get(db, card["id"])
        assert all(
            new[k] == v
            for k, v in card.items()
            if k not in ("photo_original", "back_photo", "back_photo_original")
        )
        assert new["photo_original"] is None and new["back_photo"] is None


def test_legacy_original_is_recovered_only_for_the_matching_current_photo(collection):
    client, app, card, sent = collection
    card, _ = attach(client, card, "front", "gray")
    original = card["photo_original"]
    with app.state.store.connect(write=True) as db:
        db.execute("UPDATE copies SET photo_original=NULL WHERE id=?", (card["id"],))
    assessment = evaluate(client, card).json()
    assert assessment["photos"]["front"]["original"]
    assert sent[-1]["front"] == (app.state.store.photos / original).read_bytes()
    replacement = app.state.store.save_photo(picture("green"))
    card = app.state.store.patch(
        card["id"],
        {"photo": replacement},
        card["version"],
        "pat",
        "Nouvelle photo historique",
    )
    assert card["photo_original"] is None
    new = evaluate(client, card).json()
    assert new["photos"]["front"]["image"] == replacement
    assert not new["photos"]["front"]["original"]
    assert any("avant correction" in text for text in new["result"]["limits"])


def test_near_mint_proposal_requires_both_usable_original_faces(collection):
    client, app, card, _ = collection
    app.state.conditions.reader = lambda photos: (observed(photos, "NM"), "raw NM")
    card, _ = attach(client, card, "front", "gray")
    card, _ = attach(client, card, "back", "blue")
    assert evaluate(client, card).json()["result"]["suggested_condition"] == "NM"
    app.state.conditions.reader = lambda photos: (
        {**observed(photos, "NM"), "back_usable": False},
        "raw",
    )
    assert evaluate(client, card).json()["result"]["suggested_condition"] == ""


@pytest.mark.parametrize("extra", [False, True])
def test_provider_schema_accepts_indeterminate_and_validates_extra_fields_locally(
    monkeypatch, extra
):
    from google import genai

    result = {**observed({}), "suggested_condition": None, "quality": "unusable"}
    if extra:
        result["unexpected"] = "not part of the contract"

    class FakeClient:
        def __init__(self, **kwargs):
            self.models = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def generate_content(self, **kwargs):
            schema = kwargs["config"].response_schema
            assert "additionalProperties" not in schema
            alternatives = schema["properties"]["suggested_condition"]["anyOf"]
            assert any(item.get("type") == "null" for item in alternatives)
            assert all("" not in item.get("enum", []) for item in alternatives)
            return SimpleNamespace(text=json.dumps(result))

    monkeypatch.setattr(genai, "Client", FakeClient)
    if extra:
        with pytest.raises(RuntimeError, match="réponse invalide"):
            read_condition({"front": picture("gray")})
    else:
        response, raw = read_condition({"front": picture("gray")})
        assert response["suggested_condition"] is None and json.loads(raw) == result
