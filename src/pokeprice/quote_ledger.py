"""Immutable bound quotes and an append-only, versioned selection journal.

The acquisition adapter must supply native metric/population evidence. Legacy
TCGdex snapshots are not admitted here by inferring a binding from `foil`.
"""

import json
import uuid
from datetime import date

from .print_reference import binding_key, canonical, quote_selection


def current(db, copy_id):
    row = db.execute(
        "SELECT e.state,e.quote_id,q.payload_json FROM reference_quote_events e LEFT JOIN reference_quotes q ON q.id=e.quote_id WHERE e.copy_id=? ORDER BY e.id DESC LIMIT 1",
        (copy_id,),
    ).fetchone()
    return (
        {
            "state": row["state"],
            "quote": json.loads(row["payload_json"]) if row["payload_json"] else None,
        }
        if row
        else None
    )


def journal(db, card, quote_id, state, resolution, actor, reason):
    from .inventory import now

    db.execute(
        "INSERT INTO reference_quote_events(copy_id,quote_id,state,copy_version,resolution_json,actor,reason,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (
            card["id"],
            quote_id,
            state,
            card["version"],
            canonical(resolution),
            actor,
            reason,
            now(),
        ),
    )


def select_acquisition(store, copy_id, expected_version, acquisition, actor, reason):
    """Server acquisition boundary, not a client-supplied binding override."""
    from .inventory import Conflict, now

    if not actor.strip() or not reason.strip():
        raise ValueError("Auteur et motif requis.")
    with store.connect(write=True) as db:
        before = store.get(db, copy_id)
        if before["version"] != expected_version or before["deleted_at"]:
            raise Conflict("La fiche a changé pendant le relevé du prix.")
        resolution = store.reference.decision(
            before, disputes=store.reference.disputes(db, copy_id)
        )
        if not resolution["pricing_eligible"]:
            raise ValueError("Correspondance marchande non vérifiée.")
        key = resolution["selected_binding_key"]
        bindings = store.reference.ruleset.data["bindings"].values()
        binding = next(b for b in bindings if binding_key(b) == key)
        metric = acquisition.get("metric")
        if (
            acquisition.get("binding_key") != key
            or acquisition.get("currency") != binding["currency"]
            or acquisition.get("population") != binding["population"]
            or metric not in binding["metric_family"]["metrics"]
            or acquisition.get("native_metric")
            != binding["metric_family"]["metrics"][metric]
            or not acquisition.get("acquisition_id")
            or not acquisition.get("source_payload")
            or not acquisition.get("source")
            or type(acquisition.get("amount_cents")) is not int
            or not 0 <= acquisition["amount_cents"] <= 1000000000
        ):
            raise ValueError("Relevé incompatible ou sans preuve native de métrique.")
        # Reference columns and the legacy valuation are EUR-only.
        if binding["currency"] != "EUR":
            raise ValueError("Relevé hors EUR : sélection en euros interdite.")
        date.fromisoformat(acquisition.get("observed_at", "")[:10])
        store.reference.record(copy_id, expected_version, actor, reason, _db=db)
        quote = {**acquisition, "id": str(uuid.uuid4()), "binding": binding}
        db.execute(
            "INSERT INTO reference_quotes VALUES(?,?,?,?,?)",
            (quote["id"], copy_id, canonical(quote), actor, now()),
        )
        db.execute(
            "UPDATE copies SET reference_cents=?,price_source=?,price_date=?,version=version+1,updated_at=? WHERE id=?",
            (
                quote["amount_cents"],
                quote["source"],
                quote["observed_at"],
                now(),
                copy_id,
            ),
        )
        after = store.get(db, copy_id)
        journal(db, after, quote["id"], "active", resolution, actor, reason)
        store.event(db, copy_id, actor, "bound-price-selection", reason, before, after)
        store.observe_price(db, after, actor)
        return {"card": after, "quote": quote}


def reconcile(store, db, before, after, changes, actor, reason):
    """Called in the same copy correction transaction, after observation attestation."""
    selection = current(db, before["id"])
    if selection is None:
        return
    quote = selection["quote"]
    resolution = store.reference.decision(
        after, disputes=store.reference.disputes(db, before["id"])
    )
    next_selection = quote_selection(quote, resolution, selection["state"])
    if "reference_cents" in changes:
        # A deliberate clear/replacement is a revocation, even if the amount matches.
        next_selection = {"state": "revoked"}
    elif next_selection["state"] == "active":
        after.update(
            reference_cents=quote["amount_cents"],
            price_source=quote["source"],
            price_date=quote["observed_at"],
        )
    else:
        after.update(reference_cents=None, price_source="", price_date="")
    if next_selection["state"] != selection["state"]:
        journal(
            db,
            {**after, "version": before["version"] + 1},
            quote["id"] if quote else None,
            next_selection["state"],
            resolution,
            actor,
            reason,
        )


def restore_selection(store, copy_id, expected_version, quote_id, actor, reason):
    """An explicit, audited restoration cannot undo a revocation or newer quote."""
    from .inventory import Conflict, now

    if not actor.strip() or not reason.strip():
        raise ValueError("Auteur et motif requis.")
    with store.connect(write=True) as db:
        before = store.get(db, copy_id)
        if before["version"] != expected_version or before["deleted_at"]:
            raise Conflict("La fiche a changé. Relancez la restauration.")
        selection = current(db, copy_id)
        if (
            not selection
            or selection["state"] != "suspended"
            or selection["quote"]["id"] != quote_id
        ):
            raise ValueError(
                "La cotation a été retirée ou remplacée ; restauration interdite."
            )
        quote = selection["quote"]
        resolution = store.reference.decision(
            before, disputes=store.reference.disputes(db, copy_id)
        )
        if quote_selection(quote, resolution)["state"] != "active":
            raise ValueError("La correspondance marchande reste incompatible.")
        store.reference.record(copy_id, expected_version, actor, reason, _db=db)
        db.execute(
            "UPDATE copies SET reference_cents=?,price_source=?,price_date=?,version=version+1,updated_at=? WHERE id=?",
            (
                quote["amount_cents"],
                quote["source"],
                quote["observed_at"],
                now(),
                copy_id,
            ),
        )
        after = store.get(db, copy_id)
        journal(db, after, quote_id, "active", resolution, actor, reason)
        store.event(
            db, copy_id, actor, "bound-price-restoration", reason, before, after
        )
        return after


def recheck_selection(store, copy_id, expected_version, actor, reason):
    """Apply an audited rules change without transferring or reviving a quote."""
    from .inventory import Conflict, now

    if not actor.strip() or not reason.strip():
        raise ValueError("Auteur et motif requis.")
    with store.connect(write=True) as db:
        before = store.get(db, copy_id)
        if before["version"] != expected_version or before["deleted_at"]:
            raise Conflict("La fiche a changé depuis l’audit du référentiel.")
        selection = current(db, copy_id)
        if selection is None:
            return before
        resolution = store.reference.decision(
            before, disputes=store.reference.disputes(db, copy_id)
        )
        next_selection = quote_selection(
            selection["quote"], resolution, selection["state"]
        )
        if next_selection["state"] == selection["state"]:
            return before
        store.reference.record(copy_id, expected_version, actor, reason, _db=db)
        db.execute(
            "UPDATE copies SET reference_cents=NULL,price_source='',price_date='',version=version+1,updated_at=? WHERE id=?",
            (now(), copy_id),
        )
        after = store.get(db, copy_id)
        journal(
            db,
            after,
            selection["quote"]["id"],
            next_selection["state"],
            resolution,
            actor,
            reason,
        )
        store.event(db, copy_id, actor, "bound-price-suspension", reason, before, after)
        return after
