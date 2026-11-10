"""Waiver requests for prices under the anti-undercut floor (decision 0030).

An agent never sells under the floor: its refused publication becomes a
request a person accepts, refuses, or raises to the floor. Requests live in
the events table, like photo requests, without a migration:

- ``floor-request`` (copy_id NULL): the request, its copies and prices;
- ``floor-request-decision`` (copy_id NULL): ``accepted``, ``refused`` or
  ``raised``, by a human account.

A request has two origins: ``publish`` (a refused publication) and ``audit``
(an online publication whose reference rose above its price since).
"""

import json
import uuid
from contextlib import contextmanager

from .inventory import Conflict
from .listings import Listings, is_agent, reference_cents
from .pricing import FLOOR_CENTS, euros, lot_floor_cents, lot_max_margin

REQUEST = "floor-request"
DECISION = "floor-request-decision"
AUDIT_ACTOR = "system:floor-audit"
WAIVER_SOURCE = "Dérogation accordée par "


class HumanOnly(Exception):
    """A decision only a person takes: an agent asked to take it."""


class SharedTransaction:
    """Store whose connections reuse an open transaction: all or nothing."""

    def __init__(self, store, db):
        self._store, self._db = store, db

    def __getattr__(self, name):
        return getattr(self._store, name)

    @contextmanager
    def connect(self, *, write=False):
        yield self._db


def events(db):
    """Requests oldest first, and the decision taken on each."""
    requests, decisions = [], {}
    for row in db.execute(
        "SELECT actor,kind,after_json,created_at FROM events "
        "WHERE copy_id IS NULL AND kind IN (?,?) ORDER BY id",
        (REQUEST, DECISION),
    ):
        data = json.loads(row["after_json"])
        if row["kind"] == REQUEST:
            requests.append({**data, "requested_by": row["actor"], "requested_at": row["created_at"]})
        else:
            decisions[data["request_id"]] = {**data, "by": row["actor"], "at": row["created_at"]}
    return requests, decisions


def record(store, details, actor, *, origin="publish", sale_id="", listing_id=""):
    """Record a waiver request, or return the open one asking the same thing."""
    with store.connect(write=True) as db:
        requests, decisions = events(db)
        for previous in requests:
            if (
                previous["id"] not in decisions
                and previous["origin"] == origin
                and sorted(previous["copy_ids"]) == sorted(details["copy_ids"])
                and previous["price_cents"] == details["price_cents"]
            ):
                return previous["id"]
        request = {
            **details,
            "id": str(uuid.uuid4()),
            "origin": origin,
            "sale_id": sale_id,
            "listing_id": listing_id,
        }
        store.event(
            db, None, actor, REQUEST,
            "Dérogation au plancher demandée : " + request["reason"], {}, request,
        )
        return request["id"]


def open_floor_requests(store):
    """Open waiver requests, oldest first, as the management screens show them."""
    return FloorRequests(store).open()


class FloorRequests:
    def __init__(self, store):
        self.store = store
        self.listings = Listings(store)

    # -- Reading -----------------------------------------------------------

    def open(self):
        with self.store.connect() as db:
            requests, decisions = events(db)
            pending = [r for r in requests if r["id"] not in decisions]
            copies, places, online = {}, {}, {}
            for r in pending:
                for copy_id in r["copy_ids"]:
                    row = db.execute(
                        "SELECT c.*, a.name album FROM copies c JOIN albums a ON a.id=c.album_id WHERE c.id=?",
                        (copy_id,),
                    ).fetchone()
                    copies[copy_id] = dict(row) if row else None
                    current = Listings.active(db, copy_id)
                    places[copy_id] = current["id"] if current else None
                if r["listing_id"]:
                    row = db.execute("SELECT * FROM listings WHERE id=?", (r["listing_id"],)).fetchone()
                    online[r["listing_id"]] = dict(row) if row else None
        cards = self.listings.cards(list(copies)) if copies else {}
        margin = lot_max_margin(self.store)
        result = []
        for r in pending:
            items = [copies[c] for c in r["copy_ids"]]
            # A copy gone, reserved or sold closes the request by itself.
            if any(i is None or i["deleted_at"] or i["stock_state"] != "available" for i in items):
                continue
            if r["origin"] == "audit":
                listing = online.get(r["listing_id"])
                if not listing or listing["state"] != "online" or listing["price_cents"] != r["price_cents"]:
                    continue
            elif r["lot"] and len({places[c] for c in r["copy_ids"]} - {None}) == 1 and all(
                places[c] for c in r["copy_ids"]
            ):
                continue  # Already published together, by someone else.
            refs = {c: reference_cents(cards[c]) if c in cards else 0 for c in r["copy_ids"]}
            total = sum(refs.values())
            result.append(
                {
                    "id": r["id"],
                    "origin": r["origin"],
                    "requested_by": r["requested_by"],
                    "requested_at": r["requested_at"],
                    "lot": r["lot"],
                    "title": r["title"],
                    "copy_ids": r["copy_ids"],
                    "sale_id": r["sale_id"],
                    "listing_id": r["listing_id"],
                    "price_cents": r["price_cents"],
                    "floor_cents": r["floor_cents"],
                    "current_floor_cents": max(FLOOR_CENTS, lot_floor_cents(total, margin)) if total else FLOOR_CENTS,
                    "total_reference_cents": r["total_reference_cents"],
                    "margin": r["margin"],
                    "reason": r["reason"],
                    "refusal": r["refusal"],
                    "items": [
                        {
                            "copy_id": c,
                            "name": i["name"],
                            "set_name": i["set_name"],
                            "number": i["number"],
                            "language": i["language"],
                            "album": i["album"],
                            "page": i["page"],
                            "position": i["position"],
                            "reference_cents": refs[c],
                        }
                        for c, i in zip(r["copy_ids"], items)
                    ],
                }
            )
        return result

    def get(self, request_id):
        found = next((r for r in self.open() if r["id"] == request_id), None)
        if not found:
            raise KeyError("Demande de dérogation introuvable ou déjà close.")
        return found

    # -- Deciding ------------------------------------------------------------

    @staticmethod
    def human(actor):
        if is_agent(actor):
            raise HumanOnly("Une dérogation au plancher se décide par une personne, jamais par un agent.")

    def decide(self, db, request, actor, decision, reason, listing_id=None):
        self.store.event(
            db, None, actor, DECISION,
            {
                "accepted": f"Dérogation accordée par {actor}",
                "refused": f"Dérogation refusée par {actor}",
                "raised": f"Prix relevé au plancher par {actor}",
            }[decision]
            + (" : " + reason.strip() if reason.strip() else ""),
            {},
            {"request_id": request["id"], "decision": decision, "listing_id": listing_id, "reason": reason.strip()},
        )

    def put_online(self, request, actor, price_cents, decision, reason, waiver_by=""):
        """Publish the copies of a refused publication, in one transaction."""
        with self.store.connect(write=True) as db:
            listings = Listings(SharedTransaction(self.store, db))
            if request["lot"]:
                # Like the lots tool: single publications give way to the lot.
                for copy_id in request["copy_ids"]:
                    current = Listings.active(db, copy_id)
                    if not current:
                        continue
                    count = db.execute(
                        "SELECT COUNT(*) FROM listing_items WHERE listing_id=? AND active=1",
                        (current["id"],),
                    ).fetchone()[0]
                    if count > 1:
                        raise Conflict("Un exemplaire est déjà dans un autre lot en ligne.")
                    listings.unpublish(
                        current["id"], current["version"], actor,
                        f"Regroupement dans le lot « {request['title']} »",
                    )
            listing = listings.publish(
                request["copy_ids"], actor, price_cents=price_cents, title=request["title"],
                lot=request["lot"], waiver_by=waiver_by,
            )
            if request["sale_id"]:
                sale = db.execute("SELECT * FROM sales WHERE id=?", (request["sale_id"],)).fetchone()
                if sale and sale["status"] == "draft":
                    self.store.update_sale(
                        sale["id"],
                        {
                            "channel": "Vitrine",
                            "amount_cents": price_cents,
                            "notes": ((sale["notes"] or "") + f"\nPublié en vitrine : annonce {listing['id']}").strip(),
                        },
                        sale["version"], actor, "Publication du lot en vitrine publique", _db=db,
                    )
            self.decide(db, request, actor, decision, reason, listing["id"])
        return listing

    def reprice(self, request, actor, price_cents, decision, reason, source):
        with self.store.connect() as db:
            version = db.execute(
                "SELECT version FROM listings WHERE id=?", (request["listing_id"],)
            ).fetchone()[0]
        with self.store.connect(write=True) as db:
            listing = Listings(SharedTransaction(self.store, db)).reprice(
                request["listing_id"], version, price_cents, actor,
                {
                    "accepted": f"Prix maintenu sous le plancher, dérogation accordée par {actor}",
                    "raised": f"Prix relevé au plancher anti-bradage par {actor}",
                }[decision],
                source,
            )
            self.decide(db, request, actor, decision, reason, listing["id"])
        return listing

    def accept(self, request_id, actor, reason=""):
        """Publish at the requested price, traced as a waiver granted by ``actor``."""
        self.human(actor)
        request = self.get(request_id)
        if request["origin"] == "audit":
            listing = self.reprice(
                request, actor, request["price_cents"], "accepted", reason, WAIVER_SOURCE + actor
            )
        else:
            listing = self.put_online(
                request, actor, request["price_cents"], "accepted", reason, waiver_by=actor
            )
        return {"request_id": request_id, "decision": "accepted", "listing": listing}

    def raise_to_floor(self, request_id, actor, reason=""):
        """Publish, or reprice, at today's floor instead of the requested price."""
        self.human(actor)
        request = self.get(request_id)
        floor = request["current_floor_cents"]
        if request["origin"] == "audit":
            listing = self.reprice(
                request, actor, floor, "raised", reason, "Plancher anti-bradage"
            )
        else:
            listing = self.put_online(request, actor, floor, "raised", reason)
        return {"request_id": request_id, "decision": "raised", "listing": listing}

    def refuse(self, request_id, actor, reason=""):
        self.human(actor)
        request = self.get(request_id)
        with self.store.connect(write=True) as db:
            self.decide(db, request, actor, "refused", reason)
        return {"request_id": request_id, "decision": "refused", "listing": None}

    # -- Audit ---------------------------------------------------------------

    def below_floor(self):
        """Online publications priced under today's floor, read only.

        A publication whose price a person kept by waiver is left out until
        its price changes; one with no reference at all has no floor to check.
        """
        online = [l for l in self.listings.all("online") if l["available"]]
        ids = [i["id"] for l in online for i in l["items"]]
        cards = self.listings.cards(ids) if ids else {}
        margin = lot_max_margin(self.store)
        found = []
        for listing in online:
            if listing["price_source"].startswith(WAIVER_SOURCE):
                continue
            copy_ids = [i["id"] for i in listing["items"]]
            if any(c not in cards for c in copy_ids):
                continue
            refs = {c: reference_cents(cards[c]) for c in copy_ids}
            total = sum(refs.values())
            if not total:
                continue
            floor = max(FLOOR_CENTS, lot_floor_cents(total, margin))
            if listing["price_cents"] >= floor:
                continue
            lot = len(copy_ids) > 1
            refusal = (
                f"{'Lot' if lot else listing['items'][0]['name']} en ligne à "
                f"{euros(listing['price_cents'] / 100)}, sous le plancher de {euros(floor / 100)} "
                f"({'somme des références' if lot else 'référence'} {euros(total / 100)} moins {margin} %)."
            )
            found.append(
                {
                    "listing_id": listing["id"],
                    "version": listing["version"],
                    "title": listing["title"] or listing["items"][0]["name"],
                    "lot": lot,
                    "copy_ids": copy_ids,
                    "price_cents": listing["price_cents"],
                    "floor_cents": floor,
                    "raise_to_cents": floor,
                    "references": [{"copy_id": c, "reference_cents": refs[c]} for c in copy_ids],
                    "total_reference_cents": total,
                    "margin": margin,
                    "refusal": refusal,
                }
            )
        return found

    def audit(self, *, record_requests=False, actor=AUDIT_ACTOR):
        """List online publications under the floor; with ``record_requests``,
        ask a person to keep or raise each price. Nothing is ever republished."""
        found = self.below_floor()
        for entry in found:
            entry["request_id"] = None
            if record_requests:
                entry["request_id"] = record(
                    self.store,
                    {
                        "copy_ids": entry["copy_ids"],
                        "lot": entry["lot"],
                        "title": entry["title"] if entry["lot"] else "",
                        "price_cents": entry["price_cents"],
                        "floor_cents": entry["floor_cents"],
                        "references": entry["references"],
                        "total_reference_cents": entry["total_reference_cents"],
                        "margin": entry["margin"],
                        "refusal": entry["refusal"],
                        "reason": "La cote a monté depuis la publication : garder ce prix ou le relever au plancher.",
                    },
                    actor,
                    origin="audit",
                    listing_id=entry["listing_id"],
                )
        return {"below_floor": found, "count": len(found), "recorded": record_requests}
