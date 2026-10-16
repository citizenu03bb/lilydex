import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_library import inputs

from pokeprice.inventory import SCHEMA_VERSION
from pokeprice.inventory import Store
from pokeprice.inventory_backup import (
    backup,
    export_csv,
    export_data,
    export_html,
    restore_backup,
)
from pokeprice.inventory_import import import_collection
from pokeprice.webapp import create_app


@pytest.fixture
def collection(tmp_path):
    store = Store(tmp_path / "inventory")
    manifest = inputs(tmp_path)
    import_collection(store, manifest)
    with TestClient(
        create_app(
            store.root,
            condition_reader=lambda _: pytest.fail("No model call for trash"),
        )
    ) as client:
        client.post(
            "/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}
        )
        yield store, manifest, client


def remove(client, card, **changes):
    return client.request(
        "DELETE",
        f"/api/copies/{card['id']}",
        json={
            "expected_version": card["version"],
            "reason": "Doublon saisi par erreur",
            **changes,
        },
    )


def test_removal_and_restore_keep_sources_photos_prices_history(collection, tmp_path):
    store, manifest, client = collection
    card = next(c for c in client.get("/api/copies").json()["items"] if c["photo"])
    photo = (store.photos / card["photo"]).read_bytes()
    before = client.get("/api/summary").json()
    deleted = remove(client, card)
    assert deleted.status_code == 200, deleted.text
    deleted = deleted.json()
    assert deleted["deleted_at"] and deleted["version"] == card["version"] + 1
    assert deleted["reference_cents"] == card["reference_cents"]
    assert client.get("/api/summary").json()["copies"] == before["copies"] - 1
    assert sum(a["copies"] for a in store.summary()["albums"]) == before["copies"] - 1
    assert card["id"] not in {c["id"] for c in store.listing()["items"]}
    assert (
        client.get("/api/copies?stock=available").json()["total"]
        == before["copies"] - 1
    )
    trash = client.get("/api/copies?stock=deleted").json()
    assert trash["total"] == 1 and trash["items"][0]["id"] == card["id"]
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["source"] and detail["history"][0]["kind"] == "trash"
    assert detail["history"][0]["actor"] == "pat"
    assert client.get(f"/api/copies/{card['id']}/photo").content == photo
    assert card["id"] not in export_csv(store)
    assert card["id"] not in export_html(store)
    assert next(
        c for c in export_data(store)["tables"]["copies"] if c["id"] == card["id"]
    )["deleted_at"]
    # Reimport must not recreate or reactivate removed copies.
    assert import_collection(store, manifest)["created"] == 0
    assert store.listing(stock="deleted")["total"] == 1
    archive = tmp_path / "backup.zip"
    backup(store, archive)
    restored_path = tmp_path / "restored"
    assert restore_backup(archive, restored_path)["copies"] == before["copies"] - 1
    restored_store = Store(restored_path)
    assert restored_store.listing(stock="deleted")["total"] == 1
    assert (restored_store.photos / card["photo"]).read_bytes() == photo
    restored = client.post(
        f"/api/copies/{card['id']}/restore",
        json={
            "expected_version": deleted["version"],
            "reason": "Restauration de contrôle",
        },
    )
    assert restored.status_code == 200
    assert not restored.json()["deleted_at"] and restored.json()["id"] == card["id"]
    assert store.summary()["copies"] == before["copies"]
    assert store.listing(stock="deleted")["total"] == 0
    assert (
        client.get(f"/api/copies/{card['id']}").json()["history"][0]["kind"]
        == "restore"
    )


def test_removal_requires_current_version_and_prevents_edits_or_sales(collection):
    store, _, client = collection
    card = store.listing()["items"][0]
    assert remove(client, card, expected_version=card["version"] + 1).status_code == 409
    assert remove(client, card, reason=" ").status_code == 422
    assert remove(client, card).status_code == 200
    assert remove(client, card).status_code == 409
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert (
        client.patch(
            f"/api/copies/{card['id']}",
            json={
                "expected_version": detail["version"],
                "reason": "Edit trash",
                "notes": "changed",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/sales",
            json={"title": "lot", "copy_ids": [card["id"]], "amount_eur": 1},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/copies/{card['id']}/condition-assessments",
            json={"expected_version": detail["version"]},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/copies/{card['id']}/restore",
            json={"expected_version": card["version"], "reason": "Stale restore"},
        ).status_code
        == 409
    )


@pytest.mark.parametrize("role", ["reader", "editor"])
def test_only_admin_can_remove_restore_or_browse_trash(collection, role):
    store, _, client = collection
    card = store.listing()["items"][0]
    client.post(
        "/api/users",
        json={"username": role, "password": "Collection-test-2026!", "role": role},
    )
    client.post("/api/logout")
    client.post(
        "/api/login", json={"username": role, "password": "Collection-test-2026!"}
    )
    assert remove(client, card).status_code == 403
    assert (
        client.post(
            f"/api/copies/{card['id']}/restore",
            json={"expected_version": card["version"], "reason": "Restore"},
        ).status_code
        == 403
    )
    assert client.get("/api/copies?stock=deleted").status_code == 403
    assert client.get("/api/copies").status_code == 200
    assert store.summary()["copies"] == 7
    client.post("/api/logout")
    assert remove(client, card).status_code == 401


def test_cannot_remove_copy_in_a_draft_reserved_or_sold_lot(collection):
    store, _, client = collection
    card = store.listing()["items"][0]
    sale_id = store.create_sale(
        {"title": "Lot", "amount_cents": 100}, [card["id"]], "pat"
    )
    assert remove(client, card).status_code == 409
    reserved = store.update_sale(
        sale_id, {"status": "reserved"}, 1, "pat", "Réservation"
    )
    with store.connect() as db:
        reserved_card = store.get(db, card["id"])
    assert remove(client, reserved_card).status_code == 409
    store.update_sale(
        sale_id, {"status": "cancelled"}, reserved["version"], "pat", "Annulation"
    )
    with store.connect() as db:
        available = store.get(db, card["id"])
    assert remove(client, available).status_code == 200
    other = store.listing()["items"][0]
    sold_lot = store.create_sale(
        {"title": "Vendu", "amount_cents": 100}, [other["id"]], "pat"
    )
    store.update_sale(sold_lot, {"status": "reserved"}, 1, "pat", "Réservation")
    store.update_sale(sold_lot, {"status": "sold"}, 2, "pat", "Vente")
    with store.connect() as db:
        sold_card = store.get(db, other["id"])
    assert remove(client, sold_card).status_code == 409


def test_schema_5_migration_preserves_all_copy_data(tmp_path):
    store = Store(tmp_path / "inventory")
    manifest = inputs(tmp_path)
    import_collection(store, manifest)
    with sqlite3.connect(store.database) as db:
        db.row_factory = sqlite3.Row
        db.execute("ALTER TABLE copies DROP COLUMN deleted_at")
        db.execute("ALTER TABLE copies DROP COLUMN stamp")
        for column in (
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
        db.execute("PRAGMA user_version=5")
        for table in (
            "intake_drafts",
            "capture_sessions",
            "photo_batches",
            "catalog_names",
            "catalog_lookups",
        ):
            db.execute("DROP TABLE " + table)
        before = [dict(r) for r in db.execute("SELECT * FROM copies ORDER BY id")]
    migrated = Store(store.root)
    with migrated.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        after = [dict(r) for r in db.execute("SELECT * FROM copies ORDER BY id")]
    added = (
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
    )
    assert [{k: v for k, v in c.items() if k not in added} for c in after] == before
    assert all(c["deleted_at"] == "" and c["stamp"] == "" for c in after)
