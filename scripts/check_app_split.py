#!/usr/bin/env python3
"""Preuve du découpage de `app.js` : les parties sont des déplacements à l'identique.

Les parties sont lues dans l'ordre des balises `<script>` de `index.html`
(`app.js`, puis `app-*.js`). Chaque partie autre que `app.js` commence par une
ligne `"use strict";` ajoutée ; le reste de chaque partie doit être une suite
contiguë de lignes de l'`app.js` d'origine, et ces suites, réunies, doivent
couvrir l'original exactement une fois. Le contrôle affiche, pour chaque
partie, les lignes d'origine qu'elle reprend.

Usage : python scripts/check_app_split.py [--base RÉVISION | --original FICHIER]
(par défaut, l'`app.js` de la révision cb702e3, d'avant le découpage).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "src/pokeprice/web"
SCRIPT_TAG = re.compile(r'<script src="/assets/([\w.-]+\.js)"')
APP_PART = re.compile(r"app(-[\w-]+)?\.js")
HEADER = '"use strict";'
BASE = "cb702e3"


def original_lines(args: argparse.Namespace) -> list[str]:
    if args.original:
        return Path(args.original).read_text().splitlines()
    source = subprocess.run(
        ["git", "show", f"{args.base}:src/pokeprice/web/app.js"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return source.splitlines()


def parts() -> list[str]:
    names = SCRIPT_TAG.findall((WEB / "index.html").read_text())
    return [name for name in names if APP_PART.fullmatch(name)]


def locate(body: list[str], original: list[str]) -> list[int]:
    """Every index where `body` sits in `original` as one contiguous run."""
    if not body:
        return []
    return [
        start for start, line in enumerate(original)
        if line == body[0] and original[start:start + len(body)] == body
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--base", default=BASE, help="révision git de l'app.js d'origine")
    group.add_argument("--original", help="fichier app.js d'origine")
    args = parser.parse_args()

    original = original_lines(args)
    errors: list[str] = []
    runs: list[tuple[int, int, str]] = []
    joined: list[str] = []
    for name in parts():
        lines = (WEB / name).read_text().splitlines()
        if name != "app.js":
            if not lines or lines[0] != HEADER:
                errors.append(f"{name} : la première ligne n'est pas {HEADER}")
                continue
            lines = lines[1:]
        joined += lines
        starts = locate(lines, original)
        if len(starts) != 1:
            errors.append(f"{name} : {len(starts)} emplacements contigus dans l'original (1 attendu)")
            continue
        runs.append((starts[0], starts[0] + len(lines), name))

    covered = 0
    for start, end, name in sorted(runs):
        if start != covered:
            errors.append(f"{name} : commence à la ligne {start + 1}, la ligne {covered + 1} était attendue")
        covered = max(covered, end)
    if covered != len(original):
        errors.append(f"l'original a {len(original)} lignes, les parties en couvrent {covered}")
    if Counter(joined) != Counter(original):
        errors.append("les lignes des parties, en multiensemble, diffèrent de l'original")

    print(f"{'partie':<20} {'lignes d’origine':>17} {'nombre':>7}")
    for start, end, name in runs:
        print(f"{name:<20} {f'{start + 1}–{end}':>17} {end - start:>7}")
    print(f"{'total':<20} {'':>17} {len(joined):>7} / {len(original)} lignes d'origine")
    for error in errors:
        print(f"ERREUR : {error}", file=sys.stderr)
    if errors:
        return 1
    print("OK : chaque partie est une suite contiguë de l'original, et elles le couvrent exactement une fois.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
