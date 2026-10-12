import shutil
import hashlib
import io
import json
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
from pokeprice.webapp import create_app


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
        assert browser.headers["location"] == "/?" + query
        assert visitor.get(browser.headers["location"]).status_code == 200
        assert (
            visitor.get(
                "/api/copies?" + query, headers={"Accept": "application/json"}
            ).status_code
            == 401
        )
        media = visitor.get("/assets/media.js")
        assert media.status_code == 200 and "getUserMedia" in media.text
