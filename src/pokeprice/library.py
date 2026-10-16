"""Consolidate report snapshots while preserving every album pocket and edition."""

import hashlib
import json
import os
import unicodedata
from pathlib import Path

import pandas as pd

from .html_report import build_report_cards, text_value
from .report import apply_pricing_and_anomalies, export_csv, read_report


def normalized(value):
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", str(value)).casefold()
        if not unicodedata.combining(c)
    ).strip()


def edition_key(row, copy_id):
    # An unresolved name cannot establish that two pockets contain the same edition.
    if row.get("Statut_Identification") != "confirmed":
        return "unresolved:" + copy_id
    language = text_value(row.get("Langue_Carte")) or "unknown"
    cid = text_value(row.get("TCGdex_ID"))
    identity = (
        [language, cid]
        if cid
        else [
            language,
            normalized(
                row.get("Nom_Verifie")
                if pd.notna(row.get("Nom_Verifie"))
                else row.get("Identified_Name")
            ),
            normalized(row.get("Extension")),
            text_value(row.get("Numero_Officiel")),
        ]
    )
    return (
        "edition:"
        + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[
            :24
        ]
    )


def load_manifest(path):
    path = Path(path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    albums = manifest.get("albums") if isinstance(manifest, dict) else None
    if not isinstance(albums, list) or not albums:
        raise ValueError("Le manifeste doit contenir une liste albums non vide.")
    resolved, ids, reports = [], set(), set()
    for entry in albums:
        if not isinstance(entry, dict) or any(
            not isinstance(entry.get(k), str) or not entry[k].strip()
            for k in ("id", "name", "report", "photos")
        ):
            raise ValueError("Chaque album doit définir id, name, report et photos.")
        album = dict(entry)
        for field in ("report", "photos"):
            p = Path(entry[field]).expanduser()
            album[field] = (p if p.is_absolute() else path.parent / p).resolve()
        if album["id"] in ids or album["report"] in reports:
            raise ValueError("Album ou rapport dupliqué dans le manifeste.")
        first_page = entry.get("first_page", 1)
        if type(first_page) is not int or first_page < 1:
            raise ValueError(f"first_page invalide pour {album['name']}.")
        # An album filled from a later page keeps its physical page numbers.
        album["first_page"] = first_page
        ids.add(album["id"])
        reports.add(album["report"])
        if not album["report"].is_file() or not album["photos"].is_dir():
            raise ValueError(f"Rapport ou photos introuvables pour {album['name']}.")
        html = album["report"].with_suffix(".html")
        album["html"] = html if html.is_file() else None
        resolved.append(album)
    return resolved


def consolidate(albums, output_dir, *, include_images=True):
    output_dir = Path(output_dir).resolve()
    frames, groups = [], {}
    for album in albums:
        frame = apply_pricing_and_anomalies(read_report(album["report"])).reset_index(
            drop=True
        )
        if frame[["Fichier_Image", "Position"]].duplicated().any():
            raise ValueError(f"Pochettes dupliquées dans {album['name']}.")
        cards = (
            build_report_cards(frame, album["photos"])
            if include_images
            else [{} for _ in range(len(frame))]
        )
        frame["Page"] = frame["Page"].astype(int) + album.get("first_page", 1) - 1
        frame["Album_ID"] = album["id"]
        frame["Album"] = album["name"]
        frame["Rapport_Source"] = str(album["report"])
        copy_ids, keys = [], []
        for i, row in frame.iterrows():
            copy_id = (
                album["id"]
                + ":"
                + text_value(row["Fichier_Image"])
                + ":"
                + str(int(row["Position"]))
            )
            key = edition_key(row, copy_id)
            copy_ids.append(copy_id)
            keys.append(key)
            card = cards[i]
            group = groups.setdefault(
                key,
                {
                    "id": key,
                    "name": text_value(row.get("Identified_Name"), "À identifier"),
                    "set": text_value(row.get("Extension")),
                    "number": text_value(row.get("Numero_Officiel")),
                    "language": text_value(row.get("Langue_Carte")),
                    "confirmed": row.get("Statut_Identification") == "confirmed",
                    "copies": [],
                },
            )
            copy = {
                "id": copy_id,
                "album_id": album["id"],
                "album": album["name"],
                "page": int(row["Page"]),
                "position": int(row["Position"]),
                "file": text_value(row["Fichier_Image"]),
                "condition": text_value(row.get("Etat")),
                "foil": text_value(row.get("Is_Foil")) == "Oui",
                "price_date": card.get("price_date", ""),
                "price_source": card.get("price_source", ""),
                "reference_price": card.get("reference_price_eur"),
                "image": card.get("real_crop_img", ""),
                "note": text_value(row.get("Note_Verification")),
                "report_url": "./"
                + Path(os.path.relpath(album["html"], output_dir)).as_posix()
                if album.get("html")
                else "",
                "search": " ".join(
                    text_value(row.get(k))
                    for k in (
                        "OCR_Name",
                        "Identified_Name",
                        "Nom_Verifie",
                        "Extension",
                        "Numero_Officiel",
                        "OCR_Number",
                    )
                ),
            }
            group["copies"].append(copy)
        frame["Exemplaire_ID"] = copy_ids
        frame["Edition_ID"] = keys
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    group_list = sorted(
        groups.values(),
        key=lambda g: (normalized(g["name"]), g["set"], g["number"], g["language"]),
    )
    for group in group_list:
        group["quantity"] = len(group["copies"])
    quantities = {g["id"]: g["quantity"] for g in group_list}
    combined["Nombre_Exemplaires_Edition"] = combined.Edition_ID.map(quantities)
    return combined, {
        "albums": [{"id": a["id"], "name": a["name"]} for a in albums],
        "groups": group_list,
    }


def build_library(manifest_path, output_stem):
    stem = Path(output_stem).resolve()
    stem.parent.mkdir(parents=True, exist_ok=True)
    albums = load_manifest(manifest_path)
    combined, data = consolidate(albums, stem.parent)
    # Avoid accidentally replacing one of the input reports.
    outputs = {
        Path(str(stem) + suffix).resolve() for suffix in (".csv", ".json", ".html")
    }
    inputs = {a["report"] for a in albums} | {
        a["html"] for a in albums if a.get("html")
    }
    if outputs & inputs or Path(manifest_path).resolve() in outputs:
        raise ValueError(
            "La bibliothèque doit avoir un nom distinct des rapports et du manifeste."
        )
    export_csv(combined, str(stem) + ".csv")
    metadata = json.loads(json.dumps(data))
    for group in metadata["groups"]:
        for copy in group["copies"]:
            copy.pop("image", None)
    Path(str(stem) + ".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    payload = (
        json.dumps(data, ensure_ascii=False, allow_nan=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    template = (
        Path(__file__).with_name("library_template.html").read_text(encoding="utf-8")
    )
    Path(str(stem) + ".html").write_text(
        template.replace("__LIBRARY_DATA__", payload), encoding="utf-8"
    )
    return {
        "copies": len(combined),
        "editions": sum(g["confirmed"] for g in data["groups"]),
        "unresolved": int((combined.Statut_Identification != "confirmed").sum()),
        "albums": len(albums),
    }
