"""Observation provenance, migration rehearsal and offline decision replay."""

import hashlib
import json
import sqlite3
import zipfile
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from test_intake import values
from test_print_reference import SOURCE_DOCUMENT, reference_data

from pokeprice.inventory import Conflict, Store
from pokeprice.inventory_backup import backup, export_csv, export_data, restore_backup
from pokeprice.print_reference import validate_ruleset
from pokeprice.reference_service import ReferenceService, audit_directory
from pokeprice.webapp import create_app


@pytest.fixture
def reference():
    return reference_data()


def install_fixture_reference(store, reference):
    path = store.root / "reference_documents"
    path.mkdir(exist_ok=True)
    (path / (hashlib.sha256(SOURCE_DOCUMENT).hexdigest() + ".json")).write_bytes(
        SOURCE_DOCUMENT
    )
    store.reference = ReferenceService(store, validate_ruleset(reference))


@contextmanager
def client_context(tmp_path):
    with TestClient(
        create_app(tmp_path / "inventory", variant_fetch=lambda *_: {})
    ) as client:
        client.post(
            "/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}
        )
        client.post("/api/albums", json={"name": "Test"})
        yield client


@pytest.fixture
def client(tmp_path):
    with client_context(tmp_path) as client:
        yield client


def create(client, **fields):
    response = client.post("/api/copies", json=values(client, **fields))
    assert response.status_code == 201, response.text
    return response.json()


def state(store, copy_id):
    with store.connect() as db:
        return store.get(db, copy_id)


def test_partial_observation_is_savable_without_identity_reference_or_price(client):
    card = create(client, finish="special", stamp="EX Something", stamp_state="present")
    assert card["identification_status"] == "review" and card["reference_cents"] is None
    assert not card["variant_confirmed"] and card["variant_verified_at"] == ""
    provenance = json.loads(card["observation_provenance"])
    assert (
        provenance["stamp"]["actor"] == "pat"
        and provenance["stamp"]["text"] == "EX Something"
    )
    from pokeprice.print_reference import copy_observations

    assert copy_observations(card)["finish"]["human"]
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["reference_resolution"]["market_status"] == "uncovered"


@pytest.mark.parametrize("stamp,state", [("", "present"), ("Legacy text", "absent")])
def test_mark_observation_states_are_not_interchangeable(client, stamp, state):
    result = client.post(
        "/api/copies", json=values(client, stamp=stamp, stamp_state=state)
    )
    assert result.status_code == 422
    assert client.get("/api/copies").json()["total"] == 0


def test_provenance_is_server_owned_and_absence_is_attributable(client):
    card = create(client, stamp_state="absent")
    result = client.patch(
        f"/api/copies/{card['id']}",
        json={
            "expected_version": card["version"],
            "reason": "Fake actor",
            "observation_provenance": '{"actor":"someone-else"}',
        },
    )
    assert result.status_code == 422
    assert json.loads(card["observation_provenance"])["stamp"]["actor"] == "pat"


def test_readonly_audit_does_not_migrate_schema10_or_certify_legacy(client):
    card = create(
        client,
        identification_status="confirmed",
        finish="non_holo",
        variant_confirmed=True,
        stamp="Old text",
    )
    store = client.app.state.store
    card = store.patch(
        card["id"],
        {
            "reference_cents": 123,
            "price_source": "Manual old source",
            "price_date": "2025-01-01",
        },
        card["version"],
        "pat",
        "Historical price",
    )
    with store.connect(write=True) as db:
        for column in (
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
        db.execute("PRAGMA user_version=10")
    before = store.database.read_bytes()
    audit = audit_directory(store.root)
    assert audit["counts"]["legacy_manual"] == 1 and not audit["activation_ready"]
    assert audit["verified_reference_total_cents"] is None
    assert store.database.read_bytes() == before
    with sqlite3.connect(store.database) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 10
        db.row_factory = sqlite3.Row
        old = dict(
            db.execute("SELECT * FROM copies WHERE id=?", (card["id"],)).fetchone()
        )
    migrated = Store(store.root)
    new = state(migrated, card["id"])
    assert {k: new[k] for k in old} == old
    assert new["stamp_state"] == "unobserved" and new["observation_provenance"] == "{}"
    assert (
        migrated.reference.decision(new)["price_selection"]["state"] == "legacy_manual"
    )


def test_c16_backup_restore_replays_old_rules_and_preserves_observations(
    client, reference, tmp_path
):
    card = create(
        client,
        catalog_id="synthetic-1",
        language="fr",
        number="1/1",
        identification_status="confirmed",
        finish="holo",
        stamp_state="absent",
        variant_confirmed=True,
    )
    store = client.app.state.store
    install_fixture_reference(store, reference)
    before = state(store, card["id"])
    recorded = store.reference.record(
        card["id"], card["version"], "pat", "Documented audit"
    )
    assert state(store, card["id"]) == before
    assert store.reference.replay(recorded["id"])["status"] == "reproduced"
    # Include a source once by content hash, outside the installed application.
    document = b"Synthetic source archive, no Pokemon facts"
    path = store.root / "reference_documents"
    path.mkdir(exist_ok=True)
    name = hashlib.sha256(document).hexdigest() + ".json"
    (path / name).write_bytes(document)
    target = tmp_path / "backup.zip"
    backup(store, target)
    with zipfile.ZipFile(target) as archive:
        assert (
            json.loads(archive.read("manifest.json"))["files"][
                "reference_documents/" + name
            ]
            == name[:-5]
        )
    restore_backup(target, tmp_path / "restored")
    restored = Store(tmp_path / "restored")
    assert state(restored, card["id"]) == before
    assert restored.reference.replay(recorded["id"])["status"] == "reproduced"
    assert (restored.root / "reference_documents" / name).read_bytes() == document
    exported = export_data(restored)
    assert (
        exported["tables"]["reference_rulesets"]
        and exported["tables"]["reference_decisions"]
    )


def test_c20_stale_audit_cannot_record_or_modify_any_observation(client):
    card = create(client, stamp_state="absent")
    store = client.app.state.store
    changed = store.patch(
        card["id"],
        {"notes": "Newer edit"},
        card["version"],
        "pat",
        "Concurrent correction",
    )
    with pytest.raises(Conflict):
        store.reference.record(card["id"], card["version"], "pat", "Stale audit")
    assert state(store, card["id"]) == changed
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM reference_decisions").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM reference_rulesets").fetchone()[0] == 0


def test_preview_listing_export_and_detail_share_the_same_resolution(client):
    card = create(client, finish="non_holo", stamp_state="absent")
    detail = client.get(f"/api/copies/{card['id']}").json()["reference_resolution"]
    preview = client.post(f"/api/copies/{card['id']}/variant-preview", json={}).json()[
        "reference_resolution"
    ]
    listed = client.get("/api/copies?review=coverage&sort=binder").json()["items"][0][
        "reference_resolution"
    ]
    assert detail == preview == listed
    assert "reference_market_status" in export_csv(client.app.state.store)
    assert client.get("/api/editions?review=coverage").status_code == 200


def test_dispute_is_attributed_versioned_and_not_closed_by_metadata(client, reference):
    card = create(
        client,
        catalog_id="synthetic-1",
        language="fr",
        number="1/1",
        identification_status="confirmed",
        finish="holo",
        stamp_state="absent",
        variant_confirmed=True,
    )
    store = client.app.state.store
    store.reference = ReferenceService(store, validate_ruleset(reference))
    before = state(store, card["id"])
    response = client.post(
        f"/api/copies/{card['id']}/reference-dispute",
        json={
            "expected_version": card["version"],
            "reason": "Product disputed",
            "active": True,
            "affects": "market",
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["reference_resolution"]["market_status"] == "conflict"
    after = state(store, card["id"])
    assert {k: v for k, v in after.items() if k not in ("version", "updated_at")} == {
        k: v for k, v in before.items() if k not in ("version", "updated_at")
    }
    assert (
        client.post(
            f"/api/copies/{card['id']}/reference-dispute",
            json={
                "expected_version": card["version"],
                "reason": "Stale resolution",
                "active": False,
            },
        ).status_code
        == 409
    )
    assert (
        client.get(f"/api/copies/{card['id']}").json()["reference_resolution"][
            "market_status"
        ]
        == "conflict"
    )
    assert (
        client.get("/api/copies").json()["items"][0]["reference_resolution"][
            "market_status"
        ]
        == "conflict"
    )


def test_missing_historical_engine_reports_unreproducible_instead_of_new_engine_success(
    client,
):
    card = create(client)
    store = client.app.state.store
    recorded = store.reference.record(card["id"], card["version"], "pat", "Audit")
    with store.connect(write=True) as db:
        db.execute("UPDATE reference_rulesets SET engine_version='unavailable'")
    assert store.reference.replay(recorded["id"])["status"] == "unreproducible"


def test_invalid_pack_has_explicit_diagnostic_and_keeps_legacy_quote(client):
    store = client.app.state.store
    card = create(client)
    store.reference.ruleset = None
    store.reference.error = "Invalid rules"
    result = client.get(f"/api/copies/{card['id']}").json()["reference_resolution"]
    assert result["diagnostic"] == "Invalid rules" and not result["pricing_eligible"]


def test_unsaved_mark_change_does_not_reuse_previous_mark_attestation(
    client, reference
):
    card = create(
        client,
        catalog_id="synthetic-1",
        language="fr",
        number="1/1",
        identification_status="confirmed",
        finish="holo",
        stamp_state="absent",
        variant_confirmed=True,
    )
    store = client.app.state.store
    install_fixture_reference(store, reference)
    before = state(store, card["id"])
    preview = client.post(
        f"/api/copies/{card['id']}/variant-preview",
        json={"stamp_state": "present", "stamp": "Test"},
    ).json()["reference_resolution"]
    assert preview["market_status"] == "unobserved" and not preview["pricing_eligible"]
    assert state(store, card["id"]) == before


def test_replayed_decision_reports_missing_source_content(client, reference):
    card = create(
        client,
        catalog_id="synthetic-1",
        language="fr",
        number="1/1",
        identification_status="confirmed",
        stamp_state="absent",
    )
    store = client.app.state.store
    install_fixture_reference(store, reference)
    recorded = store.reference.record(card["id"], card["version"], "pat", "Audit")
    for path in (store.root / "reference_documents").iterdir():
        path.unlink()
    replay = store.reference.replay(recorded["id"])
    assert replay["status"] == "reproduced" and replay["proof_status"] == "unavailable"
    assert replay["missing_documents"]
    assert not store.reference.decision(state(store, card["id"]))["pricing_eligible"]


def test_schema11_observations_only_migrates_and_restores_without_losing_copy(
    client, tmp_path
):
    card = create(client, finish="non_holo", stamp_state="absent")
    store = client.app.state.store
    before = state(store, card["id"])
    with store.connect(write=True) as db:
        db.execute("DROP TABLE reference_quote_events")
        db.execute("DROP TABLE reference_quotes")
        db.execute("PRAGMA user_version=11")
    archive = tmp_path / "schema11.zip"
    backup(store, archive)
    restore_backup(archive, tmp_path / "restored-schema11")
    restored = Store(tmp_path / "restored-schema11")
    assert state(restored, card["id"]) == before
    assert restored.summary()["copies"] == 1
    with restored.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 12
        assert db.execute("SELECT count(*) FROM reference_quotes").fetchone()[0] == 0


def test_schema11_with_bound_journal_migrates_without_recreating_it(client):
    card = create(client)
    store = client.app.state.store
    before = state(store, card["id"])
    with store.connect(write=True) as db:
        db.execute("PRAGMA user_version=11")
    migrated = Store(store.root)
    assert state(migrated, card["id"]) == before
    with migrated.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 12


def test_readers_cannot_record_decisions_or_disputes(client):
    card = create(client)
    client.post(
        "/api/users",
        json={
            "username": "reader",
            "password": "Collection-test-2026!",
            "role": "reader",
        },
    )
    client.post("/api/logout")
    client.post(
        "/api/login", json={"username": "reader", "password": "Collection-test-2026!"}
    )
    for action in ("reference-decision", "reference-dispute"):
        response = client.post(
            f"/api/copies/{card['id']}/{action}",
            json={
                "expected_version": card["version"],
                "reason": "Reader request",
                **({"active": True} if action.endswith("dispute") else {}),
            },
        )
        assert response.status_code == 403
