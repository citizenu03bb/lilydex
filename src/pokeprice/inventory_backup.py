"""Portable database + photo backups and offline exports of the managed state."""

import base64
import csv
import hashlib
import io
import json
import re
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path

from .inventory import Store, now


def backup(store, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError("La sauvegarde existe déjà.")
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "collection.sqlite3"
        with store.connect() as db, closing(sqlite3.connect(snapshot)) as target:
            db.backup(target)
            target.execute("DELETE FROM sessions")
            target.commit()
        files = {"collection.sqlite3": snapshot.read_bytes()}
        # Include previous photos referenced in correction history as well.
        for photo in sorted(store.photos.glob("*.jpg")):
            files["photos/" + photo.name] = photo.read_bytes()
        manifest = {
            "format": "pokeprice-inventory-v1",
            "created_at": now(),
            "files": {
                name: hashlib.sha256(body).hexdigest() for name, body in files.items()
            },
        }
        with zipfile.ZipFile(
            destination, "x", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for name, body in files.items():
                archive.writestr(name, body)
            archive.writestr(
                "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
            )
        destination.chmod(0o600)
    return {
        "path": str(destination),
        "files": len(files),
        "bytes": destination.stat().st_size,
    }


def restore_backup(archive_path, destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError("La restauration exige un nouveau dossier.")
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") != "pokeprice-inventory-v1":
            raise ValueError("Format de sauvegarde inconnu.")
        expected = manifest["files"]
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected) | {
            "manifest.json"
        }:
            raise ValueError("Contenu de sauvegarde incohérent.")
        if "collection.sqlite3" not in expected:
            raise ValueError("Base absente.")
        for name, checksum in expected.items():
            parts = Path(name).parts
            if name != "collection.sqlite3" and not (
                len(parts) == 2 and parts[0] == "photos" and parts[1].endswith(".jpg")
            ):
                raise ValueError("Chemin de sauvegarde interdit.")
            if hashlib.sha256(archive.read(name)).hexdigest() != checksum:
                raise ValueError("Somme de contrôle invalide.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
            recovered = Path(temporary) / "restored"
            recovered.mkdir()
            for name in expected:
                target = recovered / name
                target.parent.mkdir(exist_ok=True)
                target.write_bytes(archive.read(name))
            with sqlite3.connect(recovered / "collection.sqlite3") as db:
                if (
                    db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or db.execute("PRAGMA foreign_key_check").fetchall()
                ):
                    raise ValueError("Base restaurée incohérente.")
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (1, 2, 3, 4, 5, 6, 7, 8, 9):
                    raise ValueError("Version de base incompatible.")
                photos = [
                    row[0]
                    for row in db.execute(
                        "SELECT photo FROM copies WHERE photo IS NOT NULL"
                    )
                ]
                if version >= 5:
                    for field in (
                        "photo_original",
                        "back_photo",
                        "back_photo_original",
                    ):
                        photos.extend(
                            row[0]
                            for row in db.execute(
                                f"SELECT {field} FROM copies WHERE {field} IS NOT NULL"
                            )
                        )
                    for row in db.execute(
                        "SELECT photos_json FROM condition_assessments"
                    ):
                        photos.extend(
                            p["image"] for p in json.loads(row[0]).values() if p
                        )
                for name in photos:
                    if (
                        not re.fullmatch(r"[a-f0-9]{64}\.jpg", name)
                        or not (recovered / "photos" / name).is_file()
                    ):
                        raise ValueError("Photo référencée absente.")
                # Backups carry user password hashes, but never reactivate saved sessions.
                db.execute("DELETE FROM sessions")
                db.commit()
            recovered.rename(destination)
    return Store(destination).summary()


def export_data(store):
    tables = (
        "albums",
        "editions",
        "copies",
        "sources",
        "events",
        "prices",
        "sales",
        "sale_items",
        "sale_events",
        "imports",
        "condition_assessments",
    )
    with store.connect() as db:
        db.execute("BEGIN")
        return {
            "format": "pokeprice-inventory-v1",
            "exported_at": now(),
            "tables": {
                t: [dict(r) for r in db.execute("SELECT * FROM " + t)] for t in tables
            },
        }


def export_csv(store):
    rows = store.listing(limit=1000000)["items"]
    fields = [
        "id",
        "source_key",
        "name",
        "set_name",
        "number",
        "language",
        "catalog_id",
        "hp",
        "identification_status",
        "condition",
        "condition_confirmed",
        "photo",
        "photo_original",
        "back_photo",
        "back_photo_original",
        "foil",
        "stamp",
        "album",
        "page",
        "position",
        "stock_state",
        "reference_price_eur",
        "currency",
        "price_source",
        "price_date",
        "notes",
        "version",
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for r in rows:
        r = {
            **r,
            "reference_price_eur": ""
            if r["reference_cents"] is None
            else f"{r['reference_cents'] / 100:.2f}",
            "currency": "EUR",
        }
        writer.writerow(
            {
                k: (
                    "'" + str(r[k])
                    if isinstance(r.get(k), str)
                    and r[k].startswith(("=", "+", "-", "@", "\t", "\r"))
                    else r.get(k, "")
                )
                for k in fields
            }
        )
    return "\ufeff" + stream.getvalue()


def export_html(store):
    rows = store.listing(limit=1000000)["items"]
    with store.connect() as db:
        actors = {
            r["copy_id"]: r["actor"]
            for r in db.execute("SELECT copy_id,actor FROM prices ORDER BY id")
        }
    groups = {}
    for r in rows:
        group = groups.setdefault(
            r["edition_id"],
            {
                "id": r["edition_id"],
                "name": r["name"],
                "set": r["set_name"],
                "number": r["number"],
                "language": r["language"],
                "confirmed": r["identification_status"] == "confirmed",
                "copies": [],
            },
        )
        state = {"available": "Disponible", "reserved": "Réservé", "sold": "Vendu"}[
            r["stock_state"]
        ]
        photo = (
            "data:image/jpeg;base64,"
            + base64.b64encode((store.photos / r["photo"]).read_bytes()).decode()
            if r["photo"]
            else ""
        )
        group["copies"].append(
            {
                "id": r["id"],
                "album_id": r["album_id"],
                "album": r["album"],
                "page": r["page"],
                "position": r["position"],
                "file": r["source_key"],
                "condition": r["condition"],
                "condition_confirmed": bool(r["condition_confirmed"]),
                "foil": bool(r["foil"]),
                "stamp": r["stamp"],
                "price_date": r["price_date"],
                "price_source": r["price_source"],
                "price_provider": "TCGdex / Cardmarket"
                if actors.get(r["id"]) == "import"
                else "",
                "reference_price": None
                if r["reference_cents"] is None
                else r["reference_cents"] / 100,
                "image": photo,
                "back_image": "data:image/jpeg;base64,"
                + base64.b64encode(
                    (store.photos / r["back_photo"]).read_bytes()
                ).decode()
                if r["back_photo"]
                else "",
                "note": state + " · " + r["notes"],
                "report_url": "",
                "search": " ".join(
                    str(r[k] or "")
                    for k in ("name", "set_name", "number", "language", "album")
                )
                + " "
                + state,
            }
        )
        group["copies"][-1]["search"] += " " + r["search_aliases"]
    for g in groups.values():
        g["quantity"] = len(g["copies"])
    data = {"albums": store.summary()["albums"], "groups": list(groups.values())}
    payload = (
        json.dumps(data, ensure_ascii=False, allow_nan=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    return (
        Path(__file__)
        .with_name("library_template.html")
        .read_text()
        .replace("__LIBRARY_DATA__", payload)
        .replace(
            "La bibliothèque doit être régénérée après une correction d’album.",
            "Cet export reflète la collection gérée au moment de son téléchargement. Télécharger un nouvel export après une modification.",
        )
    )
