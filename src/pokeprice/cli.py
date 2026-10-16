"""
Command-line interface for pokeprice.
"""

import argparse
import glob
import os
import sys
import json
import time
from dataclasses import asdict
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
from pokeprice.ocr import get_ocr_provider, CardOCRResult, failed_result
from pokeprice.energy_gate import gated_note, gated_result
from pokeprice.tcgdex import TCGdexClient, CardPriceInfo
from pokeprice.report import (
    build_dataframe,
    export_csv,
    export_excel,
    print_summary,
    read_report,
)


def output_paths(output):
    path = Path(output)
    if path.suffix.lower() not in (".csv", ".xlsx"):
        raise ValueError("Le fichier de sortie doit avoir une extension .csv ou .xlsx.")
    path.parent.mkdir(parents=True, exist_ok=True)
    return (
        path.with_suffix(".csv"),
        path.with_suffix(".xlsx"),
        path.with_suffix(".html"),
    )


def cmd_scan(args):
    """Scan with a durable checkpoint after every pocket, including empty pockets."""
    target = Path(args.path)
    if target.is_dir():
        images = sorted(
            p
            for p in target.iterdir()
            if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
        )
    elif target.is_file():
        images = [target]
    else:
        raise ValueError(f"Chemin introuvable : {target}")
    excluded = getattr(args, "exclude", [])
    images = [p for p in images if p.name not in excluded and str(p) not in excluded]
    if getattr(args, "limit", 0) > 0:
        images = images[: args.limit]
    if not images:
        raise ValueError("Aucune image à analyser.")
    csv_path, xlsx_path, html_path = output_paths(args.output)
    checkpoint = csv_path.with_suffix(".checkpoint.json")
    provider = get_ocr_provider(backend=args.backend, model=args.model)
    model = getattr(provider, "model", args.model)
    gate = None
    if getattr(args, "energy_gate", None):
        from pokeprice.energy_gate import MARGIN, PROTOCOL, from_store
        from pokeprice.inventory import Store

        if not (Path(args.energy_gate) / "collection.sqlite3").is_file():
            raise ValueError(f"Collection introuvable : {args.energy_gate}")
        gate = from_store(Store(args.energy_gate))
        if not gate.ready:
            raise ValueError("Trop peu d’énergies de base dans la collection pour la porte.")
    corrections = []
    if getattr(args, "corrections", None):
        corrections = json.loads(Path(args.corrections).read_text())
        if not isinstance(corrections, list) or any(
            not isinstance(c, dict)
            or not isinstance(c.get("image_file"), str)
            or not isinstance(c.get("position"), int)
            or c["position"] <= 0
            or not isinstance(c.get("card_number"), str)
            for c in corrections
        ):
            raise ValueError(
                "Corrections : une liste de fichier, position et référence est requise."
            )
        if any(
            "card_name" in c
            and (not isinstance(c["card_name"], str) or not c["card_name"].strip())
            for c in corrections
        ):
            raise ValueError("Le nom corrigé doit être une chaîne non vide.")
    if any(
        "card_id" in c
        and (not isinstance(c["card_id"], str) or not c["card_id"].strip())
        for c in corrections
    ):
        raise ValueError("card_id doit être une chaîne non vide")
    if any(
        "card_language" in c and c["card_language"] not in ("fr", "en")
        for c in corrections
    ):
        raise ValueError("card_language doit être fr ou en")
    if any(
        "card_hp" in c and (type(c["card_hp"]) is not int or c["card_hp"] < 0)
        for c in corrections
    ):
        raise ValueError("card_hp doit être un entier positif ou nul")
    overrides = {(c["image_file"], c["position"]): c for c in corrections}
    if len(overrides) != len(corrections):
        raise ValueError("Corrections dupliquées pour la même pochette.")
    settings = {
        "images": [
            {
                "path": str(p.resolve()),
                "size": p.stat().st_size,
                "mtime": p.stat().st_mtime_ns,
            }
            for p in images
        ],
        "backend": args.backend,
        "model": model,
        "grid": args.grid,
        "rotate": args.rotate,
        "inset": args.inset,
        "condition": args.condition,
        "corrections": corrections,
    }
    if gate:
        settings["energy_gate"] = {"protocol": PROTOCOL, "margin": MARGIN}
    records, completed = [], set()
    if getattr(args, "resume", False):
        payload = json.loads(checkpoint.read_text())
        if payload.get("settings") != settings:
            raise ValueError("Les images ou paramètres diffèrent du checkpoint.")
        for raw in payload["records"]:
            record = dict(raw)
            record["ocr"] = CardOCRResult(**raw["ocr"]) if raw["ocr"] else None
            record["price_info"] = (
                CardPriceInfo(**raw["price_info"]) if raw["price_info"] else None
            )
            if record.get("match_status") != "failed":
                records.append(record)
        completed = {tuple(key) for key in payload["completed"]}
        failed_keys = {
            (r["image_file"], r["position"])
            for r in payload["records"]
            if r.get("match_status") == "failed"
        }
        completed -= failed_keys
    client = TCGdexClient(language="fr")

    def save_checkpoint():
        serialized = [
            {
                **r,
                "ocr": asdict(r["ocr"]) if r.get("ocr") else None,
                "price_info": asdict(r["price_info"]) if r.get("price_info") else None,
            }
            for r in records
        ]
        temp = checkpoint.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(
                {
                    "version": 1,
                    "settings": settings,
                    "records": serialized,
                    "completed": sorted(completed),
                },
                ensure_ascii=False,
                allow_nan=False,
            )
        )
        temp.replace(checkpoint)

    def record_for(page, filename, pos, result, rows=None, cols=None, crop_path=""):
        return {
            "page_num": page,
            "position": pos,
            "image_file": filename,
            "ocr": result,
            "price_info": None,
            "condition": args.condition,
            "grid_rows": rows,
            "grid_cols": cols,
            "rotation": args.rotate,
            "inset": args.inset,
            "model": model,
            "backend": args.backend,
            "crop_path": crop_path,
        }

    interrupted = False
    try:
        covers = 0
        for index, path in enumerate(images, 1):
            # A cover is not a page: the first card page stays page 1.
            page = index - covers
            print(f"📄 Photo {index}/{len(images)} : {path.name}")
            try:
                with Image.open(path) as image:
                    oriented = normalize_orientation(image, args.rotate)
                    if args.grid == "auto":
                        layout = provider.detect_layout(oriented)
                        if layout == "cover":
                            covers += 1
                            continue
                        rows, cols = detect_grid_layout(oriented, layout)
                    else:
                        rows, cols = detect_grid_layout(oriented, args.grid)
                    crops = slice_grid(oriented, rows, cols, args.inset)
            except Exception as exc:
                key = (path.name, 0)
                if key not in completed:
                    record = record_for(page, path.name, 0, failed_result(str(exc)))
                    record.update(
                        match_status="failed", verification_note=f"Page non lue : {exc}"
                    )
                    records.append(record)
                    completed.add(key)
                    save_checkpoint()
                continue
            for pos, crop in crops:
                key = (path.name, pos)
                if key in completed:
                    continue
                crop_path = ""
                if args.save_crops:
                    directory = Path(args.save_crops)
                    directory.mkdir(parents=True, exist_ok=True)
                    crop_path = str(
                        (directory / f"p{page:02d}_c{pos:02d}.png").resolve()
                    )
                    crop.save(crop_path)
                result = None
                # A basic Energy recognised by image needs no Gemini reading.
                gated = gate.check(crop) if gate else None
                if gated:
                    result = gated_result(gated)
                for attempt in range(0 if gated else getattr(args, "retries", 2) + 1):
                    try:
                        result = provider.extract_card(crop)
                    except Exception as exc:
                        result = failed_result(str(exc))
                    if result.status != "failed":
                        break
                    if attempt < getattr(args, "retries", 2):
                        time.sleep(0.25 * 2**attempt)
                if result.occupied is False and result.status == "empty":
                    completed.add(key)
                    save_checkpoint()
                    continue
                record = record_for(page, path.name, pos, result, rows, cols, crop_path)
                if result.status == "failed":
                    record.update(match_status="failed", verification_note=result.error)
                elif gated:
                    record.update(
                        match_status="unresolved", verification_note=gated_note(gated)
                    )
                elif not result.name:
                    record.update(
                        match_status="unresolved",
                        verification_note="Carte présente ou illisible : identité à vérifier.",
                    )
                else:
                    try:
                        override = overrides.get(key)
                        number = (
                            override["card_number"] if override else result.card_number
                        )
                        name = (
                            override.get("card_name", result.name)
                            if override
                            else result.name
                        )
                        hp = (
                            override.get("card_hp", result.hp)
                            if override
                            else result.hp
                        )
                        if override and override.get("card_id"):
                            price = client.get_card_by_id(
                                override["card_id"],
                                result.is_holo,
                                language=override.get("card_language"),
                            )
                            if (
                                not price
                                or price.card_number != number
                                or price.name.casefold() != name.casefold()
                                or (hp and price.hp != hp)
                            ):
                                raise ValueError(
                                    "La carte vérifiée ne correspond pas au nom, numéro ou PV"
                                )
                            price.match_method = "exact"
                            client.last_match_reason = "Édition vérifiée manuellement."
                        else:
                            price = client.search_card(name, number, result.is_holo, hp)
                        record["price_info"] = price
                        record["verification_note"] = client.last_match_reason
                        if override:
                            record["verified_number"] = number
                            record["verified_name"] = override.get("card_name", "")
                            record["verified_hp"] = override.get("card_hp")
                            record["correction_source"] = str(
                                override.get("source", "Correction fournie")
                            )
                            record["verification_note"] = (
                                f"Référence corrigée : {number}. "
                                + client.last_match_reason
                            )
                    except Exception as exc:
                        record.update(
                            match_status="failed",
                            verification_note=f"Identification indisponible : {exc}",
                        )
                records.append(record)
                completed.add(key)
                save_checkpoint()
                print(
                    f"  #{pos} {result.name or 'À identifier'} : {record.get('verification_note', '')}"
                )
    except KeyboardInterrupt:
        interrupted = True
        print("Scan interrompu : résultats partiels conservés.")
    finally:
        save_checkpoint()
        df = (
            build_dataframe(records)
            .sort_values(["Page", "Position"])
            .reset_index(drop=True)
        )
        export_csv(df, str(csv_path))
        export_excel(df, str(xlsx_path))
    if not interrupted:
        from pokeprice.html_report import generate_html_report

        generate_html_report(
            df,
            str(target if target.is_dir() else target.parent),
            str(html_path),
            title=f"Album Pokémon - {target.name}",
        )
    print_summary(df)
    return (
        1
        if interrupted or any(r.get("match_status") == "failed" for r in records)
        else 0
    )


def cmd_html(args):
    """Generates an interactive HTML visual report from a CSV/Excel file and album folder."""
    import pandas as pd
    from pokeprice.report import apply_pricing_and_anomalies
    from pokeprice.html_report import generate_html_report

    report_file = args.report_file
    album_dir = args.album_dir
    out_html = args.output or (
        report_file.replace(".xlsx", ".html").replace(".csv", ".html")
        if (report_file.endswith(".xlsx") or report_file.endswith(".csv"))
        else "report.html"
    )
    df = read_report(report_file)

    df = apply_pricing_and_anomalies(df)

    title = args.title or f"Album Pokémon - {os.path.basename(album_dir)}"
    grid = detect_grid_layout(None, args.grid) if getattr(args, "grid", None) else None
    generate_html_report(
        df,
        album_dir=album_dir,
        output_html_path=out_html,
        title=title,
        grid=grid,
        rotation=getattr(args, "rotate", "auto"),
        inset=getattr(args, "inset", 0.02),
    )
    print(f"\n🌐 Rapport web généré : {os.path.abspath(out_html)}")


def cmd_lookup(args):
    """Looks up a single card in TCGdex French database."""
    name = args.name
    num = args.number or ""
    print(f"🔎 Recherche de : '{name}' (réf: '{num}')...")
    client = TCGdexClient(language="fr")
    info = client.search_card(
        name=name, raw_number=num, is_holo=args.holo, hp=getattr(args, "pv", 0)
    )
    if not info:
        print("❌ Carte non trouvée.")
        return

    print("\n" + "=" * 50)
    print(f" Nom officiel       : {info.name}")
    print(f" Extension          : {info.set_name}")
    print(f" Numéro / Rareté    : {info.card_number} ({info.rarity})")
    print(
        f" Tendance Cardmarket: {info.cm_trend_eur:.2f} €"
        if info.cm_trend_eur
        else " Tendance Cardmarket: N/A"
    )
    if info.cm_trend_holo_eur:
        print(f" Tendance Holo / Rev: {info.cm_trend_holo_eur:.2f} €")
    if info.tcg_market_usd:
        print(f" TCGplayer Market   : ${info.tcg_market_usd:.2f}")
    if info.cardmarket_id:
        print(
            f" Lien Cardmarket    : https://www.cardmarket.com/fr/Pokemon/Products/Singles/{info.cardmarket_id}"
        )
    print("=" * 50)


def cmd_report(args):
    """Displays summary for an existing CSV report."""
    import pandas as pd

    if not os.path.exists(args.csv_file):
        print(f"Fichier introuvable : {args.csv_file}", file=sys.stderr)
        sys.exit(1)
    df = read_report(args.csv_file)
    print_summary(df)


def cmd_library(args):
    from .library import build_library

    stats = build_library(args.manifest, args.output)
    print(
        f"Bibliothèque : {stats['copies']} exemplaires, {stats['editions']} éditions identifiées, {stats['albums']} albums."
    )
    print(f"HTML : {args.output}.html")


def main():
    parser = argparse.ArgumentParser(
        prog="pokeprice",
        description="Scannez et valorisez automatiquement vos albums Pokémon avec l'IA locale Gemma 4 E4B et Cardmarket.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Subcommand: scan
    scan_p = subparsers.add_parser(
        "scan", help="Scanne une photo de page ou un dossier de photos"
    )
    scan_p.add_argument("path", help="Chemin vers une image ou un dossier d'images")
    scan_p.add_argument(
        "--grid",
        choices=["auto", "3x3", "2x2", "4x3", "3x4", "single"],
        default="auto",
        help="Disposition des pochettes (défaut: auto - détection visuelle IA)",
    )
    scan_p.add_argument(
        "--rotate",
        choices=["auto", "0", "90", "180", "270"],
        default="auto",
        help="Correction d'orientation (défaut: auto)",
    )
    scan_p.add_argument(
        "--backend",
        choices=["ollama", "gemini"],
        default="ollama",
        help="Moteur de vision (défaut: ollama local ; gemini envoie les images au cloud)",
    )
    scan_p.add_argument(
        "--model",
        default=None,
        help="Nom du modèle (défaut: gemini-3.8-flash pour gemini, gemma4:e4b-it-q4_K_M pour ollama)",
    )
    scan_p.add_argument(
        "--output",
        "-o",
        default="pokeprice_report.csv",
        help="Fichier de sortie (.csv ou .xlsx)",
    )
    scan_p.add_argument(
        "--save-crops",
        default=None,
        help="Dossier optionnel où sauvegarder les découpes individuelles de cartes",
    )
    scan_p.add_argument(
        "--inset",
        type=float,
        default=0.02,
        help="Marge intérieure de découpe (0.02 = 2%%) pour éviter les coutures plastiques",
    )
    scan_p.add_argument(
        "--condition",
        default=None,
        choices=["NM", "EX", "GD", "LP", "PL", "PO", "NM/EX"],
        help="Force cet état pour toutes les cartes (défaut: grade OCR, ou état inconnu)",
    )
    scan_p.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help="Noms de fichiers à exclure (ex: PXL_20261004_074746593.jpg)",
    )
    scan_p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Nombre maximum d'images à traiter (0 = toutes)",
    )
    scan_p.add_argument(
        "--resume",
        action="store_true",
        help="Reprend le checkpoint du même fichier de sortie",
    )
    scan_p.add_argument(
        "--retries",
        type=int,
        default=2,
        choices=range(0, 6),
        help="Réessais OCR après échec (défaut: 2)",
    )
    scan_p.add_argument(
        "--energy-gate",
        metavar="DONNEES",
        default=None,
        help="Dossier de la collection (ex. data/inventory) : les énergies de base reconnues par l'image ne sont pas lues par Gemini",
    )
    scan_p.add_argument(
        "--corrections",
        default=None,
        help="Fichier JSON de corrections de référence par fichier/position",
    )
    scan_p.set_defaults(func=cmd_scan)

    # Subcommand: lookup
    lookup_p = subparsers.add_parser(
        "lookup", help="Recherche directe du prix d'une carte par nom"
    )
    lookup_p.add_argument("name", help="Nom français de la carte (ex: Darkrai)")
    lookup_p.add_argument(
        "number", nargs="?", default=None, help="Numéro ou fraction (ex: 4/106)"
    )
    lookup_p.add_argument(
        "--pv",
        "--hp",
        dest="pv",
        type=int,
        default=0,
        help="Points de vie (PV / HP) imprimés sur la carte (ex: 80)",
    )
    lookup_p.add_argument(
        "--holo",
        action="store_true",
        help="Chercher la version holographique / reverse",
    )
    lookup_p.set_defaults(func=cmd_lookup)

    # Subcommand: report
    report_p = subparsers.add_parser(
        "report", help="Affiche le résumé d'un rapport CSV existant"
    )
    report_p.add_argument("csv_file", help="Chemin vers le fichier CSV généré")
    report_p.set_defaults(func=cmd_report)

    # Subcommand: html
    html_p = subparsers.add_parser(
        "html",
        help="Génère un rapport web interactif (photos réelles + officielles côte à côte)",
    )
    html_p.add_argument("report_file", help="Fichier CSV ou Excel généré par scan")
    html_p.add_argument("album_dir", help="Dossier contenant les photos du classeur")
    html_p.add_argument(
        "-o", "--output", default=None, help="Chemin du fichier HTML de sortie"
    )
    html_p.add_argument("--title", default=None, help="Titre de la page web")
    html_p.add_argument(
        "--grid",
        choices=["3x3", "2x2", "4x3", "3x4", "single"],
        default=None,
        help="Géométrie pour les anciens exports sans métadonnées",
    )
    html_p.add_argument(
        "--rotate", choices=["auto", "0", "90", "180", "270"], default="auto"
    )
    html_p.add_argument("--inset", type=float, default=0.02)
    html_p.set_defaults(func=cmd_html)

    library_p = subparsers.add_parser(
        "library", help="Consolide les albums et recherche tous les exemplaires"
    )
    library_p.add_argument("manifest", help="Manifeste JSON des albums à regrouper")
    library_p.add_argument(
        "-o",
        "--output",
        default="pokeprice_library",
        help="Préfixe des sorties HTML, CSV et JSON",
    )
    library_p.set_defaults(func=cmd_library)

    args = parser.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
