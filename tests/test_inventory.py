import shutil
import hashlib
import io
import json
import os
import re
import subprocess
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from test_library import inputs

from pokeprice.inventory import Conflict, Store
from pokeprice.inventory_backup import backup, export_data, export_html, restore_backup
from pokeprice.inventory_import import import_collection
from pokeprice.webapp import UserCreate, add_user, create_app, password_hash, password_valid


@pytest.fixture
def inventory(tmp_path):
    manifest = inputs(tmp_path)
    store = Store(tmp_path / "inventory")
    result = import_collection(store, manifest)
    return store, manifest, result


@pytest.fixture
def client(inventory):
    store, _, _ = inventory
    with TestClient(create_app(store.root)) as client:
        r = client.post(
            "/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}
        )
        assert r.status_code == 200
        yield client


def test_import_is_idempotent_and_keeps_manual_edits_and_raw_source(inventory):
    store, manifest, result = inventory
    assert result["created"] == 7
    before = store.listing(limit=20)["items"][0]
    edited = store.patch(
        before["id"],
        {"number": "58/127", "album_id": "b", "page": 3, "notes": "Correction humaine"},
        1,
        "pat",
        "Lecture photo",
    )
    assert (
        edited["id"] == before["id"]
        and edited["reference_cents"] is None
        and edited["catalog_id"] is None
    )
    assert import_collection(store, manifest)["unchanged"] == 7
    with store.connect() as db:
        after = store.get(db, before["id"])
        raw = json.loads(
            db.execute(
                "SELECT raw_json FROM sources WHERE copy_id=?", (before["id"],)
            ).fetchone()[0]
        )
    assert (
        after["number"] == "58/127"
        and after["page"] == 3
        and raw["Numero_Officiel"] == before["number"]
    )
    frame = pd.read_csv(manifest.parent / "a.csv")
    frame.loc[0, "OCR_Name"] = "Source changed"
    frame.to_csv(manifest.parent / "a.csv", index=False)
    changed = import_collection(store, manifest)
    assert len(changed["source_changed"]) == 1 and changed["created"] == 0
    with pytest.raises(Conflict):
        store.patch(before["id"], {"notes": "stale"}, 1, "pat", "Concurrent")


def test_unresolved_candidate_prices_not_trusted_and_photos_distinct(inventory):
    store, _, _ = inventory
    rows = store.listing(limit=20)["items"]
    unresolved = next(r for r in rows if r["identification_status"] == "unresolved")
    assert unresolved["reference_cents"] is None and unresolved["catalog_id"] is None
    twins = [r for r in rows if r["name"] == "Zarbi L" and r["language"] == "fr"]
    assert len(twins) == 3 and len({r["id"] for r in twins}) == 3
    # Same crop bytes may share content storage, but a new photo belongs to one copy only.
    photo = store.save_photo(b"new-content-test")
    changed = store.patch(
        twins[0]["id"], {"photo": photo}, 1, "pat", "Photo propre à cet exemplaire"
    )
    assert changed["photo"] == photo
    assert (
        next(r for r in store.listing(limit=20)["items"] if r["id"] == twins[1]["id"])[
            "photo"
        ]
        != photo
    )


@pytest.mark.parametrize("endpoint", ["/api/copies", "/api/editions"])
def test_binder_sort_orders_locations_before_filtering_and_pagination(
    client, inventory, endpoint
):
    store, _, _ = inventory
    cards = {(c["album_id"], c["position"]): c for c in store.listing()["items"]}
    locations = {
        ("a", 1): (1, 1),
        ("a", 2): (10, 2),
        ("a", 3): (2, 10),
        ("a", 4): (2, 2),
        ("b", 1): (10, 1),
        ("b", 2): (2, 10),
        ("b", 3): (2, 2),
    }
    for key, (page, position) in locations.items():
        card = cards[key]
        store.patch(
            card["id"],
            {"page": page, "position": position},
            card["version"],
            "pat",
            "Emplacement vérifié",
        )
    with store.connect() as db:
        db.execute("UPDATE albums SET name='z Album' WHERE id='a'")
        db.execute("UPDATE albums SET name='A album' WHERE id='b'")

    def ids(params):
        response = client.get(endpoint, params=params)
        assert response.status_code == 200
        entries = response.json()["items"]
        if endpoint == "/api/editions":
            return [[c["id"] for c in g["copies"]] for g in entries]
        return [c["id"] for c in entries]

    def expected(keys):
        if endpoint == "/api/editions":
            groups = {}
            for key in keys:
                card = cards[key]
                groups.setdefault(card["edition_id"], []).append(card["id"])
            return list(groups.values())
        return [cards[key]["id"] for key in keys]

    binder = [("b", 3), ("b", 2), ("b", 1), ("a", 1), ("a", 4), ("a", 3), ("a", 2)]
    by_name = [("b", 3), ("b", 2), ("a", 1), ("a", 2), ("b", 1), ("a", 4), ("a", 3)]
    assert ids({}) == expected(by_name)
    assert ids({"sort": "name"}) == expected(by_name)
    assert ids({"sort": "binder"}) == expected(binder)
    assert ids({"sort": "binder", "offset": 1, "limit": 2}) == expected(binder)[1:3]
    assert ids({"sort": "binder", "album": "a"}) == expected(binder[3:])
    assert ids(
        {
            "sort": "binder",
            "q": "zarbi",
            "stock": "available",
            "status": "confirmed",
            "variant": "standard",
        }
    ) == expected([("b", 2), ("b", 1), ("a", 1), ("a", 2)])
    assert client.get(endpoint, params={"sort": "invalid"}).status_code == 422

    # Two albums with the same name must still be traversed separately.
    with store.connect() as db:
        db.execute("UPDATE albums SET name='Album'")
    assert ids({"sort": "binder"}) == expected(binder[3:] + binder[:3])


def test_roles_private_photos_csrf_and_unknown_fields(client):
    assert (
        client.post(
            "/api/setup",
            json={"username": "other", "password": "Collection-test-2026!"},
        ).status_code
        == 409
    )
    card = client.get("/api/copies").json()["items"][0]
    assert client.get(f"/api/copies/{card['id']}/photo").status_code == 200
    assert (
        client.post(
            "/api/users",
            json={
                "username": "reader",
                "password": "Collection-reader-2026!",
                "role": "reader",
            },
        ).status_code
        == 201
    )
    assert (
        client.patch(
            "/api/copies/" + card["id"],
            json={"expected_version": 1, "reason": "x", "notes": "cross site"},
            headers={"Origin": "https://outside.example"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            "/api/copies/" + card["id"],
            json={"expected_version": 1, "reason": "x", "stock_state": "sold"},
        ).status_code
        == 422
    )
    client.post("/api/logout")
    assert client.get("/api/copies").status_code == 401
    assert client.get(f"/api/copies/{card['id']}/photo").status_code == 401
    assert client.get("/api/export/json").status_code == 401
    assert (
        client.post(
            "/api/login",
            json={"username": "reader", "password": "Collection-reader-2026!"},
        ).status_code
        == 200
    )
    assert client.get("/api/copies").status_code == 200
    assert (
        client.patch(
            "/api/copies/" + card["id"],
            json={"expected_version": 1, "reason": "x", "notes": "not allowed"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/sales",
            json={"title": "lot", "amount_eur": 1, "copy_ids": [card["id"]]},
        ).status_code
        == 403
    )
    assert client.get("/api/backup").status_code == 403


def test_correction_photo_and_manual_acquisition(client):
    card = client.get("/api/copies").json()["items"][0]
    r = client.patch(
        "/api/copies/" + card["id"],
        json={
            "expected_version": 1,
            "reason": "Numéro revérifié",
            "number": "51/127",
            "identification_status": "confirmed",
        },
    )
    assert r.status_code == 200 and r.json()["version"] == 2
    assert r.json()["reference_cents"] is None
    assert (
        client.patch(
            "/api/copies/" + card["id"],
            json={"expected_version": 1, "reason": "ancienne fiche", "notes": "stale"},
        ).status_code
        == 409
    )
    data = client.get("/api/copies/" + card["id"]).json()
    assert (
        len(data["history"]) == 2
        and data["source"]["data"]["Numero_Officiel"] == card["number"]
    )
    assert (
        client.patch(
            "/api/copies/" + card["id"],
            json={
                "expected_version": 2,
                "reason": "Cotation",
                "reference_price_eur": 2,
            },
        ).status_code
        == 422
    )
    r = client.patch(
        "/api/copies/" + card["id"],
        json={
            "expected_version": 2,
            "reason": "Cotation",
            "reference_price_eur": 2,
            "price_source": "Cardmarket / trend",
        },
    )
    assert r.json()["reference_cents"] == 200
    output = io.BytesIO()
    Image.new("RGB", (50, 80), "red").save(output, format="PNG")
    assert (
        client.put(
            "/api/copies/" + card["id"] + "/photo?version=3", content=output.getvalue()
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/copies/" + card["id"] + "/photo?version=4", content=b"bad-image"
        ).status_code
        == 422
    )
    new = client.post(
        "/api/copies",
        json={
            "name": "Carte manuelle",
            "album_id": "a",
            "page": 5,
            "position": 3,
            "reason": "Acquisition",
        },
    )
    assert new.status_code == 201
    assert (
        new.json()["identification_status"] == "review"
        and new.json()["reference_cents"] is None
    )
    assert client.get("/api/summary").json()["copies"] == 8


def test_revoke_access_and_keep_an_active_admin(client, inventory):
    admin = client.get("/api/session").json()
    assert (
        client.patch(
            "/api/users/" + admin["id"], json={"role": "reader", "disabled": True}
        ).status_code
        == 409
    )
    reader = client.post(
        "/api/users",
        json={
            "username": "visitor",
            "password": "Collection-visitor-2026!",
            "role": "reader",
        },
    ).json()
    with TestClient(create_app(inventory[0].root)) as visitor:
        assert (
            visitor.post(
                "/api/login",
                json={"username": "visitor", "password": "Collection-visitor-2026!"},
            ).status_code
            == 200
        )
        assert visitor.get("/api/copies").status_code == 200
        assert (
            client.patch(
                "/api/users/" + reader["id"], json={"role": "reader", "disabled": True}
            ).status_code
            == 200
        )
        assert visitor.get("/api/copies").status_code == 401
        assert (
            visitor.post(
                "/api/login",
                json={"username": "visitor", "password": "Collection-visitor-2026!"},
            ).status_code
            == 401
        )


def test_bootstrap_and_login_throttling(tmp_path):
    with pytest.raises(ValueError, match="administrateur"):
        create_app(tmp_path / "https", secure_cookie=True)
    with TestClient(create_app(tmp_path / "throttle")) as client:
        for _ in range(5):
            assert (
                client.post(
                    "/api/login",
                    json={
                        "username": "unknown",
                        "password": "Collection-invalid-2026!",
                    },
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/api/login",
                json={"username": "other", "password": "Collection-invalid-2026!"},
            ).status_code
            == 429
        )


def test_login_success_elsewhere_keeps_failures_against_another_account(tmp_path):
    owner = {"username": "owner", "password": "Collection-test-2026!"}
    helper = {"username": "helper", "password": "Collection-helper-2026!"}
    wrong = {"username": "owner", "password": "Collection-wrong-2026!"}
    with TestClient(create_app(tmp_path / "throttle")) as client:
        assert client.post("/api/setup", json=owner).status_code == 200
        assert client.post("/api/users", json=helper).status_code == 201
        statuses = [client.post("/api/login", json=wrong).status_code for _ in range(4)]
        statuses.append(client.post("/api/login", json=helper).status_code)
        statuses += [client.post("/api/login", json=wrong).status_code for _ in range(2)]
        # Logging into one's own account must not reset guesses aimed at the owner.
        assert statuses == [401] * 4 + [200, 401, 429]
    with TestClient(create_app(tmp_path / "typos")) as client:
        assert client.post("/api/setup", json=owner).status_code == 200
        for _ in range(4):
            assert client.post("/api/login", json=wrong).status_code == 401
        assert client.post("/api/login", json=owner).status_code == 200
        # The owner's own typos are forgiven once the right password is given.
        for _ in range(4):
            assert client.post("/api/login", json=wrong).status_code == 401


@pytest.mark.real_scrypt
def test_new_password_hashes_meet_owasp_scrypt_minimum():
    encoded = password_hash("Collection-test-2026!")
    algorithm, params, salt, key = encoded.split("$")
    cost = {k: int(v) for k, v in (item.split("=") for item in params.split(","))}
    # OWASP Password Storage Cheat Sheet: equivalent minimum scrypt settings.
    owasp = {(2**17, 8, 1), (2**16, 8, 2), (2**15, 8, 3), (2**14, 8, 5), (2**13, 8, 10)}
    assert algorithm == "scrypt" and (cost["n"], cost["r"], cost["p"]) in owasp
    assert len(bytes.fromhex(salt)) == 16 and len(bytes.fromhex(key)) == 32
    assert password_valid("Collection-test-2026!", encoded)
    assert not password_valid("Collection-wrong-2026!", encoded)


def test_legacy_password_hash_still_works_and_is_strengthened_at_login(tmp_path):
    owner = {"username": "owner", "password": "Collection-test-2026!"}
    salt = bytes(range(16))
    key = hashlib.scrypt(owner["password"].encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    legacy = salt.hex() + ":" + key.hex()

    def stored():
        with client.app.state.store.connect() as db:
            return db.execute("SELECT password_hash FROM users WHERE username='owner'").fetchone()[0]

    with TestClient(create_app(tmp_path / "legacy")) as client:
        assert client.post("/api/setup", json=owner).status_code == 200
        with client.app.state.store.connect(write=True) as db:
            db.execute("UPDATE users SET password_hash=? WHERE username='owner'", (legacy,))
        wrong = {**owner, "password": "Collection-wrong-2026!"}
        assert client.post("/api/login", json=wrong).status_code == 401
        assert stored() == legacy
        assert client.post("/api/login", json=owner).status_code == 200
        assert stored() != legacy and stored().startswith("scrypt$")
        assert client.post("/api/login", json=owner).status_code == 200


SIGNUP = {
    "email": "early@example.org",
    "display_name": "Tôt",
    "password": "Client-test-2026!",
    "consent": True,
}


def test_signups_wait_for_the_first_admin_and_cannot_block_setup(tmp_path):
    owner = {"username": "owner", "password": "Collection-test-2026!"}
    with TestClient(create_app(tmp_path / "blank")) as client:
        assert client.post("/api/public/signup", json=SIGNUP).status_code == 409
        assert client.get("/api/setup").json() == {"required": True}
        assert client.post("/api/setup", json=owner).status_code == 200
        assert client.post("/api/public/signup", json=SIGNUP).status_code == 202
    # A client row left by an older version does not count as an installed shop.
    store = Store(tmp_path / "older")
    with store.connect(write=True) as db:
        db.execute(
            "INSERT INTO users(id,username,password_hash,role,created_at,status) "
            "VALUES('c1','early@example.org','x','client','2026-10-16','pending')"
        )
    with TestClient(create_app(store.root)) as client:
        assert client.get("/api/setup").json() == {"required": True}
        assert client.post("/api/setup", json=owner).status_code == 200


def test_an_instance_open_to_the_network_needs_a_local_admin_first(tmp_path):
    with pytest.raises(ValueError, match="administrateur"):
        create_app(tmp_path / "lan", allowed_hosts=["192.168.1.20"])
    with Store(tmp_path / "lan").connect(write=True) as db:
        add_user(db, UserCreate(username="owner", password="Collection-test-2026!", role="admin"))
    create_app(tmp_path / "lan", allowed_hosts=["192.168.1.20"])
    create_app(tmp_path / "local", allowed_hosts=["127.0.0.1", "localhost"])


def test_backup_archive_is_private_while_it_is_written(inventory, tmp_path, monkeypatch):
    store, _, _ = inventory
    target = tmp_path / "out" / "copy.zip"
    modes = []
    writestr = zipfile.ZipFile.writestr

    def watched(self, name, data, *args, **kwargs):
        modes.append(target.stat().st_mode & 0o777)
        return writestr(self, name, data, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "writestr", watched)
    previous = os.umask(0o022)
    try:
        backup(store, target)
    finally:
        os.umask(previous)
    assert modes and set(modes) == {0o600}


def test_migration_snapshot_is_private_while_it_is_written(inventory):
    store, _, _ = inventory
    folder = store.root.parent / "backups"
    modes = []
    with store.connect() as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]

        class Watched:
            def backup(self, target):
                modes.extend(p.stat().st_mode & 0o777 for p in folder.glob("*.tmp"))
                db.backup(target)

        previous = os.umask(0o022)
        try:
            target = store.snapshot_before_migration(Watched(), version)
        finally:
            os.umask(previous)
    assert modes == [0o600] and target.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "extra, action",
    [([], "backup-server-pull"), (["--push-drive"], "backup-server-drive")],
)
def test_backup_pull_script_delegates_to_the_verified_server_pull(
    tmp_path, extra, action
):
    root = tmp_path / "repo"
    (root / "deploy").mkdir(parents=True)
    script = Path(__file__).resolve().parents[1] / "deploy/oci-pull-backup.sh"
    shutil.copy(script, root / "deploy")
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$(dirname "$0")/args"\n')
    python.chmod(0o755)
    result = subprocess.run(
        ["bash", str(root / "deploy/oci-pull-backup.sh"), "opc@203.0.113.9", *extra],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    args = (python.parent / "args").read_text().split()
    # The laptop collection is never named: the archive comes from the server.
    assert args[:3] == ["-m", "pokeprice.manage", action]
    assert "--data" not in args
    assert args[args.index("--host") + 1] == "opc@203.0.113.9"
    assert not (root / "data/backups").exists()
    bad = subprocess.run(
        ["bash", str(root / "deploy/oci-pull-backup.sh"), "opc@203.0.113.9", "--oops"],
        capture_output=True,
    )
    assert bad.returncode == 1


def test_concurrent_reservations_have_one_winner_and_atomic_lot(inventory):
    store, _, _ = inventory
    ids = [r["id"] for r in store.listing(limit=20)["items"][:2]]
    a = store.create_sale({"title": "A", "amount_cents": 100}, ids, "pat")
    b = store.create_sale({"title": "B", "amount_cents": 100}, [ids[1]], "pat")
    barrier = threading.Barrier(2)

    def reserve(sale_id):
        barrier.wait()
        try:
            store.update_sale(sale_id, {"status": "reserved"}, 1, "pat", "Réservation")
            return sale_id
        except Conflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, [a, b]))
    assert sum(v is not None for v in outcomes) == 1
    winner = next(v for v in outcomes if v)
    with store.connect() as db:
        cards = [store.get(db, i) for i in ids]
        active = db.execute("SELECT copy_id FROM sale_items WHERE active=1").fetchall()
    assert len(active) == (2 if winner == a else 1)
    if winner == b:
        assert cards[0]["stock_state"] == "available" and cards[0]["version"] == 1
    store.update_sale(
        winner,
        {
            "status": "sold",
            "fees_cents": 10,
            "shipping_charged_cents": 50,
            "shipping_cost_cents": 30,
            "packing_cents": 5,
            "paid": True,
        },
        2,
        "pat",
        "Vente payée",
    )
    sale = next(s for s in store.sales() if s["id"] == winner)
    assert sale["net_cents"] == 105
    store.update_sale(
        winner,
        {"status": "returned", "refund_cents": 150},
        3,
        "pat",
        "Retour remboursé",
    )
    assert next(s for s in store.sales() if s["id"] == winner)["net_cents"] == -45
    with store.connect() as db:
        assert all(
            store.get(db, c["id"])["stock_state"] == "available" for c in sale["items"]
        )
    assert not [s for s in store.sales() if s["status"] == "reserved"]


def test_cancelling_a_draft_does_not_release_another_sales_reservation(inventory):
    store, _, _ = inventory
    copy_id = store.listing()["items"][0]["id"]
    a = store.create_sale({"title": "A", "amount_cents": 100}, [copy_id], "pat")
    b = store.create_sale({"title": "B", "amount_cents": 100}, [copy_id], "pat")
    store.update_sale(a, {"status": "reserved"}, 1, "pat", "Réserver")
    store.update_sale(b, {"status": "cancelled"}, 1, "pat", "Annuler le brouillon")
    with store.connect() as db:
        assert store.get(db, copy_id)["stock_state"] == "reserved"
    store.update_sale(a, {"status": "cancelled"}, 2, "pat", "Libérer")
    with store.connect() as db:
        assert store.get(db, copy_id)["stock_state"] == "available"


def test_backup_restores_history_sales_sources_photos_and_invalidates_sessions(
    client, inventory, tmp_path
):
    store, _, _ = inventory
    row = store.listing()["items"][0]
    sale = store.create_sale({"title": "Lot", "amount_cents": 150}, [row["id"]], "pat")
    store.update_sale(sale, {"status": "reserved"}, 1, "pat", "Réservation")
    archive = tmp_path / "backup.zip"
    backup(store, archive)
    restored_path = tmp_path / "restored"
    assert restore_backup(archive, restored_path)["copies"] == 7
    restored = Store(restored_path)
    a, b = export_data(store)["tables"], export_data(restored)["tables"]
    assert a == b
    assert {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in store.photos.glob("*.jpg")
    } == {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in restored.photos.glob("*.jpg")
    }
    with restored.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    with pytest.raises(ValueError):
        restore_backup(archive, restored_path)
    html = export_html(restored)
    assert "data:image/jpeg;base64," in html and "Réservé" in html
    assert client.get("/api/export/html").status_code == 200
    assert client.get("/api/backup").status_code == 200
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive) as z, zipfile.ZipFile(bad, "w") as out:
        for name in z.namelist():
            out.writestr(
                name, b"corrupt" if name == "collection.sqlite3" else z.read(name)
            )
    with pytest.raises(ValueError, match="contrôle"):
        restore_backup(bad, tmp_path / "bad-restore")


def test_sale_price_goals_are_distinct_from_agreed_and_reference_prices(client):
    card = client.get("/api/copies").json()["items"][0]
    sale_id = client.post(
        "/api/sales",
        json={
            "title": "Prix distincts",
            "copy_ids": [card["id"]],
            "amount_eur": 12,
            "asking_eur": 15,
            "target_eur": 12,
            "minimum_eur": 10,
        },
    ).json()["id"]
    sale = next(s for s in client.get("/api/sales").json() if s["id"] == sale_id)
    assert (
        sale["asking_cents"],
        sale["target_cents"],
        sale["minimum_cents"],
        sale["amount_cents"],
    ) == (1500, 1200, 1000, 1200)
    assert (
        client.get("/api/copies/" + card["id"]).json()["reference_cents"]
        == card["reference_cents"]
    )
    assert (
        client.patch(
            "/api/sales/" + sale_id,
            json={
                "expected_version": 1,
                "reason": "Objectif retiré",
                "target_eur": None,
            },
        ).status_code
        == 200
    )
    sale = next(s for s in client.get("/api/sales").json() if s["id"] == sale_id)
    assert sale["target_cents"] is None and sale["amount_cents"] == 1200
    assert (
        client.patch(
            "/api/sales/" + sale_id,
            json={
                "expected_version": 2,
                "reason": "Précision incorrecte",
                "amount_eur": 1.234,
            },
        ).status_code
        == 422
    )


def test_no_script_injection_in_export(inventory):
    store, _, _ = inventory
    row = store.listing()["items"][0]
    store.patch(
        row["id"],
        {"name": "</script><script>alert(1)</script>"},
        1,
        "pat",
        "Texte libre",
    )
    html = export_html(store)
    assert "</script><script>alert(1)" not in html
    assert "\\u003c/script\\u003e" in html


def test_offline_export_keeps_original_aliases_verified_state_and_manual_price_source(
    inventory,
):
    store, _, _ = inventory
    original = store.listing(query="Évoli")["items"][0]
    first = store.patch(
        original["id"],
        {"name": "イーブイ", "condition_confirmed": True},
        1,
        "pat",
        "Nom japonais vérifié",
    )
    store.patch(
        first["id"],
        {
            "reference_cents": 200,
            "price_source": "Vente comparable renseignée",
            "price_date": "2026-10-04",
        },
        2,
        "pat",
        "Référence manuelle",
    )
    assert store.listing(query="evoli")["items"][0]["id"] == original["id"]
    script = re.search(r"<script>(.*?)</script>", export_html(store), re.S).group(1)
    node = shutil.which("node") or "node"
    result = subprocess.run(
        [node, str(Path(__file__).with_name("library_runtime.cjs"))],
        input=json.dumps(
            {"script": script, "actions": [{"field": "search", "value": "evoli"}]}
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    state = json.loads(result.stdout)[1]
    assert state["summary"].startswith("1 exemplaire")
    assert (
        "état vérifié" in state["results"]
        and "Vente comparable renseignée" in state["results"]
    )
    assert "TCGdex / Cardmarket" not in state["results"]


def test_browser_api_link_keeps_filters_without_changing_json_api(inventory):
    query = "q=Zarbi&album=abc&stock=available&status=confirmed&limit=40&offset=80"
    with TestClient(create_app(inventory[0].root)) as visitor:
        browser = visitor.get(
            "/api/copies?" + query,
            headers={"Accept": "text/html", "Sec-Fetch-Dest": "document"},
            follow_redirects=False,
        )
        assert browser.status_code == 303
        assert browser.headers["location"] == "/gestion?" + query
        assert visitor.get(browser.headers["location"]).status_code == 200
        assert (
            visitor.get(
                "/api/copies?" + query, headers={"Accept": "application/json"}
            ).status_code
            == 401
        )
        media = visitor.get("/assets/media.js")
        assert media.status_code == 200 and "getUserMedia" in media.text


def test_a_public_instance_still_answers_commands_run_on_the_server(tmp_path):
    with Store(tmp_path / "prod").connect(write=True) as db:
        add_user(db, UserCreate(username="owner", password="Collection-test-2026!", role="admin"))
    app = create_app(tmp_path / "prod", allowed_hosts=["lilydex.example.org"], secure_cookie=True)
    for host in ("127.0.0.1", "lilydex.example.org"):
        with TestClient(app, base_url=f"http://{host}") as client:
            assert client.get("/api/setup").status_code == 200
    with TestClient(app, base_url="http://evil.example.com") as client:
        assert client.get("/api/setup").status_code == 400
