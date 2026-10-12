"""Check the M1 acceptance criteria without migrating or writing the collection."""

import argparse
import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from pokeprice.inventory import Store, cents
from pokeprice.library import normalized


class ReadOnlyStore(Store):
    def __init__(self, directory):
        self.database = Path(directory).resolve() / "collection.sqlite3"

    @contextmanager
    def connect(self, **kwargs):
        db = sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        db.create_function("normalized", 1, normalized)
        try:
            yield db
        finally:
            db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data/inventory")
    parser.add_argument("--threshold", type=float, default=10)
    parser.add_argument("--known-edition", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not math.isfinite(args.threshold) or not 0.01 <= args.threshold <= 10000:
        parser.error("Le seuil doit être compris entre 0,01 et 10 000 €.")
    data = ReadOnlyStore(args.data).listing(
        limit=1000000, sort="binder", threshold_cents=cents(args.threshold)
    )
    queue = [c for c in data["items"] if c["valuation"]["needs_review"]]
    known = {}
    for catalog_id in args.known_edition:
        copies = [c for c in data["items"] if c["catalog_id"] == catalog_id]
        known[catalog_id] = {
            "present": bool(copies),
            "all_in_queue": bool(copies)
            and all(c["valuation"]["needs_review"] for c in copies),
        }
    report = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "threshold_cents": cents(args.threshold),
        "copies": data["total"],
        "review_count": len(queue),
        "review_percent": round(len(queue) / data["total"] * 100, 2)
        if data["total"]
        else None,
        "queue_at_most_15_percent": bool(data["total"])
        and len(queue) * 100 <= data["total"] * 15,
        "known_editions": known,
        "valuation_totals": data["valuation_totals"],
        "queue": [
            {
                k: c[k]
                for k in (
                    "id",
                    "catalog_id",
                    "name",
                    "number",
                    "album",
                    "page",
                    "position",
                    "valuation",
                )
            }
            for c in queue
        ],
    }
    report["passed"] = report["queue_at_most_15_percent"] and all(
        k["all_in_queue"] for k in known.values()
    )
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output)
        args.output.chmod(0o600)
        print(
            json.dumps(
                {
                    k: report[k]
                    for k in (
                        "passed",
                        "copies",
                        "review_count",
                        "review_percent",
                        "known_editions",
                    )
                },
                ensure_ascii=False,
            )
        )
    else:
        print(output, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
