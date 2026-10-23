"""Cardmarket's official price guide, for prints TCGdex leaves without a quote.

Cardmarket publishes two public files every day: the price guide (trend,
averages, holo columns) and the list of single cards (product, expansion,
name). The guide uses the same fields as TCGdex's ``cardmarket`` block, so a
missing TCGdex quote is completed from it, with its provenance. The product
comes from TCGdex when it gives one; otherwise it is matched in the same
expansion by English name and by the names of its attacks and abilities, and
only a unique match counts (decision 0016).
"""

import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.request import Request, urlopen

from .inventory import now
from .market_product import cached, fetch_tcgdex

BASE = "https://downloads.s3.cardmarket.com/productCatalog/"
FILES = {
    "price_guide_6.json": BASE + "priceGuide/price_guide_6.json",
    "products_singles_6.json": BASE + "productList/products_singles_6.json",
}
SOURCE = "Cardmarket · guide des prix"
MAX_BYTES = 64 * 1024 * 1024
MAX_AGE_SECONDS = 24 * 3600
FIELDS = ("avg", "low", "trend", "avg1", "avg7", "avg30")
# How many cards of a TCGdex set are read, at most, to find its expansion.
EXPANSION_PROBES = 60


def download(url):
    request = Request(url, headers={"User-Agent": "pokeprice/0.1.0"})
    with urlopen(request, timeout=60) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Fichier Cardmarket trop lourd.")
    return data


def has_quote(block):
    """A usable trend or 30-day average, standard or holo."""
    return any(
        isinstance((block or {}).get(k + s), (int, float))
        and not isinstance((block or {}).get(k + s), bool)
        and (block or {}).get(k + s) >= 0
        for k in ("trend", "avg30")
        for s in ("", "-holo")
    )


def key(text):
    text = (text or "").replace("♀", " f").replace("♂", " m")
    text = text.replace("?", " question ").replace("!", " exclamation ")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def product_parts(name):
    """'Unown [L] Lv.18 [LINK | Hidden Power]' -> ('unown l', {'link', 'hidden power'})."""
    groups = re.findall(r"\[([^\]]*)\]", name)
    base = re.sub(r"\s*\[.*$", "", re.sub(r"\s+Lv\.?\s*(\d+|X)\b", "", name))
    letter = groups[0] if len(groups) > 1 and len(groups[0]) <= 2 else ""
    moves = groups[-1] if groups else ""
    return key(f"{base} {letter}"), {key(m) for m in moves.split("|") if m.strip()}


class CardmarketGuide:
    def __init__(self, directory, store=None, fetch=download, get_json=fetch_tcgdex):
        self.directory, self.store = Path(directory), store
        self.fetch, self.get_json = fetch, get_json
        self.failed_at = None  # monotonic time of the last failed download
        self._loaded = None

    def _path(self, name):
        """The day's file; an older copy serves while Cardmarket is unreachable."""
        path = self.directory / name
        fresh = path.exists() and time.time() - path.stat().st_mtime < MAX_AGE_SECONDS
        retry_later = (
            self.failed_at is not None and time.monotonic() - self.failed_at < 600
        )
        if fresh or retry_later:
            return path if path.exists() else None
        try:
            data = self.fetch(FILES[name])
            json.loads(data)
        except Exception:  # noqa: BLE001 - the previous file, if any, stays usable
            self.failed_at = time.monotonic()
            return path if path.exists() else None
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
        return path

    def _data(self):
        paths = [self._path(name) for name in FILES]
        if not all(paths):
            return None
        stamp = tuple(p.stat().st_mtime for p in paths)
        if not self._loaded or self._loaded[0] != stamp:
            guide = json.loads(paths[0].read_text())
            products = json.loads(paths[1].read_text())
            self._loaded = (
                stamp,
                guide.get("createdAt", ""),
                {g["idProduct"]: g for g in guide.get("priceGuides", [])},
                {p["idProduct"]: p for p in products.get("products", [])},
            )
        return self._loaded[1:]

    def _remember(self, key_, value):
        if self.store is None:
            return
        with self.store.connect(write=True) as db:
            db.execute(
                "INSERT OR REPLACE INTO catalog_lookups VALUES(?,?,?,?)",
                (key_, 1, json.dumps(value), now()),
            )

    def expansion(self, set_id, products):
        """Cardmarket expansion of a TCGdex set, from any of its cards TCGdex maps."""
        cache_key = f"cardmarket-expansion:{set_id}"
        if self.store is not None:
            with self.store.connect() as db:
                found = cached(db, cache_key)
            if found and found.get("id_expansion"):
                return found["id_expansion"]
        listing = self.get_json(f"sets/{set_id}") or {}
        for brief in (listing.get("cards") or [])[:EXPANSION_PROBES]:
            card = self.get_json(f"cards/{brief.get('id')}") or {}
            product = ((card.get("pricing") or {}).get("cardmarket") or {}).get("idProduct")
            if product in products:
                expansion = products[product]["idExpansion"]
                self._remember(cache_key, {"id_expansion": expansion})
                return expansion
        return None

    def match(self, catalog_id, products):
        """The one product of the expansion with the same name and moves, or None."""
        set_id = catalog_id.rpartition("-")[0]
        english = self.get_json(f"cards/{catalog_id}") or {}
        expansion = self.expansion(set_id, products) if set_id else None
        if not expansion or english.get("id") != catalog_id:
            return None
        name = key(english.get("name"))
        moves = {
            key(m.get("name"))
            for m in (english.get("abilities") or []) + (english.get("attacks") or [])
            if m.get("name")
        }
        found = [
            p["idProduct"]
            for p in products.values()
            if p.get("idExpansion") == expansion
            and product_parts(p.get("name", "")) == (name, moves)
        ]
        return found[0] if len(found) == 1 else None

    def complete(self, data):
        """TCGdex card data with its missing Cardmarket quote taken from the guide."""
        pricing = data.get("pricing") or {}
        block = pricing.get("cardmarket") or {}
        if has_quote(block):
            return data
        loaded = self._data()
        if not loaded:
            return data
        created, prices, products = loaded
        product, method = block.get("idProduct"), "produit indiqué par TCGdex"
        try:
            if not isinstance(product, int):
                product = self.match(data.get("id", ""), products)
                method = "même extension, même nom, mêmes attaques"
        except Exception:  # noqa: BLE001 - no match is a valid answer
            product = None
        entry = prices.get(product) if isinstance(product, int) else None
        if not has_quote(entry):
            return data
        completed = {
            **{k + s: entry.get(k + s) for k in FIELDS for s in ("", "-holo")},
            "idProduct": product,
            "unit": "EUR",
            "updated": created,
        }
        return {
            **data,
            "pricing": {**pricing, "cardmarket": completed},
            "_acquisition": {
                **(data.get("_acquisition") or {}),
                "cardmarket_guide": {
                    "created": created,
                    "id_product": product,
                    "product_name": (products.get(product) or {}).get("name", ""),
                    "method": method,
                    "source": FILES["price_guide_6.json"],
                },
            },
        }
