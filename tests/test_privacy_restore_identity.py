"""Erasure targets survive mailbox proof, guest detachment and older backups."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from basket_helpers import accepted_prices
from fastapi.testclient import TestClient
from test_client_identity import issue, redeem
from test_privacy import accepted_request
from test_reservations import PASSWORD, activate, client_of, guest, shop, signup  # noqa: F401

from pokeprice.inventory import Store
from pokeprice.inventory_backup import backup, restore_backup
from pokeprice.privacy import Privacy, parse_erasures, read_erasures
from pokeprice.webapp import create_app


@pytest.mark.parametrize("recipient_exists_in_backup", [False, True])
def test_replay_erases_a_request_moved_by_proof_without_erasing_its_old_real_owner(
    shop, tmp_path, recipient_exists_in_backup
):
    admin, store, listings = shop
    previous, request, sale_id = accepted_request(
        admin, store, listings, "previous@example.org", "Propriétaire conservé"
    )
    kept = previous.post("/api/me/requests", json={
        "expected_prices": accepted_prices(store, [listings[1]["id"]]), "listing_ids": [listings[1]["id"]], "message": "demande distincte conservée",
    }).json()
    with store.connect(write=True) as db:
        previous_id = db.execute("SELECT client_id FROM requests WHERE id=?", (request["id"],)).fetchone()[0]
        # A migrated request's historical contact does not prove its recipient.
        db.execute("UPDATE requests SET guest=1,contact_known=0 WHERE id=?", (request["id"],))
    if recipient_exists_in_backup:
        signup(store, "recipient@example.org", "Destinataire")
    archive = tmp_path / "before-contact-and-proof.zip"
    backup(store, archive)
    current = next(row for row in admin.get("/api/requests").json() if row["id"] == request["id"])
    corrected = admin.patch(f"/api/requests/{request['id']}/contact", json={
        "expected_version": current["version"], "email": "recipient@example.org",
        "display_name": "Destinataire", "correspondence_checked": True,
    })
    assert corrected.status_code == 200, corrected.text
    if not recipient_exists_in_backup:
        signup(store, "recipient@example.org", "Destinataire")
    recipient = redeem(store, issue(admin, corrected.json()["client_id"])["token"])
    assert [row["id"] for row in recipient.get("/api/me/requests").json()] == [request["id"]]
    with store.connect() as db:
        recipient_id = db.execute("SELECT id FROM users WHERE email='recipient@example.org'").fetchone()[0]
    Privacy(store).forget(recipient_id)
    journal = read_erasures(Privacy(store).log)
    assert journal["request_ids"][recipient_id] == {request["id"]}
    destination = tmp_path / "restored"
    result = restore_backup(archive, destination, journal=journal)
    assert result["erasures"]["replayed"] == 1
    restored = Store(destination)
    with restored.connect() as db:
        assert db.execute("SELECT email FROM users WHERE id=?", (previous_id,)).fetchone()[0] == "previous@example.org"
        assert db.execute("SELECT id FROM requests WHERE id=?", (kept["id"],)).fetchone()
        assert not db.execute("SELECT id FROM requests WHERE id=?", (request["id"],)).fetchone()
        states = [list(row) for row in db.execute(
            "SELECT title,notes FROM sales WHERE id=?", (sale_id,)
        )] + [list(row) for row in db.execute(
            "SELECT before_json,after_json,reason FROM sale_events WHERE sale_id=?", (sale_id,)
        )]
    for secret in ("previous@example.org", "Propriétaire conservé", "12 rue des Lilas"):
        assert secret not in json.dumps(states, ensure_ascii=False)
    assert Privacy(restored).replay(journal)["replayed"] == 0


@pytest.mark.parametrize("keep_other_guest_request", [False, True])
def test_replay_removes_only_an_affected_empty_guest_identity(shop, tmp_path, keep_other_guest_request):
    admin, store, listings = shop
    guest(store, "recipient@example.org", [listings[0]["id"]], message="demande à effacer").raise_for_status()
    [request] = admin.get("/api/requests").json()
    isolated_id = request["client_id"]
    if keep_other_guest_request:
        guest(store, "recipient@example.org", [listings[1]["id"]], message="origine encore inconnue").raise_for_status()
        with store.connect(write=True) as db:
            db.execute("UPDATE requests SET contact_known=0 WHERE id<>?", (request["id"],))
    archive = tmp_path / "before-signup.zip"
    backup(store, archive)
    signup(store, "recipient@example.org")
    recipient = redeem(store, issue(admin, isolated_id)["token"])
    assert [row["id"] for row in recipient.get("/api/me/requests").json()] == [request["id"]]
    with store.connect() as db:
        account_id = db.execute("SELECT id FROM users WHERE email='recipient@example.org'").fetchone()[0]
    Privacy(store).forget(account_id)
    destination = tmp_path / "restored"
    restore_backup(archive, destination, journal=read_erasures(Privacy(store).log))
    with Store(destination).connect() as db:
        assert not db.execute("SELECT id FROM requests WHERE id=?", (request["id"],)).fetchone()
        assert db.execute("SELECT COUNT(*) FROM users WHERE guest_account=1").fetchone()[0] == int(keep_other_guest_request)
        assert db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == int(keep_other_guest_request)


def test_replay_preserves_unproved_requests_then_applies_a_later_guest_erasure(shop, tmp_path):
    admin, store, listings = shop
    _, request, sale_id = accepted_request(admin, store, listings)
    with store.connect(write=True) as db:
        db.execute("UPDATE requests SET guest=1,contact_known=0 WHERE id=?", (request["id"],))
        owner_id = db.execute("SELECT client_id FROM requests WHERE id=?", (request["id"],)).fetchone()[0]
    archive = tmp_path / "before-self-deletion.zip"
    backup(store, archive)
    Privacy(store).forget(owner_id, preserve_unverified=True)
    scoped = read_erasures(Privacy(store).log)
    assert scoped["request_ids"][owner_id] == set()
    assert scoped["preserve_users"] == {owner_id}
    with store.connect() as db:
        guest_id = db.execute("SELECT client_id FROM requests WHERE id=?", (request["id"],)).fetchone()[0]
    preserved_path = tmp_path / "preserved"
    restore_backup(archive, preserved_path, journal=scoped)
    with Store(preserved_path).connect() as db:
        assert db.execute("SELECT client_id FROM requests WHERE id=?", (request["id"],)).fetchone()[0] == guest_id
        assert not db.execute("SELECT id FROM users WHERE id=?", (owner_id,)).fetchone()
    Privacy(store).forget(guest_id)
    journal = read_erasures(Privacy(store).log)
    assert journal["ordered_users"] == [owner_id, guest_id]
    assert journal["request_ids"][guest_id] == {request["id"]}
    erased_path = tmp_path / "erased"
    restore_backup(archive, erased_path, journal=journal)
    with Store(erased_path).connect() as db:
        assert db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM users WHERE role='client'").fetchone()[0] == 0
        states = [list(row) for row in db.execute("SELECT title,notes FROM sales WHERE id=?", (sale_id,))]
    assert "Sacha Ketchum" not in json.dumps(states) and "sacha@example.org" not in json.dumps(states)


@pytest.mark.parametrize("was_guest", [False, True])
def test_explicit_empty_targets_do_not_erase_a_request_that_left_the_account(shop, tmp_path, was_guest):
    admin, store, listings = shop
    if was_guest:
        guest(store, "previous@example.org", [listings[0]["id"]], name="Ancien compte").raise_for_status()
        [request] = admin.get("/api/requests").json()
        accepted = admin.post(f"/api/requests/{request['id']}/accept", json={
            "expected_version": request["version"], "listing_ids": [listings[0]["id"]],
        })
        assert accepted.status_code == 200, accepted.text
        sale_id = accepted.json()["sale_id"]
    else:
        _, request, sale_id = accepted_request(admin, store, listings, "previous@example.org", "Ancien compte")
    with store.connect() as db:
        previous_id = db.execute("SELECT client_id FROM requests WHERE id=?", (request["id"],)).fetchone()[0]
    archive = tmp_path / "before-transfer.zip"
    backup(store, archive)
    with store.connect(write=True) as db:
        db.execute("UPDATE requests SET guest=1,contact_known=0 WHERE id=?", (request["id"],))
    current = next(row for row in admin.get("/api/requests").json() if row["id"] == request["id"])
    transferred = admin.patch(f"/api/requests/{request['id']}/contact", json={
        "expected_version": current["version"], "email": "recipient@example.org", "display_name": "Destinataire",
        "correspondence_checked": True,
    })
    assert transferred.status_code == 200, transferred.text
    signup(store, "recipient@example.org")
    recipient = redeem(store, issue(admin, transferred.json()["client_id"])["token"])
    assert [row["id"] for row in recipient.get("/api/me/requests").json()] == [request["id"]]
    Privacy(store).forget(previous_id)
    journal = read_erasures(Privacy(store).log)
    assert journal["request_ids"][previous_id] == set() and previous_id in journal["explicit_users"]
    destination = tmp_path / "restored"
    restore_backup(archive, destination, journal=journal)
    with Store(destination).connect() as db:
        retained = db.execute("SELECT client_id,guest,contact_known FROM requests WHERE id=?", (request["id"],)).fetchone()
        assert retained is not None and retained["client_id"] != previous_id
        assert retained["guest"] == 1 and retained["contact_known"] == 0
        assert not db.execute("SELECT id FROM users WHERE id=?", (previous_id,)).fetchone()
        assert db.execute("SELECT title FROM sales WHERE id=?", (sale_id,)).fetchone()[0] == "Vitrine · Ancien compte"


def test_legacy_missing_targets_remain_full_erasures_while_an_empty_list_is_explicit():
    old = {"user_id": "client"}
    empty = {"user_id": "client", "request_ids": []}
    encode = lambda rows: ("\n".join(json.dumps(row) for row in rows) + "\n").encode()
    assert parse_erasures(encode([empty]))["explicit_users"] == {"client"}
    assert parse_erasures(encode([old, empty]))["explicit_users"] == set()


def test_email_erasure_groups_guest_identities_but_an_explicit_id_stays_specific(shop):
    admin, store, listings = shop
    signup(store, "recipient@example.org")
    first = activate(admin, "recipient@example.org")
    guest(store, "recipient@example.org", [listings[0]["id"]], message="demande isolée").raise_for_status()
    [request] = admin.get("/api/requests").json()
    Privacy(store).forget(first["id"])
    with store.connect() as db:
        assert db.execute("SELECT id FROM requests WHERE id=?", (request["id"],)).fetchone()
    signup(store, "recipient@example.org")
    second = activate(admin, "recipient@example.org")
    signup(store, "unrelated@example.org")
    unrelated = activate(admin, "unrelated@example.org")
    result = Privacy(store).forget("RECIPIENT@example.org")
    assert result["clients"] == 2 and result["requests"] == 1
    with store.connect() as db:
        assert db.execute("SELECT id FROM users WHERE id=?", (unrelated["id"],)).fetchone()
        assert not db.execute("SELECT id FROM requests WHERE id=?", (request["id"],)).fetchone()
    intents = [json.loads(line) for line in Privacy(store).log.read_text().splitlines()
               if json.loads(line)["phase"] == "intent"][-2:]
    assert {row["user_id"] for row in intents} == {second["id"], request["client_id"]}
    assert len({row["operation"] for row in intents}) == 1


def test_email_erasure_does_not_follow_a_real_accounts_prior_profile_email(shop):
    admin, store, listings = shop
    owner, request, _ = accepted_request(admin, store, listings, "prior@example.org", "Compte conservé")
    with store.connect() as db:
        owner_id = db.execute("SELECT id FROM users WHERE email='prior@example.org'").fetchone()[0]
    owner.patch("/api/me", json={"email": "current@example.org", "display_name": "Compte conservé", "password": PASSWORD}).raise_for_status()
    redeem(store, issue(admin, owner_id)["token"])
    signup(store, "prior@example.org", "Autre compte à effacer")
    other = activate(admin, "prior@example.org")
    Privacy(store).forget("prior@example.org")
    with store.connect() as db:
        assert db.execute("SELECT id FROM users WHERE id=?", (owner_id,)).fetchone()
        assert db.execute("SELECT id FROM requests WHERE id=?", (request["id"],)).fetchone()
        assert not db.execute("SELECT id FROM users WHERE id=?", (other["id"],)).fetchone()


def test_retention_intent_records_its_selected_request_ids(shop):
    admin, store, listings = shop
    _, request, _ = accepted_request(admin, store, listings)
    with store.connect(write=True) as db:
        account_id = db.execute("SELECT client_id FROM requests WHERE id=?", (request["id"],)).fetchone()[0]
        old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        db.execute("UPDATE users SET status='refused',created_at=? WHERE id=?", (old, account_id))
    Privacy(store).purge()
    assert read_erasures(Privacy(store).log)["request_ids"][account_id] == {request["id"]}


@pytest.mark.parametrize("targets", [None, "request", [1], [""], ["same", "same"]])
def test_journal_rejects_malformed_request_targets(targets):
    body = (json.dumps({"user_id": "account", "request_ids": targets}) + "\n").encode()
    with pytest.raises(ValueError):
        parse_erasures(body)


def test_guest_mailbox_proof_is_not_blocked_by_an_unconfirmed_other_address(shop):
    admin, store, listings = shop
    signup(store, "recipient@example.org")
    account = activate(admin, "recipient@example.org")
    unproved = client_of(store, "recipient@example.org")
    unproved.patch("/api/me", json={"email": "other@example.org", "display_name": "Nom", "password": PASSWORD}).raise_for_status()
    stale = issue(admin, account["id"])
    assert stale["email"] == "other@example.org"
    guest(store, "recipient@example.org", [listings[0]["id"]], message="destinataire réel").raise_for_status()
    [request] = admin.get("/api/requests").json()
    proof = issue(admin, request["client_id"])
    assert proof["email"] == "recipient@example.org"
    assert unproved.get("/api/me/requests").json() == []
    with TestClient(create_app(store.root)) as visitor:
        assert visitor.post("/api/public/password", json={"token": stale["token"], "password": PASSWORD}).status_code == 422
    proved = redeem(store, proof["token"])
    assert unproved.get("/api/me").status_code == 401
    assert [row["id"] for row in proved.get("/api/me/requests").json()] == [request["id"]]
    assert proved.get("/api/me").json()["pending_email"] == ""
