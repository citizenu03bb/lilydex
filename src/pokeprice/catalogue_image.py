"""The edition's catalogue image and links, fetched on demand and cached."""

import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

from .inventory import now

# TCGdex adds images over time: an edition without one is asked again later.
MISSING_RETRY = timedelta(days=7)


def cache_key(card):
    return f"image:{card['language']}:{card['catalog_id']}"


def links(card, entry):
    """TCGdex publishes one image per edition: the standard print, never a variant."""
    language = entry.get("served_language") or card["language"]
    image = entry.get("image") or ""
    return {
        "catalog_id": card["catalog_id"],
        "image": image + "/high.webp" if image else "",
        "served_language": language,
        "tcgdex_url": f"https://api.tcgdex.net/v2/{quote(language)}/cards/"
        + quote(card["catalog_id"]),
    }


class CatalogueImages:
    def __init__(self, store, fetch):
        self.store = store
        self.fetch = fetch
        self.failures = {}

    def get(self, card):
        """None without an edition; a network failure is retried a minute later."""
        if not card.get("catalog_id"):
            return None
        key = cache_key(card)
        with self.store.connect() as db:
            row = db.execute(
                "SELECT found, value, checked_at FROM catalog_lookups WHERE key=?",
                (key,),
            ).fetchone()
        if row and (
            row["found"]
            or datetime.now(timezone.utc) - datetime.fromisoformat(row["checked_at"])
            < MISSING_RETRY
        ):
            return links(card, json.loads(row["value"]))
        if time.monotonic() - self.failures.get(key, -60) < 60:
            return links(card, {})
        try:
            data = self.fetch(card["catalog_id"], card["language"])
        except Exception:  # noqa: BLE001 - The form works without the catalogue image.
            self.failures[key] = time.monotonic()
            return links(card, {})
        image = data.get("image") if data.get("id") == card["catalog_id"] else ""
        parsed = urlsplit(image if isinstance(image, str) else "")
        if parsed.scheme != "https" or parsed.netloc != "assets.tcgdex.net":
            image = ""
        entry = {
            "image": image,
            "served_language": (data.get("_acquisition") or {}).get("served_language"),
        }
        with self.store.connect(write=True) as db:
            db.execute(
                "INSERT OR REPLACE INTO catalog_lookups VALUES(?,?,?,?)",
                (key, int(bool(image)), json.dumps(entry, ensure_ascii=False), now()),
            )
        return links(card, entry)
