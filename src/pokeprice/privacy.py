"""Storefront clients' personal data: erasure on request and retention limits.

The periods below are the ones announced on /a-propos: changing one means
changing the notice too. An erased client's sold lots stay in the books, with
their name, address and message replaced. Every erasure is logged by account
id outside the collection folder, so that restoring an older backup can replay
it (`restore` does so).
"""

import fcntl
import hashlib
import json
import os
import re
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


REFUSED_ACCOUNTS = timedelta(days=30)
PENDING_ACCOUNTS = timedelta(days=90)
CLOSED_REQUESTS = timedelta(days=183)
INACTIVE_CLIENTS = timedelta(days=3 * 365)
ERASED_CLIENT, ERASED_MESSAGE = "client effacé", "message effacé"
JOURNAL_MARKER = "privacy-erasure-journal"


def moment(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def scrub(text, secrets):
    """Replace each secret as a whole word, longest first."""
    for secret, placeholder in sorted(secrets, key=lambda s: -len(s[0])):
        text = re.sub(r"(?<!\w)" + re.escape(secret) + r"(?!\w)", placeholder, text)
    return text


def erasure_log(directory):
    """Beside the collection folder: a restored folder next to it shares the log."""
    return Path(directory).resolve().parent / "erasures.jsonl"


def read_erasures(path):
    """Read a locked, complete journal; missing or malformed data fails closed.

    Legacy entries without a phase are completed erasures. An intent without
    a completion is still authoritative and is replayed after a crash.
    """
    with erasures_guard(path) as journal:
        return journal


@contextmanager
def erasures_guard(path):
    """Keep the current journal stable until the restored folder is published."""
    try:
        log = Path(path).open("rb")
    except OSError as error:
        raise ValueError("Journal d’effacement absent ou illisible.") from error
    with log:
        fcntl.flock(log, fcntl.LOCK_SH)
        yield parse_erasures(log.read())


def parse_erasures(body):
    try:
        if body and not body.endswith(b"\n"):
            raise ValueError("Dernière ligne incomplète.")
        entries = [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
        pending, scopes, requests, legacy = set(), {}, {}, set()
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("user_id"), str) or not entry["user_id"]:
                raise ValueError("Identité d’effacement absente.")
            phase = entry.get("phase")
            if phase not in (None, "intent", "done"):
                raise ValueError("Phase d’effacement inconnue.")
            preserve = entry.get("preserve_unverified", False)
            if type(preserve) is not bool:
                raise ValueError("Périmètre d’effacement invalide.")
            targets = entry.get("request_ids", [])
            if (not isinstance(targets, list)
                    or any(not isinstance(target, str) or not target for target in targets)
                    or len(targets) != len(set(targets))):
                raise ValueError("Cibles d’effacement invalides.")
            if phase:
                operation = entry.get("operation")
                if not isinstance(operation, str) or not operation:
                    raise ValueError("Opération d’effacement absente.")
                key = (operation, entry["user_id"])
                if phase == "intent":
                    pending.add(key)
                elif key not in pending:
                    raise ValueError("Fin d’effacement sans intention.")
                else:
                    pending.remove(key)
            if phase != "done":
                # An older full erasure must never be weakened by a later
                # marker asking to preserve unverified guest requests.
                scopes[entry["user_id"]] = scopes.get(entry["user_id"], True) and preserve
                requests.setdefault(entry["user_id"], set()).update(targets)
                if "request_ids" not in entry:
                    legacy.add(entry["user_id"])
        return {"body": body, "users": set(scopes), "ordered_users": list(scopes), "incomplete": len(pending),
                "preserve_users": {user for user, preserve in scopes.items() if preserve},
                "request_ids": requests, "explicit_users": set(scopes) - legacy}
    except (ValueError, TypeError, UnicodeError) as error:
        raise ValueError("Journal d’effacement invalide ou incomplet.") from error


def journal_checkpoint(db):
    row = db.execute("SELECT value_json FROM settings WHERE key=?", (JOURNAL_MARKER,)).fetchone()
    if row is None:
        return None
    try:
        value = json.loads(row[0])
        if (not isinstance(value, dict) or type(value.get("bytes")) is not int or value["bytes"] < 0
                or not isinstance(value.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", value["sha256"])):
            raise ValueError("Empreinte de journal invalide.")
    except (ValueError, TypeError) as error:
        raise ValueError("Repère du journal d’effacement invalide.") from error
    return value


def validate_checkpoint(body, checkpoint):
    if checkpoint is not None and (
            len(body) < checkpoint["bytes"]
            or hashlib.sha256(body[:checkpoint["bytes"]]).hexdigest() != checkpoint["sha256"]):
        raise ValueError("Journal d’effacement tronqué, remplacé ou trop ancien pour cette base.")


def mark_journal(db, body):
    checkpoint = {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    db.execute("INSERT INTO settings(key,value_json,updated_by,updated_at) VALUES(?,?,?,?) "
               "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, "
               "updated_by=excluded.updated_by,updated_at=excluded.updated_at",
               (JOURNAL_MARKER, json.dumps(checkpoint), "privacy", datetime.now(timezone.utc).isoformat()))


def sync_directory(path):
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def journal_snapshot(store):
    """Never recreate a log that any committed erasure makes necessary."""
    path = erasure_log(store.root)
    with store.connect() as db:
        checkpoint = journal_checkpoint(db)
        if checkpoint is None:
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "wb") as log:
                    os.fsync(log.fileno())
                sync_directory(path.parent)
        body = read_erasures(path)["body"]
        validate_checkpoint(body, checkpoint)
    return body


class Privacy:
    def __init__(self, store):
        self.store = store
        self.log = erasure_log(store.root)

    def forget(self, who, reason="Demande de la personne", *, preserve_unverified=False):
        """An exact ID stays specific; an e-mail covers its client and guest identities."""
        with self.store.connect(write=True) as db:
            who = who.strip()
            exact = db.execute("SELECT * FROM users WHERE role='client' AND id=?", (who,)).fetchone()
            users = [exact] if exact else db.execute(
                "SELECT u.* FROM users u WHERE u.role='client' AND (u.email=? COLLATE NOCASE "
                "OR (u.guest_account=1 AND EXISTS(SELECT 1 FROM requests r "
                "WHERE r.client_id=u.id AND r.client_email=? COLLATE NOCASE))) ORDER BY u.guest_account,u.id",
                (who, who),
            ).fetchall()
            if not users:
                raise KeyError("Client introuvable.")
            erased = [(user["id"], reason) for user in users]
            targets = {user["id"]: self.request_ids(db, user["id"], preserve_unverified=preserve_unverified)
                       for user in users}
            operation = self.record(erased, preserve_unverified=preserve_unverified, request_ids=targets)
            mark_journal(db, read_erasures(self.log)["body"])
            results = [self.erase(db, user, preserve_unverified=preserve_unverified) for user in users]
        self.record(erased, operation=operation, phase="done", preserve_unverified=preserve_unverified,
                    request_ids=targets)
        result = {"erased": users[0]["id"], "requests": sum(row["requests"] for row in results),
                  "lots": sum(row["lots"] for row in results)}
        if len(users) > 1:
            result["clients"] = len(users)
        detached = sum(row.get("unverified_requests", 0) for row in results)
        if detached:
            result["unverified_requests"] = detached
        return result

    @staticmethod
    def request_ids(db, user_id, *, preserve_unverified=False):
        """Immutable erasure targets survive a guest's later account reassignment."""
        where = "client_id=?" + (" AND guest=0" if preserve_unverified else "")
        return [r[0] for r in db.execute(f"SELECT id FROM requests WHERE {where} ORDER BY id", (user_id,))]

    def erase(self, db, user, *, preserve_unverified=False, request_ids=None):
        detached = []
        if preserve_unverified or request_ids is not None:
            from .reservations import guest_identity
            from secrets import token_hex
            from uuid import NAMESPACE_OID, uuid5

            owned = db.execute(
                "SELECT id,client_email,created_at,guest FROM requests WHERE client_id=?", (user["id"],)
            ).fetchall()
            selected = set(request_ids) if request_ids is not None else None
            detached = [row for row in owned if (row["id"] not in selected if selected is not None else row["guest"])]
            for request in detached:
                # A later guest erasure finds this identity again when replaying
                # an archive that predates the account's self-deletion.
                identity_id = str(uuid5(NAMESPACE_OID, user["id"] + "\0" + request["client_email"].casefold()))
                guest_id = guest_identity(db, request["client_email"],
                                          token_hex(16) + ":" + token_hex(32), request["created_at"], identity_id=identity_id)
                db.execute("UPDATE requests SET client_id=?,guest=1 WHERE id=?", (guest_id, request["id"]))
                if selected is not None or not request["guest"]:
                    # The journal omits this previously signed-in request:
                    # its later ownership is not established by the archive.
                    db.execute("UPDATE requests SET contact_known=0 WHERE id=?", (request["id"],))
        secrets = [(user[key], ERASED_CLIENT) for key in ("email", "pending_email", "display_name") if user[key]]
        result = {"erased": user["id"], **self.erase_requests(db, self.request_ids(db, user["id"]), secrets=secrets)}
        db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        db.execute("DELETE FROM password_links WHERE user_id=?", (user["id"],))
        db.execute("DELETE FROM users WHERE id=?", (user["id"],))
        if detached:
            result["unverified_requests"] = len(detached)
        return result

    def erase_requests(self, db, request_ids, secrets=()):
        """Erase only these requests and copied sale identities, whoever owns them now.

        The durable journal stores request IDs rather than personal text. This
        replay path never removes a reassigned owner's unrelated profile or requests.
        """
        request_ids = set(request_ids)
        if not request_ids:
            return {"requests": 0, "lots": 0}
        requests = db.execute(
            "SELECT r.*,u.email AS owner_email,u.pending_email AS owner_pending_email,u.display_name AS owner_name "
            "FROM requests r JOIN users u ON u.id=r.client_id WHERE r.id IN ("
            + ",".join("?" for _ in request_ids) + ")", tuple(request_ids),
        ).fetchall()
        secrets = list(secrets)
        for request in requests:
            for key in ("owner_email", "owner_pending_email", "owner_name", "client_email", "client_name"):
                if request[key]:
                    secrets.append((request[key], ERASED_CLIENT))
            for identity in json.loads(request["identity_json"]):
                secrets.extend((identity[key], ERASED_CLIENT) for key in ("email", "name") if identity.get(key))
            if request["message"].strip():
                secrets.append((request["message"].strip(), ERASED_MESSAGE))
        request_ids = {r["id"] for r in requests}
        sale_ids = {r["sale_id"] for r in requests if r["sale_id"]}
        for sale_id in sale_ids:
            row = db.execute("SELECT title,notes FROM sales WHERE id=?", (sale_id,)).fetchone()
            db.execute(
                "UPDATE sales SET title=?,notes=? WHERE id=?",
                (scrub(row["title"], secrets), scrub(row["notes"], secrets), sale_id),
            )
            for event in db.execute(
                "SELECT id,before_json,after_json,reason FROM sale_events WHERE sale_id=?", (sale_id,)
            ).fetchall():
                states = []
                for raw in (event["before_json"], event["after_json"]):
                    state = json.loads(raw)
                    for key in ("title", "notes"):
                        if isinstance(state.get(key), str):
                            state[key] = scrub(state[key], secrets)
                    states.append(json.dumps(state, ensure_ascii=False))
                db.execute(
                    "UPDATE sale_events SET before_json=?,after_json=?,reason=? WHERE id=?",
                    (*states, scrub(event["reason"], secrets), event["id"]),
                )
        for event in db.execute(
            "SELECT id,reason,after_json FROM events WHERE kind='storefront-request'"
        ).fetchall():
            if json.loads(event["after_json"]).get("request_id") in request_ids:
                db.execute("UPDATE events SET reason=? WHERE id=?", (scrub(event["reason"], secrets), event["id"]))
        for request_id in request_ids:
            db.execute("DELETE FROM request_items WHERE request_id=?", (request_id,))
            db.execute("DELETE FROM requests WHERE id=?", (request_id,))
        for owner_id in {row["client_id"] for row in requests}:
            orphan = db.execute(
                "SELECT 1 FROM users u WHERE u.id=? AND u.role='client' AND u.guest_account=1 "
                "AND NOT EXISTS(SELECT 1 FROM requests r WHERE r.client_id=u.id)", (owner_id,),
            ).fetchone()
            if orphan:
                db.execute("DELETE FROM sessions WHERE user_id=?", (owner_id,))
                db.execute("DELETE FROM password_links WHERE user_id=?", (owner_id,))
                db.execute("DELETE FROM users WHERE id=?", (owner_id,))
        return {"requests": len(request_ids), "lots": len(sale_ids)}

    def purge(self, at=None):
        """Apply the retention periods; run every night before the backup."""
        at = at or datetime.now(timezone.utc)
        due = []
        with self.store.connect(write=True) as db:
            for user in db.execute(
                "SELECT u.*,MAX(r.updated_at) AS last_request FROM users u "
                "LEFT JOIN requests r ON r.client_id=u.id WHERE u.role='client' GROUP BY u.id"
            ).fetchall():
                created = moment(user["created_at"])
                last = max(created, moment(user["last_request"])) if user["last_request"] else created
                if user["status"] == "refused" and at - created > REFUSED_ACCOUNTS:
                    due.append((user, "Compte refusé"))
                elif user["status"] == "pending" and at - last > PENDING_ACCOUNTS:
                    due.append((user, "Compte jamais validé"))
                elif at - last > INACTIVE_CLIENTS:
                    due.append((user, "Client inactif"))
            erased = [(user["id"], reason) for user, reason in due]
            targets = {user["id"]: self.request_ids(db, user["id"]) for user, _ in due}
            operation = self.record(erased, request_ids=targets)
            if erased:
                mark_journal(db, read_erasures(self.log)["body"])
            for user, _ in due:
                self.erase(db, user)
            closed = [
                r["id"]
                for r in db.execute(
                    "SELECT id,status,updated_at,expires_at FROM requests WHERE sale_id IS NULL"
                ).fetchall()
                if (r["status"] in ("refused", "expired", "cancelled") and at - moment(r["updated_at"]) > CLOSED_REQUESTS)
                or (r["status"] == "sent" and at - moment(r["expires_at"]) > CLOSED_REQUESTS)
            ]
            for request_id in closed:
                db.execute("DELETE FROM request_items WHERE request_id=?", (request_id,))
                db.execute("DELETE FROM requests WHERE id=?", (request_id,))
        self.record(erased, operation=operation, phase="done", request_ids=targets)
        return {"clients": dict(Counter(reason for _, reason in due)), "requests": len(closed)}

    def record(self, erased, *, operation=None, phase="intent", preserve_unverified=False, request_ids=None):
        if not erased:
            return
        operation = operation or str(uuid.uuid4())
        with self.store.connect() as db:
            checkpoint = journal_checkpoint(db)
        flags = os.O_RDWR | os.O_APPEND | (0 if checkpoint is not None else os.O_CREAT)
        with os.fdopen(os.open(self.log, flags, 0o600), "a+b") as log:
            fcntl.flock(log, fcntl.LOCK_EX)
            log.seek(0)
            body = log.read()
            validate_checkpoint(body, checkpoint)
            parse_erasures(body)
            log.seek(0, os.SEEK_END)
            for user_id, reason in erased:
                entry = {"user_id": user_id, "reason": reason, "at": datetime.now(timezone.utc).isoformat(),
                         "phase": phase, "operation": operation,
                         "preserve_unverified": preserve_unverified}
                if request_ids is not None:
                    entry["request_ids"] = list(request_ids.get(user_id, ()))
                log.write((json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))
            log.flush()
            os.fsync(log.fileno())
            # The first durable intent also needs its directory entry on disk.
            sync_directory(self.log.parent)
        return operation

    def replay(self, journal=None):
        """Erase again, in a restored collection, every client erased since its backup."""
        journal = read_erasures(self.log) if journal is None else journal
        ids = journal["users"]
        replayed = 0
        with self.store.connect(write=True) as db:
            validate_checkpoint(journal["body"], journal_checkpoint(db))
            mark_journal(db, journal["body"])
            for user_id in journal.get("ordered_users", sorted(ids)):
                user = db.execute(
                    "SELECT * FROM users WHERE id=? AND role='client'", (user_id,)
                ).fetchone()
                if user:
                    if user_id in journal.get("explicit_users", set()):
                        self.erase(db, user, request_ids=journal["request_ids"].get(user_id, ()))
                    elif user_id in journal.get("preserve_users", set()):
                        self.erase(db, user, preserve_unverified=True)
                    else:
                        self.erase(db, user)
                    replayed += 1
                # A mailbox proof or a seller contact correction can move a
                # request to another account after the backup. The immutable
                # target erases only that request and its sale's copied PII.
                removed = self.erase_requests(db, journal.get("request_ids", {}).get(user_id, ()))
                if not user and removed["requests"]:
                    replayed += 1
        result = {"replayed": replayed}
        if journal["incomplete"]:
            result["incomplete"] = journal["incomplete"]
        return result
