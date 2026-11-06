"""Portable database + photo backups and offline exports of the managed state."""

import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path

from .inventory import SCHEMA_VERSION, Store, now

FORMAT = "pokeprice-inventory-v1"
# Same base and documents, but photos stay once in a reserve beside the archives.
LIGHT_FORMAT = "pokeprice-inventory-v2"
PHOTO = re.compile(r"[a-f0-9]{64}\.jpg")
DOCUMENT = re.compile(r"[a-f0-9]{64}\.(pdf|json|html|jpg|png)")
# Fixed ZIP timestamps: the same light archive always rebuilds the same bytes.
EPOCH = (1980, 1, 1, 0, 0, 0)

# Room left for the app and the restore check after an archive is written.
FREE_SPACE_MARGIN = 512 * 2**20


def private_file(destination):
    # Private from its first byte: a chmod after writing leaves a readable window.
    return os.fdopen(
        os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
    )


def reserve_photo(source, reserve):
    """Keep one photo in the reserve: a hard link, or a copy across disks."""
    target = reserve / source.name
    if target.exists():
        return
    try:
        os.link(source, target)
    except FileExistsError:
        pass
    except OSError:
        pending = reserve / f".{source.name}.part"
        pending.unlink(missing_ok=True)
        try:
            with source.open("rb") as body, private_file(pending) as output:
                shutil.copyfileobj(body, output)
            os.replace(pending, target)
        finally:
            pending.unlink(missing_ok=True)


def backup(store, destination, reserve=None):
    """Archive the base, its photos and reference documents.

    With a reserve folder, photos named by their SHA-256 go there once instead
    of into the archive, which only lists them (format v2).
    """
    destination = Path(destination)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError("La sauvegarde existe déjà.")
    from .privacy import erasure_log, journal_snapshot, read_erasures

    # Check the DB's durable erasure marker without changing the collection.
    # A lost used journal cannot turn into a valid-looking empty record.
    journal_snapshot(store)
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "collection.sqlite3"
        with store.connect() as db, closing(sqlite3.connect(snapshot)) as target:
            db.backup(target)
            target.execute("DELETE FROM sessions")
            from .agent import disable_tokens

            disable_tokens(target)
            target.commit()
        files = {"collection.sqlite3": snapshot.read_bytes()}
        # An erasure after the DB snapshot must still be replayable.
        files["erasures.jsonl"] = read_erasures(erasure_log(store.root))["body"]
        reserved = {}
        # Include previous photos referenced in correction history as well.
        for photo in sorted(store.photos.glob("*.jpg")):
            if reserve is not None and PHOTO.fullmatch(photo.name):
                reserved[photo.name] = photo.stat().st_size
            else:
                files["photos/" + photo.name] = photo.read_bytes()
        documents = store.root / "reference_documents"
        if documents.exists():
            for document in sorted(documents.iterdir()):
                if not document.is_file() or not DOCUMENT.fullmatch(document.name):
                    raise ValueError("Document de référence non qualifié.")
                body = document.read_bytes()
                if hashlib.sha256(body).hexdigest() != document.stem:
                    raise ValueError("Document de référence altéré.")
                files["reference_documents/" + document.name] = body
        manifest = {
            "format": FORMAT if reserve is None else LIGHT_FORMAT,
            "created_at": now(),
            "files": {
                name: hashlib.sha256(body).hexdigest() for name, body in files.items()
            },
        }
        if reserve is not None:
            manifest["photos"] = reserved
        # A full disk would also starve the running app: refuse before writing.
        needed = sum(len(body) for body in files.values()) + FREE_SPACE_MARGIN
        free = shutil.disk_usage(destination.parent).free
        if free < needed:
            raise OSError(
                f"Espace disque insuffisant pour la sauvegarde : {free // 2**20} Mo libres, "
                f"{needed // 2**20} Mo nécessaires. Libérez de la place (anciennes "
                "sauvegardes ponctuelles, caches) avant de recommencer."
            )
        if reserve is not None:
            reserve = Path(reserve)
            reserve.mkdir(mode=0o700, parents=True, exist_ok=True)
            for name in reserved:
                reserve_photo(store.photos / name, reserve)
        try:
            with (
                private_file(destination) as output,
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
        "files": len(files) + len(reserved),
        "bytes": destination.stat().st_size,
    }


def read_manifest(archive):
    """Manifest of a v1 or v2 archive, with its external photos ({} for v1)."""
    manifest = json.loads(archive.read("manifest.json"))
    if manifest.get("format") not in (FORMAT, LIGHT_FORMAT):
        raise ValueError("Format de sauvegarde inconnu.")
    photos = manifest.get("photos", {}) if manifest["format"] == LIGHT_FORMAT else {}
    if not isinstance(photos, dict) or any(
        not PHOTO.fullmatch(name)
        or type(size) is not int
        or "photos/" + name in manifest["files"]
        for name, size in photos.items()
    ):
        raise ValueError("Manifeste de photos incohérent.")
    return manifest, photos


def photo_names(archive_path):
    """Every photo an archive needs, whether it holds it or lists it."""
    with zipfile.ZipFile(archive_path) as archive:
        manifest, photos = read_manifest(archive)
    return set(photos) | {
        name.removeprefix("photos/")
        for name in manifest["files"]
        if name.startswith("photos/")
    }


def light_photos(archive_path):
    """Photos listed by a v2 archive ({name: bytes}), or None for a v1 archive."""
    with zipfile.ZipFile(archive_path) as archive:
        manifest, photos = read_manifest(archive)
    return photos if manifest["format"] == LIGHT_FORMAT else None


def reserved_photo(reserve, name, size):
    path = Path(reserve) / name
    if not PHOTO.fullmatch(name) or not path.is_file():
        raise ValueError(f"Photo absente de la réserve : {name}.")
    body = path.read_bytes()
    if len(body) != size or hashlib.sha256(body).hexdigest() != path.stem:
        raise ValueError(f"Photo altérée dans la réserve : {name}.")
    return body


def prune_reserve(reserve, archives, keep=()):
    """Remove reserve photos that no kept archive needs and `keep` does not hold.

    An unreadable archive stops the pruning: nothing is removed. Returns the
    names removed.
    """
    reserve = Path(reserve)
    if not reserve.is_dir():
        return []
    needed = set(keep)
    for archive in archives:
        needed |= photo_names(archive)
    removed = []
    for photo in sorted(reserve.glob("*.jpg")):
        if photo.name not in needed:
            photo.unlink()
            removed.append(photo.name)
    return removed


def assemble(light_path, reserve, destination):
    """Rebuild a self-contained v1 archive from a v2 archive and its reserve.

    The result is deterministic: the same inputs always give the same bytes.
    """
    destination = Path(destination)
    with zipfile.ZipFile(light_path) as light:
        manifest, photos = read_manifest(light)
        if manifest["format"] != LIGHT_FORMAT:
            raise ValueError("Seule une archive v2 se reconstitue.")
        names = light.namelist()
        if len(names) != len(set(names)) or set(names) != set(manifest["files"]) | {
            "manifest.json"
        }:
            raise ValueError("Contenu de sauvegarde incohérent.")
        files = dict(manifest["files"])
        files.update(
            {"photos/" + name: Path(name).stem for name in photos}
        )
        try:
            with private_file(destination) as output, zipfile.ZipFile(
                output, "w"
            ) as archive:
                for name in sorted(files):
                    if name in manifest["files"]:
                        body = light.read(name)
                        if hashlib.sha256(body).hexdigest() != files[name]:
                            raise ValueError("Somme de contrôle invalide.")
                    else:
                        stem = name.removeprefix("photos/")
                        body = reserved_photo(reserve, stem, photos[stem])
                    archive.writestr(
                        zipfile.ZipInfo(name, EPOCH),
                        body,
                        compress_type=zipfile.ZIP_DEFLATED,
                    )
                archive.writestr(
                    zipfile.ZipInfo("manifest.json", EPOCH),
                    json.dumps(
                        {
                            "format": FORMAT,
                            "created_at": manifest["created_at"],
                            "files": files,
                        },
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    ),
                    compress_type=zipfile.ZIP_DEFLATED,
                )
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    return {"path": str(destination), "files": len(files)}


def restore_backup(archive_path, destination, photos=None, *, journal=None):
    """Restore into a new folder.

    A v2 archive reads its photos from `photos`, by default the reserve
    `photos/` beside the archive. A validated current `journal` is replayed
    before publishing the destination. Omitting it is for archive verification
    or the CLI's explicit --sans-journal recovery only.
    """
    destination = Path(destination)
    if destination.exists():
        raise ValueError("La restauration exige un nouveau dossier.")
    with zipfile.ZipFile(archive_path) as archive:
        manifest, external = read_manifest(archive)
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
                name not in ("collection.sqlite3", "erasures.jsonl")
                and not (
                    len(parts) == 2
                    and parts[0] == "photos"
                    and parts[1].endswith(".jpg")
                )
                and not (
                    len(parts) == 2
                    and parts[0] == "reference_documents"
                    and DOCUMENT.fullmatch(parts[1])
                )
            ):
                raise ValueError("Chemin de sauvegarde interdit.")
            if hashlib.sha256(archive.read(name)).hexdigest() != checksum:
                raise ValueError("Somme de contrôle invalide.")
            if parts[0] == "reference_documents" and Path(name).stem != checksum:
                raise ValueError("Identité de document incohérente.")
            if name == "erasures.jsonl":
                from .privacy import parse_erasures

                parse_erasures(archive.read(name))
        reserve = Path(photos) if photos else Path(archive_path).parent / "photos"
        if external and not reserve.is_dir():
            raise ValueError(
                "Réserve de photos introuvable : indiquez son dossier (option --photos)."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
            recovered = Path(temporary) / "restored"
            recovered.mkdir()
            for name in expected:
                if name == "erasures.jsonl":
                    # This older snapshot never replaces the current journal.
                    continue
                target = recovered / name
                target.parent.mkdir(exist_ok=True)
                target.write_bytes(archive.read(name))
            if external:
                (recovered / "photos").mkdir(exist_ok=True)
            for name, size in external.items():
                (recovered / "photos" / name).write_bytes(
                    reserved_photo(reserve, name, size)
                )
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
            result = Store(recovered).summary()
            if journal is not None:
                from .privacy import Privacy

                result["erasures"] = Privacy(Store(recovered)).replay(journal)
                result.update(Store(recovered).summary())
            recovered.rename(destination)
    return result


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
