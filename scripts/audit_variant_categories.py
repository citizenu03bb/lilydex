"""Read-only audit of physical observations and recorded price categories."""

import argparse
import json
from pathlib import Path

from audit_valuation import ReadOnlyStore
from pokeprice.variant_pricing import category, pricing_issue


def audit(directory):
    store = ReadOnlyStore(directory)
    with store.connect() as db:
        context = store.valuation_context(db)
        cards = [
            dict(r)
            for r in db.execute(
                "SELECT c.*,a.name album FROM copies c JOIN albums a ON a.id=c.album_id WHERE c.deleted_at='' ORDER BY a.name,c.page,c.position,c.id"
            )
        ]
        changed = set()
        for event in db.execute(
            "SELECT copy_id,before_json,after_json FROM events WHERE kind='correction'"
        ):
            before, after = json.loads(event[1]), json.loads(event[2])
            if before.get("foil") != after.get("foil"):
                changed.add(event[0])
        problems = []
        for card in cards:
            snapshot = store.category_metadata(card, context)
            decision = category(card, snapshot)
            if issue := pricing_issue(card, snapshot):
                problems.append(
                    {
                        **{
                            k: card[k]
                            for k in (
                                "id",
                                "name",
                                "number",
                                "catalog_id",
                                "album",
                                "page",
                                "position",
                                "finish",
                                "stamp",
                                "variant_confirmed",
                                "reference_cents",
                            )
                        },
                        "recorded_category": "Foil" if card["foil"] else "Standard",
                        "expected_category": (
                            "Foil" if decision["foil"] else "Standard"
                        )
                        if decision["mode"] == "automatic"
                        else "À vérifier",
                        "automatic": decision["mode"] == "automatic",
                        "reason": issue,
                    }
                )
    return {
        "copies": len(cards),
        "observed_finishes": sum(bool(c["finish"]) for c in cards),
        "automatic_mismatches": sum(p["automatic"] for p in problems),
        "ambiguous_observations": sum(not p["automatic"] for p in problems),
        "changed_category_without_finish": sum(
            c["id"] in changed and not c["finish"] for c in cards
        ),
        "problems": problems,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data/inventory")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.data)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
        args.output.chmod(0o600)
        print(
            json.dumps(
                {k: v for k, v in report.items() if k != "problems"}, ensure_ascii=False
            )
        )
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
