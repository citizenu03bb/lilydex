"""Storefront reservation requests: nothing is blocked until the seller accepts.

Accepting creates a lot through the existing sale workflow and reserves it in
the same transaction as the request's answer: a cancellation or another answer
to the same request either comes first and wins, or waits and is refused.
"""

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from .inventory import Conflict, now

EXPIRY = timedelta(days=7)
OPEN_LIMIT = 10  # Open requests per client, against abuse.
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s.]{2,}$")
SALE_STATUS = {
    "draft": "Acceptée",
    "reserved": "Réservée",
    "sold": "Vendue",
    "shipped": "Expédiée",
    "completed": "Terminée",
    "cancelled": "Annulée",
    "returned": "Retournée",
}
REQUEST_STATUS = {
    "sent": "Envoyée",
    "accepted": "Acceptée",
    "partially_accepted": "Acceptée en partie",
    "refused": "Refusée",
    "expired": "Expirée",
    "cancelled": "Annulée",
}


def valid_email(value):
    value = (value or "").strip()
    if len(value) > 254 or not EMAIL.match(value):
        raise ValueError("Adresse e-mail invalide.")
    return value


class Reservations:
    def __init__(self, store, storefront):
        self.store, self.storefront = store, storefront

    # -- Accounts ---------------------------------------------------------

    def signup(self, email, display_name, password_hash):
        """Create a pending client; an existing address is silently left alone."""
        email = valid_email(email)
        with self.store.connect(write=True) as db:
            known = db.execute(
                "SELECT 1 FROM users WHERE email=? OR username=?", (email, email)
            ).fetchone()
            if known:
                return False
            timestamp = now()
            db.execute(
                "INSERT INTO users(id,username,password_hash,role,created_at,email,"
                "display_name,status,consent_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    email,
                    password_hash,
                    "client",
                    timestamp,
                    email,
                    display_name.strip(),
                    "pending",
                    timestamp,
                ),
            )
            return True

    def clients(self):
        with self.store.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,email,display_name,status,disabled,created_at,consent_at "
                    "FROM users WHERE role='client' "
                    "ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, created_at DESC"
                )
            ]

    def set_client(self, client_id, status, disabled):
        with self.store.connect(write=True) as db:
            row = db.execute(
                "SELECT id FROM users WHERE id=? AND role='client'", (client_id,)
            ).fetchone()
            if not row:
                raise KeyError("Client introuvable.")
            db.execute(
                "UPDATE users SET status=?,disabled=? WHERE id=?",
                (status, int(disabled), client_id),
            )
            db.execute("DELETE FROM sessions WHERE user_id=?", (client_id,))
        return {"ok": True}

    # -- Requests ---------------------------------------------------------

    def expire(self, db):
        db.execute(
            "UPDATE requests SET status='expired',updated_at=?,version=version+1 "
            "WHERE status='sent' AND expires_at<?",
            (now(), now()),
        )

    def describe(self, db, row, *, staff=False):
        request = dict(row)
        sale = (
            db.execute("SELECT status FROM sales WHERE id=?", (request["sale_id"],)).fetchone()
            if request["sale_id"]
            else None
        )
        request["status_label"] = (
            SALE_STATUS[sale[0]] if sale else REQUEST_STATUS[request["status"]]
        )
        request["sale_status"] = sale[0] if sale else None
        items = []
        for item in db.execute(
            "SELECT i.listing_id,i.price_cents,i.outcome,l.title FROM request_items i "
            "JOIN listings l ON l.id=i.listing_id WHERE i.request_id=? ORDER BY i.rowid",
            (request["id"],),
        ):
            cards = self.storefront.cards(db, item["listing_id"])
            entry = {
                "listing_id": item["listing_id"],
                "price_cents": item["price_cents"],
                "outcome": item["outcome"],
                "label": item["title"]
                or (cards[0]["name"] if len(cards) == 1 else f"Lot de {len(cards)} cartes"),
                "available": bool(self.storefront.rows(db, item["listing_id"])),
            }
            if staff:
                entry["copies"] = [
                    {"id": c["id"], "name": c["name"], "number": c["number"],
                     "set_name": c["set_name"], "stock_state": c["stock_state"]}
                    for c in cards
                ]
            items.append(entry)
        request["items"] = items
        request["total_cents"] = sum(i["price_cents"] for i in items)
        if not staff:
            request.pop("client_id")
        return request

    def mine(self, client_id):
        with self.store.connect(write=True) as db:
            self.expire(db)
            return [
                self.describe(db, r)
                for r in db.execute(
                    "SELECT * FROM requests WHERE client_id=? ORDER BY created_at DESC",
                    (client_id,),
                ).fetchall()
            ]

    def create(self, client_id, listing_ids, message):
        if not listing_ids or len(listing_ids) != len(set(listing_ids)):
            raise ValueError("Choisissez des cartes distinctes.")
        with self.store.connect(write=True) as db:
            self.expire(db)
            open_count = db.execute(
                "SELECT COUNT(*) FROM requests WHERE client_id=? AND status='sent'",
                (client_id,),
            ).fetchone()[0]
            if open_count >= OPEN_LIMIT:
                raise Conflict("Trop de demandes en attente : attendez une réponse du vendeur.")
            prices = {}
            for listing_id in listing_ids:
                rows = self.storefront.rows(db, listing_id)
                if not rows:
                    raise Conflict("Une carte n’est plus disponible : actualisez la vitrine.")
                prices[listing_id] = rows[0]["price_cents"]
            timestamp = datetime.now(timezone.utc)
            request = {
                "id": str(uuid.uuid4()),
                "client_id": client_id,
                "status": "sent",
                "message": message.strip(),
                "created_at": timestamp.isoformat(),
                "updated_at": timestamp.isoformat(),
                "expires_at": (timestamp + EXPIRY).isoformat(),
            }
            db.execute(
                "INSERT INTO requests(" + ",".join(request) + ") VALUES("
                + ",".join("?" for _ in request) + ")",
                list(request.values()),
            )
            db.executemany(
                "INSERT INTO request_items(request_id,listing_id,price_cents) VALUES(?,?,?)",
                [(request["id"], l, prices[l]) for l in listing_ids],
            )
            return self.describe(db, db.execute("SELECT * FROM requests WHERE id=?", (request["id"],)).fetchone())

    def cancel(self, client_id, request_id, version):
        with self.store.connect(write=True) as db:
            row = db.execute(
                "SELECT * FROM requests WHERE id=? AND client_id=?", (request_id, client_id)
            ).fetchone()
            if not row:
                raise KeyError("Demande introuvable.")
            if row["version"] != version:
                raise Conflict("La demande a changé. Actualisez la page.")
            if row["status"] != "sent":
                raise Conflict("Seule une demande en attente peut être annulée.")
            db.execute(
                "UPDATE requests SET status='cancelled',updated_at=?,version=version+1 WHERE id=?",
                (now(), request_id),
            )
            return self.describe(db, db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone())

    def all(self):
        with self.store.connect(write=True) as db:
            self.expire(db)
            result = []
            for row in db.execute(
                "SELECT r.*,u.email,u.display_name FROM requests r JOIN users u ON u.id=r.client_id "
                "ORDER BY CASE r.status WHEN 'sent' THEN 0 ELSE 1 END, r.created_at DESC"
            ).fetchall():
                request = self.describe(db, row, staff=True)
                result.append(request)
            return result

    def refuse(self, request_id, version, actor, reason):
        if not reason.strip():
            raise ValueError("Précisez le motif.")
        with self.store.connect(write=True) as db:
            self.expire(db)
            row = self.pending(db, request_id, version)
            db.execute(
                "UPDATE requests SET status='refused',decision=?,updated_at=?,version=version+1 WHERE id=?",
                (reason.strip(), now(), request_id),
            )
            db.execute("UPDATE request_items SET outcome='refused' WHERE request_id=?", (request_id,))
            self.log(db, row, actor, "refused", reason)
        return {"ok": True}

    def pending(self, db, request_id, version):
        row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise KeyError("Demande introuvable.")
        if row["version"] != version:
            raise Conflict("La demande a changé. Rechargez-la.")
        if row["status"] != "sent":
            raise Conflict("Cette demande a déjà reçu une réponse ou a expiré.")
        return row

    def log(self, db, row, actor, decision, reason):
        for (listing_id,) in db.execute(
            "SELECT listing_id FROM request_items WHERE request_id=?", (row["id"],)
        ).fetchall():
            for card in self.storefront.cards(db, listing_id):
                db.execute(
                    "INSERT INTO events(copy_id,actor,kind,reason,before_json,after_json,created_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (card["id"], actor, "storefront-request", reason, "{}",
                     json.dumps({"request_id": row["id"], "decision": decision}), now()),
                )

    def accept(self, request_id, version, listing_ids, actor):
        """Accept all or part of a request: the chosen cards become a reserved lot."""
        with self.store.connect(write=True) as db:
            self.expire(db)
            row = self.pending(db, request_id, version)
            client = db.execute(
                "SELECT email,display_name FROM users WHERE id=?", (row["client_id"],)
            ).fetchone()
            items = {
                r["listing_id"]: r["price_cents"]
                for r in db.execute(
                    "SELECT listing_id,price_cents FROM request_items WHERE request_id=?", (request_id,)
                )
            }
            chosen = [l for l in listing_ids if l in items]
            if not chosen or len(chosen) != len(set(listing_ids)):
                raise ValueError("Choisissez des cartes de cette demande.")
            unavailable = [l for l in chosen if not self.storefront.rows(db, l)]
            if unavailable:
                raise Conflict("Une carte choisie n’est plus disponible : retirez-la de l’acceptation.")
            copy_ids = [c["id"] for l in chosen for c in self.storefront.cards(db, l)]
            title = f"Vitrine · {client['display_name'] or client['email']}"
            sale_id = self.store.create_sale(
                {
                    "title": title[:256],
                    "channel": "Vitrine",
                    "notes": f"Demande {request_id} de {client['email']}."
                    + (f"\nMessage : {row['message']}" if row["message"] else ""),
                    "amount_cents": sum(items[l] for l in chosen),
                    "asking_cents": sum(items[l] for l in chosen),
                },
                copy_ids,
                actor,
                _db=db,
            )
            sale_version = db.execute("SELECT version FROM sales WHERE id=?", (sale_id,)).fetchone()[0]
            try:
                self.store.update_sale(
                    sale_id, {"status": "reserved"}, sale_version, actor,
                    "Demande de la vitrine acceptée", _db=db,
                )
            except Conflict:
                # The rollback drops the draft too: the request stays open, nothing is left.
                raise Conflict("Un exemplaire vient d’être réservé ailleurs : rechargez la demande.") from None
            status = "accepted" if set(chosen) == set(items) else "partially_accepted"
            db.execute(
                "UPDATE requests SET status=?,sale_id=?,updated_at=?,version=version+1 WHERE id=?",
                (status, sale_id, now(), request_id),
            )
            for listing_id in items:
                db.execute(
                    "UPDATE request_items SET outcome=? WHERE request_id=? AND listing_id=?",
                    ("accepted" if listing_id in chosen else "refused", request_id, listing_id),
                )
            self.log(db, row, actor, status, "Demande de la vitrine acceptée")
        return {"ok": True, "sale_id": sale_id, "status": status}
