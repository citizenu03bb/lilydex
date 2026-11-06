"""Mailbox ownership and historical erasure: isolated fake accounts and backups."""

import json

from fastapi.testclient import TestClient
from test_privacy import accepted_request, dump
from test_reservations import PASSWORD, activate, client_of, guest, shop, signup  # noqa: F401

from pokeprice.inventory import Store
from pokeprice.inventory_backup import backup, restore_backup
from pokeprice.privacy import Privacy
from pokeprice.webapp import create_app


def issue(admin, account_id):
    made = admin.post(f"/api/clients/{account_id}/password-link")
    assert made.status_code == 201, made.text
    return made.json()


def redeem(store, token):
    browser = TestClient(create_app(store.root))
    browser.__enter__()
    response = browser.post("/api/public/password", json={"token": token, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return browser


def test_pending_address_cannot_capture_a_guest_request_then_proof_can(shop):
    admin, store, listings = shop
    signup(store, "old@example.org", "Compte approuvé")
    account = activate(admin, "old@example.org")
    owner = client_of(store, "old@example.org")
    changed = owner.patch("/api/me", json={"email": "recipient@example.org", "display_name": "Nouveau nom", "password": PASSWORD})
    assert changed.json() == {"email": "old@example.org", "pending_email": "recipient@example.org", "display_name": "Nouveau nom"}
    guest(store, "recipient@example.org", [listings[0]["id"]], message="message du destinataire").raise_for_status()
    [request] = admin.get("/api/requests").json()
    assert request["client_id"] != account["id"]
    assert owner.get("/api/me/requests").json() == []
    assert owner.post(f"/api/me/requests/{request['id']}/cancel", json={"expected_version": request["version"]}).status_code == 404
    assert owner.post(f"/api/clients/{account['id']}/password-link").status_code == 403
    made = issue(admin, account["id"])
    assert made["email"] == "recipient@example.org"
    with store.connect() as db:
        assert db.execute("SELECT email_verified_at FROM users WHERE id=?", (account["id"],)).fetchone()[0] == ""
    recipient = redeem(store, made["token"])
    assert recipient.get("/api/me").json()["email"] == "recipient@example.org"
    assert [r["id"] for r in recipient.get("/api/me/requests").json()] == [request["id"]]
    assert owner.get("/api/me").status_code == 401


def test_unverified_account_deletion_does_not_delete_a_guest_at_its_address(shop):
    admin, store, listings = shop
    signup(store, "recipient@example.org")
    account = activate(admin, "recipient@example.org")
    owner = client_of(store, "recipient@example.org")
    guest(store, "recipient@example.org", [listings[0]["id"]], message="demande indépendante").raise_for_status()
    [request] = admin.get("/api/requests").json()
    assert owner.get("/api/me/requests").json() == []
    assert owner.post("/api/me/delete", json={"password": PASSWORD}).json() == {"ok": True}
    assert [r["id"] for r in admin.get("/api/requests").json()] == [request["id"]]
    assert request["client_id"] != account["id"]
    Privacy(store).forget(request["client_id"])
    assert "demande indépendante" not in dump(store)


def test_profile_change_revokes_links_and_old_address_is_not_reactivated(shop):
    admin, store, _ = shop
    signup(store, "old@example.org")
    account = activate(admin, "old@example.org")
    owner = client_of(store, "old@example.org")
    first = issue(admin, account["id"])
    owner.patch("/api/me", json={"email": "next@example.org", "display_name": "Nom", "password": PASSWORD}).raise_for_status()
    second = issue(admin, account["id"])
    owner.patch("/api/me", json={"email": "last@example.org", "display_name": "Nom", "password": PASSWORD}).raise_for_status()
    with TestClient(create_app(store.root)) as browser:
        for link in (first, second):
            assert browser.post("/api/public/password", json={"token": link["token"], "password": PASSWORD}).status_code == 422
    current = issue(admin, account["id"])
    browser = redeem(store, current["token"])
    assert browser.get("/api/me").json()["email"] == "last@example.org"


def test_signup_after_guest_does_not_expose_guest_until_current_mailbox_proof(shop):
    admin, store, listings = shop
    guest(store, "recipient@example.org", [listings[0]["id"]]).raise_for_status()
    isolated = admin.get("/api/clients").json()[0]
    signup(store, "recipient@example.org", "Compte séparé")
    with store.connect() as db:
        account_id = db.execute("SELECT id FROM users WHERE email='recipient@example.org'").fetchone()[0]
    admin.patch(f"/api/clients/{account_id}", json={"status": "active"}).raise_for_status()
    owner = client_of(store, "recipient@example.org")
    assert owner.get("/api/me/requests").json() == []
    # The seller's link made from the guest reaches the actual signup account.
    proved = redeem(store, issue(admin, isolated["id"])["token"])
    assert len(proved.get("/api/me/requests").json()) == 1
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE guest_account=1").fetchone()[0] == 0


def test_erasure_removes_frozen_identity_after_profile_and_mailbox_change(shop):
    admin, store, listings = shop
    owner, request, sale_id = accepted_request(admin, store, listings, "old@example.org", "Ancien Nom")
    with store.connect() as db:
        uid = db.execute("SELECT id FROM users WHERE email='old@example.org'").fetchone()[0]
    owner.patch("/api/me", json={"email": "next@example.org", "display_name": "Nouveau Nom", "password": PASSWORD}).raise_for_status()
    proved = redeem(store, issue(admin, uid)["token"])
    assert proved.post("/api/me/delete", json={"password": PASSWORD}).status_code == 200
    for secret in ("old@example.org", "Ancien Nom", "next@example.org", "Nouveau Nom", "12 rue des Lilas"):
        assert secret not in dump(store)
    assert any(s["id"] == sale_id for s in admin.get("/api/sales").json())


def test_mailbox_proof_can_recover_a_legacy_request_attached_to_another_account(shop):
    admin, store, listings = shop
    signup(store, "wrong@example.org")
    original = activate(admin, "wrong@example.org")
    owner = client_of(store, "wrong@example.org")
    owner.post("/api/me/requests", json={"listing_ids": [listings[0]["id"]]}).raise_for_status()
    with store.connect(write=True) as db:
        db.execute("UPDATE requests SET guest=1,client_email='recipient@example.org'")
    assert owner.get("/api/me/requests").json() == []
    signup(store, "recipient@example.org")
    account = activate(admin, "recipient@example.org")
    proved = redeem(store, issue(admin, account["id"])["token"])
    assert len(proved.get("/api/me/requests").json()) == 1
    assert any(c["id"] == original["id"] for c in admin.get("/api/clients").json())


def test_replaying_detachment_recreates_the_id_of_a_later_guest_erasure(shop, tmp_path):
    admin, store, listings = shop
    _, request, _ = accepted_request(admin, store, listings)
    with store.connect(write=True) as db:
        db.execute("UPDATE requests SET guest=1")
        uid = db.execute("SELECT client_id FROM requests").fetchone()[0]
    archive = tmp_path / "before-detachment.zip"
    backup(store, archive)
    Privacy(store).forget(uid, preserve_unverified=True)
    with store.connect() as db:
        detached_id = db.execute("SELECT client_id FROM requests").fetchone()[0]
    Privacy(store).forget(detached_id)
    restored_path = tmp_path / "another-parent" / "restored"
    restore_backup(archive, restored_path)
    restored = Store(restored_path)
    Privacy(restored).forget(uid, preserve_unverified=True)
    with restored.connect() as db:
        assert db.execute("SELECT client_id FROM requests").fetchone()[0] == detached_id
    Privacy(restored).forget(detached_id)
    assert "Sacha Ketchum" not in dump(restored)
    with restored.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0


def test_unknown_legacy_contact_stays_quarantined_until_seller_recovers_its_origin(shop):
    admin, store, listings = shop
    signup(store, "attacker@example.org", "Compte courant")
    account = activate(admin, "attacker@example.org")
    original = client_of(store, "attacker@example.org")
    first = original.post("/api/me/requests", json={"listing_ids": [listings[0]["id"]], "message": "message privé du destinataire"}).json()
    # This is what the old data can establish after the pre-fix claimant changed
    # profile: the current address is a guess, not the guest's actual origin.
    with store.connect(write=True) as db:
        db.execute("UPDATE requests SET guest=1,contact_known=0,identity_json=? WHERE id=?",
                   (json.dumps([{"email": "attacker@example.org", "name": "Ancien nom copié"}]), first["id"]))
    proved_attacker = redeem(store, issue(admin, account["id"])["token"])
    assert proved_attacker.get("/api/me/requests").json() == []
    assert "message privé du destinataire" not in proved_attacker.get("/api/me/export").text
    assert proved_attacker.post(f"/api/me/requests/{first['id']}/cancel", json={"expected_version": 1}).status_code == 404
    assert admin.post(f"/api/requests/{first['id']}/accept", json={"expected_version": 1, "listing_ids": [listings[0]["id"]]}).status_code == 409
    assert proved_attacker.patch(f"/api/requests/{first['id']}/contact", json={"expected_version": 1, "email": "attacker@example.org", "display_name": "A", "correspondence_checked": True}).status_code == 403
    assert proved_attacker.post("/api/me/delete", json={"password": PASSWORD}).json() == {"ok": True, "unverified_requests": 1}
    [unknown] = admin.get("/api/requests").json()
    assert unknown["contact_known"] == 0
    assert admin.post(f"/api/clients/{unknown['client_id']}/password-link").status_code == 409
    payload = {"expected_version": unknown["version"], "email": "recipient@example.org", "display_name": "Destinataire", "correspondence_checked": True}
    assert admin.patch(f"/api/requests/{first['id']}/contact", json={**payload, "expected_version": 99}).status_code == 409
    assert admin.patch(f"/api/requests/{first['id']}/contact", json={**payload, "correspondence_checked": False}).status_code == 422
    recovered = admin.patch(f"/api/requests/{first['id']}/contact", json=payload)
    assert recovered.status_code == 200, recovered.text
    guest_id = recovered.json()["client_id"]
    # A new request can share that identity; an unknown legacy row alongside it
    # must not hitchhike when a proved recipient collects the known requests.
    guest(store, "recipient@example.org", [listings[1]["id"]], message="autre origine inconnue").raise_for_status()
    with store.connect(write=True) as db:
        db.execute("UPDATE requests SET contact_known=0 WHERE id<>?", (first["id"],))
    signup(store, "recipient@example.org")
    recipient = redeem(store, issue(admin, guest_id)["token"])
    owned = recipient.get("/api/me/requests").json()
    assert [row["id"] for row in owned] == [first["id"]]
    assert "identity_json" not in owned[0]
    assert "Ancien nom copié" not in recipient.get("/api/me/export").text
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM requests WHERE client_id=? AND contact_known=0", (guest_id,)).fetchone()[0] == 1
        assert db.execute("SELECT guest_account FROM users WHERE id=?", (guest_id,)).fetchone()[0] == 1


def test_request_id_erasure_survives_reassignment_and_leaves_other_owner_data(shop):
    admin, store, listings = shop
    _, request, sale_id = accepted_request(admin, store, listings)
    signup(store, "another@example.org", "Autre compte")
    other = activate(admin, "another@example.org")
    browser = client_of(store, "another@example.org")
    kept = browser.post("/api/me/requests", json={"listing_ids": [listings[1]["id"]]}).json()
    privacy = Privacy(store)
    with store.connect(write=True) as db:
        original = db.execute("SELECT client_id FROM requests WHERE id=?", (request["id"],)).fetchone()[0]
        targets = privacy.request_ids(db, original)
        db.execute("UPDATE requests SET client_id=? WHERE id=?", (other["id"], request["id"]))
        assert privacy.erase_requests(db, targets) == {"requests": 1, "lots": 1}
        assert privacy.erase_requests(db, targets) == {"requests": 0, "lots": 0}
        assert db.execute("SELECT id FROM users WHERE id=?", (other["id"],)).fetchone()
        assert db.execute("SELECT id FROM requests WHERE id=?", (kept["id"],)).fetchone()
        sale = db.execute("SELECT title,notes FROM sales WHERE id=?", (sale_id,)).fetchone()
        assert "Sacha Ketchum" not in json.dumps(tuple(sale)) and "sacha@example.org" not in json.dumps(tuple(sale))
        db.execute("UPDATE requests SET guest=1 WHERE id=?", (kept["id"],))
        assert privacy.request_ids(db, other["id"], preserve_unverified=True) == []


def test_schema25_backup_restoration_recovers_old_identity_and_isolates_legacy_requests(shop, tmp_path):
    admin, store, listings = shop
    _, request, sale_id = accepted_request(admin, store, listings, "old@example.org", "Ancien Nom")
    # Recreate the pre-migration schema and its profile-change flaw only in the
    # fixture DB, then restore its actual ZIP before running the new migration.
    with store.connect(write=True) as db:
        db.execute("UPDATE users SET email='new@example.org',username='new@example.org',display_name='Nouveau Nom' WHERE email='old@example.org'")
        for table, columns in {"requests": ("client_email", "client_name", "guest", "contact_known", "identity_json"),
                               "users": ("pending_email", "email_verified_at", "guest_account"),
                               "password_links": ("email",)}.items():
            for column in columns:
                db.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        db.execute("PRAGMA user_version=25")
    archive = tmp_path / "schema25.zip"
    backup(store, archive)
    destination = tmp_path / "restored"
    restore_backup(archive, destination)
    restored = Store(destination)
    with restored.connect() as db:
        row = db.execute("SELECT * FROM requests WHERE id=?", (request["id"],)).fetchone()
        assert row["client_email"] == "old@example.org" and row["client_name"] == "Ancien Nom"
        assert db.execute("SELECT email_verified_at FROM users WHERE email='new@example.org'").fetchone()[0] == ""
        assert row["guest"] == 1
        assert db.execute("SELECT guest_account,email FROM users WHERE id=?", (row["client_id"],)).fetchone()[:] == (0, "new@example.org")
        legacy_id = row["client_id"]
    browser = client_of(restored, "new@example.org")
    assert browser.get("/api/me/requests").json() == []
    assert browser.post("/api/me/delete", json={"password": PASSWORD}).json() == {"ok": True, "unverified_requests": 1}
    with restored.connect() as db:
        guest_id = db.execute("SELECT client_id FROM requests WHERE id=?", (request["id"],)).fetchone()[0]
        assert guest_id != legacy_id
    Privacy(restored).forget(guest_id)
    assert "Ancien Nom" not in dump(restored) and "old@example.org" not in dump(restored)
    assert sale_id in dump(restored)
    # An erasure marker written before schema 26 keeps its full meaning after
    # restore: migration must not move these rows beyond the old journal ID.
    older = tmp_path / "old-journal" / "restored"
    restore_backup(archive, older)
    recovered = Store(older)
    privacy = Privacy(recovered)
    privacy.log.write_text(json.dumps({"user_id": legacy_id, "reason": "Demande vérifiée", "at": "2026-11-01T00:00:00+00:00"}) + "\n")
    assert privacy.replay()["replayed"] == 1
    assert "old@example.org" not in dump(recovered)
    with recovered.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0
