"""Storefront publications: a single card or a lot, each at one displayed price."""

import json
import sqlite3
import uuid

from .inventory import Conflict, now
from .pricing import FLOOR_CENTS, display_price, euros, round_up_tenth

# What the management screens show of each published copy.
ITEM_FIELDS = (
    "id",
    "name",
    "set_name",
    "number",
    "language",
    "condition",
    "finish",
    "stamp",
    "stock_state",
    "deleted_at",
    "photo",
)


class Listings:
    def __init__(self, store):
        self.store = store

    def cards(self, copy_ids=None):
        """Copies with their valuation, as the collection listing computes it."""
        rows = self.store.listing(limit=10**9)["items"]
        wanted = set(copy_ids) if copy_ids is not None else None
        return {r["id"]: r for r in rows if wanted is None or r["id"] in wanted}

    def proposal(self, copy_id):
        card = self.cards([copy_id]).get(copy_id)
        if card is None:
            with self.store.connect() as db:
                card = self.store.get(db, copy_id)  # deleted: no valuation needed
            return display_price(card, {})
        return display_price(card, card["valuation"])

    @staticmethod
    def active(db, copy_id):
        row = db.execute(
            "SELECT l.* FROM listings l JOIN listing_items i ON i.listing_id=l.id "
            "WHERE i.copy_id=? AND i.active=1",
            (copy_id,),
        ).fetchone()
        return dict(row) if row else None

    def event(self, db, copy_id, actor, kind, reason, before, after):
        db.execute(
            "INSERT INTO events(copy_id,actor,kind,reason,before_json,after_json,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                copy_id,
                actor,
                kind,
                reason,
                json.dumps(before or {}, ensure_ascii=False),
                json.dumps(after or {}, ensure_ascii=False),
                now(),
            ),
        )

    def publish(self, copy_ids, actor, *, price_cents=None, title="", lot=False):
        """Publish one copy, or several copies as one lot at a single price.

        A copy alone takes its computed price unless a manual price is given; a lot
        always needs an explicit price, and the floor applies to the lot as a whole.
        """
        if not copy_ids or len(copy_ids) != len(set(copy_ids)):
            raise ValueError("Sélectionnez des exemplaires distincts.")
        if lot and len(copy_ids) < 2:
            raise ValueError("Un lot réunit au moins deux exemplaires.")
        if len(copy_ids) > 1 and not lot:
            raise ValueError("Plusieurs exemplaires : publiez-les en lot, ou un par un.")
        if lot and price_cents is None:
            raise ValueError("Fixez le prix du lot.")
        cards = self.cards(copy_ids)
        override = (
            {"amount_cents": price_cents, "mode": "manual", "source": "Prix fixé à la main"}
            if price_cents is not None
            else None
        )
        proposals = {}
        for copy_id in copy_ids:
            card = cards.get(copy_id)
            if card is None:
                raise Conflict("Un exemplaire a été supprimé de la collection.")
            proposals[copy_id] = display_price(
                card,
                card["valuation"],
                # The floor of a lot is checked on its total, not on each card.
                {**override, "amount_cents": FLOOR_CENTS} if lot else override,
            )
            if not proposals[copy_id]["publishable"]:
                raise ValueError(
                    f"{card['name']} : " + " ".join(proposals[copy_id]["reasons"])
                )
        if lot and price_cents < FLOOR_CENTS:
            raise ValueError(f"Un lot se vend au moins {euros(FLOOR_CENTS / 100)}.")
        chosen = proposals[copy_ids[0]] if not lot else {
            "price_cents": price_cents,
            "mode": "manual",
            "source": "Prix fixé à la main",
            "date": now(),
        }
        timestamp = now()
        with self.store.connect(write=True) as db:
            for copy_id in copy_ids:
                card = self.store.get(db, copy_id)
                if card["deleted_at"] or card["stock_state"] != "available":
                    raise Conflict("Un exemplaire a été réservé, vendu ou supprimé entre-temps.")
            current = self.active(db, copy_ids[0]) if not lot else None
            if current and db.execute(
                "SELECT COUNT(*) FROM listing_items WHERE listing_id=? AND active=1",
                (current["id"],),
            ).fetchone()[0] == 1:
                # Publishing a card again only updates the price of its publication.
                changes = {
                    "price_cents": chosen["price_cents"],
                    "price_mode": chosen["mode"],
                    "price_source": chosen["source"],
                    "price_date": chosen["date"] or "",
                }
                db.execute(
                    "UPDATE listings SET price_cents=?,price_mode=?,price_source=?,price_date=?,"
                    "updated_at=?,version=version+1 WHERE id=?",
                    (*changes.values(), timestamp, current["id"]),
                )
                self.event(db, copy_ids[0], actor, "listing", "Prix de vitrine mis à jour", current, changes)
                return self.get(db, current["id"])
            listing = {
                "id": str(uuid.uuid4()),
                "title": title.strip(),
                "state": "online",
                "price_cents": chosen["price_cents"],
                "price_mode": chosen["mode"],
                "price_source": chosen["source"],
                "price_date": chosen["date"] or "",
                "published_at": timestamp,
                "published_by": actor,
                "updated_at": timestamp,
            }
            db.execute(
                "INSERT INTO listings(" + ",".join(listing) + ") VALUES("
                + ",".join("?" for _ in listing) + ")",
                list(listing.values()),
            )
            try:
                db.executemany(
                    "INSERT INTO listing_items(listing_id,copy_id) VALUES(?,?)",
                    [(listing["id"], c) for c in copy_ids],
                )
            except sqlite3.IntegrityError:
                raise Conflict("Un exemplaire est déjà publié : retirez d’abord sa publication.")
            for copy_id in copy_ids:
                self.event(
                    db, copy_id, actor, "listing",
                    "Publication en lot dans la vitrine" if lot else "Publication dans la vitrine",
                    {}, listing,
                )
            return self.get(db, listing["id"])

    def unpublish(self, listing_id, version, actor, reason):
        if not reason.strip():
            raise ValueError("Précisez le motif.")
        with self.store.connect(write=True) as db:
            before = db.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
            if not before:
                raise KeyError("Publication introuvable.")
            if before["version"] != version:
                raise Conflict("La publication a changé. Rechargez-la avant de la retirer.")
            if before["state"] == "offline":
                raise Conflict("Cette publication est déjà retirée.")
            copies = [
                r[0]
                for r in db.execute(
                    "SELECT copy_id FROM listing_items WHERE listing_id=? AND active=1", (listing_id,)
                )
            ]
            db.execute(
                "UPDATE listings SET state='offline',updated_at=?,version=version+1 WHERE id=?",
                (now(), listing_id),
            )
            db.execute("UPDATE listing_items SET active=0 WHERE listing_id=?", (listing_id,))
            for copy_id in copies:
                self.event(db, copy_id, actor, "unlisting", reason, dict(before), {"state": "offline"})
            return self.get(db, listing_id)

    def get(self, db, listing_id):
        row = db.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
        if not row:
            raise KeyError("Publication introuvable.")
        listing = dict(row)
        items = []
        for (copy_id,) in db.execute(
            "SELECT copy_id FROM listing_items WHERE listing_id=? ORDER BY rowid", (listing_id,)
        ):
            card = self.store.get(db, copy_id)
            items.append({k: card[k] for k in ITEM_FIELDS})
        listing["items"] = items
        # Reserved, sold or deleted copies take the publication out of the storefront.
        listing["available"] = listing["state"] == "online" and all(
            i["stock_state"] == "available" and not i["deleted_at"] for i in items
        )
        return listing

    def all(self, state="online"):
        with self.store.connect() as db:
            listings = [
                self.get(db, r[0])
                for r in db.execute(
                    "SELECT id FROM listings WHERE (?='' OR state=?) ORDER BY published_at DESC",
                    (state, state),
                )
            ]
        trend_items = [
            l["items"][0]["id"] for l in listings if l["price_mode"] == "trend" and len(l["items"]) == 1
        ]
        cards = self.cards(trend_items) if trend_items else {}
        for listing in listings:
            listing["drift"] = None
            card = cards.get(listing["items"][0]["id"]) if listing["items"] else None
            if card and listing["price_mode"] == "trend":
                current = card["valuation"].get("trend_cents")
                # A newer reading never changes the displayed price by itself.
                if current is not None and round_up_tenth(current) != listing["price_cents"]:
                    listing["drift"] = {
                        "current_cents": round_up_tenth(current),
                        "price_date": card.get("price_date") or "",
                    }
        return listings
