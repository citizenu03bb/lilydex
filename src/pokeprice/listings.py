"""Storefront publications: a single card or a lot, each at one displayed price."""

import json
import re
import sqlite3
import uuid
from urllib.parse import quote, urlencode

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

    def publish(
        self, copy_ids, actor, *, price_cents=None, title="", lot=False,
        price_mode="manual", price_source="Prix fixé à la main",
    ):
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
        # An imposed price keeps its origin, e.g. a trend to review later.
        override = (
            {"amount_cents": price_cents, "mode": price_mode, "source": price_source}
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
            "mode": price_mode,
            "source": price_source,
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


# The storefront shows only these fields, built one by one: nothing private
# (notes, provenance, history, album place, copy ids, raw prices) can leak.
# Codes only: the storefront's dictionaries name them (docs/decisions/0020).
FINISHES = ("non_holo", "holo", "holo_border", "reverse", "special")
CONDITIONS = ("MT", "NM", "NM/EX", "EX", "GD", "LP", "PL", "PO")


def public_condition(card):
    """Only an explicitly confirmed, nonempty grade is public."""
    return (card["condition"] or None) if card["condition_confirmed"] else None


def public_item(index, card):
    return {
        "index": index,
        "name": card["name"],
        "set_name": card["set_name"],
        "number": card["number"],
        "language": card["language"],
        # An estimated condition is never shown as a fact.
        "condition": public_condition(card),
        "finish": card["finish"] if card["finish"] in FINISHES else None,
        "stamp": card["stamp"] if card["stamp_state"] == "present" else None,
        "distribution": (
            card["distribution"] if card["distribution_state"] == "present" else None
        ),
        "photos": [
            side for side, key in (("front", "photo"), ("back", "back_photo")) if card[key]
        ],
    }


def one_slip(a, b):
    """True when b is a with one letter added, removed, changed or swapped."""
    if a == b or abs(len(a) - len(b)) > 1:
        return a == b
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    if len(a) == len(b):
        return a[i + 1 :] == b[i + 1 :] or (a[i : i + 2] == b[i : i + 2][::-1] and a[i + 2 :] == b[i + 2 :])
    longer, shorter = (a, b) if len(a) > len(b) else (b, a)
    return longer[i + 1 :] == shorter[i:]


def near(term, text):
    """A search term found as is, or within one slip of a word for terms of five letters or more."""
    if term in text:
        return True
    return len(term) >= 5 and any(one_slip(term, word) for word in re.findall(r"\w+", text))


class Storefront:
    """Read-only view of online publications whose copies are all available."""

    def __init__(self, store):
        self.store = store
        from .public_media import PublicMedia

        self.media = PublicMedia(store.root)

    def rows(self, db, listing_id=None):
        rows = db.execute(
            "SELECT l.id,l.title,l.price_cents,l.price_date,l.published_at FROM listings l "
            "WHERE l.state='online' AND (? IS NULL OR l.id=?) AND NOT EXISTS ("
            " SELECT 1 FROM listing_items i JOIN copies c ON c.id=i.copy_id"
            " WHERE i.listing_id=l.id AND i.active=1"
            " AND (c.stock_state!='available' OR c.deleted_at!=''))",
            (listing_id, listing_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def cards(self, db, listing_id):
        return [
            dict(r)
            for r in db.execute(
                "SELECT c.* FROM listing_items i JOIN copies c ON c.id=i.copy_id "
                "WHERE i.listing_id=? AND i.active=1 ORDER BY i.rowid",
                (listing_id,),
            )
        ]

    def public(self, row, cards):
        items = []
        for index, card in enumerate(cards):
            item = public_item(index, card)
            item["media"] = {}
            for side, field in (("front", "photo"), ("back", "back_photo")):
                if not card[field]:
                    continue
                try:
                    description = self.media.describe(self.store.photos / card[field])
                except (OSError, ValueError):
                    # A missing/broken file must not hide the whole catalogue.
                    continue
                variants = []
                for variant in description["variants"]:
                    formats = ("jpeg",) if variant["size"] == "thumb" else variant.get("formats", self.media.formats)
                    for format in formats:
                        query = urlencode({"item": index, "side": side, "size": variant["size"], "format": format})
                        variants.append({
                            "size": variant["size"], "width": variant["width"],
                            "height": variant["height"], "format": format,
                            "url": f"/api/public/listings/{quote(row['id'], safe='')}/photo?{query}",
                        })
                item["media"][side] = {
                    "width": description["width"], "height": description["height"],
                    "variants": variants,
                }
            items.append(item)
        return {
            "id": row["id"],
            "title": row["title"],
            "price_cents": row["price_cents"],
            "price_date": (row["price_date"] or row["published_at"])[:10],
            "items": items,
        }

    def search(
        self, query="", language="", max_cents=None, sort="recent", limit=48, offset=0,
        *, extension="", finish="", condition="",
    ):
        """Filter all available publications before sorting and pagination."""
        from .inventory import normalized

        terms = normalized(query).split()
        with self.store.connect() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT l.id,l.title,l.price_cents,l.price_date,l.published_at FROM listings l "
                    "WHERE l.state='online' AND NOT EXISTS ("
                    " SELECT 1 FROM listing_items i JOIN copies c ON c.id=i.copy_id"
                    " WHERE i.listing_id=l.id AND i.active=1"
                    " AND (c.stock_state!='available' OR c.deleted_at!=''))"
                )
            ]
            cards = {}
            for row in db.execute(
                "SELECT i.listing_id, c.* FROM listing_items i JOIN copies c ON c.id=i.copy_id "
                "JOIN listings l ON l.id=i.listing_id WHERE i.active=1 AND l.state='online' "
                "ORDER BY i.rowid"
            ):
                card = dict(row)
                cards.setdefault(card.pop("listing_id"), []).append(card)
            # Visitors search in their own language: Eevee finds Évoli.
            names = dict(
                db.execute(
                    "SELECT catalog_id, group_concat(name, ' ') FROM catalog_names GROUP BY catalog_id"
                ).fetchall()
            )
        # Facets describe all available publications, not just the current page.
        on_sale = [c for row in rows for c in cards.get(row["id"], [])]
        languages = sorted({c["language"] for c in on_sale} - {""})
        extensions = sorted({c["set_name"] for c in on_sale} - {""}, key=normalized)
        finishes = [key for key in FINISHES if any(c["finish"] == key for c in on_sale)]
        public_grades = {public_condition(c) for c in on_sale}
        conditions = [grade for grade in CONDITIONS if grade in public_grades]
        if None in public_grades:
            conditions.append("unknown")
        candidates = []
        for row in rows:
            items = cards.get(row["id"], [])
            if not items:
                continue
            # A lot must contain a card satisfying all card-level criteria.
            # Its price and contents remain those of the whole publication.
            if not any(
                (not language or c["language"] == language)
                and (not extension or c["set_name"] == extension)
                and (not finish or c["finish"] == finish)
                and (not condition or (public_condition(c) is None if condition == "unknown" else public_condition(c) == condition))
                for c in items
            ):
                continue
            if max_cents is not None and row["price_cents"] > max_cents:
                continue
            text = normalized(
                " ".join(
                    f"{c['name']} {names.get(c['catalog_id'], '')} {c['set_name']} {c['number']}"
                    for c in items
                )
                + " "
                + row["title"]
            )
            candidates.append((row, items, text))
        approximate = False
        matching = [p for p in candidates if all(t in p[2] for t in terms)]
        if terms and not matching:
            # One slip of the keyboard is forgiven, and the page says so.
            matching = [p for p in candidates if all(near(t, p[2]) for t in terms)]
            approximate = bool(matching)
        # A bulk publication takes minutes: within one day the name, then the id,
        # set the order, so it reads naturally and pages never overlap.
        matching.sort(key=lambda p: (normalized(p[0]["title"] or p[1][0]["name"]), p[0]["id"]))
        if sort != "name":
            matching.sort(key=lambda p: p[0]["published_at"][:10], reverse=True)
        if sort in ("price", "price_desc"):
            matching.sort(key=lambda p: p[0]["price_cents"], reverse=sort == "price_desc")
        result = {
            # Decode photo dimensions only for the returned page, never the whole catalogue.
            "items": [self.public(row, items) for row, items, _ in matching[offset : offset + limit]],
            "total": len(matching),
            "languages": languages, "extensions": extensions, "finishes": finishes,
            "conditions": conditions,
        }
        if approximate:
            result["approximate"] = True
        return result

    def get(self, listing_id):
        with self.store.connect() as db:
            rows = self.rows(db, listing_id)
            if not rows:
                raise KeyError("Carte absente de la vitrine.")
            return self.public(rows[0], self.cards(db, listing_id))

    def photo(self, listing_id, index, side, size):
        with self.store.connect() as db:
            if not self.rows(db, listing_id):
                raise KeyError("Carte absente de la vitrine.")
            cards = self.cards(db, listing_id)
        if not 0 <= index < len(cards):
            raise KeyError("Photo absente.")
        name = cards[index]["photo" if side == "front" else "back_photo"]
        if not name:
            raise KeyError("Photo absente.")
        return self.store.thumbnail(name) if size == "thumb" else self.store.photos / name
