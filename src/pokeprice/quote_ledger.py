"""Immutable bound quotes and an append-only, versioned selection journal.

The acquisition adapter must supply native metric/population evidence. Legacy
TCGdex snapshots are not admitted here by inferring a binding from `foil`.
A suspension is always journaled: it never lifts by itself when its cause goes.
"""

import json
import uuid
from datetime import date

from .print_reference import binding_key, canonical, quote_selection
from .valuation import amount


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


def suspend(store, db, before, selection, resolution, actor, reason):
    """Journal a suspension and clear the reference columns in one version bump."""
    from .inventory import now

    db.execute(
        "UPDATE copies SET reference_cents=NULL,price_source='',price_date='',version=version+1,updated_at=? WHERE id=?",
        (now(), before["id"]),
    )
    after = store.get(db, before["id"])
    journal(db, after, selection["quote"]["id"], "suspended", resolution, actor, reason)
    store.event(
        db, before["id"], actor, "bound-price-suspension", reason, before, after
    )
    return after


def select_acquisition(store, copy_id, expected_version, acquisition, actor, reason):
    """Server acquisition boundary, not a client-supplied binding override.

    One native payload supplies every metric of the binding's family at once, so
    trend and avg30 always come from the same acquisition.
    """
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
        payload = acquisition.get("source_payload")
        if (
            acquisition.get("binding_key") != key
            or acquisition.get("currency") != binding["currency"]
            or acquisition.get("population") != binding["population"]
            or not acquisition.get("acquisition_id")
            or not isinstance(payload, dict)
            or not payload
            or not acquisition.get("source")
        ):
            raise ValueError("Relevé incompatible ou sans preuve native de métrique.")
        family = binding["metric_family"]["metrics"]
        amounts = {
            metric: amount(payload.get(native)) for metric, native in family.items()
        }
        if any(v is None or v > 1000000000 for v in amounts.values()):
            raise ValueError(
                "Relevé incomplet : chaque métrique de la famille doit venir du même relevé natif."
            )
        # Reference columns and the legacy valuation are EUR-only.
        if binding["currency"] != "EUR":
            raise ValueError("Relevé hors EUR : sélection en euros interdite.")
        date.fromisoformat(acquisition.get("observed_at", "")[:10])
        store.reference.record(copy_id, expected_version, actor, reason, _db=db)
        common = {
            k: v
            for k, v in acquisition.items()
            if k not in ("id", "metric", "native_metric", "amount_cents")
        }
        quotes = [
            {
                **common,
                "id": str(uuid.uuid4()),
                "metric": metric,
                "native_metric": family[metric],
                "amount_cents": cents,
                "binding": binding,
            }
            for metric, cents in sorted(amounts.items())
        ]
        for quote in quotes:
            db.execute(
                "INSERT INTO reference_quotes VALUES(?,?,?,?,?)",
                (quote["id"], copy_id, canonical(quote), actor, now()),
            )
        # The reference column keeps its meaning: the trend when the family has one.
        quote = next((q for q in quotes if q["metric"] == "trend"), quotes[0])
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
        return {"card": after, "quote": quote, "quotes": quotes}


def select_transcription(
    store, copy_id, expected_version, metrics, observed_on, actor, reason, capture=""
):
    """Every metric of the selected binding, read together on the market page.

    The values typed from one page view form the native payload of a single
    acquisition; the binding comes from the server's resolution, never the client.
    """
    from .inventory import now

    with store.connect() as db:
        card = store.get(db, copy_id)
        resolution = store.reference.decision(
            card, disputes=store.reference.disputes(db, copy_id)
        )
    binding = store.reference.selected_binding(resolution)
    if binding is None:
        raise ValueError("Correspondance marchande non vérifiée.")
    family = binding["metric_family"]["metrics"]
    if set(metrics) != set(family):
        raise ValueError(
            "Relevé incomplet : saisissez ensemble " + ", ".join(sorted(family)) + "."
        )
    day = date.fromisoformat(observed_on)
    if day > date.fromisoformat(now()[:10]):
        raise ValueError("Date de relevé dans le futur.")
    payload = {family[metric]: float(value) for metric, value in metrics.items()}
    payload["entry"] = "transcription"
    if capture:
        payload["capture_sha256"] = capture
    return select_acquisition(
        store,
        copy_id,
        expected_version,
        {
            "binding_key": resolution["selected_binding_key"],
            "currency": binding["currency"],
            "population": binding["population"],
            "acquisition_id": str(uuid.uuid4()),
            "source": binding["market"].capitalize() + " · page produit (saisie)",
            "observed_at": day.isoformat(),
            "source_payload": payload,
        },
        actor,
        reason,
    )


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
    elif selection["state"] == "active":
        if next_selection["state"] == "active":
            after.update(
                reference_cents=quote["amount_cents"],
                price_source=quote["source"],
                price_date=quote["observed_at"],
            )
        else:
            after.update(reference_cents=None, price_source="", price_date="")
    # A suspended or revoked selection no longer owns the reference columns:
    # a manual price entered since then is the user's and stays untouched.
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
    from .inventory import Conflict

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
        return suspend(store, db, before, selection, resolution, actor, reason)


def recheck_all(store, actor, reason, *, apply=False):
    """List, then on request journal, every active selection the rules now block."""
    with store.connect() as db:
        pending = []
        for row in db.execute(
            "SELECT DISTINCT copy_id FROM reference_quote_events ORDER BY copy_id"
        ).fetchall():
            card = store.get(db, row["copy_id"])
            selection = current(db, card["id"])
            if card["deleted_at"] or selection["state"] != "active":
                continue
            resolution = store.reference.decision_for(db, card)
            if resolution["price_selection"]["state"] != "active":
                pending.append(
                    {
                        "copy_id": card["id"],
                        "expected_version": card["version"],
                        "name": card["name"],
                        "reason_codes": resolution["reason_codes"],
                    }
                )
    if apply:
        for item in pending:
            recheck_selection(
                store, item["copy_id"], item["expected_version"], actor, reason
            )
    return {"applied": apply, "suspensions": pending}
