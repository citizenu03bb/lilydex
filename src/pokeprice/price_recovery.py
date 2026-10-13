"""Recover only sourced quotes lost by compatible physical clarifications."""

import json

from .inventory import Conflict
from .variant_pricing import PRICE_IDENTITY, compatible_quote

ACTOR = "system:price-recovery"
PRICE_FIELDS = ("reference_cents", "price_source", "price_date")


def candidates(store, *, copy_ids=None, _db=None):
    if _db is None:
        with store.connect() as db:
            return candidates(store, copy_ids=copy_ids, _db=db)
    result = []
    for row in _db.execute(
        "SELECT * FROM copies WHERE deleted_at='' AND reference_cents IS NULL"
    ):
        card = dict(row)
        if copy_ids is not None and card["id"] not in copy_ids:
            continue
        if card["price_source"] or card["price_date"] or not card["variant_confirmed"]:
            continue
        snapshot = store.category_snapshot(_db, card)
        later = []
        for event in _db.execute(
            "SELECT * FROM events WHERE copy_id=? AND kind='correction' ORDER BY id DESC",
            (card["id"],),
        ):
            before, after = (
                json.loads(event["before_json"]),
                json.loads(event["after_json"]),
            )
            lost = (
                before.get("reference_cents") is not None
                and after.get("reference_cents") is None
            )
            if not lost:
                later.append((before, after))
                continue
            # Examine the latest removal only: never revive a quote explicitly
            # cleared later, or overwrite subsequent identity/product decisions.
            if (
                before.get("finish", "") != after.get("finish", "")
                and after.get("finish") == card["finish"]
                and before.get("price_source", "").strip()
                and before.get("price_date", "").strip()
                and not after.get("price_source")
                and not after.get("price_date")
                and compatible_quote(before, after, snapshot)
                and compatible_quote(before, card, snapshot)
                and all(
                    all(b.get(k) == a.get(k) for k in PRICE_FIELDS)
                    and all(b.get(k) == a.get(k) for k in PRICE_IDENTITY if k != "foil")
                    for b, a in later
                )
            ):
                result.append(
                    {
                        "copy_id": card["id"],
                        "name": card["name"],
                        "expected_version": card["version"],
                        "loss_event_id": event["id"],
                        **{k: before[k] for k in PRICE_FIELDS},
                    }
                )
            break
    return result


def apply(store, plan):
    """Version-checked, atomic, quote-only repair with a fixed maintenance actor."""
    if len({p["copy_id"] for p in plan}) != len(plan):
        raise ValueError("Exemplaire répété dans le plan de restauration.")
    with store.connect(write=True) as db:
        current = {p["copy_id"]: p for p in candidates(store, _db=db)}
        if any(current.get(p["copy_id"]) != p for p in plan):
            raise Conflict("Le plan de restauration a changé. Relancez l’audit.")
        for p in plan:
            store.patch(
                p["copy_id"],
                {k: p[k] for k in PRICE_FIELDS},
                p["expected_version"],
                ACTOR,
                f"Restauration de la cotation compatible antérieure à l’événement {p['loss_event_id']} ; source et date d’origine conservées.",
                _db=db,
            )
        return {"restored": len(plan), "items": plan}
