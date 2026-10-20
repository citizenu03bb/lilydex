#!/usr/bin/env python3
"""Générer docs/COMMANDES.md depuis les analyseurs argparse des trois commandes.

La référence ne peut donc pas diverger du code : tests/test_docs.py vérifie
que le fichier est à jour. Après un changement d'option :

    python scripts/gen_commandes.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "docs" / "COMMANDES.md"

COMMANDES = [
    ("pokeprice", "pokeprice.cli", "Pipeline d'albums : numériser des classeurs en ligne de commande."),
    ("pokeprice-manage", "pokeprice.manage", "Application de gestion et exploitation : serveur, imports, exports, sauvegardes, comptes."),
    ("pokeprice-agent", "pokeprice.agent_client", "Client du pilote agent : appelle l'API déléguée, jamais la base."),
]

INTRO = """# Référence des commandes

> **Pour qui :** toute personne qui lance Lilydex en ligne de commande.
> **Vous y trouverez :** chaque commande, ses sous-commandes et leurs options, telles que le code les définit.
> **Statut :** généré par `scripts/gen_commandes.py` depuis le code ; ne pas modifier à la main.

Depuis un clone du dépôt, préfixez chaque commande par `uv run --extra web`
(par exemple `uv run --extra web pokeprice-manage serve`). Sur le serveur de
production, lancez-les sous l'utilisateur `pokeprice` avec `--data` explicite :
la forme complète est dans [Héberger Lilydex](DEPLOYMENT.md). Sans `--data`,
`pokeprice-manage` vise `data/inventory` dans le dossier courant.

Pour l'usage pas à pas, voyez le [guide de l'application](APP.md).
"""


class _Captured(Exception):
    def __init__(self, parser):
        self.parser = parser


def capturer(module_name: str) -> argparse.ArgumentParser:
    module = __import__(module_name, fromlist=["main"])

    def parse_args(self, *args, **kwargs):
        raise _Captured(self)

    with mock.patch.object(argparse.ArgumentParser, "parse_args", parse_args), \
            mock.patch.object(sys, "argv", [module_name]):
        try:
            module.main()
        except _Captured as captured:
            return captured.parser
    raise RuntimeError(f"{module_name}.main() n'a pas analysé d'arguments")


def nettoyer(texte: str | None) -> str:
    return " ".join((texte or "").split()).replace("%%", "%").replace("|", "\\|")


def options(parser: argparse.ArgumentParser) -> list[str]:
    lignes = []
    for action in parser._actions:
        if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
            continue
        if action.help == argparse.SUPPRESS:
            continue
        if action.option_strings:
            nom = ", ".join(f"`{o}`" for o in action.option_strings)
            if action.nargs != 0 and not isinstance(action, argparse._StoreConstAction):
                nom += f" `{action.metavar or action.dest.upper()}`"
        else:
            nom = f"`{action.metavar or action.dest}`"
        detail = nettoyer(action.help)
        if action.choices and not isinstance(action.choices, dict):
            detail += (" " if detail else "") + "Valeurs : " + ", ".join(f"`{c}`" for c in action.choices) + "."
        if action.option_strings and action.default not in (None, False, argparse.SUPPRESS, [], ""):
            detail += (" " if detail else "") + f"Par défaut : `{action.default}`."
        lignes.append(f"| {nom} | {detail} |")
    if not lignes:
        return []
    return ["| Argument | Effet |", "|---|---|", *lignes, ""]


def sous_commandes(parser: argparse.ArgumentParser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            aides = {a.dest: a.help for a in action._choices_actions}
            for nom, sous in action.choices.items():
                yield nom, aides.get(nom), sous


def section(commande: str, parser: argparse.ArgumentParser, niveau: int, chemin: str) -> list[str]:
    lignes = []
    for nom, aide, sous in sous_commandes(parser):
        complet = f"{chemin} {nom}"
        lignes += [f"{'#' * niveau} `{complet}`", ""]
        if nettoyer(aide) or nettoyer(sous.description):
            lignes += [nettoyer(sous.description) or nettoyer(aide), ""]
        lignes += options(sous)
        lignes += section(commande, sous, niveau + 1, complet)
    return lignes


def generer() -> str:
    lignes = [INTRO]
    for commande, module, resume in COMMANDES:
        parser = capturer(module)
        lignes += [f"## `{commande}`", "", resume, ""]
        globales = options(parser)
        if globales:
            lignes += ["Options communes :", "", *globales]
        lignes += section(commande, parser, 3, commande)
    return "\n".join(lignes).rstrip() + "\n"


def main() -> int:
    OUT.write_text(generer(), encoding="utf-8")
    print(f"écrit {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
