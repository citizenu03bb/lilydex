"""Dated TCGdex price snapshots for confirmed identities; no condition discount."""

import json
import re
import statistics
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .inventory import Conflict, cents, now

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
# Below this value cards are sold in bulk lots: warnings would only be noise.
MATERIAL_EUR = 2.0


def fetch_card(catalog_id, language):
    """Card JSON with pricing; the Cardmarket product is shared by all languages."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", catalog_id or ""):
        raise ValueError("Identifiant de catalogue invalide.")
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
        if isinstance(data, dict) and (data.get("pricing") or {}).get("cardmarket"):
            return data
    raise RuntimeError(
        "TCGdex indisponible ou sans prix Cardmarket pour cette carte. Réessayez plus tard."
    )


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
    variant_check = bool(material and foil and variants and not variants.get("reverse"))
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
    spread = [v for v in (metrics["avg1"], metrics["avg7"], metrics["avg30"]) if v]
    if (
        reference
        and reference >= MATERIAL_EUR
        and spread
        and max(spread + [reference]) >= 2 * min(spread + [reference])
    ):
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
    return {
        "source": SOURCE,
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
    """Competitive asking price for this condition, with its method and confidence."""
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
        cheapest = same[:3]
        estimate = statistics.median(cheapest)
        low, high = cheapest[0], cheapest[-1]
        method = f"Médiane des {len(cheapest)} offres les moins chères en {grade}."
        confidence = "bonne" if len(same) >= 3 else "moyenne"
    else:
        # Nearest condition with offers, preferring better ones (listed first).
        nearest = min(by_grade, key=lambda g: (abs(g - target), g > target))
        steps = target - nearest
        base = by_grade[nearest][0]
        estimate = base * STEP_DISCOUNT**steps
        low, high = estimate * 0.8, estimate * 1.25
        method = (
            f"Aucune offre en {grade} : offre la moins chère en {GRADES[nearest]} "
            f"({euros(base)}) × {str(STEP_DISCOUNT).replace('.', ',')} par cran d’état "
            f"({steps:+d}). "
            "Décote par défaut, à calibrer sur vos ventes."
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


class PriceService:
    def __init__(self, store, fetch=fetch_card):
        self.store, self.fetch = store, fetch

    def latest(self, db, copy_id, kind="price-snapshot"):
        row = db.execute(
            "SELECT after_json FROM events WHERE copy_id=? AND kind=? ORDER BY id DESC LIMIT 1",
            (copy_id, kind),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def estimate(self, copy_id, text, actor):
        """Record a sale estimate from pasted offers; the card itself is unchanged."""
        with self.store.connect() as db:
            card = self.store.get(db, copy_id)
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

    def refresh(self, copy_id, version, actor):
        with self.store.connect() as db:
            card = self.store.get(db, copy_id)
        if card["identification_status"] != "confirmed" or not card["catalog_id"]:
            raise ValueError(
                "Identifiez et confirmez l’édition avant de relever son prix."
            )
        if card["version"] != version:
            raise Conflict("La fiche a changé. Rechargez-la avant de relever le prix.")
        # The network call stays outside the write transaction.
        snapshot = summarize(
            self.fetch(card["catalog_id"], card["language"]), card["foil"]
        )
        snapshot["observed_at"] = now()
        changes = {
            "reference_cents": cents(snapshot["reference_eur"]),
            "price_source": f"{SOURCE} {snapshot['reference_field']}",
            "price_date": snapshot["updated"] or snapshot["observed_at"],
        }
        with self.store.connect(write=True) as db:
            current = self.store.get(db, copy_id)
            if current["version"] != version:
                raise Conflict("La fiche a changé pendant le relevé. Rechargez-la.")
            if any(current[k] != v for k, v in changes.items()):
                self.store.patch(
                    copy_id,
                    changes,
                    version,
                    actor,
                    "Relevé de prix TCGdex",
                    _db=db,
                )
            self.store.event(
                db, copy_id, actor, "price-snapshot", "Relevé TCGdex", {}, snapshot
            )
            return {**self.store.get(db, copy_id), "price_snapshot": snapshot}
