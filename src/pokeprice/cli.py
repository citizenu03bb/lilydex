"""
Command-line interface for pokeprice.
"""

import argparse
import glob
import os
import sys
from pathlib import Path
from PIL import Image

try:
    from dotenv import load_dotenv
    home_env = Path.home() / ".env"
    if home_env.exists():
        load_dotenv(home_env)
    load_dotenv()
except ImportError:
    pass

from pokeprice.slicer import normalize_orientation, detect_grid_layout, slice_grid
from pokeprice.ocr import get_ocr_provider
from pokeprice.tcgdex import TCGdexClient
from pokeprice.report import build_dataframe, export_csv, export_excel, print_summary


def cmd_scan(args):
    """Scans an image or a folder of images."""
    target_path = args.path
    if os.path.isdir(target_path):
        patterns = ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.JPG", "*.JPEG", "*.PNG"]
        image_files = []
        for pat in patterns:
            image_files.extend(glob.glob(os.path.join(target_path, pat)))
        image_files = sorted(list(set(image_files)))
    elif os.path.isfile(target_path):
        image_files = [target_path]
    else:
        print(f"Erreur : Chemin introuvable : {target_path}", file=sys.stderr)
        sys.exit(1)

    if not image_files:
        print(f"Aucune image trouvée dans : {target_path}", file=sys.stderr)
        sys.exit(1)

    if args.exclude:
        image_files = [f for f in image_files if os.path.basename(f) not in args.exclude and f not in args.exclude]

    if args.limit and args.limit > 0:
        image_files = image_files[:args.limit]

    ocr_provider = get_ocr_provider(backend=args.backend, model=args.model)
    actual_model = getattr(ocr_provider, "model", args.model)
    print(f"🔍 Initialisation du pipeline pokeprice...")
    print(f" • Modèle OCR : {args.backend} ({actual_model})")
    print(f" • Images à analyser : {len(image_files)}")
    print(f" • Grille : {args.grid} | Rotation : {args.rotate}")

    tcgdex_client = TCGdexClient(language="fr")

    if args.save_crops:
        os.makedirs(args.save_crops, exist_ok=True)

    records = []
    
    for page_idx, img_path in enumerate(image_files, 1):
        filename = os.path.basename(img_path)
        print(f"\n📄 Traitement Page {page_idx}/{len(image_files)}: {filename}")
        
        try:
            raw_img = Image.open(img_path)
        except Exception as e:
            print(f"  ❌ Erreur d'ouverture {img_path}: {e}")
            continue

        # 1. Orientation
        oriented = normalize_orientation(raw_img, rotation=args.rotate)

        # 2. Grid determination
        if args.grid == "auto":
            detected_layout = ocr_provider.detect_layout(oriented)
            if detected_layout == "cover":
                print(f"  ℹ️ Image identifiée comme couverture d'album ou sans cartes : ignorée automatiquement.")
                continue
            elif detected_layout == "3x3":
                rows, cols = 3, 3
            elif detected_layout == "4x3":
                rows, cols = (4, 3) if oriented.height >= oriented.width else (3, 4)
            elif detected_layout == "single":
                rows, cols = 1, 1
            else:
                rows, cols = 2, 2
            print(f"  Grille auto-détectée par l'IA : {detected_layout} ({rows}×{cols} = {rows * cols} cartes)")
        else:
            rows, cols = detect_grid_layout(oriented, requested_layout=args.grid)
            print(f"  Grille configurée manuellement : {rows}×{cols} ({rows * cols} cartes)")

        # 3. Slicing
        crops = slice_grid(oriented, rows=rows, cols=cols, inset_pct=args.inset)

        # 4. Process each crop
        for pos, crop_img in crops:
            print(f"  -> Carte {pos}/{len(crops)}...", end="", flush=True)

            if args.save_crops:
                crop_fname = f"p{page_idx:02d}_c{pos:02d}_{filename}"
                crop_img.save(os.path.join(args.save_crops, crop_fname))

            # OCR extraction
            ocr_res = ocr_provider.extract_card(crop_img)

            if not ocr_res.name or ocr_res.name.lower() in ("vide", "empty", "none", "aucun", "aucune"):
                print(" [Emplacement vide]")
                continue

            # TCGdex Lookup
            price_info = None
            if ocr_res.name:
                price_info = tcgdex_client.search_card(
                    name=ocr_res.name,
                    raw_number=ocr_res.card_number,
                    is_holo=ocr_res.is_holo,
                    hp=ocr_res.hp
                )

            val_str = f"{price_info.cm_recommended_eur:.2f} €" if (price_info and price_info.cm_recommended_eur) else "N/A"
            identified = price_info.name if price_info else ocr_res.name
            holo_tag = " ✨ [Holo]" if ocr_res.is_holo else ""
            cond_tag = f" [{ocr_res.condition}]" if ocr_res.condition else ""
            flaws_tag = f" ⚠️ ({ocr_res.flaws})" if (ocr_res.flaws and ocr_res.flaws.lower() not in ("none", "none visible", "aucun", "aucune", "aucun défaut")) else ""
            print(f" {identified} ({ocr_res.card_number}){holo_tag}{cond_tag}{flaws_tag} => {val_str}")

            records.append({
                "page_num": page_idx,
                "position": pos,
                "image_file": filename,
                "ocr": ocr_res,
                "price_info": price_info,
                "condition": ocr_res.condition or getattr(args, "condition", "NM/EX"),
                "flaws": ocr_res.flaws or ""
            })

    # 5. Build and export report
    df = build_dataframe(records)
    out_file = args.output
    if out_file.endswith(".xlsx"):
        xlsx_file = out_file
        csv_file = out_file.replace(".xlsx", ".csv")
        html_file = out_file.replace(".xlsx", ".html")
    else:
        csv_file = out_file
        xlsx_file = out_file.replace(".csv", ".xlsx")
        html_file = out_file.replace(".csv", ".html")

    export_excel(df, xlsx_file)
    export_csv(df, csv_file)
    print(f"\n💾 Données exportées avec succès vers :")
    print(f" • Excel : {xlsx_file}")
    print(f" • CSV   : {csv_file}")

    if os.path.isdir(target_path):
        try:
            from pokeprice.html_report import generate_html_report
            title = f"Album Pokémon - {os.path.basename(target_path)}"
            generate_html_report(df, album_dir=target_path, output_html_path=html_file, title=title)
            print(f" • Web HTML interactif : {html_file}")
        except Exception as e:
            print(f"  (Note: Génération HTML non effectuée : {e})")

    # 6. Terminal Summary
    print_summary(df)


def cmd_html(args):
    """Generates an interactive HTML visual report from a CSV/Excel file and album folder."""
    import pandas as pd
    report_file = args.report_file
    album_dir = args.album_dir
    out_html = args.output or (
        report_file.replace(".xlsx", ".html").replace(".csv", ".html")
        if (report_file.endswith(".xlsx") or report_file.endswith(".csv"))
        else "report.html"
    )
    if report_file.endswith(".xlsx"):
        df = pd.read_excel(report_file)
    else:
        df = pd.read_csv(report_file)

    title = args.title or f"Album Pokémon - {os.path.basename(album_dir)}"
    from pokeprice.html_report import generate_html_report
    generate_html_report(df, album_dir=album_dir, output_html_path=out_html, title=title)
    print(f"\n🌐 Rapport web ouvert : file://{os.path.abspath(out_html)}")


def cmd_lookup(args):
    """Looks up a single card in TCGdex French database."""
    name = args.name
    num = args.number or ""
    print(f"🔎 Recherche de : '{name}' (réf: '{num}')...")
    client = TCGdexClient(language="fr")
    info = client.search_card(
        name=name,
        raw_number=num,
        is_holo=args.holo,
        hp=getattr(args, "pv", 0)
    )
    if not info:
        print("❌ Carte non trouvée.")
        return

    print("\n" + "=" * 50)
    print(f" Nom officiel       : {info.name}")
    print(f" Extension          : {info.set_name}")
    print(f" Numéro / Rareté    : {info.card_number} ({info.rarity})")
    print(f" Tendance Cardmarket: {info.cm_trend_eur:.2f} €" if info.cm_trend_eur else " Tendance Cardmarket: N/A")
    if info.cm_trend_holo_eur:
        print(f" Tendance Holo / Rev: {info.cm_trend_holo_eur:.2f} €")
    if info.tcg_market_usd:
        print(f" TCGplayer Market   : ${info.tcg_market_usd:.2f}")
    if info.cardmarket_id:
        print(f" Lien Cardmarket    : https://www.cardmarket.com/fr/Pokemon/Products/Singles/{info.cardmarket_id}")
    print("=" * 50)


def cmd_report(args):
    """Displays summary for an existing CSV report."""
    import pandas as pd
    if not os.path.exists(args.csv_file):
        print(f"Fichier introuvable : {args.csv_file}", file=sys.stderr)
        sys.exit(1)
    df = pd.read_csv(args.csv_file)
    print_summary(df)


def main():
    parser = argparse.ArgumentParser(
        prog="pokeprice",
        description="Scannez et valorisez automatiquement vos albums Pokémon avec l'IA locale Gemma 4 E4B et Cardmarket."
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Subcommand: scan
    scan_p = subparsers.add_parser("scan", help="Scanne une photo de page ou un dossier de photos")
    scan_p.add_argument("path", help="Chemin vers une image ou un dossier d'images")
    scan_p.add_argument(
        "--grid",
        choices=["auto", "3x3", "2x2", "4x3", "single"],
        default="auto",
        help="Disposition des pochettes (défaut: auto - détection visuelle IA)"
    )
    scan_p.add_argument(
        "--rotate",
        choices=["auto", "0", "90", "180", "270"],
        default="auto",
        help="Correction d'orientation (défaut: auto)"
    )
    scan_p.add_argument(
        "--backend",
        choices=["ollama", "gemini"],
        default="gemini" if os.getenv("GEMINI_API_KEY") else "ollama",
        help="Moteur de vision (défaut: gemini si GEMINI_API_KEY présent, sinon ollama)"
    )
    scan_p.add_argument(
        "--model",
        default=None,
        help="Nom du modèle (défaut: gemini-3.8-flash pour gemini, gemma4:e4b-it-q4_K_M pour ollama)"
    )
    scan_p.add_argument(
        "--output", "-o",
        default="pokeprice_report.csv",
        help="Fichier de sortie (.csv ou .xlsx)"
    )
    scan_p.add_argument(
        "--save-crops",
        default=None,
        help="Dossier optionnel où sauvegarder les découpes individuelles de cartes"
    )
    scan_p.add_argument(
        "--inset",
        type=float,
        default=0.02,
        help="Marge intérieure de découpe (0.02 = 2%%) pour éviter les coutures plastiques"
    )
    scan_p.add_argument(
        "--condition",
        default="NM/EX",
        help="État de conservation des cartes pour le rapport (défaut: NM/EX)"
    )
    scan_p.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help="Noms de fichiers à exclure (ex: PXL_20261004_074746593.jpg)"
    )
    scan_p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Nombre maximum d'images à traiter (0 = toutes)"
    )
    scan_p.set_defaults(func=cmd_scan)

    # Subcommand: lookup
    lookup_p = subparsers.add_parser("lookup", help="Recherche directe du prix d'une carte par nom")
    lookup_p.add_argument("name", help="Nom français de la carte (ex: Darkrai)")
    lookup_p.add_argument("number", nargs="?", default=None, help="Numéro ou fraction (ex: 4/106)")
    lookup_p.add_argument("--pv", "--hp", dest="pv", type=int, default=0, help="Points de vie (PV / HP) imprimés sur la carte (ex: 80)")
    lookup_p.add_argument("--holo", action="store_true", help="Chercher la version holographique / reverse")
    lookup_p.set_defaults(func=cmd_lookup)

    # Subcommand: report
    report_p = subparsers.add_parser("report", help="Affiche le résumé d'un rapport CSV existant")
    report_p.add_argument("csv_file", help="Chemin vers le fichier CSV généré")
    report_p.set_defaults(func=cmd_report)

    # Subcommand: html
    html_p = subparsers.add_parser("html", help="Génère un rapport web interactif (photos réelles + officielles côte à côte)")
    html_p.add_argument("report_file", help="Fichier CSV ou Excel généré par scan")
    html_p.add_argument("album_dir", help="Dossier contenant les photos du classeur")
    html_p.add_argument("-o", "--output", default=None, help="Chemin du fichier HTML de sortie")
    html_p.add_argument("--title", default=None, help="Titre de la page web")
    html_p.set_defaults(func=cmd_html)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
