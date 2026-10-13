"""Doubtful Cardmarket products: TCGdex sometimes maps two cards to one product.

Example (13 October 2026): dp4-3 Darkrai Lv.38 and dp4-4 Darkrai Lv.40 both
carry idProduct 277905, the Lv.38. Neighbouring numbers of the same set are
compared at each price refresh; a person then confirms or rejects the product.
"""

import json
import re
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from .inventory import Conflict, now

API = "https://api.tcgdex.net/v2/en/"
CACHE_DAYS = 30
VERDICTS = ("wrong", "verified", "")


def fetch_tcgdex(path):
    request = Request(API + path, headers={"User-Agent": "pokeprice/0.1.0"})
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read())


def neighbours(catalog_id):
    """Previous and next local numbers, keeping prefixes and zero padding."""
    set_id, _, local = (catalog_id or "").rpartition("-")
    match = re.fullmatch(r"(.*?)(\d+)", local)
    if not set_id or not match:
        return []
    prefix, digits = match.groups()
    width = len(digits) if digits.startswith("0") else 0
    return [
        f"{set_id}-{prefix}{str(n).zfill(width)}"
        for n in (int(digits) - 1, int(digits) + 1)
        if n > 0
    ]


def set_code_from(data):
    """Code printed on Cardmarket products (GE, HS…); promos use PR-XX online."""
    code = ((data or {}).get("abbreviation") or {}).get("official")
    online = (data or {}).get("tcgOnline") or ""
    if not code and online.startswith("PR-"):
        code = online[3:]
    return (
        code
        if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9]{1,8}", code)
        else None
    )


def cached(db, key):
    row = db.execute(
        "SELECT value, checked_at FROM catalog_lookups WHERE key=?", (key,)
    ).fetchone()
    if not row:
        return None
    try:
        checked = datetime.fromisoformat(row["checked_at"])
    except ValueError:
        return None
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - checked).days >= CACHE_DAYS:
        return None
    return json.loads(row["value"]) if row["value"] else {}


def cached_set_code(db, catalog_id):
    set_id = (catalog_id or "").rpartition("-")[0]
    return (cached(db, f"set-code:{set_id}") or {}).get("code") if set_id else None


class MarketProducts:
    def __init__(self, store, fetch=fetch_tcgdex):
        self.store, self.fetch = store, fetch

    def _lookup(self, key, path, extract):
        """Cached network lookup; a failure is not cached and returns None."""
        with self.store.connect() as db:
            value = cached(db, key)
        if value is not None or self.fetch is None:
            return value
        try:
            value = extract(self.fetch(path))
        except Exception:  # noqa: BLE001 - A missing neighbour must not block a refresh.
            return None
        with self.store.connect(write=True) as db:
            db.execute(
                "INSERT OR REPLACE INTO catalog_lookups VALUES(?,?,?,?)",
                (key, 1, json.dumps(value, ensure_ascii=False), now()),
            )
        return value

    def product(self, catalog_id):
        def extract(data):
            cardmarket = ((data or {}).get("pricing") or {}).get("cardmarket") or {}
            return {
                "id_product": cardmarket.get("idProduct"),
                "name": (data or {}).get("name") or "",
                "hp": (data or {}).get("hp"),
            }

        return self._lookup(
            f"cardmarket-product:{catalog_id}", f"cards/{catalog_id}", extract
        )

    def set_code(self, catalog_id):
        set_id = (catalog_id or "").rpartition("-")[0]
        if not set_id:
            return None
        found = self._lookup(
            f"set-code:{set_id}", f"sets/{set_id}", lambda d: {"code": set_code_from(d)}
        )
        return (found or {}).get("code")

    def shared_with(self, catalog_id, id_product):
        if not isinstance(id_product, int):
            return []
        shared = []
        for other in neighbours(catalog_id):
            found = self.product(other)
            if found and found.get("id_product") == id_product:
                shared.append(
                    {
                        "catalog_id": other,
                        "name": found.get("name") or "",
                        "hp": found.get("hp"),
                    }
                )
        return shared

    def judge(self, copy_id, version, verdict, actor, reason):
        """Record a person's verdict; a wrong product drops its TCGdex prices."""
        if verdict not in VERDICTS:
            raise ValueError("Verdict inconnu.")
        with self.store.connect() as db:
            card = self.store.get(db, copy_id)
        if card["identification_status"] != "confirmed" or not card["catalog_id"]:
            raise ValueError(
                "Identifiez et confirmez l’édition avant de juger son produit Cardmarket."
            )
        self.set_code(
            card["catalog_id"]
        )  # Warms the search link; network stays outside writes.
        with self.store.connect(write=True) as db:
            card = self.store.get(db, copy_id)
            if card["version"] != version:
                raise Conflict("La fiche a changé. Rechargez-la avant de modifier.")
            row = db.execute(
                "SELECT after_json FROM events WHERE copy_id=? AND kind='price-snapshot' ORDER BY id DESC LIMIT 1",
                (copy_id,),
            ).fetchone()
            snapshot = json.loads(row[0]) if row else {}
            id_product = snapshot.get("id_product")
            if snapshot.get("catalog_id") != card["catalog_id"] or not isinstance(
                id_product, int
            ):
                raise ValueError(
                    "Relevez d’abord le prix TCGdex : aucun produit Cardmarket à juger."
                )
            before = self.store.market_verdicts(db).get(card["catalog_id"], {})
            record = {
                "catalog_id": card["catalog_id"],
                "id_product": id_product,
                "verdict": verdict,
                "shared_with": snapshot.get("shared_product_with") or [],
                "observed_at": now(),
            }
            self.store.event(
                db, copy_id, actor, "market-product", reason, before, record
            )
            if verdict == "wrong":
                for other in db.execute(
                    "SELECT id,version FROM copies WHERE deleted_at='' AND catalog_id=? AND price_source LIKE 'TCGdex%'",
                    (card["catalog_id"],),
                ).fetchall():
                    self.store.patch(
                        other["id"],
                        {"reference_cents": None, "price_source": "", "price_date": ""},
                        other["version"],
                        actor,
                        "Produit Cardmarket signalé incorrect : prix TCGdex retiré",
                        _db=db,
                    )
            return self.store.get(db, copy_id)
