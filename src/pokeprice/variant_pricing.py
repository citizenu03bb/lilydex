"""Price categories supported by physical observations and documented print runs."""

import re

from .library import normalized


def has_original_holo_and_reverse(snapshot):
    """Explicitly priced holo and reverse prints, without a matte print."""
    raw = snapshot.get("raw") or {}
    prints = raw.get("tcgplayer") if isinstance(raw, dict) else None
    return bool(
        isinstance(prints, dict)
        and "normal" not in prints
        and isinstance(prints.get("holofoil"), dict)
        and isinstance(prints.get("reverse-holofoil"), dict)
    )


def has_parallel_holo(snapshot):
    """Two explicitly priced prints, matte and holo, with no reverse print."""
    variants = snapshot.get("variants") or {}
    raw = snapshot.get("raw") or {}
    prints = raw.get("tcgplayer") if isinstance(raw, dict) else None
    prints = prints if isinstance(prints, dict) else {}
    return bool(
        isinstance(variants, dict)
        and variants.get("normal") is True
        and variants.get("holo") is True
        and variants.get("reverse") is False
        and isinstance(prints.get("normal"), dict)
        and isinstance(prints.get("holofoil"), dict)
    )


def category(card, snapshot=None):
    """Derive the marketplace category without inventing a physical observation."""
    finish = card.get("finish") or ""
    result = {
        "foil": None,
        "mode": "review",
        "reason": "Édition ou variante spéciale à vérifier : précisez le produit dans les observations.",
    }
    if not finish:
        return {
            **result,
            "mode": "legacy",
            "reason": "Renseignez la finition observée pour calculer la catégorie.",
        }
    if finish == "non_holo":
        return {
            "foil": False,
            "mode": "automatic",
            "reason": "Finition mate : Standard.",
        }
    if finish == "reverse":
        return {
            "foil": True,
            "mode": "automatic",
            "reason": "Fond brillant : Foil / reverse.",
        }
    if (
        finish not in ("holo", "holo_border")
        or card.get("identification_status") != "confirmed"
    ):
        return result
    edition = re.fullmatch(r"(ex8|ex13|ex14)-(\d+)", card.get("catalog_id") or "")
    stamp = normalized(card.get("stamp") or "")
    # Pokémon's EX Holon Phantoms checklist: 18–98 have a non-holo standard
    # and a parallel foil. The set-stamped foil is marketed as reverse holo,
    # even when only the illustration is shiny. Scope this to the documented set.
    # https://assets.pokemon.com/assets/cms/pdf/tcg/checklists/holonphantoms_checklist.pdf
    if edition and (
        (
            edition[1] == "ex8"
            and 16 <= int(edition[2]) <= 95
            and stamp in ("ex deoxys", "deoxys")
        )
        or (
            edition[1] == "ex13"
            and 18 <= int(edition[2]) <= 98
            and stamp
            in (
                "ex fantomes holon",
                "fantomes holon",
                "ex holon phantoms",
                "holon phantoms",
            )
        )
        or (
            edition[1] == "ex14"
            and 14 <= int(edition[2]) <= 88
            and stamp
            in (
                "ex gardiens de cristal",
                "gardiens de cristal",
                "ex crystal guardians",
                "crystal guardians",
            )
        )
    ):
        # EX Deoxys: 16–95 have a matte standard and a parallel foil.
        # https://assets.pokemon.com/assets/cms/pdf/tcg/checklists/deoxys_checklist.pdf
        # EX Crystal Guardians: 14–88 have a standard non-holo and a parallel foil.
        # https://assets.pokemon.com/assets/cms/pdf/tcg/checklists/crystalguardians_checklist.pdf
        return {
            "foil": True,
            "mode": "automatic",
            "reason": "Illustration holo avec tampon d’extension : Foil / reverse tamponnée.",
        }
    if stamp:
        return result
    snapshot = snapshot or {}
    if not card.get("catalog_id") or snapshot.get("catalog_id") != card["catalog_id"]:
        return result
    variants = snapshot.get("variants") or {}
    if not isinstance(variants, dict):
        return result
    if has_parallel_holo(snapshot):
        # POP 9 Manaphy, for example, has a matte and a separate holo print.
        # Both are explicit price variants; the shiny print is not a reverse.
        return {
            "foil": True,
            "mode": "automatic",
            "reason": "Impression holo distincte de la version mate : Foil (holo parallèle, pas reverse).",
        }
    if has_original_holo_and_reverse(snapshot):
        # Baggaïd / Scrafty bw4-74: the checklist confirms an original holo
        # and a parallel reverse, despite TCGdex's incorrect matte-only flags.
        # https://assets.pokemon.com/assets/cms2/pdf/trading-card-game/checklist/bw4_web_cardlist_en.pdf
        return {
            "foil": False,
            "mode": "automatic",
            "reason": "Impressions holo d’origine et reverse distinctes : illustration holo = Standard.",
        }
    if variants.get("holo") is True and variants.get("normal") is False:
        return {
            "foil": False,
            "mode": "automatic",
            "reason": "Cette édition est holo d’origine : Standard.",
        }
    if (
        variants.get("normal") is True
        and variants.get("holo") is False
        and variants.get("reverse") is True
    ):
        return {
            "foil": True,
            "mode": "automatic",
            "reason": "Cette édition est mate d’origine ; son impression brillante est Foil / reverse.",
        }
    return result


def pricing_issue(card, snapshot=None):
    decision = category(card, snapshot)
    if decision["mode"] == "automatic" and bool(card.get("foil")) != decision["foil"]:
        return (
            "Catégorie enregistrée incohérente. "
            + decision["reason"]
            + " Enregistrez la fiche ou relevez le prix pour appliquer la catégorie calculée."
        )
    if decision["mode"] == "review" and not (
        card.get("variant_confirmed")
        and (card.get("variant_observation") or "").strip()
    ):
        return decision["reason"]
    return None


PRICE_IDENTITY = (
    "name",
    "set_name",
    "number",
    "language",
    "catalog_id",
    "foil",
    "stamp",
)


def compatible_quote(before, after, snapshot=None):
    """A physical clarification must still refer to the same priced product."""
    if not after.get("catalog_id") or any(
        before.get(k) != after.get(k) for k in PRICE_IDENTITY
    ):
        return False
    if any(c.get("identification_status") != "confirmed" for c in (before, after)):
        return False
    decision = category(after, snapshot)
    if decision["mode"] != "automatic" or pricing_issue(after, snapshot):
        return False
    # An old unspecified finish used the stored marketplace category. A known
    # ambiguous or inconsistent finish cannot establish quote compatibility.
    return not before.get("finish") or (
        category(before, snapshot)["mode"] == "automatic"
        and not pricing_issue(before, snapshot)
    )
