"""Close-up shots in series (decision 0048), in binder order.

The queue is the review agent's current verdict on the cards in scope (an
import, an album or a list of copies), worked out in simulation: nothing is
written to build it, so it works while ``agent_review_apply`` is off, when the
agent records no request. A view already shot in a series, or already retaken
for a recorded request, is not asked again (decision 0022): the card goes to a
person instead.

A shot goes through the copy's own photo path; afterwards the card is read
again on its new photos and the agent runs on it alone, writing only when the
setting allows. Its verdict is logged on the copy (``closeup-review``).
"""

import json
import threading
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from .agent_review import VIEW_SIDE, is_open, request_events, review_apply, run_events

SHOT_EVENT = "closeup-shot"
REVIEW_EVENT = "closeup-review"
# The card in hand: its front first (one photo for the face, the most specific
# view the agent asked), then turned over for the back.
STEP_ORDER = {"holo": 0, "corner": 1, "front": 2, "back": 3}
DEFAULT_GRID = "3x3"
# A new reading normally comes back within a minute. Past this delay without a
# verdict, the work after the response was lost (a restart): it is started again.
STALE_AFTER = timedelta(minutes=10)


def side_of(view):
    return "back" if VIEW_SIDE[view] == "back_photo" else "front"


def shot_events(db, copy_ids):
    """Series shots and their later verdicts, per copy, oldest first."""
    found: dict[str, list[dict]] = {copy_id: [] for copy_id in copy_ids}
    if not copy_ids:
        return found
    marks = ",".join("?" * len(copy_ids))
    for row in db.execute(
        f"SELECT copy_id,kind,after_json,created_at FROM events WHERE kind IN (?,?) "
        f"AND copy_id IN ({marks}) ORDER BY id",
        (SHOT_EVENT, REVIEW_EVENT, *copy_ids),
    ):
        found[row["copy_id"]].append(
            {"kind": row["kind"], "at": row["created_at"], **json.loads(row["after_json"])}
        )
    return found


class Closeups:
    """``review`` is the app's AgentReview; ``grids()`` maps an album id to the
    grid of its latest binder import."""

    def __init__(self, store, review, grids=None, clock=None):
        self.store, self.review = store, review
        self.grids: Callable[[], dict[str, str]] = grids or dict
        self.clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
        # Two shots of one card land a few seconds apart: its second reading
        # waits for the first instead of failing on "already running".
        self.guard = threading.Lock()
        self.locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)

    def scope(self, db, *, import_id=None, album=None, copy_ids=None):
        """Available copies in scope, in binder order."""
        query = (
            "SELECT c.id FROM copies c JOIN albums a ON a.id=c.album_id "
            "WHERE c.deleted_at='' AND c.stock_state='available'"
        )
        args: list = []
        if import_id:
            query += " AND c.source_key LIKE ?"
            args.append(f"binder:{import_id}:%")
        if album:
            query += " AND (a.id=? OR a.name=?)"
            args += [album, album]
        if copy_ids is not None:
            query += f" AND c.id IN ({','.join('?' * len(copy_ids))})"
            args += list(copy_ids)
        query += " ORDER BY a.name,c.page,c.position,c.id"
        return [row[0] for row in db.execute(query, args)]

    @staticmethod
    def answered(card, view, shots, requests, undone):
        """A view shot in a series, or retaken for a recorded request."""
        if any(s["kind"] == SHOT_EVENT and s["view"] == view for s in shots):
            return True
        return any(
            r["view"] == view and r["run_id"] not in undone and not is_open(r, undone)
            for r in requests
        )

    @staticmethod
    def pending(card, shots):
        """The last shot whose new reading has not come back yet, else None."""
        last_shot = max(
            (i for i, s in enumerate(shots) if s["kind"] == SHOT_EVENT), default=None
        )
        if last_shot is None:
            return None
        if any(s["kind"] == REVIEW_EVENT for s in shots[last_shot + 1:]):
            return None
        return shots[last_shot]

    def stale(self, shot):
        """A shot left without a verdict past STALE_AFTER: its reading was lost."""
        try:
            taken = datetime.fromisoformat(shot["at"])
        except (KeyError, TypeError, ValueError):
            return True
        if taken.tzinfo is None:
            taken = taken.replace(tzinfo=UTC)
        return self.clock() - taken > STALE_AFTER

    def queue(self, *, import_id=None, album=None, copy_ids=None, threshold_cents=1000):
        """The steps of a series: one card each, its views in the order of the hand."""
        if not (import_id or album or copy_ids):
            raise ValueError("Choisissez un import, un album ou des exemplaires.")
        with self.store.connect() as db:
            ids = self.scope(db, import_id=import_id, album=album, copy_ids=copy_ids)
        report = self.review.run(
            apply=False, read=False, copy_ids=ids, threshold_cents=threshold_cents,
            trigger="closeup-queue",
        )
        asked = {item["copy_id"]: item["views"] for item in report["photo_requests"]}
        grids = self.grids()
        steps, handed, pending = [], [], []
        with self.store.connect() as db:
            _, undone = run_events(db)
            shots = shot_events(db, ids)
            for copy_id in ids:
                card = self.store.get(db, copy_id)
                place = {
                    "copy_id": copy_id,
                    "version": card["version"],
                    "album_id": card["album_id"],
                    "album": card.get("album") or "",
                    "page": card["page"],
                    "position": card["position"],
                    "name": card["name"],
                    "number": card["number"],
                    "set_name": card["set_name"],
                }
                waiting = self.pending(card, shots[copy_id])
                if waiting is not None:
                    pending.append({**place, "stale": self.stale(waiting)})
                    continue
                if copy_id not in asked:
                    continue
                requests = request_events(db, copy_id)
                views, again = [], []
                for want in asked[copy_id]:
                    if self.answered(card, want["view"], shots[copy_id], requests, undone):
                        again.append(want["reason"])
                    else:
                        views.append({
                            "view": want["view"],
                            "side": side_of(want["view"]),
                            "glint": want["view"] == "holo",
                            "reason": want["reason"],
                        })
                if again:
                    handed.append({
                        **place,
                        "reason": "La photo déjà reprise ne suffit pas : la carte reste en l’état. "
                        + " ".join(again),
                    })
                    continue
                views.sort(key=lambda v: STEP_ORDER[v["view"]])
                steps.append({
                    **place,
                    "grid": grids.get(card["album_id"], DEFAULT_GRID),
                    "has_photo": bool(card["photo"]),
                    "has_back": bool(card["back_photo"]),
                    "views": views,
                })
        return {
            "apply": review_apply(self.store),
            "cards": len(ids),
            "steps": steps,
            "handed": handed,
            "pending": pending,
            # Lost readings, started again after the response (see the route).
            "resumed": [p["copy_id"] for p in pending if p["stale"]],
            "shots": sum(len(s["views"]) for s in steps),
        }

    def record_shot(self, copy_id, view, photo, actor):
        with self.store.connect(write=True) as db:
            self.store.event(
                db, copy_id, actor, SHOT_EVENT,
                "Prise de près en série : " + view,
                {}, {"view": view, "side": side_of(view), "photo": photo},
            )

    def after_shot(self, copy_id, threshold_cents=1000):
        """Read the card on its new photos, then let the agent decide on it alone.

        It writes only when ``agent_review_apply`` is on; its verdict is logged
        either way. A failure is logged too, never raised.
        """
        with self.guard:
            lock = self.locks[copy_id]
        with lock:
            return self._after_shot(copy_id, threshold_cents)

    def _after_shot(self, copy_id, threshold_cents):
        apply = review_apply(self.store)
        try:
            errors = self.review.read_missing(copy_id, threshold_cents)
            report = self.review.run(
                apply=apply, read=False, copy_ids=[copy_id],
                threshold_cents=threshold_cents, trigger="closeup",
            )
        except Exception as error:  # noqa: BLE001 - Never in the person's way.
            errors, report = [type(error).__name__], None
        verdict = {"applied": apply, "errors": errors, "outcome": "error", "views": [],
                   "reason": ""}
        if report is not None:
            # Decision 0050: a partial confirmation still leaves the photo or
            # the « en l'état » to say.
            if report["confirmed"] and not report["confirmed"][0].get("partial"):
                verdict["outcome"] = "confirm"
            elif report["photo_requests"]:
                verdict["outcome"] = "photo"
                verdict["views"] = [v["view"] for v in report["photo_requests"][0]["views"]]
                verdict["reason"] = " ".join(
                    v["reason"] for v in report["photo_requests"][0]["views"])
            elif report["kept"] or report["skipped"]:
                # Decision 0049: what the photos do not settle stays as recorded.
                verdict["outcome"] = "keep"
                verdict["reason"] = (report["kept"] or report["skipped"])[0]["reason"]
            else:
                verdict["outcome"] = "none"
        with self.store.connect(write=True) as db:
            card = self.store.get(db, copy_id)
            self.store.event(
                db, copy_id, self.review.actor, REVIEW_EVENT,
                "Nouvelle lecture après une prise de près"
                + ("" if apply else " (simulation)"),
                {}, {**verdict, "photo": card["photo"] or "", "back_photo": card["back_photo"] or ""},
            )
        return verdict

    def results(self, *, import_id=None, album=None, copy_ids=None):
        """The latest verdict after a series shot, per card, in binder order."""
        with self.store.connect() as db:
            ids = self.scope(db, import_id=import_id, album=album, copy_ids=copy_ids)
            shots = shot_events(db, ids)
            out = []
            for copy_id in ids:
                verdicts = [s for s in shots[copy_id] if s["kind"] == REVIEW_EVENT]
                if not verdicts and not shots[copy_id]:
                    continue
                card = self.store.get(db, copy_id)
                out.append({
                    "copy_id": copy_id,
                    "album": card.get("album") or "",
                    "page": card["page"],
                    "position": card["position"],
                    "name": card["name"],
                    "number": card["number"],
                    "shots": [s["view"] for s in shots[copy_id] if s["kind"] == SHOT_EVENT],
                    "verdict": verdicts[-1] if verdicts else None,
                })
        return out
