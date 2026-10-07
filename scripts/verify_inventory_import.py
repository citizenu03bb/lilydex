"""Audit the initial migration against the existing standalone library export."""

import argparse
import base64
import json
from pathlib import Path
import re

from pokeprice.inventory import Store
from pokeprice.report import read_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/inventory")
    parser.add_argument("--library", default="pokeprice_library")
    parser.add_argument(
        "--output", default="outputs/development/import-validation.json"
    )
    args = parser.parse_args()
    store = Store(args.data)
    frame = read_report(args.library + ".csv")
    html = Path(args.library + ".html").read_text()
    embedded = json.loads(
        re.search(r"const LIBRARY = (.*?);\nconst search", html, re.S).group(1)
    )
    images = {
        c["id"]: base64.b64decode(c["image"].split(",", 1)[1])
        for g in embedded["groups"]
        for c in g["copies"]
    }
    with store.connect() as db:
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT c.*,s.raw_json FROM copies c JOIN sources s ON s.copy_id=c.id"
            )
        ]
    by_source = {r["source_key"]: r for r in rows}
    if len(rows) != len(frame) or set(by_source) != set(frame.Exemplaire_ID):
        raise ValueError("Les exemplaires importés ne correspondent pas aux sources.")
    for original in json.loads(frame.to_json(orient="records", force_ascii=False)):
        row = by_source[original["Exemplaire_ID"]]
        raw = json.loads(row["raw_json"])
        for key in (
            "Numero_Officiel",
            "PV_Verifie",
            "PV",
            "TCGdex_ID",
            "Langue_Carte",
            "Is_Foil",
            "Statut_Identification",
            "Note_Verification",
            "Source_Correction",
            "OCR_Brut",
            "Etat",
            "Prix_Reference_EUR",
        ):
            if raw.get(key) != original.get(key):
                raise ValueError(f"Provenance altérée : {row['source_key']}, {key}")
        if row["version"] != 1:
            raise ValueError("Cet audit initial exige des fiches encore non modifiées.")
        if (store.photos / row["photo"]).read_bytes() != images[row["source_key"]]:
            raise ValueError("Photo différente de la bibliothèque initiale.")
        if row["identification_status"] != "confirmed" and (
            row["reference_cents"] is not None or row["catalog_id"] is not None
        ):
            raise ValueError("Une proposition est devenue une référence confirmée.")
    result = {
        "source_copies": len(frame),
        "imported_copies": len(rows),
        "stable_ids": len({r["id"] for r in rows}),
        "photos_byte_identical": len(rows),
        "provenance_checked": len(rows),
        "inventory": store.summary(),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
