"""Storefront clients' personal data: erasure on request and retention limits.

The periods below are the ones announced on /a-propos: changing one means
changing the notice too. An erased client's sold lots stay in the books, with
their name, address and message replaced. Every erasure is logged by account
id outside the collection folder, so that restoring an older backup can replay
it (`restore` does so).
"""

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


REFUSED_ACCOUNTS = timedelta(days=30)
PENDING_ACCOUNTS = timedelta(days=90)
CLOSED_REQUESTS = timedelta(days=183)
INACTIVE_CLIENTS = timedelta(days=3 * 365)
ERASED_CLIENT, ERASED_MESSAGE = "client effacé", "message effacé"


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


class Privacy:
    def __init__(self, store):
        self.store = store
        self.log = erasure_log(store.root)

    def forget(self, who, reason="Demande de la personne", *, preserve_unverified=False):
        """Erase one client, found by e-mail or account id; staff accounts are never touched."""
        with self.store.connect(write=True) as db:
            user = db.execute(
                "SELECT * FROM users WHERE role='client' AND (email=? COLLATE NOCASE OR id=?)",
                (who.strip(), who.strip()),
            ).fetchone()
            if not user:
                raise KeyError("Client introuvable.")
            result = self.erase(db, user, preserve_unverified=preserve_unverified)
        self.record([(user["id"], reason)])
        return result

    @staticmethod
    def request_ids(db, user_id, *, preserve_unverified=False):
        """Immutable erasure targets survive a guest's later account reassignment."""
        where = "client_id=?" + (" AND guest=0" if preserve_unverified else "")
        return [r[0] for r in db.execute(f"SELECT id FROM requests WHERE {where} ORDER BY id", (user_id,))]

    def erase(self, db, user, *, preserve_unverified=False):
        detached = []
        if preserve_unverified:
            from .reservations import guest_identity
            from secrets import token_hex
            from uuid import NAMESPACE_OID, uuid5

            detached = db.execute(
                "SELECT id,client_email,created_at FROM requests WHERE client_id=? AND guest=1", (user["id"],)
            ).fetchall()
            for request in detached:
                # A later guest erasure finds this identity again when replaying
                # an archive that predates the account's self-deletion.
                identity_id = str(uuid5(NAMESPACE_OID, user["id"] + "\0" + request["client_email"].casefold()))
                guest_id = guest_identity(db, request["client_email"],
                                          token_hex(16) + ":" + token_hex(32), request["created_at"], identity_id=identity_id)
                db.execute("UPDATE requests SET client_id=? WHERE id=?", (guest_id, request["id"]))
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
        self.record([(user["id"], reason) for user, reason in due])
        return {"clients": dict(Counter(reason for _, reason in due)), "requests": len(closed)}

    def record(self, erased):
        if not erased:
            return
        self.log.touch(mode=0o600)
        with self.log.open("a", encoding="utf-8") as log:
            for user_id, reason in erased:
                entry = {"user_id": user_id, "reason": reason, "at": datetime.now(timezone.utc).isoformat()}
                log.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def replay(self):
        """Erase again, in a restored collection, every client erased since its backup."""
        if not self.log.exists():
            return {"replayed": 0}
        ids = {json.loads(line)["user_id"] for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()}
        replayed = 0
        with self.store.connect(write=True) as db:
            for user_id in sorted(ids):
                user = db.execute(
                    "SELECT * FROM users WHERE id=? AND role='client'", (user_id,)
                ).fetchone()
                if user:
                    self.erase(db, user)
                    replayed += 1
        return {"replayed": replayed}
