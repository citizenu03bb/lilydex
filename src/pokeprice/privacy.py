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

    def forget(self, who, reason="Demande de la personne"):
        """Erase one client, found by e-mail or account id; staff accounts are never touched."""
        with self.store.connect(write=True) as db:
            user = db.execute(
                "SELECT * FROM users WHERE role='client' AND (email=? COLLATE NOCASE OR id=?)",
                (who.strip(), who.strip()),
            ).fetchone()
            if not user:
                raise KeyError("Client introuvable.")
            result = self.erase(db, user)
        self.record([(user["id"], reason)])
        return result

    def erase(self, db, user):
        requests = db.execute(
            "SELECT id,message,sale_id FROM requests WHERE client_id=?", (user["id"],)
        ).fetchall()
        secrets = [(user["email"], ERASED_CLIENT)]
        if user["display_name"].strip():
            secrets.append((user["display_name"].strip(), ERASED_CLIENT))
        secrets += [(r["message"].strip(), ERASED_MESSAGE) for r in requests if r["message"].strip()]
        request_ids = {r["id"] for r in requests}
        sale_ids = {r["sale_id"] for r in requests if r["sale_id"]}
        # Accepted requests copied the client into their lot and its history.
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
        # Card histories keep the decision, not what the seller wrote about the client.
        for event in db.execute(
            "SELECT id,reason,after_json FROM events WHERE kind='storefront-request'"
        ).fetchall():
            if json.loads(event["after_json"]).get("request_id") in request_ids:
                db.execute(
                    "UPDATE events SET reason=? WHERE id=?", (scrub(event["reason"], secrets), event["id"])
                )
        for request_id in request_ids:
            db.execute("DELETE FROM request_items WHERE request_id=?", (request_id,))
            db.execute("DELETE FROM requests WHERE id=?", (request_id,))
        db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        db.execute("DELETE FROM users WHERE id=?", (user["id"],))
        return {"erased": user["id"], "requests": len(request_ids), "lots": len(sale_ids)}

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
                elif user["status"] == "pending" and at - created > PENDING_ACCOUNTS:
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
