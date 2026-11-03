#!/usr/bin/env python3
"""Annonces prêtes à poster sur Vinted, Leboncoin ou Cardmarket, sans rien publier.

La base est ouverte en lecture seule. Pour Vinted et Leboncoin, un dossier par
annonce (annonce.txt et photos) ; pour Cardmarket, le fichier d'import de stock.
Les cartes et lots écartés sont listés dans exclues.txt.
Mode d'emploi : docs/VENTE-PLATEFORMES.md.

Usage :
  python scripts/export_annonces.py --data <base> --plateforme vinted --sortie <dossier>
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeprice.marketplace_export import DEFAULT_MARGIN, PLATFORMS, run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", required=True, help="dossier de la collection (lecture seule)")
    parser.add_argument("--plateforme", required=True, choices=PLATFORMS)
    parser.add_argument("--sortie", required=True, help="dossier neuf où écrire les annonces")
    parser.add_argument(
        "--marge", type=float, default=DEFAULT_MARGIN * 100,
        help="pourcentage maximal sous la cote de référence (défaut : %(default)s)",
    )
    host = os.environ.get("POKEPRICE_HOST", "")
    parser.add_argument(
        "--site", default=f"https://{host}" if host else "",
        help="adresse publique de la vitrine, pour le lien vers la fiche (défaut : POKEPRICE_HOST)",
    )
    args = parser.parse_args(argv)
    try:
        written, export = run(
            args.data, args.plateforme, args.sortie, margin=args.marge / 100, site=args.site
        )
    except (FileNotFoundError, FileExistsError, ValueError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1
    what = "ligne(s) dans le fichier Cardmarket" if args.plateforme == "cardmarket" else "annonce(s)"
    print(f"{len(written)} {what} dans {args.sortie}.")
    print(f"{len(export.excluded)} carte(s) ou lot(s) écartés : voir exclues.txt.")
    if args.plateforme != "cardmarket" and not args.site:
        print("Sans --site, les annonces ne contiennent pas de lien vers la fiche.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
