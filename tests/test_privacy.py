import json
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from test_reservations import PASSWORD, activate, client_of, shop, signup  # noqa: F401

from pokeprice import manage
from pokeprice.inventory import Store
from pokeprice.inventory_backup import backup
from pokeprice.privacy import Privacy
from pokeprice.webapp import create_app


def accepted_request(admin, store, listings, email="sacha@example.org", name="Sacha Ketchum"):
    signup(store, email, name)
    activate(admin, email)
    me = client_of(store, email)
    me.post("/api/me/requests", json={"listing_ids": [listings[0]["id"]], "message": "12 rue des Lilas"})
    request = admin.get("/api/requests").json()[0]
    sale_id = admin.post(
        f"/api/requests/{request['id']}/accept",
        json={"expected_version": request["version"], "listing_ids": [listings[0]["id"]]},
    ).json()["sale_id"]
    return me, request, sale_id


def dump(store):
    with store.connect() as db:
        return json.dumps(
            [
                [dict(r) for r in db.execute(f"SELECT * FROM {table}")]
                for table in ("users", "sessions", "requests", "request_items", "sales", "sale_events", "events")
            ],
            ensure_ascii=False,
        )


def test_forgetting_a_client_keeps_the_lot_but_not_the_person(shop):
    admin, store, listings = shop
    me, request, sale_id = accepted_request(admin, store, listings)
    assert "Sacha Ketchum" in dump(store) and "12 rue des Lilas" in dump(store)

    result = Privacy(store).forget("SACHA@example.org")
    assert result["requests"] == 1 and result["lots"] == 1
    text = dump(store)
    for secret in ("sacha@example.org", "Sacha Ketchum", "12 rue des Lilas"):
        assert secret not in text
    assert request["id"] not in json.dumps(admin.get("/api/requests").json())
    sale = next(s for s in admin.get("/api/sales").json() if s["id"] == sale_id)
    assert sale["title"] == "Vitrine · client effacé" and sale["amount_cents"] == 120
    assert "message effacé" in sale["notes"] and sale["status"] == "reserved"
    assert me.get("/api/me").status_code == 401  # the session went with the account
    assert [u["username"] for u in admin.get("/api/users").json()] == ["pat"]
    log = [json.loads(line) for line in Privacy(store).log.read_text().splitlines()]
    assert [entry["user_id"] for entry in log] == [result["erased"]]
    assert "sacha" not in Privacy(store).log.read_text()


def test_only_clients_can_be_forgotten(shop):
    _, store, _ = shop
    with pytest.raises(KeyError):
        Privacy(store).forget("pat")
    with pytest.raises(KeyError):
        Privacy(store).forget("inconnu@example.org")


def test_retention_periods(shop):
    admin, store, listings = shop
    emails = ["refuse@example.org", "attente@example.org", "inactif@example.org", "recent@example.org", "fidele@example.org"]
    for email in emails:
        signup(store, email)
    for email in emails[2:]:
        activate(admin, email)
    clients = {c["email"]: c["id"] for c in admin.get("/api/clients").json()}
    admin.patch(f"/api/clients/{clients['refuse@example.org']}", json={"status": "refused"})
    fidele = client_of(store, "fidele@example.org")
    kept_sale = fidele.post("/api/me/requests", json={"listing_ids": [listings[1]["id"]]}).json()
    stale = fidele.post("/api/me/requests", json={"listing_ids": [listings[2]["id"]]}).json()
    fidele.post(f"/api/me/requests/{stale['id']}/cancel", json={"expected_version": 1})
    at = datetime.now(timezone.utc)
    old = (at - timedelta(days=4 * 365)).isoformat()
    with store.connect(write=True) as db:
        db.execute("UPDATE users SET created_at=? WHERE email IN (?,?,?)", (old, *emails[:3]))
        db.execute("UPDATE users SET created_at=? WHERE email=?", (old, "fidele@example.org"))
        db.execute("UPDATE requests SET updated_at=? WHERE id=?", ((at - timedelta(days=200)).isoformat(), stale["id"]))

    result = Privacy(store).purge(at)
    assert result == {
        "clients": {"Compte refusé": 1, "Compte jamais validé": 1, "Client inactif": 1},
        "requests": 1,
    }
    assert {c["email"] for c in admin.get("/api/clients").json()} == {"recent@example.org", "fidele@example.org"}
    assert [r["id"] for r in fidele.get("/api/me/requests").json()] == [kept_sale["id"]]
    assert Privacy(store).purge(at) == {"clients": {}, "requests": 0}
    assert len(Privacy(store).log.read_text().splitlines()) == 3


def test_a_restore_replays_erasures_made_since_the_archive(shop, tmp_path, monkeypatch, capsys):
    admin, store, listings = shop
    accepted_request(admin, store, listings)
    archive = tmp_path / "avant.zip"
    backup(store, archive)
    Privacy(store).forget("sacha@example.org")
    restored = store.root.parent / "restauree"
    monkeypatch.setattr(sys, "argv", ["manage", "--data", str(restored), "restore", str(archive)])
    manage.main()
    assert json.loads(capsys.readouterr().out)["erasures"] == {"replayed": 1}
    assert "sacha@example.org" not in dump(Store(restored))


def test_the_notice_names_the_controller_from_the_server(shop, monkeypatch):
    _, store, _ = shop
    monkeypatch.setenv("POKEPRICE_CONTROLLER_NAME", "Camille <b>Dupont</b>")
    with TestClient(create_app(store.root)) as visitor:
        page = visitor.get("/a-propos").text
    assert "Camille &lt;b&gt;Dupont&lt;/b&gt;" in page and "{{" not in page
    assert "30 jours" in page and "90 jours" in page and "6 mois" in page and "3 ans" in page


def test_a_client_corrects_exports_and_deletes_their_account(shop):
    admin, store, listings = shop
    me, request, _ = accepted_request(admin, store, listings)
    wrong = me.patch("/api/me", json={"display_name": "Sacha", "email": "s@example.org", "password": "faux-mot-de-passe"})
    assert wrong.status_code == 403
    changed = me.patch("/api/me", json={"display_name": "Sacha K.", "email": "S@example.org", "password": PASSWORD})
    assert changed.json() == {"email": "S@example.org", "display_name": "Sacha K."}
    signup(store, "autre@example.org")
    taken = me.patch("/api/me", json={"display_name": "X", "email": "autre@example.org", "password": PASSWORD})
    assert taken.status_code == 409
    me.post("/api/logout")
    me = client_of(store, "s@example.org")  # the new address is the login

    exported = me.get("/api/me/export")
    assert "attachment" in exported.headers["content-disposition"]
    data = exported.json()
    assert data["account"]["email"] == "S@example.org" and "password_hash" not in json.dumps(data)
    assert [r["id"] for r in data["requests"]] == [request["id"]]

    assert me.post("/api/me/delete", json={"password": "faux-mot-de-passe"}).status_code == 403
    assert me.post("/api/me/delete", json={"password": PASSWORD}).json() == {"ok": True}
    assert me.get("/api/me").status_code == 401
    assert "S@example.org" not in dump(store)
    assert json.loads(Privacy(store).log.read_text().splitlines()[0])["reason"] == "Suppression par la personne"


def test_staff_cannot_use_the_client_account_routes(shop):
    admin, _, _ = shop
    assert admin.get("/api/me/export").status_code == 403
    assert admin.post("/api/me/delete", json={"password": "Collection-test-2026!"}).status_code == 403
