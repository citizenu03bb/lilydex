"""Tests for bulk card moves across albums and pages (preview, collisions, atomic apply, undo)."""

import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from pokeprice.inventory import SCHEMA_VERSION, Conflict, Store
from pokeprice.webapp import create_app


@pytest.fixture()
def env(tmp_path):
    root = tmp_path / "inventory"
    app = create_app(root)
    with TestClient(app) as client:
        setup = client.post(
            "/api/setup",
            json={"username": "pat", "password": "correct-horse-battery"},
        )
        assert setup.status_code == 200
        origin = client.post("/api/albums", json={"name": "Classeur Wizards"}).json()
        target = client.post("/api/albums", json={"name": "Classeur Platine"}).json()
        yield client, app.state.store, origin, target


def make_card(client, album_id, *, name="Pikachu", number="58/102", page=1, position=1):
    res = client.post(
        "/api/copies",
        json={
            "name": name,
            "set_name": "Set de Base",
            "number": number,
            "language": "fr",
            "identification_status": "confirmed",
            "condition": "NM",
            "condition_confirmed": True,
            "foil": False,
            "finish": "non_holo",
            "variant_confirmed": True,
            "album_id": album_id,
            "page": page,
            "position": position,
            "reason": "Création test",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_auto_placement_uses_first_free_slots_and_wraps_pages(env):
    client, _store, origin, target = env
    # Occupy p.1 #1 and p.1 #3 in the target album (with 3 slots per page).
    make_card(client, target["id"], name=" Occupant 1", number="1/10", page=1, position=1)
    make_card(client, target["id"], name="Occupant 3", number="3/10", page=1, position=3)

    c1 = make_card(client, origin["id"], name=" Bulbizarre", number="44/102", page=1, position=1)
    c2 = make_card(client, origin["id"], name="Salamèche", number="46/102", page=1, position=2)
    c3 = make_card(client, origin["id"], name="Carapuce", number="63/102", page=1, position=3)

    preview = client.post(
        "/api/move-batches",
        json={
            "copies": [{"id": c["id"], "expected_version": c["version"]} for c in (c1, c2, c3)],
            "album_id": target["id"],
            "mode": "auto",
            "slots": 3,
            "reason": "Regroupement starters",
        },
    )
    assert preview.status_code == 201, preview.text
    job = preview.json()
    assert job["status"] == "preview"
    assert job["data"]["has_collisions"] is False
    assert job["data"]["collisions_count"] == 0
    slots = [(i["to_page"], i["to_position"]) for i in job["data"]["items"]]
    assert slots == [(1, 2), (2, 1), (2, 2)]


def test_from_slot_preview_flags_collisions_and_apply_refuses_occupied_slots(env):
    client, store, origin, target = env
    occupant = make_card(client, target["id"], name="Évoli", number="55/64", page=2, position=2)
    c1 = make_card(client, origin["id"], name="Pikachu", number="58/102", page=1, position=1)
    c2 = make_card(client, origin["id"], name="Raichu", number="14/102", page=1, position=2)

    preview = client.post(
        "/api/move-batches",
        json={
            "copies": [{"id": c["id"], "expected_version": c["version"]} for c in (c1, c2)],
            "album_id": target["id"],
            "mode": "from_slot",
            "start_page": 2,
            "start_position": 1,
            "slots": 9,
            "reason": "Déplacement vers page 2",
        },
    )
    assert preview.status_code == 201, preview.text
    job = preview.json()
    assert job["data"]["has_collisions"] is True
    assert job["data"]["collisions_count"] == 1
    first_item, second_item = job["data"]["items"]
    assert first_item["collision"] is False
    assert (first_item["to_page"], first_item["to_position"]) == (2, 1)
    assert second_item["collision"] is True
    assert (second_item["to_page"], second_item["to_position"]) == (2, 2)
    assert second_item["occupied_by"][0]["id"] == occupant["id"]
    assert second_item["occupied_by"][0]["name"] == "Évoli"

    # Applying a batch with a slot collision is refused and writes nothing.
    applied = client.post(f"/api/move-batches/{job['id']}/apply")
    assert applied.status_code == 409
    assert "Évoli" in applied.json()["detail"]
    assert client.get(f"/api/copies/{c1['id']}").json()["album_id"] == origin["id"]
    assert client.get(f"/api/copies/{c2['id']}").json()["album_id"] == origin["id"]
    assert not list((store.root.parent / "backups").glob("before-move-batch-*.sqlite3"))


def test_live_collision_created_after_preview_is_refused_on_apply(env):
    client, _store, origin, target = env
    c1 = make_card(client, origin["id"], name="Pikachu", number="58/102", page=1, position=1)
    job = client.post(
        "/api/move-batches",
        json={
            "copies": [{"id": c1["id"], "expected_version": c1["version"]}],
            "album_id": target["id"],
            "mode": "from_slot",
            "start_page": 3,
            "start_position": 4,
            "reason": "Test collision concurrente",
        },
    ).json()
    assert job["data"]["has_collisions"] is False

    # Another card takes slot (3, 4) before apply.
    make_card(client, target["id"], name="Ronflex", number="11/64", page=3, position=4)
    applied = client.post(f"/api/move-batches/{job['id']}/apply")
    assert applied.status_code == 409
    assert "Ronflex" in applied.json()["detail"]
    assert client.get(f"/api/copies/{c1['id']}").json()["album_id"] == origin["id"]


def test_apply_and_undo_record_per_card_history_and_preserve_confirmations(env):
    client, store, origin, target = env
    c1 = make_card(client, origin["id"], name="Pikachu", number="58/102", page=1, position=1)
    c2 = make_card(client, origin["id"], name="Mewtwo", number="10/102", page=1, position=5)

    job = client.post(
        "/api/move-batches",
        json={
            "copies": [{"id": c["id"], "expected_version": c["version"]} for c in (c1, c2)],
            "album_id": target["id"],
            "mode": "auto",
            "reason": "Classement dans Platine",
        },
    ).json()

    applied = client.post(f"/api/move-batches/{job['id']}/apply")
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    # The database alone, as it was before the move: no photo archive.
    (copy,) = (store.root.parent / "backups").glob("before-move-batch-*.sqlite3")
    assert not list((store.root.parent / "backups").glob("*.zip"))
    assert copy.stat().st_mode & 0o777 == 0o600
    with closing(sqlite3.connect(copy)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT album_id FROM copies WHERE id=?", (c1["id"],)).fetchone() == (
            origin["id"],
        )

    after1 = client.get(f"/api/copies/{c1['id']}").json()
    after2 = client.get(f"/api/copies/{c2['id']}").json()
    assert (after1["album_id"], after1["page"], after1["position"]) == (target["id"], 1, 1)
    assert (after2["album_id"], after2["page"], after2["position"]) == (target["id"], 1, 2)
    assert after1["version"] == 2 and after2["version"] == 2
    assert after1["condition_confirmed"] == 1 and after1["variant_confirmed"] == 1
    assert any(
        e["kind"] == "correction" and e["reason"] == "Classement dans Platine"
        for e in after1["history"]
    )

    # Cannot apply twice.
    assert client.post(f"/api/move-batches/{job['id']}/apply").status_code == 409

    # Undo restores the whole batch atomically.
    undone = client.post(f"/api/move-batches/{job['id']}/undo")
    assert undone.status_code == 200, undone.text
    assert undone.json()["status"] == "undone"

    restored1 = client.get(f"/api/copies/{c1['id']}").json()
    restored2 = client.get(f"/api/copies/{c2['id']}").json()
    assert (restored1["album_id"], restored1["page"], restored1["position"]) == (origin["id"], 1, 1)
    assert (restored2["album_id"], restored2["page"], restored2["position"]) == (origin["id"], 1, 5)
    assert restored1["version"] == 3 and restored2["version"] == 3
    assert any(
        e["kind"] == "correction" and "Annulation du déplacement" in e["reason"]
        for e in restored1["history"]
    )
    assert client.post(f"/api/move-batches/{job['id']}/undo").status_code == 409


def test_version_conflict_in_middle_of_batch_writes_nothing(env, monkeypatch):
    client, store, origin, target = env
    c1 = make_card(client, origin["id"], name="Carte 1", number="1/10", page=1, position=1)
    c2 = make_card(client, origin["id"], name="Carte 2", number="2/10", page=1, position=2)
    c3 = make_card(client, origin["id"], name="Carte 3", number="3/10", page=1, position=3)

    job = client.post(
        "/api/move-batches",
        json={
            "copies": [{"id": c["id"], "expected_version": c["version"]} for c in (c1, c2, c3)],
            "album_id": target["id"],
            "mode": "auto",
            "reason": "Déplacement atomique",
        },
    ).json()

    # Case 1: middle card modified before apply is called.
    store.patch(c2["id"], {"notes": "Modifiée ailleurs"}, 1, "pat", "Concurrence")
    res = client.post(f"/api/move-batches/{job['id']}/apply")
    assert res.status_code == 409
    assert not list((store.root.parent / "backups").glob("before-move-batch-*.sqlite3"))
    for original, expected_ver in ((c1, 1), (c2, 2), (c3, 1)):
        current = client.get(f"/api/copies/{original['id']}").json()
        assert current["version"] == expected_ver
        assert current["album_id"] == origin["id"]
        assert current["page"] == original["page"]
        assert current["position"] == original["position"]

    # Case 2: mid-transaction conflict after the first card has already been patched on db.
    job2 = client.post(
        "/api/move-batches",
        json={
            "copies": [
                {"id": c1["id"], "expected_version": 1},
                {"id": c2["id"], "expected_version": 2},
                {"id": c3["id"], "expected_version": 1},
            ],
            "album_id": target["id"],
            "mode": "auto",
            "reason": "Conflit au milieu de la transaction",
        },
    ).json()

    real_patch = store.patch
    calls = []

    def conflict_on_second(copy_id, changes, version, actor, reason, **kwargs):
        calls.append(copy_id)
        if len(calls) == 2:
            # First card was already updated on _db; now the second card conflicts.
            raise Conflict("La fiche du milieu a changé pendant la transaction.")
        return real_patch(copy_id, changes, version, actor, reason, **kwargs)

    monkeypatch.setattr(store, "patch", conflict_on_second)
    res2 = client.post(f"/api/move-batches/{job2['id']}/apply")
    assert res2.status_code == 409
    assert calls == [c1["id"], c2["id"]]

    # Verify the first card's update and event were rolled back.
    after_c1 = client.get(f"/api/copies/{c1['id']}").json()
    assert after_c1["version"] == 1
    assert (after_c1["album_id"], after_c1["page"], after_c1["position"]) == (origin["id"], 1, 1)
    assert not any(e["reason"] == "Conflit au milieu de la transaction" for e in after_c1["history"])
    assert client.get(f"/api/move-batches/{job2['id']}").json()["status"] == "preview"


def test_undo_conflict_rolls_back_all_if_any_card_changed_since_move(env):
    client, store, origin, target = env
    c1 = make_card(client, origin["id"], name="Carte 1", number="1/10", page=1, position=1)
    c2 = make_card(client, origin["id"], name="Carte 2", number="2/10", page=1, position=2)

    job = client.post(
        "/api/move-batches",
        json={
            "copies": [{"id": c["id"], "expected_version": c["version"]} for c in (c1, c2)],
            "album_id": target["id"],
            "mode": "auto",
            "reason": "Déplacement avant édition",
        },
    ).json()
    assert client.post(f"/api/move-batches/{job['id']}/apply").status_code == 200

    # Edit the second card after the move: undo must refuse and keep the first card in target.
    store.patch(c2["id"], {"notes": "Note ajoutée après déplacement"}, 2, "pat", "Note")
    undone = client.post(f"/api/move-batches/{job['id']}/undo")
    assert undone.status_code == 409
    assert client.get(f"/api/copies/{c1['id']}").json()["album_id"] == target["id"]
    assert client.get(f"/api/copies/{c2['id']}").json()["album_id"] == target["id"]


def test_reserved_sold_and_active_lot_cards_are_refused(env):
    client, _store, origin, target = env
    c_free = make_card(client, origin["id"], name="Libre", number="1/10", page=1, position=1)
    c_lot = make_card(client, origin["id"], name="En lot", number="2/10", page=1, position=2)

    # Create a draft sale lot containing c_lot.
    sale = client.post(
        "/api/sales",
        json={
            "title": "Lot Pikachu",
            "copy_ids": [c_lot["id"]],
            "amount_eur": "5.00",
        },
    )
    assert sale.status_code == 201, sale.text
    sale_id = sale.json()["id"]

    # 1. Draft lot card is refused at preview.
    preview_draft = client.post(
        "/api/move-batches",
        json={
            "copies": [
                {"id": c_free["id"], "expected_version": c_free["version"]},
                {"id": c_lot["id"], "expected_version": c_lot["version"]},
            ],
            "album_id": target["id"],
        },
    )
    assert preview_draft.status_code == 409
    assert "Lot Pikachu" in preview_draft.json()["detail"]

    # 2. Reserve the lot: c_lot becomes stock_state='reserved'.
    reserved = client.patch(
        f"/api/sales/{sale_id}",
        json={
            "expected_version": 1,
            "status": "reserved",
            "reason": "Réservation client",
        },
    )
    assert reserved.status_code == 200
    c_lot_reserved = client.get(f"/api/copies/{c_lot['id']}").json()
    assert c_lot_reserved["stock_state"] == "reserved"

    preview_reserved = client.post(
        "/api/move-batches",
        json={
            "copies": [{"id": c_lot["id"], "expected_version": c_lot_reserved["version"]}],
            "album_id": target["id"],
        },
    )
    assert preview_reserved.status_code == 409
    assert "réservé" in preview_reserved.json()["detail"]

    # 3. Cancel the lot: c_lot returns to available and can now be moved.
    cancelled = client.patch(
        f"/api/sales/{sale_id}",
        json={
            "expected_version": reserved.json()["version"],
            "status": "cancelled",
            "reason": "Annulation client",
        },
    )
    assert cancelled.status_code == 200
    c_lot_available = client.get(f"/api/copies/{c_lot['id']}").json()
    assert c_lot_available["stock_state"] == "available"

    preview_ok = client.post(
        "/api/move-batches",
        json={
            "copies": [{"id": c_lot["id"], "expected_version": c_lot_available["version"]}],
            "album_id": target["id"],
        },
    )
    assert preview_ok.status_code == 201
    assert client.post(f"/api/move-batches/{preview_ok.json()['id']}/apply").status_code == 200

    # 4. If a card becomes reserved between preview and apply, apply refuses with 409.
    c_race = make_card(client, origin["id"], name="Course", number="3/10", page=1, position=3)
    job_race = client.post(
        "/api/move-batches",
        json={
            "copies": [{"id": c_race["id"], "expected_version": c_race["version"]}],
            "album_id": target["id"],
        },
    ).json()
    client.post(
        "/api/sales",
        json={"title": "Lot concurrent", "copy_ids": [c_race["id"]], "amount_eur": "5.00"},
    )
    applied_race = client.post(f"/api/move-batches/{job_race['id']}/apply")
    assert applied_race.status_code == 409
    assert "Lot concurrent" in applied_race.json()["detail"]


def test_sold_card_is_refused(env):
    client, _store, origin, target = env
    c_sold = make_card(client, origin["id"], name="Dracaufeu", number="4/102", page=1, position=1)
    sale_id = client.post(
        "/api/sales",
        json={"title": "Vente Dracaufeu", "copy_ids": [c_sold["id"]], "amount_eur": "150.00"},
    ).json()["id"]
    sale = client.patch(
        f"/api/sales/{sale_id}",
        json={"expected_version": 1, "status": "reserved", "reason": "Réservé"},
    ).json()
    client.patch(
        f"/api/sales/{sale_id}",
        json={"expected_version": sale["version"], "status": "sold", "reason": "Vendu"},
    )
    card = client.get(f"/api/copies/{c_sold['id']}").json()
    assert card["stock_state"] == "sold"

    res = client.post(
        "/api/move-batches",
        json={
            "copies": [{"id": card["id"], "expected_version": card["version"]}],
            "album_id": target["id"],
        },
    )
    assert res.status_code == 409
    assert "vendu" in res.json()["detail"]


def test_deleted_card_is_refused(env):
    client, store, origin, target = env
    c_del = make_card(client, origin["id"], name="Supprimée", number="9/10", page=1, position=1)
    deleted = store.set_deleted(c_del["id"], True, c_del["version"], "pat", "Mise à la corbeille")
    res = client.post(
        "/api/move-batches",
        json={
            "copies": [{"id": deleted["id"], "expected_version": deleted["version"]}],
            "album_id": target["id"],
        },
    )
    assert res.status_code == 409
    assert "corbeille" in res.json()["detail"]


def test_same_album_page_move_vacates_own_slots(env):
    client, _store, origin, _target = env
    c1 = make_card(client, origin["id"], name="P1", number="1/10", page=1, position=1)
    c2 = make_card(client, origin["id"], name="P2", number="2/10", page=1, position=2)

    # Shift c1 and c2 by one pocket on the same page (to positions 2 and 3):
    # slot (1, 2) was occupied by c2, which is itself moving to (1, 3), so no collision!
    job = client.post(
        "/api/move-batches",
        json={
            "copies": [{"id": c["id"], "expected_version": c["version"]} for c in (c1, c2)],
            "album_id": origin["id"],
            "mode": "from_slot",
            "start_page": 1,
            "start_position": 2,
            "reason": "Décalage d’une case",
        },
    ).json()
    assert job["data"]["has_collisions"] is False
    assert client.post(f"/api/move-batches/{job['id']}/apply").status_code == 200
    assert client.get(f"/api/copies/{c1['id']}").json()["position"] == 2
    assert client.get(f"/api/copies/{c2['id']}").json()["position"] == 3


def test_storefront_single_card_is_signaled_and_multi_card_lot_is_refused(env):
    client, _store, origin, target = env
    c1 = make_card(client, origin["id"], name="Unitaire", number="1/10", page=1, position=1)
    c2 = make_card(client, origin["id"], name="Lot A", number="2/10", page=1, position=2)
    c3 = make_card(client, origin["id"], name="Lot B", number="3/10", page=1, position=3)

    # Publish c1 individually in storefront.
    pub_single = client.post(
        "/api/listings",
        json={"copy_ids": [c1["id"]], "price_eur": "2.00"},
    )
    assert pub_single.status_code == 201, pub_single.text

    # Publish c2 and c3 as an online multi-card lot.
    pub_lot = client.post(
        "/api/listings",
        json={"copy_ids": [c2["id"], c3["id"]], "lot": True, "title": "Duo Base", "price_eur": "3.00"},
    )
    assert pub_lot.status_code == 201, pub_lot.text

    # Single-card storefront listing is allowed and flagged with published=True.
    preview_single = client.post(
        "/api/move-batches",
        json={
            "copies": [{"id": c1["id"], "expected_version": c1["version"]}],
            "album_id": target["id"],
        },
    )
    assert preview_single.status_code == 201
    assert preview_single.json()["data"]["items"][0]["published"] is True

    # Multi-card storefront lot is refused.
    preview_lot = client.post(
        "/api/move-batches",
        json={
            "copies": [{"id": c2["id"], "expected_version": c2["version"]}],
            "album_id": target["id"],
        },
    )
    assert preview_lot.status_code == 409
    assert "Duo Base" in preview_lot.json()["detail"]


def test_undo_refuses_when_origin_slot_was_taken_meanwhile(env):
    client, _store, origin, target = env
    c1 = make_card(client, origin["id"], name="Voyageuse", number="1/10", page=1, position=1)
    job = client.post(
        "/api/move-batches",
        json={
            "copies": [{"id": c1["id"], "expected_version": c1["version"]}],
            "album_id": target["id"],
        },
    ).json()
    assert client.post(f"/api/move-batches/{job['id']}/apply").status_code == 200

    # Another card now takes origin p.1 #1.
    make_card(client, origin["id"], name="Intruse", number="9/10", page=1, position=1)
    undone = client.post(f"/api/move-batches/{job['id']}/undo")
    assert undone.status_code == 409
    assert "Intruse" in undone.json()["detail"]
    assert client.get(f"/api/copies/{c1['id']}").json()["album_id"] == target["id"]


def test_schema_23_migration_creates_move_batches_table(tmp_path):
    root = tmp_path / "inventory"
    store = Store(root)
    with closing(sqlite3.connect(store.database)) as db:
        db.executescript("DROP TABLE move_batches; PRAGMA user_version=22;")
    reopened = Store(root)
    with reopened.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION >= 23
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='move_batches'"
        ).fetchone()
    assert list((tmp_path / "backups").glob(f"before-schema{SCHEMA_VERSION}-from22-*.sqlite3"))
