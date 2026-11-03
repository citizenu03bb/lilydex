"""The review agent confirms variant and condition when the evidence suffices.

Otherwise it asks for one more photo. It writes through the very path a human
uses (``VariantCheckService.confirm`` and ``ConditionService.confirm``), as
``agent:revue``, with the readings, its scores and its run as evidence. Each
run is one event, and undoing it restores every copy nobody touched since.

Photo requests live in the events table (``photo-request``): a request stays
open while the photo of its face is unchanged, its run is not undone and the
copy is still available. A new photo closes it and, on the server, starts a
fresh analysis of that copy (``after_photo``).

See docs/CONDITION-ASSESSMENT.md and docs/decisions/0021.
"""

import json
import uuid

from .condition_assessment import assessment_rows, auto_condition_decision
from .edition_check import MARGIN
from .inventory import Conflict, now
from .verification import (
    auto_variant_decision,
    check_inputs,
    check_rows,
    edition_score,
    high_stakes,
    propose_variant,
)

ACTOR = "agent:revue"
VIEWS = ("front", "back", "holo", "corner")
# The face a requested view replaces: a holo glint or a corner close-up is a
# better front photo, read again by the same checks.
VIEW_SIDE = {"front": "photo", "holo": "photo", "corner": "photo", "back": "back_photo"}
VIEW_PRIORITY = {view: rank for rank, view in enumerate(VIEWS)}
# One photo per face answers every request on it: the most specific view wins.
# A close-up with four sharp corners is also a sharp front; a holo glint is
# what decision 0008 needs before any price.
SPECIFIC = {"holo": 0, "corner": 1, "front": 2, "back": 0}


def run_events(db):
    """Runs by id, and the ids of the undone ones."""
    runs, undone = {}, set()
    for row in db.execute(
        "SELECT kind,after_json,created_at FROM events "
        "WHERE copy_id IS NULL AND kind IN ('agent-review','agent-review-undo') ORDER BY id"
    ):
        data = json.loads(row["after_json"])
        if row["kind"] == "agent-review":
            runs[data["run_id"]] = {**data, "created_at": row["created_at"]}
        else:
            undone.add(data["run_id"])
    return runs, undone


def request_events(db, copy_id=None):
    """Every photo request with its copy's placement, oldest first."""
    query = (
        "SELECT e.id,e.copy_id,e.after_json,e.created_at,c.photo,c.back_photo,"
        "c.deleted_at,c.stock_state,c.name,c.number,c.set_name,c.page,c.position,"
        "c.album_id,c.version,a.name album FROM events e JOIN copies c ON c.id=e.copy_id "
        "JOIN albums a ON a.id=c.album_id WHERE e.kind='photo-request'"
    )
    args = ()
    if copy_id:
        query += " AND e.copy_id=?"
        args = (copy_id,)
    return [
        {**dict(row), **json.loads(row["after_json"])}
        for row in db.execute(query + " ORDER BY e.id", args)
    ]


def is_open(request, undone):
    side = VIEW_SIDE[request["view"]]
    return (
        request["run_id"] not in undone
        and not request["deleted_at"]
        and request["stock_state"] == "available"
        and (request[side] or "") == (request["photos"].get(side) or "")
    )


class AgentReview:
    """``inputs(copy_id, threshold_cents)`` returns the catalogue snapshot and
    valuation of a copy; the services are the app's own."""

    def __init__(
        self,
        store,
        variant_checks,
        conditions,
        edition_checks=None,
        inputs=None,
        actor=ACTOR,
    ):
        self.store, self.variant_checks, self.conditions = store, variant_checks, conditions
        self.edition_checks = edition_checks
        self.inputs = inputs or (
            lambda copy_id, threshold: check_inputs(store, None, copy_id, threshold)
        )
        self.actor = actor

    # -- Reading -----------------------------------------------------------

    def candidates(self, db, album=None, copy_ids=None):
        """Identified, available copies still waiting for a confirmation, in binder order."""
        query = (
            "SELECT c.id FROM copies c JOIN albums a ON a.id=c.album_id "
            "WHERE c.deleted_at='' AND c.stock_state='available' "
            "AND c.identification_status='confirmed' "
            "AND NOT (c.variant_confirmed AND c.condition_confirmed)"
        )
        args = []
        if album:
            query += " AND (a.id=? OR a.name=?)"
            args += [album, album]
        if copy_ids is not None:
            query += f" AND c.id IN ({','.join('?' * len(copy_ids))})"
            args += list(copy_ids)
        query += " ORDER BY a.name,c.page,c.position,c.id"
        return [row[0] for row in db.execute(query, args)]

    def evidence(self, copy_id, threshold_cents):
        """Current card, readings and stakes; readings on replaced photos are stale."""
        snapshot, valuation = self.inputs(copy_id, threshold_cents)
        with self.store.connect() as db:
            card = self.store.get(db, copy_id)
            checks = check_rows(db, card)
            editions = check_rows(db, card, "edition")
            try:
                assessments = assessment_rows(self.store, db, card)
            except ValueError:  # A referenced photo is missing.
                assessments = []
        return {
            "card": card,
            "snapshot": snapshot,
            "valuation": valuation,
            "check": next((c for c in checks if not c["stale"]), None),
            "edition": next((e for e in editions if not e["stale"]), None),
            "assessment": next((a for a in assessments if not a["stale"]), None),
        }

    def read_missing(self, copy_id, threshold_cents):
        """Run the checks the copy lacks on its current photos; errors are reported."""
        found = self.evidence(copy_id, threshold_cents)
        card, errors = found["card"], []
        steps = []
        if not card["photo"]:
            return errors
        if not found["check"] and not card["variant_confirmed"]:
            steps.append(
                lambda: self.variant_checks.evaluate(
                    copy_id,
                    card["version"],
                    self.actor,
                    snapshot=found["snapshot"],
                    valuation=found["valuation"],
                    trigger="agent",
                )
            )
        if (
            not found["edition"]
            and not card["variant_confirmed"]
            and self.edition_checks is not None
            and self.edition_checks.available
        ):
            steps.append(
                lambda: self.edition_checks.evaluate(
                    copy_id, card["version"], self.actor, "agent"
                )
            )
        if not found["assessment"] and not card["condition_confirmed"]:
            steps.append(
                lambda: self.conditions.evaluate(copy_id, card["version"], self.actor)
            )
        for step in steps:
            try:
                step()
            except (Conflict, RuntimeError, ValueError, KeyError) as error:
                errors.append(str(error))
            except Exception as error:  # noqa: BLE001 - Never leak provider details.
                errors.append(type(error).__name__)
        return errors

    # -- Deciding ----------------------------------------------------------

    def decide(self, found):
        """One decision per copy: confirm both halves together, or say what is missing.

        Both halves are confirmed together, or neither: a new photo resets them
        anyway, and the price needs the two.
        """
        card, valuation = found["card"], found["valuation"]
        high_value = high_stakes(valuation)
        assessment = found["assessment"]
        back_usable = bool(
            card.get("back_photo")
            and assessment
            and assessment["result"].get("back_usable")
        )
        decisions = {}
        if not card["variant_confirmed"]:
            check = found["check"]
            proposal = (
                propose_variant(card, check["result"], found["snapshot"], valuation)
                if check
                else None
            )
            edition = None
            if found["edition"]:
                edition = edition_score(card, found["edition"])
            decisions["variant"] = auto_variant_decision(
                card,
                check,
                proposal,
                edition,
                MARGIN,
                high_value=high_value,
                back_usable=back_usable,
            )
            if decisions["variant"]["action"] == "confirm":
                decisions["variant"]["check_id"] = check["id"]
                decisions["variant"]["proposal"] = proposal
        if not card["condition_confirmed"]:
            decisions["condition"] = auto_condition_decision(
                card, assessment, high_value=high_value
            )
            if decisions["condition"]["action"] == "confirm":
                decisions["condition"]["assessment_id"] = assessment["id"]
        wanted = {}
        for d in decisions.values():
            if d["action"] != "photo":
                continue
            side = VIEW_SIDE[d["view"]]
            if side not in wanted or SPECIFIC[d["view"]] < SPECIFIC[wanted[side][0]]:
                wanted[side] = (d["view"], d["reason"])
        photos = sorted(wanted.values(), key=lambda item: VIEW_PRIORITY[item[0]])
        skipped = [d["reason"] for d in decisions.values() if d["action"] == "skip"]
        return {
            "high_value": high_value,
            "decisions": decisions,
            "photos": photos,
            "skipped": skipped,
            "confirm": bool(decisions)
            and all(d["action"] == "confirm" for d in decisions.values()),
        }

    # -- Writing -----------------------------------------------------------

    def confirm(self, found, verdict, run_id):
        """Apply both confirmations through the human path; returns the undo record."""
        card = found["card"]
        version = card["version"]
        before = {
            k: card[k]
            for k in (
                "finish",
                "stamp",
                "stamp_state",
                "variant_confirmed",
                "condition",
                "condition_confirmed",
            )
        }
        applied = []
        variant = verdict["decisions"].get("variant")
        if variant:
            changed = self.variant_checks.confirm(
                card["id"],
                variant["check_id"],
                version,
                variant["values"],
                self.actor,
                "Variante confirmée par l’agent : " + variant["reason"],
                variant["proposal"],
                decision={
                    "decided_by": "agent",
                    "run_id": run_id,
                    "score": variant["score"],
                    "high_value": verdict["high_value"],
                },
            )
            version = changed["version"]
            applied.append("variant")
        condition = verdict["decisions"].get("condition")
        if condition:
            changed = self.conditions.confirm(
                card["id"],
                condition["assessment_id"],
                version,
                condition["grade"],
                self.actor,
                f"État {condition['grade']} confirmé par l’agent sur photos",
                decision={
                    "decided_by": "agent",
                    "run_id": run_id,
                    "score": condition["score"],
                    "high_value": verdict["high_value"],
                },
            )
            version = changed["version"]
            applied.append("condition")
        return {"copy_id": card["id"], "before": before, "version": version, "applied": applied}

    def request(self, db, card, view, reason, run_id, undone):
        """Record a photo request unless the same view is already open.

        A view asked once and answered is not asked again: the copy is left
        to a human instead of looping on photos. Returns None or the reason.
        """
        for previous in request_events(db, card["id"]):
            if previous["view"] != view or previous["run_id"] in undone:
                continue
            if is_open(previous, undone):
                return "open"
            return "answered"
        self.store.event(
            db,
            card["id"],
            self.actor,
            "photo-request",
            "Photo demandée par l’agent : " + reason,
            {},
            {
                "run_id": run_id,
                "view": view,
                "reason": reason,
                "photos": {"photo": card["photo"] or "", "back_photo": card["back_photo"] or ""},
            },
        )
        return None

    def run(
        self,
        *,
        apply=False,
        read=False,
        album=None,
        copy_ids=None,
        limit=None,
        threshold_cents=1000,
        trigger="batch",
    ):
        """Review every waiting copy; without ``apply``, nothing is written."""
        run_id = str(uuid.uuid4()) if apply else None
        report = {
            "run_id": run_id,
            "applied": apply,
            "trigger": trigger,
            "confirmed": [],
            "photo_requests": [],
            "skipped": [],
            "human_decisions_saved": 0,
        }
        with self.store.connect() as db:
            ids = self.candidates(db, album, copy_ids)
        if limit is not None:
            ids = ids[:limit]
        for copy_id in ids:
            errors = self.read_missing(copy_id, threshold_cents) if read and apply else []
            found = self.evidence(copy_id, threshold_cents)
            card = found["card"]
            label = f"{card['name']} {card['number']} · p.{card['page']} #{card['position']}"
            item = {"copy_id": copy_id, "label": label}
            if not card["photo"]:
                verdict = {
                    "confirm": False,
                    "photos": [("front", "Aucune photo du recto : photographiez la carte.")],
                    "skipped": [],
                }
            else:
                verdict = self.decide(found)
            if verdict["confirm"]:
                saved = len(verdict["decisions"])
                if apply:
                    try:
                        record = self.confirm(found, verdict, run_id)
                    except (Conflict, ValueError, KeyError) as error:
                        report["skipped"].append({**item, "reason": str(error)})
                        continue
                    item["undo"] = record
                    saved = len(record["applied"])
                report["confirmed"].append({**item, "decisions": saved})
                report["human_decisions_saved"] += saved
                continue
            if verdict["photos"]:
                asked = []
                for view, reason in verdict["photos"]:
                    if apply:
                        with self.store.connect(write=True) as db:
                            _, undone = run_events(db)
                            status = self.request(db, card, view, reason, run_id, undone)
                        if status == "answered":
                            report["skipped"].append(
                                {
                                    **item,
                                    "reason": "La photo déjà reprise ne suffit pas : examen en main. "
                                    + reason,
                                }
                            )
                            continue
                        if status == "open":
                            continue
                    asked.append({"view": view, "reason": reason})
                if asked:
                    report["photo_requests"].append({**item, "views": asked})
                continue
            reasons = errors + verdict["skipped"]
            report["skipped"].append(
                {**item, "reason": " ".join(dict.fromkeys(reasons)) or "Rien à décider."}
            )
        if apply:
            with self.store.connect(write=True) as db:
                self.store.event(
                    db,
                    None,
                    self.actor,
                    "agent-review",
                    f"Passage de l’agent de revue ({trigger})",
                    {},
                    {
                        "run_id": run_id,
                        "trigger": trigger,
                        "threshold_cents": threshold_cents,
                        "confirmed": [
                            {k: c[k] for k in ("copy_id", "decisions", "undo")}
                            for c in report["confirmed"]
                        ],
                        "photo_requests": len(report["photo_requests"]),
                        "skipped": len(report["skipped"]),
                        "human_decisions_saved": report["human_decisions_saved"],
                    },
                )
        return report

    def undo(self, run_id, actor, reason=""):
        """Withdraw a whole run: its confirmations and its photo requests.

        A copy changed since the run (its version moved) is left as it is and
        reported; the person decides.
        """
        with self.store.connect() as db:
            runs, undone = run_events(db)
        if run_id not in runs:
            raise KeyError("Passage introuvable.")
        if run_id in undone:
            raise Conflict("Ce passage est déjà annulé.")
        restored, kept = [], []
        reason = reason or f"Annulation du passage de l’agent {run_id}"
        for item in runs[run_id]["confirmed"]:
            record = item["undo"]
            try:
                self.store.patch(
                    record["copy_id"], record["before"], record["version"], actor, reason
                )
                restored.append(record["copy_id"])
            except (Conflict, ValueError) as error:
                kept.append({"copy_id": record["copy_id"], "reason": str(error)})
        with self.store.connect(write=True) as db:
            self.store.event(
                db,
                None,
                actor,
                "agent-review-undo",
                reason,
                {},
                {"run_id": run_id, "restored": restored, "kept": kept, "at": now()},
            )
        return {"run_id": run_id, "restored": restored, "kept": kept}

    # -- Reading back --------------------------------------------------------

    def runs(self):
        with self.store.connect() as db:
            runs, undone = run_events(db)
        return [
            {
                "run_id": run_id,
                "created_at": run["created_at"],
                "trigger": run["trigger"],
                "confirmed": len(run["confirmed"]),
                "photo_requests": run["photo_requests"],
                "skipped": run["skipped"],
                "human_decisions_saved": run["human_decisions_saved"],
                "undone": run_id in undone,
            }
            for run_id, run in reversed(runs.items())
        ]

    def photo_requests(self):
        """Open requests in binder order: album, page, pocket."""
        with self.store.connect() as db:
            _, undone = run_events(db)
            requests = [r for r in request_events(db) if is_open(r, undone)]
        latest = {}
        for r in requests:  # One line per copy and face, the latest request.
            latest[(r["copy_id"], VIEW_SIDE[r["view"]])] = r
        return [
            {
                "copy_id": r["copy_id"],
                "version": r["version"],
                "album_id": r["album_id"],
                "album": r["album"],
                "page": r["page"],
                "position": r["position"],
                "name": r["name"],
                "number": r["number"],
                "set_name": r["set_name"],
                "view": r["view"],
                "side": "back" if VIEW_SIDE[r["view"]] == "back_photo" else "front",
                "reason": r["reason"],
                "requested_at": r["created_at"],
            }
            for r in sorted(
                latest.values(),
                key=lambda r: (
                    r["album"],
                    r["page"],
                    r["position"],
                    VIEW_PRIORITY[r["view"]],
                ),
            )
        ]

    def after_photo(self, copy_id, threshold_cents=1000):
        """A photo answered a request: read the copy again and decide, in the background.

        Only copies the agent asked about are read; a failure stays in the
        events, never in the person's way.
        """
        try:
            with self.store.connect() as db:
                if not request_events(db, copy_id):
                    return None
            return self.run(
                apply=True,
                read=True,
                copy_ids=[copy_id],
                threshold_cents=threshold_cents,
                trigger="photo",
            )
        except Exception as error:  # noqa: BLE001 - A background review never breaks an upload.
            known = isinstance(error, (Conflict, RuntimeError, ValueError, KeyError))
            with self.store.connect(write=True) as db:
                self.store.event(
                    db,
                    copy_id,
                    self.actor,
                    "verification-failed",
                    "Nouvelle analyse automatique après photo impossible",
                    {},
                    {
                        "kind": "agent-review",
                        "trigger": "photo",
                        "error": str(error) if known else type(error).__name__,
                    },
                )
            return None
