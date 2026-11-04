"""The management assistant, V0: what the agent did, and what waits for Lily.

The agents act alone (decisions 0021 and 0022); what is left to a person is
a short list: photos the review agent asked for, storefront requests to
answer, lots to ship, and the floor waivers (decision 0030). Each
source is a small function that returns ``Item`` values; ``Todo`` sorts
them into one queue and adds up the minutes.

``done_since`` only counts events the application already records (events
and sale_events tables); it writes nothing and invents no history.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from .agent_review import run_events

# Groups in the queue, most urgent first: a request expires, a paid lot waits
# for its parcel, a photo can wait for the next session at the binder.
RANK = {"request": 10, "floor": 20, "ship": 30, "payment": 40, "photo": 50}
# Rough minutes per item, for the morning estimate only.
MINUTES = {"request": 3, "floor": 2, "ship": 10, "payment": 2, "photo": 1}
VIEWS = ("front", "back", "holo", "corner")


@dataclass
class Item:
    """One decision or gesture for Lily.

    ``action`` names an existing screen: ``view`` (collection or sales), the
    ``target`` element to bring into view, and, for a photo, the copy.
    """

    kind: str
    title: str
    reason: str
    action: dict
    key: tuple = ()
    minutes: int = 0
    id: str = ""
    data: dict = field(default_factory=dict)

    def __post_init__(self):
        self.minutes = self.minutes or MINUTES.get(self.kind, 2)


def card_label(card):
    return " ".join(filter(None, [card.get("name"), card.get("number")])) or "Carte"


def euros(cents):
    return f"{(cents or 0) / 100:.2f} €".replace(".", ",")


def photo_items(photo_requests):
    """``photo_requests()`` is AgentReview.photo_requests: binder order already."""

    def source():
        items = []
        for rank, request in enumerate(photo_requests()):
            view = request["view"] if request["view"] in VIEWS else "front"
            items.append(Item(
                kind="photo",
                id=f"photo-{request['copy_id']}-{request['side']}",
                title=f"{card_label(request)} · {request['album']} p. {request['page']}, "
                f"pochette {request['position']}",
                reason=request["reason"],
                action={
                    "view": "collection",
                    "target": f"photo-request-{request['copy_id']}-{request['side']}",
                    "copy_id": request["copy_id"],
                },
                key=(rank,),
                data={"view": view, "copy_id": request["copy_id"], "name": request["name"],
                      "number": request["number"], "album": request["album"],
                      "page": request["page"], "position": request["position"]},
            ))
        return items

    return source


def reservation_items(store):
    """Storefront requests to answer, reserved lots to confirm, sold lots to ship."""

    def source():
        items = []
        moment = datetime.now(timezone.utc).isoformat()
        with store.connect() as db:
            for row in db.execute(
                "SELECT r.id,r.created_at,r.expires_at,COUNT(i.listing_id) cards,"
                "COALESCE(SUM(i.price_cents),0) total FROM requests r "
                "JOIN request_items i ON i.request_id=r.id "
                "WHERE r.status='sent' AND r.expires_at>=? GROUP BY r.id ORDER BY r.expires_at",
                (moment,),
            ):
                plural = "s" if row["cards"] > 1 else ""
                items.append(Item(
                    kind="request",
                    id=f"request-{row['id']}",
                    title=f"Demande : {row['cards']} carte{plural}, {euros(row['total'])}",
                    reason=f"Accepter ou refuser avant le {row['expires_at'][:10]}, sinon elle expire.",
                    action={"view": "sales", "target": f"demande-{row['id']}", "request_id": row["id"]},
                    key=(row["expires_at"],),
                    data={"cards": row["cards"], "total_cents": row["total"],
                          "expires_at": row["expires_at"]},
                ))
            for row in db.execute(
                "SELECT s.id,s.title,s.status,s.paid,s.amount_cents,s.shipping_charged_cents,"
                "s.updated_at,COUNT(i.copy_id) cards FROM sales s "
                "LEFT JOIN sale_items i ON i.sale_id=s.id "
                "WHERE s.status IN ('reserved','sold') GROUP BY s.id ORDER BY s.updated_at"
            ):
                total = row["amount_cents"] + row["shipping_charged_cents"]
                target = {"view": "sales", "target": f"vente-{row['id']}", "sale_id": row["id"]}
                if row["status"] == "sold":
                    items.append(Item(
                        kind="ship", id=f"ship-{row['id']}",
                        title=f"À expédier : {row['title']}",
                        reason="Vente confirmée : préparer l’enveloppe, puis marquer le lot expédié.",
                        action=target, key=(row["updated_at"],),
                        data={"cards": row["cards"], "total_cents": total, "title": row["title"]},
                    ))
                else:
                    paid = bool(row["paid"])
                    items.append(Item(
                        kind="payment", id=f"payment-{row['id']}",
                        title=f"Réservé : {row['title']} · {euros(total)}",
                        reason="Paiement noté : confirmer la vente pour libérer l’envoi."
                        if paid else "Vérifier si le paiement est arrivé, puis confirmer la vente.",
                        action=target, key=(not paid, row["updated_at"]),
                        data={"cards": row["cards"], "total_cents": total, "paid": paid,
                              "title": row["title"]},
                    ))
        return items

    return source


def floor_items(floor_requests):
    """Floor waivers waiting for a person (decision 0030).

    ``floor_requests()`` returns the open requests as ``FloorRequests.open``
    does: ``id``, ``title``, ``items``, ``copy_ids``, ``price_cents``,
    ``floor_cents`` (or ``current_floor_cents``, preferred) and ``reason``.
    """

    def source():
        items = []
        for rank, request in enumerate(floor_requests()):
            price = request.get("price_cents")
            floor = request.get("current_floor_cents", request.get("floor_cents"))
            reason = request.get("reason") or "Prix demandé sous le plancher anti-bradage."
            if price is not None and floor is not None:
                reason = f"{euros(price)} demandé, plancher {euros(floor)}. {reason}"
            items.append(Item(
                kind="floor", id=f"floor-{request['id']}",
                title=request.get("title")
                or ", ".join(card_label(i) for i in request.get("items", []))
                or card_label(request),
                reason=reason,
                action={"view": "collection", "target": f"floor-request-{request['id']}",
                        "floor_request_id": request["id"]},
                key=(rank,),
                data={"price_cents": price, "floor_cents": floor,
                      "copy_ids": request.get("copy_ids", [])},
            ))
        return items

    return source


class Todo:
    """The sources in one queue; ``register`` adds one (name, function)."""

    def __init__(self, store, photo_requests=None, floor_requests=None):
        self.store = store
        self.sources = {}
        if photo_requests is not None:
            self.register("photos", photo_items(photo_requests))
        self.register("reservations", reservation_items(store))
        # Only when the floor service exists (decision 0030).
        if floor_requests is not None:
            self.register("floor", floor_items(floor_requests))

    def register(self, name, source):
        self.sources[name] = source

    def waiting(self):
        items = [item for source in self.sources.values() for item in source()]
        items.sort(key=lambda item: (RANK.get(item.kind, 90), item.key))
        result = []
        for order, item in enumerate(items):
            entry = asdict(item)
            entry.pop("key")
            entry["order"] = order
            result.append(entry)
        return result

    def done_since(self, since):
        """Counts from the recorded events since ``since`` (ISO 8601)."""
        with self.store.connect() as db:
            runs, undone = run_events(db)
            confirmed = asked = passes = 0
            for run_id, run in runs.items():
                if run["created_at"] < since or run_id in undone:
                    continue
                passes += 1
                confirmed += len(run.get("confirmed", []))
                asked += run.get("photo_requests", 0)
            published, unpublished = {}, set()
            for row in db.execute(
                "SELECT kind,before_json,after_json FROM events "
                "WHERE kind IN ('listing','unlisting') AND created_at>=? ORDER BY id",
                (since,),
            ):
                before, after = json.loads(row["before_json"]), json.loads(row["after_json"])
                if row["kind"] == "unlisting":
                    unpublished.add(before.get("id"))
                elif not before and after.get("id"):  # A price update has a before.
                    published[after["id"]] = published.get(after["id"], 0) + 1
            sales = {}
            sold_cents = 0
            for row in db.execute(
                "SELECT before_json,after_json FROM sale_events WHERE created_at>=? ORDER BY id",
                (since,),
            ):
                before, after = json.loads(row["before_json"]), json.loads(row["after_json"])
                status = after.get("status")
                # A sale created as a draft is not a step yet; one created reserved is.
                if status and status != "draft" and before.get("status") != status:
                    sales[status] = sales.get(status, 0) + 1
                    if status == "sold":
                        sold_cents += after.get("amount_cents", 0)
            received = db.execute(
                "SELECT COUNT(*) FROM requests WHERE created_at>=?", (since,)
            ).fetchone()[0]
            answered = {}
            for row in db.execute(
                "SELECT after_json FROM events WHERE kind='storefront-request' AND created_at>=?",
                (since,),
            ):
                after = json.loads(row["after_json"])
                answered[after.get("request_id")] = after.get("decision")
        decisions = {}
        for decision in answered.values():
            decisions[decision] = decisions.get(decision, 0) + 1
        return {
            "since": since,
            "agent": {"passes": passes, "confirmed": confirmed, "photos_asked": asked},
            "listings": {
                "published": len(published),
                "lots": sum(1 for count in published.values() if count > 1),
                "cards": sum(published.values()),
                "unpublished": len(unpublished),
            },
            "sales": {"transitions": sales, "sold_cents": sold_cents},
            "requests": {"received": received, "answered": decisions},
        }

    def brief(self, since=None):
        since = since or default_since()
        waiting = self.waiting()
        return {
            "done_since": self.done_since(since),
            "waiting": waiting,
            "minutes": sum(item["minutes"] for item in waiting),
        }


def default_since(moment=None):
    """The last 24 hours: a morning brief covers the day before."""
    return ((moment or datetime.now(timezone.utc)) - timedelta(days=1)).isoformat()


def parse_since(value):
    """A date (2026-11-03) or a full ISO moment, read as UTC when naive."""
    moment = datetime.fromisoformat(value.strip())
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def brief_text(brief):
    """Title and body of the pushed brief: counts only, no client data."""
    done, waiting = brief["done_since"], brief["waiting"]
    kinds = {}
    for item in waiting:
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    if waiting:
        title = f"À toi : {len(waiting)} chose{'s' if len(waiting) > 1 else ''}, environ {brief['minutes']} min"
    else:
        title = "Rien ne t’attend aujourd’hui"
    lines = []
    agent, listings, sales = done["agent"], done["listings"], done["sales"]["transitions"]
    made = []
    if agent["confirmed"]:
        made.append(f"{agent['confirmed']} carte(s) confirmée(s) par l’agent")
    if listings["published"]:
        made.append(f"{listings['published']} annonce(s) publiée(s)")
    if listings["unpublished"]:
        made.append(f"{listings['unpublished']} retirée(s)")
    if sales.get("sold"):
        made.append(f"{sales['sold']} vente(s), {euros(done['sales']['sold_cents'])}")
    if done["requests"]["received"]:
        made.append(f"{done['requests']['received']} demande(s) reçue(s)")
    lines.append("Fait : " + (", ".join(made) if made else "rien de nouveau") + ".")
    labels = {"request": "demande(s) à répondre", "floor": "dérogation(s) de plancher",
              "ship": "lot(s) à expédier", "payment": "paiement(s) à vérifier",
              "photo": "photo(s) à reprendre"}
    todo = [f"{kinds[k]} {labels[k]}" for k in RANK if kinds.get(k)]
    if todo:
        lines.append("À toi : " + ", ".join(todo) + ".")
    return title, "\n".join(lines)
