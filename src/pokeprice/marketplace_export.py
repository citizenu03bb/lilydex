"""Ready-to-post listings for Vinted, Leboncoin and Cardmarket, from a read-only base.

Nothing is published: the export writes a folder per listing (``annonce.txt`` and
its photos) for Vinted and Leboncoin, or the seller stock CSV for Cardmarket. A
person copies, pastes or imports it. See docs/VENTE-PLATEFORMES.md.

A price is never below the anti-bargain floor: the reference price (the
Cardmarket trend, or the dated manual quote that stands in for it) less a
configurable margin. A copy whose identity, condition or variant is not confirmed,
or that has no price, is left out and listed apart with the reason.
"""

import contextlib
import csv
import json
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .inventory import SCHEMA_VERSION, Store
from .listings import Listings, public_condition
from .pricing import CARDMARKET_LANGUAGES, FLOOR_CENTS, display_price, euros

PLATFORMS = ("vinted", "leboncoin", "cardmarket")

# Default share of the reference price a listing may go below it. 0.10: never
# under 90 % of the reference. The command takes --marge to change it.
DEFAULT_MARGIN = 0.10

# Title limits. Neither platform documents them publicly; these are the
# shortest values sellers report, so a title is never cut. Check the posting
# form and correct here if it accepts more.
TITLE_MAX = {"vinted": 50, "leboncoin": 50}
# Most photos one listing takes; the rest are left in the folder, not attached.
PHOTOS_MAX = {"vinted": 20, "leboncoin": 10}
# Price steps in cents: Leboncoin takes whole euros, the others cents. Prices
# are always rounded up, so rounding never takes a price under its floor.
PRICE_STEP = {"vinted": 10, "leboncoin": 100, "cardmarket": 1}
# Suggested category, as named in each posting form. To check if a site renames it.
CATEGORY = {
    "vinted": "Loisirs et collections › Cartes à collectionner",
    "leboncoin": "Loisirs › Collection",
}

# Cardmarket seller stock import (Stock › Importer). Columns follow the article
# fields of Cardmarket's stock API: correct a name, the order or the separator
# here if Cardmarket's import page asks for something else.
CARDMARKET_COLUMNS = (
    "idProduct",
    "count",
    "price",
    "idLanguage",
    "condition",
    "isReverseHolo",
    "isFirstEd",
    "isSigned",
    "comments",
)
CARDMARKET_DELIMITER = ";"
CARDMARKET_FILE = "cardmarket-stock.csv"
# Cardmarket grades; NM/EX has none and is offered as EX, the lower one.
CARDMARKET_GRADES = {
    "MT": "MT", "NM": "NM", "NM/EX": "EX", "EX": "EX",
    "GD": "GD", "LP": "LP", "PL": "PL", "PO": "PO",
}

GRADE_WORDS = {
    "MT": "parfait",
    "NM": "presque neuf",
    "NM/EX": "entre presque neuf et excellent",
    "EX": "excellent",
    "GD": "bon",
    "LP": "légèrement joué",
    "PL": "joué",
    "PO": "abîmé",
}
MESSAGES = Path(__file__).parent / "web" / "messages" / "fr.json"


class ReadOnlyStore(Store):
    """A collection opened by SQLite in read-only mode: no migration, no write.

    Store() creates folders and migrates; this one only checks the schema and
    refuses any write, so the export can run on the production base safely.
    """

    def __init__(self, directory):
        from .reference_service import ReferenceService

        self.root = Path(directory).resolve()
        self.photos = self.root / "photos"
        self.database = self.root / "collection.sqlite3"
        if not self.database.is_file():
            raise FileNotFoundError(f"Aucune collection dans {self.root}.")
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise ValueError(
                "Version de base différente de celle du code : mettez à jour l’un ou "
                "l’autre avant d’exporter."
            )
        self.reference = ReferenceService(self)

    @contextlib.contextmanager
    def connect(self, *, write=False):
        if write:
            raise PermissionError("Export en lecture seule : aucune écriture permise.")
        db = sqlite3.connect(
            self.database.as_uri() + "?mode=ro", uri=True, timeout=15
        )
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()


@dataclass
class Annonce:
    kind: str  # "carte" or "lot"
    cards: list
    price_cents: int
    floor_cents: int
    listing_id: str = ""
    lot_title: str = ""
    notes: list = field(default_factory=list)


@dataclass
class Export:
    annonces: list
    excluded: list  # (label, reason)


def labels():
    messages = json.loads(MESSAGES.read_text(encoding="utf-8"))
    return {k: v for k, v in messages.items() if k.startswith(("language.", "finish."))}


def card_label(card):
    return " · ".join(
        [card["name"], card["set_name"] or "extension ?", card["number"] or "numéro ?", card["language"]]
    )


def round_up(amount_cents, step):
    return -(-amount_cents // step) * step


def floor_price(reference_cents, margin):
    """Lowest acceptable price: the reference less the margin, never under 0.50 €."""
    if not 0 <= margin < 1:
        raise ValueError("La marge est une part du prix, entre 0 et 1 (0.10 pour 10 %).")
    return max(FLOOR_CENTS, -(-round(reference_cents * (1 - margin) * 1000) // 1000))


def platform_price(price_cents, floor_cents, platform):
    return round_up(max(price_cents, floor_cents), PRICE_STEP[platform])


def reference(card):
    valuation = card.get("valuation") or {}
    for key in ("trend_cents", "prudent_cents"):
        if isinstance(valuation.get(key), int):
            return valuation[key]
    return None


def blockers(card):
    """Why a copy cannot be offered: identity, condition and variant must be confirmed."""
    reasons = []
    if card["identification_status"] != "confirmed":
        reasons.append("identité à confirmer")
    if not public_condition(card):
        reasons.append("état à confirmer")
    if not card["variant_confirmed"]:
        reasons.append("variante à confirmer")
    if reference(card) is None:
        reasons.append("aucune cote de référence pour vérifier le plancher")
    return reasons


def collect(store, margin=DEFAULT_MARGIN):
    """Every available copy and published lot, priced, or excluded with a reason."""
    floor_price(0, margin)  # Validates the margin before reading anything.
    cards = {c["id"]: c for c in store.listing(limit=10**9)["items"]}
    listings = Listings(store)
    with store.connect() as db:
        online = [
            listings.get(db, row[0])
            for row in db.execute(
                "SELECT id FROM listings WHERE state='online' ORDER BY published_at, id"
            )
        ]
    annonces, excluded, in_lot, single = [], [], set(), {}
    for listing in online:
        ids = [i["id"] for i in listing["items"]]
        if len(ids) == 1:
            single[ids[0]] = listing
            continue
        in_lot.update(ids)
        title = listing["title"] or f"Lot de {len(ids)} cartes"
        if not listing["available"]:
            excluded.append((title, "lot avec un exemplaire réservé, vendu ou supprimé"))
            continue
        members = [cards[i] for i in ids]
        problems = [f"{c['name']} : {', '.join(blockers(c))}" for c in members if blockers(c)]
        if problems:
            excluded.append((title, "; ".join(problems)))
            continue
        floor = floor_price(sum(reference(c) for c in members), margin)
        annonces.append(
            Annonce("lot", members, listing["price_cents"], floor, listing["id"], title)
        )
    for card in sorted(cards.values(), key=lambda c: (c["name"], c["set_name"], c["number"], c["id"])):
        if card["deleted_at"] or card["stock_state"] != "available" or card["id"] in in_lot:
            continue
        reasons = blockers(card)
        listing = single.get(card["id"])
        if listing:
            price = listing["price_cents"]
        else:
            proposal = display_price(card, card["valuation"])
            price = proposal["price_cents"] if proposal["publishable"] else None
            if price is None and not reasons:
                reasons += [r.rstrip(".").lower() for r in proposal["reasons"]] or ["aucun prix"]
        if reasons:
            excluded.append((card_label(card), "; ".join(reasons)))
            continue
        annonces.append(
            Annonce(
                "carte", [card], price, floor_price(reference(card), margin),
                listing["id"] if listing else "",
            )
        )
    return Export(annonces, excluded)


def fit(parts, limit):
    """Join the parts that fit, in order; the first one is shortened if needed."""
    first, *rest = [p for p in parts if p]
    title = first if len(first) <= limit else first[: limit - 1].rstrip() + "…"
    for part in rest:
        if len(title) + 3 + len(part) <= limit:
            title += " - " + part
    return title


def title(annonce, platform):
    limit = TITLE_MAX[platform]
    if annonce.kind == "lot":
        return fit([annonce.lot_title, "cartes Pokémon"], limit)
    card = annonce.cards[0]
    return fit(
        [
            f"Carte Pokémon {card['name']}",
            card["number"],
            card["set_name"],
            card["language"].upper(),
            public_condition(card),
        ],
        limit,
    )


def card_lines(card, words):
    finish = words.get(f"finish.{card['finish']}") or ("Brillante" if card["foil"] else "Normale")
    grade = public_condition(card)
    lines = [
        f"Nom : {card['name']}",
        f"Extension : {card['set_name'] or 'non précisée'}",
        f"Numéro : {card['number'] or 'non précisé'}",
        f"Langue : {words.get('language.' + card['language'], card['language'])}",
        f"État : {grade} ({GRADE_WORDS.get(grade, 'voir photos')})",
        f"Variante : {finish}",
    ]
    if card["stamp_state"] == "present" and card["stamp"]:
        lines.append(f"Tampon : {card['stamp']}")
    return lines


def description(annonce, site, words):
    link = f"{site.rstrip('/')}/carte/{annonce.listing_id}" if site and annonce.listing_id else ""
    if annonce.kind == "lot":
        text = [f"{annonce.lot_title}", "", f"Lot de {len(annonce.cards)} cartes Pokémon :", ""]
        for n, card in enumerate(annonce.cards, 1):
            text.append(f"{n}. " + " ; ".join(card_lines(card, words)))
    else:
        text = ["Carte Pokémon à l’unité.", "", *card_lines(annonce.cards[0], words)]
    text += [
        "",
        "État vérifié à la main. Les photos montrent l’exemplaire vendu.",
        "Frais de port calculés par la plateforme.",
    ]
    if link:
        text += ["", f"Fiche et photos en grand : {link}"]
    return "\n".join(text)


def photos(annonce, store):
    """Fronts first, then backs, so a capped listing still shows every card."""
    found = []
    for face, field_name in (("recto", "photo"), ("verso", "back_photo")):
        for n, card in enumerate(annonce.cards, 1):
            name = card[field_name]
            if name and (store.photos / name).is_file():
                prefix = f"carte{n:02d}-" if annonce.kind == "lot" else ""
                found.append((store.photos / name, f"{prefix}{face}.jpg"))
    return found


def slug(text):
    from .inventory import normalized

    return re.sub(r"[^a-z0-9]+", "-", normalized(text)).strip("-")[:50] or "annonce"


def prepare(target):
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"{target} n’est pas vide : choisissez un dossier neuf.")
    target.mkdir(parents=True, exist_ok=True)
    return target


def write_excluded(target, export):
    lines = [f"{label} — {reason}" for label, reason in export.excluded]
    (target / "exclues.txt").write_text(
        "Cartes et lots non exportés, et pourquoi :\n\n" + "\n".join(lines) + "\n"
        if lines
        else "Aucune carte exclue.\n",
        encoding="utf-8",
    )


def write_folders(store, export, platform, target, site=""):
    """One folder per listing: annonce.txt to copy and paste, then its photos."""
    target = prepare(target)
    words = labels()
    written = []
    for n, annonce in enumerate(export.annonces, 1):
        price = platform_price(annonce.price_cents, annonce.floor_cents, platform)
        head = title(annonce, platform)
        folder = target / f"{n:03d}-{slug(head)}"
        folder.mkdir()
        files = photos(annonce, store)
        attached, extra = files[: PHOTOS_MAX[platform]], files[PHOTOS_MAX[platform] :]
        checks = list(annonce.notes)
        if not files:
            checks.append("Aucune photo : photographiez la carte avant de publier.")
        if extra:
            checks.append(
                f"{len(extra)} photo(s) au-delà de la limite de {PHOTOS_MAX[platform]} : "
                "dans le dossier « en-plus »."
            )
            (folder / "en-plus").mkdir()
        for source, name in attached:
            shutil.copyfile(source, folder / name)
        for source, name in extra:
            shutil.copyfile(source, folder / "en-plus" / name)
        sections = [
            ("TITRE", head),
            ("PRIX", euros(price / 100)),
            ("CATÉGORIE CONSEILLÉE", CATEGORY[platform]),
            ("DESCRIPTION", description(annonce, site, words)),
            ("PHOTOS", "\n".join(name for _, name in attached) or "aucune"),
        ]
        if checks:
            sections.append(("À VÉRIFIER", "\n".join(checks)))
        (folder / "annonce.txt").write_text(
            "\n\n".join(f"{name}\n{body}" for name, body in sections) + "\n",
            encoding="utf-8",
        )
        written.append({"folder": folder.name, "title": head, "price_cents": price})
    write_excluded(target, export)
    return written


def cardmarket_products(store):
    """Known Cardmarket products per catalogue id; a product judged wrong is dropped."""
    with store.connect() as db:
        verdicts = store.market_verdicts(db)
        rows = db.execute(
            "SELECT key,value FROM catalog_lookups "
            "WHERE found=1 AND key LIKE 'cardmarket-product:%'"
        ).fetchall()
    products = {}
    for key, value in rows:
        catalog_id = key.split(":", 1)[1]
        id_product = (json.loads(value) if value else {}).get("id_product")
        verdict = verdicts.get(catalog_id, {})
        if verdict.get("verdict") == "wrong" and verdict.get("id_product") == id_product:
            continue
        if isinstance(id_product, int) and not isinstance(id_product, bool):
            products[catalog_id] = id_product
    return products


def cardmarket_rows(store, export):
    """Rows of the stock CSV, identical articles grouped; others excluded with a reason."""
    products = cardmarket_products(store)
    grouped, excluded = {}, []
    for annonce in export.annonces:
        if annonce.kind == "lot":
            excluded.append((annonce.lot_title, "Cardmarket vend les cartes à l’unité, pas en lot"))
            continue
        card = annonce.cards[0]
        id_product = products.get(card["catalog_id"] or "")
        language = CARDMARKET_LANGUAGES.get(card["language"])
        if id_product is None:
            excluded.append((card_label(card), "produit Cardmarket inconnu"))
            continue
        if language is None:
            excluded.append((card_label(card), "langue absente de Cardmarket"))
            continue
        row = {
            "idProduct": id_product,
            "price": platform_price(annonce.price_cents, annonce.floor_cents, "cardmarket"),
            "idLanguage": language,
            "condition": CARDMARKET_GRADES[public_condition(card)],
            "isReverseHolo": int(card["finish"] == "reverse" or (not card["finish"] and bool(card["foil"]))),
            "isFirstEd": 0,
            "isSigned": 0,
            "comments": "",
        }
        key = tuple(row.items())
        grouped.setdefault(key, {**row, "count": 0})["count"] += 1
    rows = []
    for row in grouped.values():
        row["price"] = f"{row['price'] // 100}.{row['price'] % 100:02d}"
        rows.append({column: row[column] for column in CARDMARKET_COLUMNS})
    return rows, excluded


def write_cardmarket(store, export, target):
    target = prepare(target)
    rows, excluded = cardmarket_rows(store, export)
    with (target / CARDMARKET_FILE).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, CARDMARKET_COLUMNS, delimiter=CARDMARKET_DELIMITER)
        writer.writeheader()
        writer.writerows(rows)
    export.excluded.extend(excluded)
    write_excluded(target, export)
    return rows


def run(data, platform, target, *, margin=DEFAULT_MARGIN, site=""):
    if platform not in PLATFORMS:
        raise ValueError("Plateforme inconnue : " + ", ".join(PLATFORMS) + ".")
    store = ReadOnlyStore(data)
    export = collect(store, margin)
    if platform == "cardmarket":
        return write_cardmarket(store, export, target), export
    return write_folders(store, export, platform, target, site), export
