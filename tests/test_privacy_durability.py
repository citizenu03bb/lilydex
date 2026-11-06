"""Crash paths use temporary collections and simulated transfers only."""

import json
import sys
import zipfile
from datetime import datetime, timedelta, timezone

import pytest
from test_privacy import accepted_request, dump
from test_reservations import shop, signup  # noqa: F401

from pokeprice import manage, privacy
from pokeprice.daily_backup import daily
from pokeprice.inventory import Store
from pokeprice.inventory_backup import backup, restore_backup
from pokeprice.privacy import JOURNAL_MARKER, Privacy, erasure_log, parse_erasures, read_erasures


@pytest.mark.parametrize("action", ["forget", "purge"])
@pytest.mark.parametrize("failure", ["write", "fsync"])
def test_no_erasure_commits_when_its_intent_cannot_be_durable(shop, monkeypatch, action, failure):
    _, store, _ = shop
    signup(store, "client@example.org")
    with store.connect(write=True) as db:
        db.execute("UPDATE users SET created_at=? WHERE email=?",
                   ((datetime.now(timezone.utc) - timedelta(days=100)).isoformat(), "client@example.org"))
    before = dump(store)

    def broken(*args, **kwargs):
        raise OSError("Disque indisponible")

    if failure == "write":
        monkeypatch.setattr(Privacy, "record", broken)
    else:
        monkeypatch.setattr(privacy.os, "fsync", broken)
    with pytest.raises(OSError):
        if action == "forget":
            Privacy(store).forget("client@example.org")
        else:
            Privacy(store).purge()
    assert dump(store) == before


def test_intent_survives_a_failure_before_commit_and_is_replayed(shop, tmp_path, monkeypatch):
    admin, store, listings = shop
    accepted_request(admin, store, listings)
    archive = tmp_path / "before.zip"
    backup(store, archive)
    erase = Privacy.erase

    def interrupted(self, db, user, **scope):
        erase(self, db, user, **scope)
        raise RuntimeError("Arrêt avant validation")

    with monkeypatch.context() as patch:
        patch.setattr(Privacy, "erase", interrupted)
        with pytest.raises(RuntimeError):
            Privacy(store).forget("sacha@example.org")
    assert "sacha@example.org" in dump(store)
    journal = read_erasures(erasure_log(store.root))
    assert journal["incomplete"] == 1
    destination = tmp_path / "restored"
    result = restore_backup(archive, destination, journal=journal)
    assert result["erasures"] == {"replayed": 1, "incomplete": 1}
    assert "sacha@example.org" not in dump(Store(destination))
    assert Privacy(Store(destination)).replay(journal)["replayed"] == 0


def test_failure_after_commit_keeps_a_durable_intent_for_restore(shop, tmp_path, monkeypatch):
    _, store, _ = shop
    signup(store, "client@example.org")
    archive = tmp_path / "before.zip"
    backup(store, archive)
    record = Privacy.record

    def interrupted(self, erased, **options):
        if options.get("phase") == "done":
            raise OSError("Fin non écrite après validation")
        return record(self, erased, **options)

    monkeypatch.setattr(Privacy, "record", interrupted)
    with pytest.raises(OSError):
        Privacy(store).forget("client@example.org")
    assert "client@example.org" not in dump(store)
    destination = tmp_path / "restored"
    restored = restore_backup(archive, destination, journal=read_erasures(erasure_log(store.root)))
    assert restored["erasures"] == {"replayed": 1, "incomplete": 1}
    assert "client@example.org" not in dump(Store(destination))


@pytest.mark.parametrize("body", [None, b"not json\n", b'{"user_id":"client"}', b'{"x":1}\n',
                                  b'{"user_id":"client","phase":"done","operation":"x"}\n'])
def test_cli_restore_refuses_missing_or_invalid_journal_before_publishing(shop, tmp_path, monkeypatch, body):
    _, store, _ = shop
    archive = tmp_path / "before.zip"
    backup(store, archive)
    destination = tmp_path / "elsewhere" / "restored"
    journal = tmp_path / "missing-or-invalid.jsonl"
    if body is not None:
        journal.write_bytes(body)
    monkeypatch.setattr(sys, "argv", ["manage", "--data", str(destination), "restore", str(archive), "--journal", str(journal)])
    with pytest.raises(ValueError, match="Journal d’effacement"):
        manage.main()
    assert not destination.exists()
    assert not destination.parent.exists()


def test_failed_replay_does_not_publish_restored_data(shop, tmp_path, monkeypatch):
    admin, store, listings = shop
    accepted_request(admin, store, listings)
    archive = tmp_path / "before.zip"
    backup(store, archive)
    Privacy(store).forget("sacha@example.org")
    destination = tmp_path / "restored"

    def broken(*args, **scope):
        raise OSError("Erreur pendant le rejeu")

    monkeypatch.setattr(Privacy, "erase", broken)
    with pytest.raises(OSError):
        restore_backup(archive, destination, journal=read_erasures(erasure_log(store.root)))
    assert not destination.exists()


def test_explicit_restore_without_journal_announces_the_risk(shop, tmp_path, monkeypatch, capsys):
    _, store, _ = shop
    archive = tmp_path / "before.zip"
    backup(store, archive)
    destination = tmp_path / "restored"
    monkeypatch.setattr(sys, "argv", ["manage", "--data", str(destination), "restore", str(archive), "--sans-journal"])
    manage.main()
    assert "effacées peuvent réapparaître" in json.loads(capsys.readouterr().out)["warning"]
    assert destination.exists()


def test_backup_carries_journal_and_same_day_retry_refreshes_it(shop):
    _, store, _ = shop
    signup(store, "client@example.org")
    first = daily(store)
    with zipfile.ZipFile(first["path"]) as archive:
        assert archive.read("erasures.jsonl") == b""
    Privacy(store).forget("client@example.org")
    current = erasure_log(store.root).read_bytes()
    second = daily(store)
    assert second["sha256"] != first["sha256"]
    with zipfile.ZipFile(second["path"]) as archive:
        assert archive.read("erasures.jsonl") == current
    assert daily(store)["sha256"] == second["sha256"]


def test_old_embedded_journal_never_replaces_current_one(shop, tmp_path):
    _, store, _ = shop
    signup(store, "client@example.org")
    archive = tmp_path / "before.zip"
    backup(store, archive)
    Privacy(store).forget("client@example.org")
    current = erasure_log(store.root).read_bytes()
    restore_backup(archive, store.root.parent / "restored", journal=read_erasures(erasure_log(store.root)))
    assert erasure_log(store.root).read_bytes() == current


def test_legacy_journal_entries_remain_replayable(tmp_path):
    log = tmp_path / "erasures.jsonl"
    log.write_text('{"user_id":"ancien-client","reason":"Demande"}\n')
    assert read_erasures(log)["users"] == {"ancien-client"}


@pytest.mark.parametrize("action", ["backup", "daily", "forget"])
def test_a_missing_previously_used_journal_is_never_recreated(shop, tmp_path, action):
    _, store, _ = shop
    signup(store, "client@example.org")
    Privacy(store).forget("client@example.org")
    with store.connect() as db:
        assert db.execute("SELECT 1 FROM settings WHERE key=?", (JOURNAL_MARKER,)).fetchone()
    erasure_log(store.root).unlink()
    if action == "forget":
        signup(store, "second@example.org")
    with pytest.raises((ValueError, OSError)):
        if action == "backup":
            backup(store, tmp_path / "must-not-exist.zip")
        elif action == "daily":
            daily(store)
        else:
            Privacy(store).forget("second@example.org")
    assert not erasure_log(store.root).exists()
    assert not (tmp_path / "must-not-exist.zip").exists()


def test_journal_scope_defaults_to_full_and_full_intents_dominate():
    old = {"user_id": "client"}
    scoped = {"user_id": "client", "phase": "intent", "operation": "new", "preserve_unverified": True}
    encode = lambda rows: ("\n".join(json.dumps(row) for row in rows) + "\n").encode()
    assert parse_erasures(encode([scoped]))["preserve_users"] == {"client"}
    assert parse_erasures(encode([old, scoped]))["preserve_users"] == set()
    with pytest.raises(ValueError):
        parse_erasures(encode([{**scoped, "preserve_unverified": "yes"}]))


def test_scoped_intent_is_replayed_with_its_original_scope(shop, monkeypatch):
    _, store, _ = shop
    signup(store, "client@example.org")
    with store.connect() as db:
        user_id = db.execute("SELECT id FROM users WHERE email='client@example.org'").fetchone()[0]
    operation = Privacy(store).record([(user_id, "Test")], preserve_unverified=True)
    Privacy(store).record([(user_id, "Test")], operation=operation, phase="done", preserve_unverified=True)
    journal = read_erasures(erasure_log(store.root))
    assert journal["preserve_users"] == {user_id}
    observed = []
    monkeypatch.setattr(Privacy, "erase", lambda self, db, user, **scope: observed.append(scope))
    Privacy(store).replay(journal)
    assert observed == [{"preserve_unverified": True}]


@pytest.mark.parametrize("action", ["backup", "forget"])
def test_a_zeroed_journal_cannot_replace_its_committed_prefix(shop, tmp_path, action):
    _, store, _ = shop
    signup(store, "client@example.org")
    Privacy(store).forget("client@example.org")
    log = erasure_log(store.root)
    log.write_bytes(b"")
    if action == "forget":
        signup(store, "second@example.org")
    with pytest.raises(ValueError, match="tronqué, remplacé ou trop ancien"):
        if action == "backup":
            backup(store, tmp_path / "rejected.zip")
        else:
            Privacy(store).forget("second@example.org")
    assert log.read_bytes() == b""
    assert not (tmp_path / "rejected.zip").exists()


def test_restore_rejects_a_journal_older_than_the_database_checkpoint(shop, tmp_path):
    _, store, _ = shop
    signup(store, "first@example.org")
    signup(store, "second@example.org")
    Privacy(store).forget("first@example.org")
    older = read_erasures(erasure_log(store.root))
    Privacy(store).forget("second@example.org")
    archive = tmp_path / "current.zip"
    backup(store, archive)
    destination = tmp_path / "rejected"
    with pytest.raises(ValueError, match="tronqué, remplacé ou trop ancien"):
        restore_backup(archive, destination, journal=older)
    assert not destination.exists()


def test_replay_follows_intent_order_instead_of_sorting_account_ids(shop, monkeypatch):
    _, store, _ = shop
    signup(store, "first@example.org")
    signup(store, "second@example.org")
    with store.connect() as db:
        ids = sorted((row[0] for row in db.execute("SELECT id FROM users WHERE role='client'")), reverse=True)
    Privacy(store).record([(user_id, "Test") for user_id in ids])
    journal = read_erasures(erasure_log(store.root))
    assert journal["ordered_users"] == ids
    observed = []
    monkeypatch.setattr(Privacy, "erase", lambda self, db, user: observed.append(user["id"]))
    Privacy(store).replay(journal)
    assert observed == ids
