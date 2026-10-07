import io
import json
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_intake import client as intake_client
from test_intake import draft, values

from pokeprice.capture import CaptureService
from pokeprice.daily_backup import daily, public_status, record_external, verify
from pokeprice.intake import IntakeService
from pokeprice.inventory_backup import backup


@pytest.fixture
def client(tmp_path):
    yield from intake_client.__wrapped__(tmp_path)


def series(client, **overrides):
    data = values(client)
    data.pop("reason")
    response = client.post(
        "/api/capture-sessions",
        json={
            "album_id": data["album_id"],
            "slots": 9,
            "page": 1,
            "position": 9,
            **overrides,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def ready(client, session, front, back=None):
    response = client.patch(
        "/api/capture-sessions/" + session["id"],
        json={
            "expected_version": session["version"],
            "front_token": front,
            "back_token": back,
            "fields": {"name": "Saisie conservée", "number": "77/203"},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_capture_rehydrates_two_photos_and_fields_after_restart(client):
    session = series(client)
    front, back = draft(client), draft(client)
    session = ready(client, session, front, back)
    store = client.app.state.store
    fresh = IntakeService(store)
    assert fresh.draft(front, client.get("/api/session").json()["id"])["photo"]
    capture = CaptureService(store, fresh)
    owner = client.get("/api/session").json()["id"]
    assert capture.listing(owner)[0]["data"]["fields"]["name"] == "Saisie conservée"
    data = values(client, position=9)
    result = capture.save(
        session["id"], owner, "pat", session["version"], front, data, None, False, []
    )
    assert result["card"]["back_photo"] and result["card"]["photo_original"]
    # The detail view reads both states of every history entry as objects.
    history = client.get(f"/api/copies/{result['card']['id']}").json()["history"]
    assert any(e["reason"] == "Verso enregistré avec la série" for e in history)
    assert all(
        isinstance(json.loads(e[key]), dict)
        for e in history
        for key in ("before_json", "after_json")
    )
    assert result["session"]["data"]["page"] == 2
    assert result["session"]["data"]["position"] == 1
    assert result["session"]["data"]["completed"] == 1
    fresh = IntakeService(store)
    assert fresh.draft(back, owner)["saved"] == result["card"]["id"]
    assert fresh.draft(front, owner)["saved"] == result["card"]["id"]
    # An uncertain retry after restart returns the committed copy without advancement.
    again = CaptureService(store, fresh).save(
        session["id"], owner, "pat", 1, front, data, None, False, []
    )
    assert again["card"]["id"] == result["card"]["id"]
    assert store.summary()["copies"] == 1


def test_capture_double_save_concurrently_creates_one_copy(client):
    session = ready(client, series(client), draft(client))
    store = client.app.state.store
    owner = client.get("/api/session").json()["id"]
    service = CaptureService(store, client.app.state.intake)

    def save(_):
        return service.save(
            session["id"],
            owner,
            "pat",
            session["version"],
            session["data"]["front_token"],
            values(client, position=9),
            None,
            False,
            [],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, range(2)))
    assert results[0]["card"]["id"] == results[1]["card"]["id"]
    assert store.summary()["copies"] == 1


def test_duplicate_photo_or_location_requires_ack_and_failed_save_keeps_series(client):
    first = client.post(
        "/api/intake/" + draft(client) + "/save", json=values(client)
    ).json()
    session = ready(client, series(client, position=1), draft(client))
    token = session["data"]["front_token"]
    matches = client.post(f"/api/intake/{token}/duplicates", json=values(client)).json()
    assert matches[0]["id"] == first["id"] and len(matches[0]["reasons"]) == 2
    payload = {**values(client), "token": token, "expected_version": session["version"]}
    assert (
        client.post(
            f"/api/capture-sessions/{session['id']}/save", json=payload
        ).status_code
        == 409
    )
    unchanged = client.get("/api/capture-sessions/" + session["id"]).json()
    assert (
        unchanged["version"] == session["version"]
        and unchanged["data"]["completed"] == 0
    )
    payload["duplicate_acknowledgments"] = [matches[0]["acknowledgment"]]
    created = client.post(f"/api/capture-sessions/{session['id']}/save", json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["card"]["id"] != first["id"]
    assert client.get("/api/summary").json()["copies"] == 2


def test_session_draft_and_batch_are_private_and_reader_cannot_write(client):
    session = ready(client, series(client), draft(client))
    token = session["data"]["front_token"]
    assert client.delete("/api/intake/" + token).status_code == 409
    card = client.post("/api/copies", json=values(client, position=3)).json()
    job = client.post(
        "/api/photo-batches",
        json={"copies": [{"id": card["id"], "expected_version": card["version"]}]},
    ).json()
    client.post(
        "/api/users",
        json={
            "username": "readonly",
            "password": "Collection-test-2026!",
            "role": "reader",
        },
    )
    client.post(
        "/api/users",
        json={
            "username": "other",
            "password": "Collection-test-2026!",
            "role": "editor",
        },
    )
    client.post("/api/logout")
    client.post(
        "/api/login", json={"username": "other", "password": "Collection-test-2026!"}
    )
    assert client.get("/api/capture-sessions").json() == []
    assert client.get("/api/capture-sessions/" + session["id"]).status_code == 404
    assert client.get("/api/intake/" + token).status_code == 404
    assert client.get("/api/photo-batches/" + job["id"]).status_code == 404
    assert client.get("/api/backup/status").status_code == 403
    # Pending capture tokens and privately typed drafts do not appear in shared exports.
    assert token not in client.get("/api/export/json").text
    client.post("/api/logout")
    client.post(
        "/api/login", json={"username": "readonly", "password": "Collection-test-2026!"}
    )
    assert client.get("/api/editions").status_code == 200
    assert client.get("/api/capture-sessions").status_code == 403
    assert (
        client.post(
            "/api/photo-batches",
            json={"copies": [{"id": card["id"], "expected_version": 1}]},
        ).status_code
        == 403
    )


def test_explicit_discard_cannot_rehydrate_after_restart(client):
    token = draft(client)
    assert client.delete("/api/intake/" + token).status_code == 200
    with pytest.raises(KeyError):
        IntakeService(client.app.state.store).draft(
            token, client.get("/api/session").json()["id"]
        )


def test_closed_series_releases_drafts_and_two_series_cannot_share_photo(client):
    first = ready(client, series(client), draft(client))
    first = client.patch(
        "/api/capture-sessions/" + first["id"],
        json={"expected_version": first["version"], "status": "paused"},
    ).json()
    second = series(client)
    forbidden = client.patch(
        "/api/capture-sessions/" + second["id"],
        json={
            "expected_version": second["version"],
            "front_token": first["data"]["front_token"],
        },
    )
    assert forbidden.status_code == 409
    closed = client.patch(
        "/api/capture-sessions/" + first["id"],
        json={"expected_version": first["version"], "status": "closed"},
    )
    assert closed.status_code == 200 and closed.json()["data"]["front_token"] is None
    assert client.get("/api/intake/" + first["data"]["front_token"]).status_code == 404


def test_grouped_view_stock_totals_across_filtered_copies(client):
    store = client.app.state.store
    data = values(client)
    data.pop("reason")
    for position in (1, 2, 3):
        store.create_copy(
            {
                **data,
                "position": position,
                "catalog_id": "test-1",
                "identification_status": "confirmed",
            },
            "pat",
            "Test",
        )
    cards = store.listing()["items"]
    sid = store.create_sale(
        {"title": "Réservation", "amount_cents": 100}, [cards[0]["id"]], "pat"
    )
    store.update_sale(sid, {"status": "reserved"}, 1, "pat", "Réservation test")
    grouped = client.get("/api/editions?stock=available").json()
    assert grouped["total"] == 1 and grouped["copies_total"] == 2
    group = grouped["items"][0]
    assert group["quantity"] == 2 and group["global_quantity"] == 3
    assert group["stock_counts"] == {"available": 2, "reserved": 1, "sold": 0}
    assert len({c["id"] for c in group["copies"]}) == 2


def test_photo_batch_preview_selected_apply_and_undo_retains_originals(client):
    token = draft(client)
    first = client.post(f"/api/intake/{token}/save", json=values(client)).json()
    second = client.post("/api/copies", json=values(client, position=2)).json()
    job = client.post(
        "/api/photo-batches",
        json={
            "copies": [
                {"id": c["id"], "expected_version": c["version"]}
                for c in (first, second)
            ],
            "options": {"crop": False, "perspective": False, "balance": False},
        },
    ).json()
    assert job["status"] == "preview" and job["data"]["items"][1]["result"] is None
    assert (
        client.get(
            f"/api/photo-batches/{job['id']}/photo/{first['id']}/result"
        ).status_code
        == 200
    )
    assert client.get("/api/copies/" + first["id"]).json()["version"] == 1
    applied = client.post(
        f"/api/photo-batches/{job['id']}/apply", json={"copy_ids": [first["id"]]}
    )
    assert applied.status_code == 200, applied.text
    card = client.get("/api/copies/" + first["id"]).json()
    assert card["photo_original"] == first["photo_original"]
    assert (
        client.post(
            f"/api/photo-batches/{job['id']}/apply", json={"copy_ids": [first["id"]]}
        ).status_code
        == 409
    )
    undone = client.post(f"/api/photo-batches/{job['id']}/undo")
    assert undone.status_code == 200, undone.text
    restored = client.get("/api/copies/" + first["id"]).json()
    assert (
        restored["photo"] == first["photo"]
        and restored["photo_original"] == first["photo_original"]
    )
    assert list(
        client.app.state.store.root.parent.joinpath("backups").glob(
            "before-photo-batch-*.zip"
        )
    )


def test_bulk_application_rolls_back_all_if_any_version_changed(client):
    store = client.app.state.store
    first = client.post(
        "/api/intake/" + draft(client) + "/save", json=values(client)
    ).json()
    second_values = values(client, position=2)
    second_values.pop("reason")
    second = store.create_copy(
        {**second_values, "photo": first["photo"]}, "pat", "Test"
    )
    job = client.post(
        "/api/photo-batches",
        json={
            "copies": [{"id": c["id"], "expected_version": 1} for c in (first, second)]
        },
    ).json()
    store.patch(second["id"], {"notes": "Concurrent"}, 1, "pat", "Test")
    assert (
        client.post(
            f"/api/photo-batches/{job['id']}/apply",
            json={"copy_ids": [first["id"], second["id"]]},
        ).status_code
        == 409
    )
    assert client.get("/api/copies/" + first["id"]).json()["version"] == 1
    assert (
        client.post(
            f"/api/photo-batches/{job['id']}/apply", json={"copy_ids": [first["id"]]}
        ).status_code
        == 200
    )
    store.patch(first["id"], {"notes": "Éditée après traitement"}, 2, "pat", "Test")
    assert client.post(f"/api/photo-batches/{job['id']}/undo").status_code == 409


def test_listing_package_excludes_notes_payments_and_does_not_reserve(client):
    store = client.app.state.store
    card = client.post(
        "/api/intake/" + draft(client) + "/save", json=values(client)
    ).json()
    card = store.patch(card["id"], {"notes": "PRIVATE-COPY-NOTE"}, 1, "pat", "Test")
    sid = store.create_sale(
        {
            "title": "Mon lot",
            "amount_cents": 123,
            "asking_cents": 456,
            "minimum_cents": 50,
            "notes": "PRIVATE-SALE-NOTE",
        },
        [card["id"]],
        "pat",
    )
    response = client.get(f"/api/sales/{sid}/listing-package")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        text = archive.read("description.txt").decode()
        assert "4.56 EUR" in text and "état à vérifier" in text
        assert "verso" in archive.read("a-completer.txt").decode()
        assert any(n.endswith("recto.jpg") for n in archive.namelist())
        assert b"PRIVATE" not in archive.read("cartes.json")
        assert "PRIVATE" not in text
    assert store.listing()["items"][0]["stock_state"] == "available"


def test_daily_verified_backup_retention_and_external_record(client):
    store = client.app.state.store
    folder = store.root.parent / "backups"
    folder.mkdir()
    for day in range(1, 10):
        (folder / f"daily-2000-01-{day:02d}.zip").touch()
    manual = folder / "collection-manual.zip"
    backup(store, manual)
    result = daily(store)
    assert verify(result["path"])["sha256"] == result["sha256"]
    assert len(list(folder.glob("daily-*.zip"))) == 7 and manual.exists()
    external = record_external(
        store, result["path"], "drive-test-file", result["bytes"]
    )
    assert external["verification"] == "metadata-size"
    assert "path" not in public_status(store)["external"]
    with pytest.raises(ValueError):
        record_external(store, result["path"], "x", 1)
    with pytest.raises(ValueError):
        record_external(
            store, result["path"], "x", result["bytes"], expected_sha256="stale-hash"
        )
    with zipfile.ZipFile(result["path"]) as archive:
        database = store.root.parent / "backup-test.sqlite3"
        database.write_bytes(archive.read("collection.sqlite3"))
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
