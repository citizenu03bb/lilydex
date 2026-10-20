#!/usr/bin/env python3
"""Contrôle de la documentation : liens, dates et motifs privés.

Erreurs (le contrôle échoue) :
- un lien relatif vers une cible absente du dépôt, ou vers outputs/ ou data/,
  que git ignore : ces liens sont morts sur GitHub ;
- dans une page vivante (liste PAGES_VIVANTES), une date hors d'une ligne
  « Conditions de mesure » ou d'un bloc de code ;
- un motif de la liste privée (nom, e-mail, adresse IP…), si elle existe.

Avertissements (affichés, sans échec) : dans une page vivante, les mots qui
décrivent un état par rapport au passé (« désormais », « pas encore »…).

La liste privée est un fichier hors du dépôt, une expression régulière par
ligne : $POKEPRICE_PRIVATE_PATTERNS, ou ~/.config/pokeprice/motifs-prives.txt.

Usage : python scripts/check_docs.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Pages qui décrivent le fonctionnement actuel, sans récit daté. Une page
# rejoint cette liste quand elle a été réécrite (mode cliquet).
PAGES_VIVANTES = {
    "AGENTS.md",
    "CONTRIBUTING.md",
    "docs/APP.md",
    "docs/CONDITION-ASSESSMENT.md",
    "docs/DAILY-BACKUPS.md",
    "docs/DEPLOYMENT.md",
    "README.en.md",
    "README.md",
    "docs/COMMANDES.md",
    "docs/GLOSSAIRE.md",
    "docs/IA-VISION.md",
    "docs/PRINT_REFERENCE_GUIDE.md",
    "docs/README.md",
    "docs/ROADMAP.md",
    "docs/VALUATION.md",
    "docs/VITRINE.md",
    "skills/pokeprice-collection/SKILL.md",
}

MOIS = "janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre"
DATE = re.compile(
    rf"\b20\d\d-\d\d-\d\d\b"
    rf"|\b\d{{1,2}}(?:er)? (?:{MOIS})\b"
    rf"|\b(?:{MOIS}) 20\d\d\b"
    rf"|\b20\d{{6}}\b",
    re.IGNORECASE,
)
RELATIF = re.compile(
    r"\b(?:désormais|pas encore|reste à|depuis le \d{1,2}|à ce jour|dorénavant)\b", re.IGNORECASE
)
LIEN = re.compile(r"\]\(([^)\s]+)\)")
ZONE_PERMISE = re.compile(r"conditions de mesure", re.IGNORECASE)


def documents() -> list[Path]:
    paths = [ROOT / name for name in ("README.md", "README.en.md", "CONTRIBUTING.md",
                                      "AGENTS.md", "SECURITY.md")]
    paths += sorted((ROOT / "docs").rglob("*.md"))
    paths += sorted((ROOT / "skills").glob("*/SKILL.md"))
    paths += sorted((ROOT / ".github").rglob("*.md")) if (ROOT / ".github").exists() else []
    return [p for p in paths if p.exists()]


def lignes_hors_code(text: str):
    """Numéro et contenu des lignes hors des blocs de code délimités."""
    in_code = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            yield number, line


def sans_code_ni_url(line: str) -> str:
    line = re.sub(r"`[^`]*`", "", line)
    return re.sub(r"\]\([^)]*\)|https?://\S+", "", line)


def ancre(titre: str) -> str:
    """L'ancre que GitHub donne à un titre."""
    titre = re.sub(r"[`*_]", "", titre.strip().lower())
    titre = re.sub(r"[^\w\- ]", "", titre)
    return titre.replace(" ", "-")


def ancres(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return {
        ancre(line.lstrip("#"))
        for _, line in lignes_hors_code(text)
        if re.match(r"#{1,6} ", line)
    }


def liens_morts(path: Path, text: str) -> list[str]:
    errors = []
    for number, line in lignes_hors_code(text):
        for full_target in LIEN.findall(line):
            if re.match(r"[a-z]+:", full_target):
                continue
            target, _, fragment = full_target.partition("#")
            resolved = (path.parent / target).resolve() if target else path.resolve()
            try:
                relative = resolved.relative_to(ROOT).as_posix()
            except ValueError:
                errors.append(f"{number}: lien hors du dépôt : {target}")
                continue
            if relative.split("/", 1)[0] in {"outputs", "data"}:
                errors.append(f"{number}: lien vers {relative}, ignoré par git (mort sur GitHub)")
            elif not resolved.exists():
                errors.append(f"{number}: lien mort : {target}")
            elif fragment and resolved.suffix == ".md" and fragment not in ancres(resolved):
                errors.append(f"{number}: ancre absente : {full_target}")
    return errors


def dates_interdites(text: str) -> list[str]:
    errors = []
    for number, line in lignes_hors_code(text):
        if ZONE_PERMISE.search(line):
            continue
        for match in DATE.finditer(sans_code_ni_url(line)):
            errors.append(f"{number}: date dans une page vivante : « {match.group(0)} »")
    return errors


def mots_relatifs(text: str) -> list[str]:
    return [
        f"{number}: « {match.group(0)} » décrit un état par rapport au passé"
        for number, line in lignes_hors_code(text)
        for match in RELATIF.finditer(sans_code_ni_url(line))
    ]


def motifs_prives() -> list[re.Pattern]:
    source = os.environ.get("POKEPRICE_PRIVATE_PATTERNS") or str(
        Path.home() / ".config/pokeprice/motifs-prives.txt"
    )
    path = Path(source)
    if not path.is_file():
        return []
    return [
        re.compile(line.strip(), re.IGNORECASE)
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def controler() -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    private = motifs_prives()
    for path in documents():
        name = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        found = liens_morts(path, text)
        if name in PAGES_VIVANTES:
            found += dates_interdites(text)
            warnings += [f"{name}:{w}" for w in mots_relatifs(text)]
        for pattern in private:
            for number, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    found.append(f"{number}: motif privé")
        errors += [f"{name}:{e}" for e in found]
    return errors, warnings


def main() -> int:
    errors, warnings = controler()
    for warning in warnings:
        print(f"avertissement {warning}")
    for error in errors:
        print(f"erreur {error}")
    print(f"{len(errors)} erreur(s), {len(warnings)} avertissement(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
