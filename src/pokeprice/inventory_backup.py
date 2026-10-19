"""Portable database + photo backups and offline exports of the managed state."""

import base64
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path

from .inventory import SCHEMA_VERSION, Store, now


def backup(store, destination):
    destination = Path(destination)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError("La sauvegarde existe déjà.")
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "collection.sqlite3"
        with store.connect() as db, closing(sqlite3.connect(snapshot)) as target:
            db.backup(target)
            target.execute("DELETE FROM sessions")
            from .agent import disable_tokens

            disable_tokens(target)
            target.commit()
        files = {"collection.sqlite3": snapshot.read_bytes()}
        # Include previous photos referenced in correction history as well.
        for photo in sorted(store.photos.glob("*.jpg")):
            files["photos/" + photo.name] = photo.read_bytes()
        documents = store.root / "reference_documents"
        if documents.exists():
            for document in sorted(documents.iterdir()):
                if not document.is_file() or not re.fullmatch(
                    r"[a-f0-9]{64}\.(pdf|json|html|jpg|png)", document.name
                ):
                    raise ValueError("Document de référence non qualifié.")
                body = document.read_bytes()
                if hashlib.sha256(body).hexdigest() != document.stem:
                    raise ValueError("Document de référence altéré.")
                files["reference_documents/" + document.name] = body
        manifest = {
            "format": "pokeprice-inventory-v1",
            "created_at": now(),
            "files": {
                name: hashlib.sha256(body).hexdigest() for name, body in files.items()
            },
        }
        # Private from its first byte: a chmod after writing leaves a readable window.
        handle = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with (
                os.fdopen(handle, "wb") as output,
                zipfile.ZipFile(
                    output, "w", compression=zipfile.ZIP_DEFLATED
                ) as archive,
            ):
                for name, body in files.items():
                    archive.writestr(name, body)
                archive.writestr(
                    "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
                )
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
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
            if (
                name != "collection.sqlite3"
                and not (
                    len(parts) == 2
                    and parts[0] == "photos"
                    and parts[1].endswith(".jpg")
                )
                and not (
                    len(parts) == 2
                    and parts[0] == "reference_documents"
                    and re.fullmatch(r"[a-f0-9]{64}\.(pdf|json|html|jpg|png)", parts[1])
                )
            ):
                raise ValueError("Chemin de sauvegarde interdit.")
            if hashlib.sha256(archive.read(name)).hexdigest() != checksum:
                raise ValueError("Somme de contrôle invalide.")
            if parts[0] == "reference_documents" and Path(name).stem != checksum:
                raise ValueError("Identité de document incohérente.")
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
                if version not in range(1, SCHEMA_VERSION + 1):
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
                if version >= 14:
                    for row in db.execute("SELECT photos_json FROM verifications"):
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
                from .agent import disable_tokens

                disable_tokens(db)
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
        "agent_drafts",
        "condition_assessments",
        "verifications",
        "reference_rulesets",
        "reference_engines",
        "reference_decisions",
        "reference_quotes",
        "reference_quote_events",
    )
    with store.connect() as db:
        db.execute("BEGIN")
        exported = {
            "format": "pokeprice-inventory-v1",
            "exported_at": now(),
            "tables": {
                t: [dict(r) for r in db.execute("SELECT * FROM " + t)] for t in tables
            },
        }
        unknown = {
            r["sale_id"]
            for r in exported["tables"]["agent_drafts"]
            if not r["amount_known"]
        }
        for sale in exported["tables"]["sales"]:
            if sale["id"] in unknown:
                sale["amount_cents"] = None
        return exported


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
        "finish",
        "variant_confirmed",
        "variant_verified_at",
        "variant_verified_by",
        "variant_observation",
        "photo",
        "photo_original",
        "back_photo",
        "back_photo_original",
        "foil",
        "stamp",
        "stamp_state",
        "distribution",
        "distribution_state",
        "observation_provenance",
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
        "reference_print_status",
        "reference_market_status",
        "reference_price_state",
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
            "reference_print_status": r["reference_resolution"]["print_status"],
            "reference_market_status": r["reference_resolution"]["market_status"],
            "reference_price_state": r["reference_resolution"]["price_selection"][
                "state"
            ],
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
                "finish": r["finish"],
                "variant_confirmed": bool(r["variant_confirmed"]),
                "variant_verified_at": r["variant_verified_at"],
                "variant_verified_by": r["variant_verified_by"],
                "variant_observation": r["variant_observation"],
                "foil": bool(r["foil"]),
                "stamp": r["stamp"],
                "stamp_state": r["stamp_state"],
                "distribution": r["distribution"],
                "distribution_state": r["distribution_state"],
                "observation_provenance": json.loads(r["observation_provenance"]),
                "reference_resolution": r["reference_resolution"],
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
