#!/usr/bin/env python3
"""Évaluer la porte énergie carte par carte, chaque carte hors de sa propre banque.

Protocole : la banque est la collection (photos des exemplaires actifs, noms
enregistrés). Pour chaque exemplaire, on retire de la banque toutes les lignes
qui partagent sa photo, puis on lui applique la règle de la porte
(`EnergyGate.check`) avec son propre vecteur. On compte :

- les énergies de base admises (vrais positifs) sur toutes les énergies de base ;
- les autres cartes admises à tort (fausses admissions), avec leur nom ;
- le type proposé, comparé au type enregistré quand il est connu.

Les étiquettes viennent des noms enregistrés : une carte mal nommée fausse la
mesure dans les deux sens. La base est ouverte en lecture seule ; les vecteurs
manquants sont calculés en mémoire, sans écrire de cache.

Usage (option vision) :
    uv run --extra vision python scripts/eval_energy_gate.py data/inventory [--margins 0.05,0.08,0.10]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pokeprice.energy_gate import MARGIN, EnergyGate, basic_energy  # noqa: E402


def load_bank(data: Path):
    import torch
    from PIL import Image

    from pokeprice.edition_check import Dinov2EditionReader

    uri = f"file:{data / 'collection.sqlite3'}?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        rows = db.execute(
            "SELECT name, photo FROM copies WHERE deleted_at='' AND photo IS NOT NULL"
        ).fetchall()
    photos = data / "photos"
    rows = [(name, photo) for name, photo in rows if (photos / photo).is_file()]
    cache_file = data / "references" / "energy-bank.pt"
    cache = torch.load(cache_file, weights_only=True) if cache_file.exists() else {}
    missing = sorted({photo for _, photo in rows if photo not in cache})
    if missing:
        reader = Dinov2EditionReader(data / "references")
        for start in range(0, len(missing), 64):
            batch = missing[start : start + 64]
            images = []
            for name in batch:
                with Image.open(photos / name) as image:
                    images.append(image.convert("RGB"))
            for name, vector in zip(batch, reader.embed(images), strict=True):
                cache[name] = vector
    vectors = torch.stack([cache[photo] for _, photo in rows])
    return rows, vectors


def evaluate(rows, vectors, margin):
    labels = [basic_energy(name) for name, _ in rows]
    basic = [b for b, _ in labels]
    types = [t for _, t in labels]
    photos = [photo for _, photo in rows]
    admitted, missed, false_admissions = 0, [], Counter()
    type_right = type_wrong = type_none = 0
    for i, (name, photo) in enumerate(rows):
        keep = [j for j in range(len(rows)) if photos[j] != photo]
        gate = EnergyGate(
            lambda _images, v=vectors[i]: v.unsqueeze(0),
            vectors[keep],
            [basic[j] for j in keep],
            [types[j] for j in keep],
            margin=margin,
        )
        evidence = gate.check(_Blank())
        if basic[i]:
            if evidence:
                admitted += 1
                proposal = evidence["type_proposal"]
                if not types[i] or not proposal:
                    type_none += 1
                elif proposal == types[i]:
                    type_right += 1
                else:
                    type_wrong += 1
            else:
                missed.append(name)
        elif evidence:
            false_admissions[name] += 1
    return {
        "margin": margin,
        "copies": len(rows),
        "basic_energies": sum(basic),
        "basic_admitted": admitted,
        "basic_missed": Counter(missed).most_common(),
        "false_admissions": sum(false_admissions.values()),
        "false_admission_names": false_admissions.most_common(),
        "type_right": type_right,
        "type_wrong": type_wrong,
        "type_not_compared": type_none,
    }


class _Blank:
    """Stands for the pocket image: the vector is injected through ``embed``."""

    def convert(self, _mode):
        return self


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data", type=Path, help="Dossier de données (base et photos)")
    parser.add_argument("--margins", default=f"0.05,0.08,{MARGIN}")
    parser.add_argument("--json", type=Path, help="Écrire le résultat dans ce fichier")
    args = parser.parse_args()
    rows, vectors = load_bank(args.data)
    results = [evaluate(rows, vectors, float(m)) for m in args.margins.split(",")]
    for r in results:
        print(
            f"marge {r['margin']:.2f} : {r['basic_admitted']}/{r['basic_energies']} énergies de base "
            f"admises, {r['false_admissions']} autre(s) carte(s) admise(s) "
            f"{r['false_admission_names'] or ''} ; type juste {r['type_right']}, "
            f"faux {r['type_wrong']}, non comparé {r['type_not_compared']}"
        )
    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
