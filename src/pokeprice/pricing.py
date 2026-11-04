"""Dated TCGdex price snapshots for confirmed identities; no condition discount."""

import copy
import json
import re
import statistics
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .inventory import Conflict, cents, now
from .valuation import applicable
from .variant_pricing import (
    category,
    has_original_holo_and_reverse,
    has_parallel_holo,
    pricing_issue,
)

# Cardmarket filter codes; unknown values leave the filter out.
CARDMARKET_LANGUAGES = {
    "en": 1,
    "fr": 2,
    "de": 3,
    "es": 4,
    "it": 5,
    "ja": 7,
    "pt": 8,
    "ko": 10,
}
CARDMARKET_CONDITIONS = {
    "NM": 2,
    "NM/EX": 3,
    "EX": 3,
    "GD": 4,
    "LP": 5,
    "PL": 6,
    "PO": 7,
}
SOURCE = "TCGdex · Cardmarket"
GUIDE_SOURCE = "Cardmarket · guide des prix"
# Below this value cards are sold in bulk lots: warnings would only be noise.
MATERIAL_EUR = 2.0


class NoCardmarketQuote(ValueError):
    """TCGdex knows the card but has no Cardmarket quote: retrying will not help."""


def fetch_catalogue_card(catalog_id, language, *, require_price=False):
    """Edition metadata is useful even when no euro quote is available."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", catalog_id or ""):
        raise ValueError("Identifiant de catalogue invalide.")
    unpriced = False
    for lang in dict.fromkeys([language, "en"]):
        request = Request(
            f"https://api.tcgdex.net/v2/{lang}/cards/{catalog_id}",
            headers={"User-Agent": "pokeprice/0.1.0"},
        )
        try:
            with urlopen(request, timeout=15) as response:
                data = json.loads(response.read())
        except Exception:  # noqa: BLE001, S112 - Try the next language; details are not useful.
            continue
        if not isinstance(data, dict) or data.get("id") != catalog_id:
            continue
        if require_price and not (data.get("pricing") or {}).get("cardmarket"):
            unpriced = True
            continue
        return {
            **data,
            "_acquisition": {
                "provider": "TCGdex",
                "requested_language": language,
                "served_language": lang,
                "source": request.full_url,
            },
        }
    if unpriced:
        raise NoCardmarketQuote(
            "TCGdex connaît cette carte mais ne fournit aucun prix Cardmarket. "
            "Relevez la tendance sur Cardmarket et saisissez-la comme prix de "
            "référence, avec sa source : elle servira de valeur manuelle."
        )
    raise RuntimeError("TCGdex indisponible pour cette édition. Réessayez plus tard.")


def fetch_card(catalog_id, language):
    """Card JSON with pricing; the Cardmarket product is shared by all languages."""
    return fetch_catalogue_card(catalog_id, language, require_price=True)


def fetch_card_with_guide(guide):
    """fetch_card, completed by Cardmarket's price guide when TCGdex has no quote."""
    from .cardmarket_guide import has_quote

    def fetch(catalog_id, language):
        try:
            data = fetch_card(catalog_id, language)
        except NoCardmarketQuote as missing:
            data = guide.complete(fetch_catalogue_card(catalog_id, language))
            if not has_quote((data.get("pricing") or {}).get("cardmarket")):
                raise missing
            return data
        return guide.complete(data)

    fetch.guide = guide
    return fetch


def summarize(data, foil):
    """Prices of the copy's variant, with the warnings a seller must check."""
    cardmarket = (data.get("pricing") or {}).get("cardmarket") or {}
    suffix = "-holo" if foil else ""

    def value(key):
        v = cardmarket.get(key + suffix)
        return float(v) if isinstance(v, (int, float)) and v >= 0 else None

    metrics = {k: value(k) for k in ("low", "avg1", "avg7", "avg30", "avg", "trend")}
    field = "trend" if metrics["trend"] is not None else "avg30"
    reference = metrics[field]
    warnings = []
    other = cardmarket.get("trend" if foil else "trend-holo")
    other = float(other) if isinstance(other, (int, float)) and other > 0 else None
    material = max(reference or 0, other or 0) >= MATERIAL_EUR
    variants = data.get("variants") or {}
    # Foil without any known reverse: holo stamp, promo, or a misread variant.
    variant_check = bool(
        material
        and foil
        and variants
        and not variants.get("reverse")
        and not has_parallel_holo({"variants": variants, "raw": data.get("pricing")})
        and not has_original_holo_and_reverse({"raw": data.get("pricing")})
    )
    if variant_check:
        warnings.append(
            "TCGdex ne connaît pas de version Foil (reverse) de cette carte"
            + (
                " : elle est imprimée holo d’origine. Sauf variante spéciale "
                "(tampon, promo), choisissez « Standard » : son prix est la tendance."
                if variants.get("holo") and not variants.get("normal")
                else " : vérifiez qu’elle brille plus que la version standard "
                "(reverse, holo tamponnée…) avant de retenir ce prix."
            )
        )
    if (
        material
        and other
        and reference
        and max(other, reference) / min(other, reference) >= 3
    ):
        warnings.append(
            f"L’autre variante cote {f'{other:.2f}'.replace('.', ',')} € : "
            "une erreur de variante changerait fortement la valeur."
        )
    if unstable(metrics, reference):
        warnings.append(
            "Marché instable : les moyennes sur 1, 7 et 30 jours divergent fortement."
        )
    if (
        reference
        and reference >= MATERIAL_EUR
        and metrics["low"] is not None
        and metrics["low"] < reference * 0.25
    ):
        warnings.append(
            "Le prix bas est très inférieur à la tendance : peu d’offres comparables."
        )
    guide = (data.get("_acquisition") or {}).get("cardmarket_guide")
    return {
        "source": GUIDE_SOURCE if guide else SOURCE,
        "cardmarket_guide": guide,
        "acquisition": data.get("_acquisition")
        or {"provider": "TCGdex", "requested_language": None, "served_language": None},
        "requested_language": (data.get("_acquisition") or {}).get(
            "requested_language"
        ),
        "served_language": (data.get("_acquisition") or {}).get("served_language"),
        "catalog_id": data.get("id"),
        "variant": "holo/reverse" if foil else "normale",
        "updated": cardmarket.get("updated") or "",
        "id_product": cardmarket.get("idProduct"),
        "metrics": metrics,
        "reference_field": field + suffix,
        "reference_eur": reference,
        "other_variant_trend_eur": other,
        "warnings": warnings,
        "variant_check": variant_check,
        "variants": variants,
        "rarity": data.get("rarity") or "",
        "raw": data.get("pricing"),
    }


def unstable(metrics, reference):
    """The 1, 7 and 30-day averages and the reference differ twofold, from 2 € up."""
    spread = [v for v in (metrics.get("avg1"), metrics.get("avg7"), metrics.get("avg30")) if v]
    return bool(
        reference
        and reference >= MATERIAL_EUR
        and spread
        and max(spread + [reference]) >= 2 * min(spread + [reference])
    )


def binding_market_url(binding):
    """A bound product link uses its evidenced native filters, never `foil`."""
    if binding.get("market") != "cardmarket":
        return None
    product = re.fullmatch(r"cardmarket:(\d+)", binding.get("product_ref", ""))
    if not product:
        return None
    filters = binding.get("filters", {})
    query = {"idProduct": product[1], **({} if filters == {"none": True} else filters)}
    return "https://www.cardmarket.com/fr/Pokemon/Products?" + urlencode(
        query, doseq=True
    )


def cardmarket_url(id_product, language="", condition="", foil=False):
    """Offers of the product for the copy's language, condition (or better) and variant."""
    if not isinstance(id_product, int):
        return None
    query = {"idProduct": id_product}
    if language in CARDMARKET_LANGUAGES:
        query["language"] = CARDMARKET_LANGUAGES[language]
    if condition in CARDMARKET_CONDITIONS:
        query["minCondition"] = CARDMARKET_CONDITIONS[condition]
    if foil:
        query["isReverseHolo"] = "Y"
    return "https://www.cardmarket.com/fr/Pokemon/Products?" + urlencode(query)


def cardmarket_search_url(english_name, catalog_id, set_code=None):
    """Inferred search when TCGdex gives no product: a unique match opens its page."""
    if not english_name or not catalog_id or "-" not in catalog_id:
        return None
    number = catalog_id.rsplit("-", 1)[1]
    # Cardmarket spells gender signs [F]/[M]; the bare name still matches.
    name = re.sub(r"[♀♂]", " ", english_name)
    # "Darkrai GE 4" opens the product; "Darkrai 4" may list several.
    words = " ".join(f"{name} {set_code or ''} {number}".split())
    return "https://www.cardmarket.com/fr/Pokemon/Products/Search?" + urlencode(
        {"searchString": words}
    )


# --- Sale estimate from offers pasted from a Cardmarket product page ---------

# Cardmarket condition codes, best first.
GRADES = ["MT", "NM", "EX", "GD", "LP", "PL", "PO"]
# Default discount for each condition step below, until own sales calibrate it.
STEP_DISCOUNT = 0.75
PRICE = re.compile(r"^(\d{1,3}(?:[.\u202f ]\d{3})*,\d{2}) ?€$")
STAMP_WORDS = re.compile(r"stamp|tampon|tamponn|logo", re.IGNORECASE)


def euros(value):
    return f"{value:.2f}".replace(".", ",") + " €"


def parse_offers(text):
    """Offers as (condition, price, comment) from text copied off a Cardmarket page.

    Each offer reads: seller lines, a condition code, optional comment lines,
    then a price such as "59,00 €". Header prices (trend, averages) have no
    condition code before them and are skipped.
    """
    offers, current = [], None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line in GRADES:
            current = {"condition": line, "comment": []}
            continue
        match = PRICE.match(line)
        if match and current:
            amount = float(re.sub(r"[.\u202f ]", "", match.group(1)).replace(",", "."))
            offers.append(
                {
                    "condition": current["condition"],
                    "price_eur": amount,
                    "comment": " ".join(current["comment"])[:300],
                }
            )
            current = None
        elif current:
            current["comment"].append(line)
    return offers


def estimate_sale(offers, condition, *, stamp=""):
    """Market asking price for this condition, with its range, method and confidence."""
    warnings = []
    used = offers
    if stamp:
        used = [o for o in offers if STAMP_WORDS.search(o["comment"])]
        warnings.append(
            f"Variante tamponnée : {len(used)} offre(s) sur {len(offers)} mentionnent "
            "un tampon dans leur commentaire ; les autres sont écartées."
        )
    grade = "EX" if condition == "NM/EX" else condition
    if not used:
        raise ValueError("Aucune offre comparable dans le texte collé.")
    if grade not in GRADES:
        raise ValueError(
            "Renseignez l’état de la carte avant d’estimer son prix de vente."
        )
    target = GRADES.index(grade)
    by_grade = {}
    for offer in used:
        by_grade.setdefault(GRADES.index(offer["condition"]), []).append(
            offer["price_eur"]
        )
    for prices in by_grade.values():
        prices.sort()
    same = by_grade.get(target, [])
    if same:
        # Market price: median of every comparable asking price, not the cheapest
        # few, which are often damaged copies or clearance sales.
        estimate = statistics.median(same)
        if len(same) >= 4:
            low, _, high = statistics.quantiles(same, n=4, method="inclusive")
            spread = "premier au troisième quartile"
        else:
            low, high = same[0], same[-1]
            spread = "offre la moins chère à la plus chère"
        method = f"Médiane des {len(same)} offres en {grade} ; fourchette : {spread}."
        confidence = (
            "bonne" if len(same) >= 5 else "moyenne" if len(same) >= 2 else "faible"
        )
    else:
        # Nearest condition with offers, preferring better ones (listed first).
        nearest = min(by_grade, key=lambda g: (abs(g - target), g > target))
        steps = target - nearest
        base = statistics.median(by_grade[nearest])
        estimate = base * STEP_DISCOUNT**steps
        low, high = estimate * 0.8, estimate * 1.25
        method = (
            f"Aucune offre en {grade} : médiane en {GRADES[nearest]} "
            f"({euros(base)}) × {str(STEP_DISCOUNT).replace('.', ',')} par cran d’état "
            f"({steps:+d}). Décote par défaut, à calibrer sur vos ventes."
        )
        confidence = "faible"
    if len(used) < 3:
        warnings.append("Moins de trois offres comparables : estimation fragile.")
    return {
        "estimate_eur": round(estimate, 2),
        "low_eur": round(low, 2),
        "high_eur": round(high, 2),
        "condition": grade,
        "method": method,
        "confidence": confidence,
        "offers_used": len(used),
        "offers_total": len(offers),
        "by_condition": {
            GRADES[g]: prices[:5] for g, prices in sorted(by_grade.items())
        },
        "warnings": warnings,
    }


FLOOR_CENTS = 50  # Below this, a card goes into a lot or is given away.
HIGH_VALUE_CENTS = 1000  # From here, a trend alone is not a selling price.
TREND_CONDITIONS = {"MT", "NM", "EX", "NM/EX"}


def round_up_tenth(amount_cents):
    return -(-amount_cents // 10) * 10


def display_price(card, valuation, override=None):
    """Storefront price for one copy, or the reasons it cannot be published alone.

    Decisions of 16 October: a manual price wins, then an estimate from offers in
    the same condition, then the Cardmarket trend rounded up to the next tenth for
    checked NM/EX cards under 10 €. No condition discount is ever applied; below
    the 0.50 € floor the card belongs in a lot or is given away.
    """
    result = {
        "publishable": False,
        "price_cents": None,
        "mode": None,
        "source": "",
        "date": "",
        "reasons": [],
        "suggestion": None,
    }
    reasons = result["reasons"]
    if card.get("deleted_at"):
        reasons.append("Exemplaire supprimé de la collection.")
    if card.get("stock_state", "available") != "available":
        reasons.append("Exemplaire déjà réservé ou vendu.")
    if card.get("identification_status") != "confirmed":
        reasons.append("Identité à confirmer avant de publier.")
    if reasons:
        return result
    manual = (valuation or {}).get("manual_price")
    raw = None
    if override:
        raw = override["amount_cents"]
        result.update(
            price_cents=override["amount_cents"],
            mode=override.get("mode", "manual"),
            source=override.get("source") or "Prix fixé à la main",
            date=override.get("date") or now(),
        )
    elif not card.get("condition_confirmed"):
        reasons.append("État à confirmer, ou prix à fixer à la main.")
    elif (valuation or {}).get("sale_estimate_cents") is not None:
        raw = valuation["sale_estimate_cents"]
        result.update(
            price_cents=round_up_tenth(valuation["sale_estimate_cents"]),
            mode="offers",
            source="Estimation sur les offres Cardmarket au même état",
        )
    elif manual:
        raw = manual["amount_cents"]
        result.update(
            price_cents=round_up_tenth(manual["amount_cents"]),
            mode="manual",
            source=manual["source"],
            date=manual["observed_at"],
        )
    elif not card.get("variant_confirmed") or (valuation or {}).get("price_variant_issue"):
        reasons.append("Variante à vérifier sur la carte avant un prix automatique.")
    elif card.get("condition") not in TREND_CONDITIONS:
        reasons.append(
            f"État {card.get('condition') or 'inconnu'} : pas de tendance pour un état "
            "inférieur à EX, fixez le prix à la main."
        )
    elif (valuation or {}).get("trend_cents") is None:
        reasons.append("Aucune tendance relevée : relevez le prix ou fixez-le à la main.")
    elif valuation["trend_cents"] >= HIGH_VALUE_CENTS:
        reasons.append(
            "10 € ou plus : estimez le prix sur les offres au même état, ou fixez-le à la main."
        )
    else:
        raw = valuation["trend_cents"]
        result.update(
            price_cents=round_up_tenth(valuation["trend_cents"]),
            mode="trend",
            source=SOURCE + " (tendance)",
            date=card.get("price_date") or "",
        )
    # The floor is checked before rounding: 0.41 € stays a card for a lot.
    if result["price_cents"] is not None and raw < FLOOR_CENTS:
        reasons.append(
            f"Sous le plancher de {euros(FLOOR_CENTS / 100)} ({euros(raw / 100)}) : "
            "à mettre dans un lot ou à offrir."
        )
        result["suggestion"] = "lot"
    result["publishable"] = result["price_cents"] is not None and not reasons
    return result


# A batch reports the copies whose reference moves by this share or more.
NOTABLE_CHANGE = 0.2
# What makes a new snapshot worth a journal entry.
SNAPSHOT_KEYS = ("catalog_id", "source", "id_product", "reference_field", "reference_eur")


def snapshot_changed(previous, snapshot):
    return previous is None or any(
        previous.get(k) != snapshot.get(k) for k in SNAPSHOT_KEYS
    )


def remember_product(db, catalog_id, snapshot, data):
    """Keep the product TCGdex gives as the card's catalogue lookup.

    A batch then prices the card from Cardmarket's guide without asking TCGdex.
    A product the guide matched itself is not TCGdex's and is not kept.
    """
    from .cardmarket_guide import TCGDEX_PRODUCT

    product = snapshot.get("id_product")
    guide = snapshot.get("cardmarket_guide")
    if not isinstance(product, int) or (guide and guide.get("method") != TCGDEX_PRODUCT):
        return
    key = f"cardmarket-product:{catalog_id}"
    row = db.execute(
        "SELECT value FROM catalog_lookups WHERE key=? AND found=1", (key,)
    ).fetchone()
    old = json.loads(row[0] or "{}") if row else {}
    if old.get("id_product") == product:
        return
    # Neighbour warnings show English names: other languages keep the old one.
    english = (data.get("_acquisition") or {}).get("served_language") == "en"
    value = {
        "id_product": product,
        "name": (data.get("name") if english else old.get("name")) or "",
        "hp": data.get("hp") if english else old.get("hp"),
    }
    db.execute(
        "INSERT OR REPLACE INTO catalog_lookups VALUES(?,?,?,?)",
        (key, 1, json.dumps(value, ensure_ascii=False), now()),
    )


def held_pending(db, copy_id):
    """The copy's last held quote is newer than its last snapshot."""
    held, snapshot = db.execute(
        "SELECT max(CASE WHEN kind='price-held' THEN id END),"
        " max(CASE WHEN kind='price-snapshot' THEN id END)"
        " FROM events WHERE copy_id=? AND kind IN ('price-held','price-snapshot')",
        (copy_id,),
    ).fetchone()
    return held is not None and held > (snapshot or 0)


def new_summary(selected):
    return {
        "selected": selected,
        "editions": 0,
        "refreshed": 0,
        "changed": 0,
        "recorded": 0,
        "warned": 0,
        "variant_check": 0,
        "shared_product": [],
        "failed": [],
        "notable": [],
        "held": [],
        "reference_before_cents": 0,
        "reference_after_cents": 0,
    }


def tally(summary, row, card, error, threshold=NOTABLE_CHANGE):
    """Add one copy's outcome to a batch summary."""
    before = row["reference_cents"]
    summary["reference_before_cents"] += before or 0
    if error:
        summary["failed"].append({"id": row["id"], "error": error})
        summary["reference_after_cents"] += before or 0
        return
    after = card["reference_cents"]
    snapshot = card["price_snapshot"]
    summary["refreshed"] += 1
    summary["changed"] += after != before
    summary["recorded"] += bool(card.get("snapshot_recorded"))
    summary["warned"] += bool(snapshot["warnings"])
    summary["variant_check"] += bool(snapshot.get("variant_check"))
    summary["reference_after_cents"] += after or 0
    if card.get("held"):
        summary["held"].append(
            {
                "id": row["id"],
                "name": row.get("name") or card.get("name") or "",
                "catalog_id": row["catalog_id"],
                "before_cents": before,
                "proposed_cents": snapshot["held"]["proposed_cents"],
                "source": f"{snapshot['source']} {snapshot['reference_field']}",
            }
        )
    if snapshot.get("shared_product_with"):
        summary["shared_product"].append(row["id"])
    if notable(before, after, threshold):
        summary["notable"].append(
            {
                "id": row["id"],
                "name": row.get("name") or card.get("name") or "",
                "catalog_id": row["catalog_id"],
                "before_cents": before,
                "after_cents": after,
                "source": card.get("price_source") or "",
            }
        )


def notable(before, after, threshold):
    """A price that appears, disappears or moves by the threshold, from 2 € up."""
    if before == after:
        return False
    if before is None or after is None:
        return True
    if max(before, after) < MATERIAL_EUR * 100:
        return False
    return abs(after - before) >= threshold * before


class PriceService:
    def __init__(self, store, fetch=fetch_card, market=None):
        self.store, self.fetch, self.market = store, fetch, market

    def latest(self, db, copy_id, kind="price-snapshot"):
        row = db.execute(
            "SELECT after_json FROM events WHERE copy_id=? AND kind=? ORDER BY id DESC LIMIT 1",
            (copy_id, kind),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def selected(self, *, album="", only_missing=False, unpriced=False, limit=None, copy_ids=None):
        """Confirmed copies linked to the catalogue, in a stable order."""
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT id,version,reference_cents,catalog_id,language,name FROM copies WHERE deleted_at='' AND identification_status='confirmed' AND catalog_id IS NOT NULL AND (?='' OR album_id=?) ORDER BY id",
                (album, album),
            ).fetchall()
            done = (
                {
                    r[0]
                    for r in db.execute(
                        "SELECT DISTINCT copy_id FROM events WHERE kind='price-snapshot'"
                    )
                }
                if only_missing
                else set()
            )
        wanted = None if copy_ids is None else set(copy_ids)
        return [
            dict(r)
            for r in rows
            if not (only_missing and r["id"] in done)
            and not (unpriced and r["reference_cents"] is not None)
            and (wanted is None or r["id"] in wanted)
        ][:limit]

    def refresh_many(
        self,
        actor,
        *,
        album="",
        only_missing=False,
        unpriced=False,
        limit=None,
        workers=4,
        copy_ids=None,
        threshold=NOTABLE_CHANGE,
    ):
        """Snapshot every confirmed identity; one failure never stops the others.

        Copies of one edition (catalogue id and language) share a single
        catalogue request: its answer is applied to each of them.
        """
        from concurrent.futures import ThreadPoolExecutor

        rows = self.selected(
            album=album,
            only_missing=only_missing,
            unpriced=unpriced,
            limit=limit,
            copy_ids=copy_ids,
        )
        editions = list(dict.fromkeys((r["catalog_id"], r["language"]) for r in rows))

        def fetch(edition):
            catalog_id, language = edition
            try:
                if self.market:
                    # Cached for the search link, even when TCGdex has no euro quote.
                    self.market.set_code(catalog_id)
                return edition, self.fetch(catalog_id, language), None
            except Exception as error:  # noqa: BLE001 - Reported per card.
                return edition, None, str(error)

        def one(row):
            data, error = answers[(row["catalog_id"], row["language"])]
            if error:
                return row, None, error
            try:
                card = self.refresh(
                    row["id"],
                    row["version"],
                    actor,
                    data=copy.deepcopy(data),
                    batch=True,
                    threshold=threshold,
                )
                return row, card, None
            except Exception as error:  # noqa: BLE001 - Reported per card.
                return row, None, str(error)

        summary = new_summary(len(rows))
        summary["editions"] = len(editions)
        with ThreadPoolExecutor(workers) as pool:
            answers = {e: (d, err) for e, d, err in pool.map(fetch, editions)}
            for row, card, error in pool.map(one, rows):
                tally(summary, row, card, error, threshold)
        return summary

    def refresh_from_guide(
        self,
        actor,
        guide,
        *,
        album="",
        only_missing=False,
        unpriced=False,
        limit=None,
        workers=4,
        threshold=NOTABLE_CHANGE,
    ):
        """Price every copy whose Cardmarket product is known from the day's guide.

        The product comes from the catalogue lookups TCGdex filled
        (``cardmarket-product:*``); the variants come from the copy's last
        snapshot. All these snapshots are written in one transaction, without
        any catalogue request. The other copies take the usual path.
        """
        from .cardmarket_guide import CACHED_PRODUCT, FILES
        from .market_product import neighbours

        loaded = guide.load()
        if not loaded:
            raise RuntimeError(
                "Guide des prix Cardmarket indisponible : relancez sans --from-guide."
            )
        rows = self.selected(
            album=album, only_missing=only_missing, unpriced=unpriced, limit=limit
        )
        with self.store.connect() as db:
            products = {
                r["key"].partition(":")[2]: json.loads(r["value"] or "{}")
                for r in db.execute(
                    "SELECT key,value FROM catalog_lookups WHERE found=1 AND key LIKE 'cardmarket-product:%'"
                )
            }
            verdicts = self.store.market_verdicts(db)
            latest = {
                r["copy_id"]: json.loads(r["after_json"])
                for r in db.execute(
                    "SELECT copy_id,after_json FROM events WHERE id IN "
                    "(SELECT max(id) FROM events WHERE kind='price-snapshot' GROUP BY copy_id) ORDER BY id"
                )
            }
        # Variants of an edition, from any copy's snapshot of the same catalogue id.
        known = {s.get("catalog_id"): s for s in latest.values() if s.get("catalog_id")}
        planned, fallback = [], []
        for row in rows:
            catalog_id = row["catalog_id"]
            product = (products.get(catalog_id) or {}).get("id_product")
            base = latest.get(row["id"])
            if (base or {}).get("catalog_id") != catalog_id:
                base = known.get(catalog_id)
            data = (
                guide.quote(
                    {
                        "id": catalog_id,
                        # TCGdex's other markets still tell parallel holos apart.
                        "pricing": base.get("raw") or {},
                        "variants": base.get("variants") or {},
                        "rarity": base.get("rarity") or "",
                        "_acquisition": {
                            "provider": "Cardmarket",
                            "requested_language": row["language"],
                            "served_language": None,
                            "source": FILES["price_guide_6.json"],
                        },
                    },
                    product,
                    CACHED_PRODUCT,
                    loaded=loaded,
                )
                if base and applicable(verdicts.get(catalog_id), product) != "wrong"
                else None
            )
            (planned if data else fallback).append((row, data))
        summary = new_summary(len(rows))
        summary["guide"] = {"created": loaded[0], "priced": 0}
        with self.store.connect(write=True) as db:
            for row, data in planned:
                # One savepoint per copy: a refused copy leaves the others intact.
                db.execute("SAVEPOINT copy")
                try:
                    card = self.store.get(db, row["id"])
                    if card["version"] != row["version"]:
                        raise Conflict("La fiche a changé pendant le relevé.")
                    card, data, snapshot = self._quote(
                        card, data, verdicts.get(row["catalog_id"])
                    )
                    product = snapshot["id_product"]
                    snapshot["shared_product_with"] = [
                        {
                            "catalog_id": other,
                            "name": products[other].get("name") or "",
                            "hp": products[other].get("hp"),
                        }
                        for other in neighbours(row["catalog_id"])
                        if (products.get(other) or {}).get("id_product") == product
                    ]
                    snapshot["observed_at"] = now()
                    result = self._record(
                        db,
                        row["id"],
                        row["version"],
                        card,
                        snapshot,
                        actor,
                        batch=True,
                        threshold=threshold,
                    )
                    db.execute("RELEASE copy")
                except Exception as error:  # noqa: BLE001 - Reported per card.
                    db.execute("ROLLBACK TO copy")
                    db.execute("RELEASE copy")
                    tally(summary, row, None, str(error), threshold)
                    continue
                summary["guide"]["priced"] += 1
                tally(summary, row, result, None, threshold)
        if fallback:
            rest = self.refresh_many(
                actor,
                workers=workers,
                copy_ids=[row["id"] for row, _ in fallback],
                threshold=threshold,
            )
            summary["editions"] = rest["editions"]
            for key, value in rest.items():
                if key in ("selected", "editions"):
                    continue
                summary[key] = summary[key] + value
        else:
            summary["editions"] = 0
        return summary

    def estimate(self, copy_id, text, actor):
        """Record a sale estimate from pasted offers; the card itself is unchanged."""
        with self.store.connect() as db:
            card = self.store.get(db, copy_id)
            metadata = self.store.category_snapshot(db, card)
        if issue := pricing_issue(card, metadata):
            raise ValueError(issue)
        offers = parse_offers(text)
        if not offers:
            raise ValueError(
                "Aucune offre reconnue. Copiez la liste des offres de la page Cardmarket (Ctrl+A, Ctrl+C) puis collez-la ici."
            )
        result = estimate_sale(offers, card["condition"], stamp=card["stamp"])
        plain_text = (text or "")[:4000].lower()
        if card["name"].lower() not in plain_text:
            result["warnings"].append(
                f"Le texte collé ne mentionne pas « {card['name']} » : vérifiez qu’il s’agit du bon produit."
            )
        result.update(
            observed_at=now(),
            catalog_id=card["catalog_id"],
            name=card["name"],
            number=card["number"],
            set_name=card["set_name"],
            language=card["language"],
            foil=bool(card["foil"]),
            stamp=card["stamp"],
            offers=offers[:60],
        )
        with self.store.connect(write=True) as db:
            self.store.event(
                db,
                copy_id,
                actor,
                "sale-estimate",
                "Estimation de vente depuis des offres Cardmarket collées",
                {},
                result,
            )
        return result

    def refresh(
        self, copy_id, version, actor, *, data=None, batch=False, threshold=NOTABLE_CHANGE
    ):
        """Quote one copy; ``data`` is the edition's answer when a batch has it.

        A batch leaves the copy untouched when only the quote date moves, so
        an unchanged price costs neither a new version nor a journal entry.
        """
        with self.store.connect() as db:
            card = self.store.get(db, copy_id)
        if card["identification_status"] != "confirmed" or not card["catalog_id"]:
            raise ValueError(
                "Identifiez et confirmez l’édition avant de relever son prix."
            )
        if card["version"] != version:
            raise Conflict("La fiche a changé. Rechargez-la avant de relever le prix.")
        # The network calls stay outside the write transaction.
        if data is None:
            if self.market:
                # Cached for the search link, even when TCGdex has no euro quote.
                self.market.set_code(card["catalog_id"])
            data = self.fetch(card["catalog_id"], card["language"])
        with self.store.connect() as db:
            verdict = self.store.market_verdicts(db).get(card["catalog_id"])
        card, data, snapshot = self._quote(card, data, verdict)
        snapshot["shared_product_with"] = (
            self.market.shared_with(card["catalog_id"], snapshot["id_product"])
            if self.market
            else []
        )
        snapshot["observed_at"] = now()
        with self.store.connect(write=True) as db:
            result = self._record(
                db, copy_id, version, card, snapshot, actor, batch=batch, threshold=threshold
            )
            # The edition name in the copy's language comes free with the relevé.
            from .names import NameCatalog

            NameCatalog.record(
                db, card["catalog_id"], card["language"], data.get("name"), "edition"
            )
            remember_product(db, card["catalog_id"], snapshot, data)
            return result

    def _quote(self, card, data, verdict):
        """The copy (with its calculated category) and its checked snapshot."""
        if data.get("id") != card["catalog_id"]:
            raise ValueError("Le catalogue retourné ne correspond pas à cette édition.")
        decision = category(card, summarize(data, card["foil"]))
        if decision["mode"] == "automatic":
            card = {**card, "foil": decision["foil"]}
        snapshot = summarize(data, card["foil"])
        if issue := pricing_issue(card, snapshot):
            raise ValueError(issue)
        if applicable(verdict, snapshot["id_product"]) == "wrong":
            # The guide may know the print's own product (decision 0016).
            guide = getattr(self.fetch, "guide", None)
            rematched = (
                guide.complete(
                    {**data, "pricing": {**(data.get("pricing") or {}), "cardmarket": {}}}
                )
                if guide
                else data
            )
            product = ((rematched.get("pricing") or {}).get("cardmarket") or {}).get(
                "idProduct"
            )
            if isinstance(product, int) and product != snapshot["id_product"]:
                data = rematched
                decision = category(card, summarize(data, card["foil"]))
                if decision["mode"] == "automatic":
                    card = {**card, "foil": decision["foil"]}
                snapshot = summarize(data, card["foil"])
                if issue := pricing_issue(card, snapshot):
                    raise ValueError(issue)
        if applicable(verdict, snapshot["id_product"]) == "wrong":
            raise ValueError(
                "Le produit Cardmarket que TCGdex associe à cette carte a été "
                "signalé incorrect. Saisissez la tendance relevée sur la bonne "
                "page comme prix de référence, avec sa source."
            )
        return card, data, snapshot

    def _record(
        self, db, copy_id, version, card, snapshot, actor, *, batch=False, threshold=NOTABLE_CHANGE
    ):
        """Apply a snapshot inside the caller's write transaction.

        The price-snapshot event is written only when the price, the source or
        the Cardmarket product changes, or when the copy itself changes.
        A batch keeps the reference that an unstable market would move by the
        threshold (decision 0023): the quote goes to a price-held event, for
        review, and the copy and its valuation stay as they were.
        """
        current = self.store.get(db, copy_id)
        if current["version"] != version:
            raise Conflict("La fiche a changé pendant le relevé. Rechargez-la.")
        changes = {
            "foil": bool(card["foil"]),
            "reference_cents": cents(snapshot["reference_eur"]),
            "price_source": f"{snapshot['source']} {snapshot['reference_field']}",
            "price_date": snapshot["updated"] or snapshot["observed_at"],
        }
        if (
            batch
            and bool(current["foil"]) == changes["foil"]
            and current["reference_cents"] is not None
            and notable(current["reference_cents"], changes["reference_cents"], threshold)
            and unstable(snapshot["metrics"], snapshot["reference_eur"])
        ):
            snapshot = {
                **snapshot,
                "held": {
                    "reference_cents": current["reference_cents"],
                    "proposed_cents": changes["reference_cents"],
                },
            }
            recorded = snapshot_changed(self.latest(db, copy_id, "price-held"), snapshot)
            if recorded:
                self.store.event(
                    db, copy_id, actor, "price-held", "Cote retenue : marché instable", {}, snapshot
                )
            return {
                **current,
                "price_snapshot": snapshot,
                "snapshot_recorded": recorded,
                "held": True,
            }
        compared = (
            ("foil", "reference_cents", "price_source")
            if batch and current["price_date"]
            else changes
        )
        patched = any(current[k] != changes[k] for k in compared)
        if patched:
            self.store.patch(
                copy_id,
                changes,
                version,
                actor,
                f"Relevé de prix {snapshot['source']}",
                _db=db,
                _category_snapshot=snapshot,
            )
        recorded = (
            patched
            or snapshot_changed(self.latest(db, copy_id), snapshot)
            # A quote that clears a held one is written, so the review ends.
            or held_pending(db, copy_id)
        )
        if recorded:
            self.store.event(
                db, copy_id, actor, "price-snapshot", "Relevé TCGdex", {}, snapshot
            )
        return {
            **self.store.get(db, copy_id),
            "price_snapshot": snapshot,
            "snapshot_recorded": recorded,
        }
