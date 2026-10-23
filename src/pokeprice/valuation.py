"""Read-only valuation of dated evidence; hypotheses never become reference prices."""

import math
from decimal import Decimal, ROUND_HALF_UP

from .energy_gate import basic_energy
from .variant_pricing import category, pricing_issue

DEFAULT_THRESHOLD_CENTS = 1000
IDENTITY_FIELDS = ("catalog_id", "name", "number", "set_name", "language")
ESTIMATE_FIELDS = (*IDENTITY_FIELDS, "foil", "stamp", "condition")


def amount(value):
    """An absent, negative or non-finite quote stays unknown, including booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), ROUND_HALF_UP))


def market(snapshot):
    raw = (snapshot or {}).get("raw") or {}
    if not isinstance(raw, dict):
        return {}
    quotes = raw.get("cardmarket") or {}
    if not isinstance(quotes, dict):
        return {}
    # Legacy snapshots still have the selected metrics, but no other avg30.
    if not quotes and snapshot:
        suffix = "-holo" if snapshot.get("variant") == "holo/reverse" else ""
        quotes = {k + suffix: v for k, v in snapshot.get("metrics", {}).items()}
    return quotes if quotes.get("unit", "EUR") == "EUR" else {}


def variant_values(snapshot):
    quotes = market(snapshot)
    variants = (snapshot or {}).get("variants") or {}
    if not isinstance(variants, dict):
        variants = {}
    result = []
    for foil, suffix in ((False, ""), (True, "-holo")):
        trend, average = (
            amount(quotes.get("trend" + suffix)),
            amount(quotes.get("avg30" + suffix)),
        )
        if trend is None and average is None and not (foil and variants.get("reverse")):
            continue
        spread = [
            v
            for key in ("trend", "avg1", "avg7", "avg30")
            if (v := amount(quotes.get(key + suffix))) is not None and v > 0
        ]
        result.append(
            {
                "foil": foil,
                "trend_cents": trend,
                "average_30d_cents": average,
                "prudent_cents": min(trend, average)
                if trend is not None and average is not None
                else None,
                "unstable": bool(spread and max(spread) >= 2 * min(spread)),
            }
        )
    return result


def candidates_from_evidence(card, evidence):
    """Only the last matching search is plausible; older searches are history."""
    searches = (evidence or {}).get("searches") or []
    if not searches:
        return []
    search = searches[-1]
    if any(
        search.get("query", {}).get(k) != card.get(k)
        for k in ("name", "number", "language")
    ):
        return []
    if search.get("query", {}).get("hp") is not None and search["query"][
        "hp"
    ] != card.get("hp"):
        return []
    return search.get("candidates") or []


def applicable(verdict, id_product):
    """A verdict on another product (TCGdex fixed its mapping) no longer applies."""
    if verdict and id_product is not None and verdict.get("id_product") == id_product:
        return verdict.get("verdict") or ""
    return ""


def other_cards(shared):
    """Number first: TCGdex names are English (Airmure is Skarmory)."""
    return ", ".join(
        f"n° {o['catalog_id'].rpartition('-')[2]} ({o.get('name') or '?'} en anglais"
        + (f", {o['hp']} PV" if o.get("hp") else "")
        + ")"
        for o in shared
    )


def manual_reference(card):
    """A dated reference typed by a person, as opposed to a TCGdex refresh."""
    amount_cents = card.get("reference_cents")
    source = (card.get("price_source") or "").strip()
    if (
        not isinstance(amount_cents, int)
        or isinstance(amount_cents, bool)
        or amount_cents < 0
        or not source
        or source.startswith("TCGdex")
        or not card.get("price_date")
    ):
        return None
    return {
        "amount_cents": amount_cents,
        "source": source,
        "observed_at": card["price_date"],
    }


def assess(
    card,
    snapshot=None,
    estimate=None,
    candidates=(),
    *,
    threshold_cents=1000,
    category_snapshot=None,
    market_verdict=None,
):
    confirmed = card["identification_status"] == "confirmed"
    physically_confirmed = bool(confirmed and card.get("variant_confirmed"))
    metadata = category_snapshot or snapshot
    decision = category(card, metadata)
    issue = pricing_issue(card, metadata)
    variant_confirmed = physically_confirmed and not issue
    catalogue_warning = bool(
        card["foil"]
        and (snapshot or {}).get("catalog_id") == card.get("catalog_id")
        and (snapshot or {}).get("variant_check")
    )
    # The product mapping belongs to the catalogue id, even once its price is cleared.
    id_product = (
        (snapshot or {}).get("id_product")
        if confirmed and (snapshot or {}).get("catalog_id") == card.get("catalog_id")
        else None
    )
    # Identity/variant corrections clear price_date. Never revive their old price.
    if (
        not confirmed
        or not card.get("price_date")
        or ((snapshot or {}).get("catalog_id") != card.get("catalog_id"))
    ):
        snapshot = None
        shared = []
    else:
        shared = (snapshot or {}).get("shared_product_with") or []
    verdict = applicable(market_verdict, id_product)
    if verdict:
        shared = []
    market_product = (
        {"id_product": id_product, "verdict": verdict, "shared_with": shared}
        if id_product is not None
        else None
    )
    if verdict == "wrong":
        snapshot = None  # These quotes describe another card.
    values = variant_values(snapshot)
    variants = (snapshot or {}).get("variants") or {}
    if not isinstance(variants, dict):
        variants = {}
    current = next((v for v in values if v["foil"] == bool(card["foil"])), {})
    if issue:
        current = {}  # The stored category's quote does not price this physical print.
    manual = None
    if confirmed and not issue and current.get("prudent_cents") is None:
        manual = manual_reference(card)
    if manual:
        # Simple fallback: a dated manual quote stands in for the missing
        # TCGdex prudent price. It is usually a trend alone, so it stays flagged.
        current = {
            "foil": bool(card["foil"]),
            "trend_cents": manual["amount_cents"],
            "average_30d_cents": None,
            "prudent_cents": manual["amount_cents"],
            "unstable": False,
        }
        values = [v for v in values if v["foil"] != bool(card["foil"])] + [current]
    # Once the physical print is checked, rejected variants are no longer plausible.
    plausible_values = (
        [current]
        if variant_confirmed and current
        else ([] if variant_confirmed else values)
    )
    hypotheses = [
        {
            **v,
            "catalog_id": card.get("catalog_id"),
            "source": (snapshot or {}).get("source"),
            "observed_at": (snapshot or {}).get("updated")
            or (snapshot or {}).get("observed_at"),
        }
        for v in plausible_values
    ]
    if manual:
        for h in hypotheses:
            if h["foil"] == bool(card["foil"]):
                h.update(source=manual["source"], observed_at=manual["observed_at"])
    if not confirmed:
        for candidate in candidates:
            candidate_snapshot = candidate.get("price_snapshot")
            if (
                candidate_snapshot
                and candidate_snapshot.get("catalog_id") == candidate["id"]
            ):
                hypotheses.extend(
                    {
                        **v,
                        "catalog_id": candidate["id"],
                        "source": candidate.get("source")
                        or candidate_snapshot.get("source"),
                        "observed_at": candidate_snapshot.get("updated")
                        or candidate_snapshot.get("observed_at"),
                    }
                    for v in variant_values(candidate_snapshot)
                )
    known = [h["prudent_cents"] for h in hypotheses if h["prudent_cents"] is not None]
    risk = max(known) if known else None
    missing_candidates = not confirmed and len(
        {h["catalog_id"] for h in hypotheses}
    ) < len(candidates)
    incomplete = (
        any(h["prudent_cents"] is None for h in hypotheses)
        or missing_candidates
        or bool(manual)
    )
    material_unknown = (
        any(
            h["prudent_cents"] is None
            and (
                (h["trend_cents"] is None and h["average_30d_cents"] is None)
                or max(h["trend_cents"] or 0, h["average_30d_cents"] or 0)
                >= threshold_cents
            )
            for h in hypotheses
        )
        or missing_candidates
    )
    reasons = []
    if card.get("category_was_changed") and not card.get("finish"):
        reasons.append(
            {
                "code": "variant",
                "label": "Ancienne correction de catégorie : renseignez la finition observée pour la vérifier.",
            }
        )
    if issue:
        reasons.append(
            {
                "code": "price_variant"
                if decision["mode"] == "automatic"
                else "price_category",
                "label": issue,
            }
        )
    if not confirmed:
        reasons.append({"code": "identity", "label": "Identité incertaine"})
    if confirmed and shared:
        own = (card.get("catalog_id") or "").rpartition("-")[2]
        reasons.append(
            {
                "code": "market_product",
                "label": f"TCGdex donne aussi ce produit Cardmarket à {other_cards(shared)} : "
                f"vérifiez que la page montre votre n° {own}, puis confirmez-la ou signalez-la incorrecte.",
            }
        )
    # A confirmed basic Energy is sold by the lot: there is no quote to chase (0015).
    bulk = bool(
        confirmed
        and not issue
        and current.get("prudent_cents") is None
        and basic_energy(card.get("name", ""))[0]
    )
    if not bulk and (
        risk is None
        or material_unknown
        or (confirmed and current.get("prudent_cents") is None)
    ):
        reasons.append(
            {
                "code": "missing_price",
                "label": "Prix à actualiser : valeur prudente incomplète",
            }
        )
    if risk is not None and risk >= threshold_cents:
        if not physically_confirmed or not card.get("condition_confirmed"):
            reasons.append(
                {
                    "code": "value",
                    "label": "Carte de valeur : examen physique à terminer",
                }
            )
        alternative = next((v for v in values if v["foil"] != bool(card["foil"])), {})
        other = alternative.get("prudent_cents")
        own = current.get("prudent_cents")
        if (
            not physically_confirmed
            and other is not None
            and other >= threshold_cents
            and (own is None or other >= 3 * max(own, 1))
        ):
            reasons.append(
                {"code": "variant_premium", "label": "Variante à forte prime"}
            )
        if not physically_confirmed:
            reasons.append(
                {
                    "code": "variant",
                    "label": "Variante et tampon à vérifier physiquement",
                }
            )
        if not card.get("condition_confirmed"):
            reasons.append({"code": "condition", "label": "État non validé"})
    if (
        catalogue_warning
        and not physically_confirmed
        and not any(r["code"] == "variant" for r in reasons)
    ):
        reasons.append(
            {
                "code": "variant",
                "label": "Variante à vérifier : catalogue incomplet ou discordant",
            }
        )
    sale = None
    if (
        confirmed
        and not issue
        and estimate
        and all(
            estimate.get(k) == card.get(k) for k in ("language", "stamp", "condition")
        )
        and bool(estimate.get("foil")) == bool(card["foil"])
    ):
        if all(
            k not in estimate or estimate[k] == card.get(k) for k in IDENTITY_FIELDS
        ):
            sale = amount(estimate.get("estimate_eur"))
    return {
        "trend_cents": current.get("trend_cents"),
        "prudent_cents": current.get("prudent_cents"),
        "sale_estimate_cents": sale,
        "risk_cents": risk,
        "risk_incomplete": risk is None or incomplete,
        "threshold_cents": threshold_cents,
        "is_valuable": risk is not None and risk >= threshold_cents,
        "market_unstable": any(h["unstable"] for h in hypotheses),
        "variant_catalog_warning": catalogue_warning,
        "manual_price": manual,
        "market_product": market_product,
        "price_variant_issue": issue,
        "bulk": bulk,
        "needs_review": bool(reasons),
        "reasons": reasons,
        "hypotheses": hypotheses,
    }


def assess_binding(card, resolution, quotes, *, threshold_cents=1000):
    """Valuation of a bound selection never mixes in a legacy foil snapshot."""
    from .print_reference import prudent_quote

    selection = resolution["price_selection"]
    selected = selection["quote"]
    eligible = (
        selection["state"] == "active"
        and resolution["pricing_eligible"]
        and selected["currency"] == "EUR"
    )
    current_quotes = [
        q
        for q in quotes
        if eligible
        and q.get("acquisition_id") == selected.get("acquisition_id")
        and q.get("binding_key") == selected["binding_key"]
        and q.get("currency") == "EUR"
        and q.get("population") == selected["population"]
    ]
    trends = [q["amount_cents"] for q in current_quotes if q["metric"] == "trend"]
    trend = trends[0] if len(trends) == 1 else None
    prudent = (
        prudent_quote(current_quotes, selected["binding"], resolution)
        if eligible
        else None
    )
    risk = prudent if prudent is not None else trend
    reasons = []
    if not eligible:
        reasons.append(
            {
                "code": "binding",
                "label": "Cotation suspendue ou retirée : correspondance marchande à résoudre",
            }
        )
    if prudent is None:
        reasons.append(
            {
                "code": "price",
                "label": "Valeur prudente inconnue pour la correspondance sélectionnée",
            }
        )
    if risk is not None and risk >= threshold_cents:
        if not card.get("variant_confirmed"):
            reasons.append({"code": "variant", "label": "Finition physique à examiner"})
        if not card.get("condition_confirmed"):
            reasons.append({"code": "condition", "label": "État physique à examiner"})
    return {
        "trend_cents": trend,
        "prudent_cents": prudent,
        "sale_estimate_cents": None,
        "risk_cents": risk,
        "risk_incomplete": prudent is None,
        "threshold_cents": threshold_cents,
        "is_valuable": risk is not None and risk >= threshold_cents,
        "market_unstable": False,
        "variant_catalog_warning": False,
        "manual_price": None,
        "market_product": None,
        "price_variant_issue": None if eligible else reasons[0]["label"],
        "bulk": False,
        "needs_review": bool(reasons),
        "reasons": reasons,
        "hypotheses": [],
    }


def totals(cards):
    """Known subtotals always carry coverage; an entirely missing total is null."""
    result = {}
    bulk = sum(bool(c["valuation"].get("bulk")) for c in cards)
    for key in ("trend", "prudent", "sale_estimate"):
        known = [
            c["valuation"][key + "_cents"]
            for c in cards
            if c["valuation"][key + "_cents"] is not None
        ]
        result[key + "_cents"] = sum(known) if known else None
        result[key + "_known"] = len(known)
        # Bulk copies have no price by design; they are counted apart.
        result[key + "_missing"] = len(cards) - len(known) - bulk
    result["bulk_copies"] = bulk
    result["copies"] = len(cards)
    result["review_count"] = sum(c["valuation"]["needs_review"] for c in cards)
    return result
