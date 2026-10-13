"""Cache edition finish metadata independently of prices and human observations."""

import json
import time

from .inventory import now


def cache_key(card):
    return f"variant:{card.get('language', '')}:{card.get('catalog_id', '')}"


class VariantCatalogue:
    def __init__(self, store, fetch):
        self.store = store
        self.fetch = fetch
        self.failures = {}

    def ensure(self, card):
        """A form edit may fetch missing metadata; collection reads stay local."""
        if (
            card.get("finish") not in ("holo", "holo_border")
            or card.get("stamp")
            or card.get("identification_status") != "confirmed"
            or not card.get("catalog_id")
        ):
            return
        with self.store.connect() as db:
            if self.store.category_snapshot(db, card) is not None:
                return
        key = cache_key(card)
        if time.monotonic() - self.failures.get(key, -60) < 60:
            return
        try:
            data = self.fetch(card["catalog_id"], card["language"])
            if data.get("id") != card["catalog_id"] or not isinstance(
                data.get("variants"), dict
            ):
                raise ValueError("Métadonnées d’édition incohérentes.")
            # Retain print identities, never USD amounts as euro price evidence.
            prints = (data.get("pricing") or {}).get("tcgplayer")
            snapshot = {
                "catalog_id": data["id"],
                "variants": data["variants"],
                "source": "TCGdex · finitions de l’édition",
                "acquisition": data.get("_acquisition")
                or {
                    "provider": "TCGdex",
                    "requested_language": card["language"],
                    "served_language": None,
                },
                "requested_language": card["language"],
                "served_language": (data.get("_acquisition") or {}).get(
                    "served_language"
                ),
                "raw": {
                    "tcgplayer": {
                        k: {"productId": v.get("productId")}
                        if isinstance(v, dict)
                        else v
                        for k, v in (prints.items() if isinstance(prints, dict) else ())
                        if k not in ("unit", "updated")
                    }
                },
            }
        except Exception:  # noqa: BLE001 - Offline metadata must not block physical observations.
            self.failures[key] = time.monotonic()
            return
        with self.store.connect(write=True) as db:
            db.execute(
                "INSERT OR REPLACE INTO catalog_lookups VALUES(?,?,?,?)",
                (key, 1, json.dumps(snapshot, ensure_ascii=False), now()),
            )
