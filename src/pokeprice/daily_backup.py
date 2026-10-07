"""Verified daily backups and an explicit record of external copies."""

import fcntl
import hashlib
import json
import os
import tempfile
from datetime import datetime
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

from .inventory import now
from .inventory_backup import backup, restore_backup

DRIVE_FOLDER = "DOSSIER-DRIVE-PRIVE"


def serialized(action):
    @wraps(action)
    def run(store, *args, **kwargs):
        with (store.root / "backup.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                return action(store, *args, **kwargs)
            except Exception:
                data = status(store)
                data.update(
                    last_error="Échec de la sauvegarde ou de sa vérification. Consultez le journal et réessayez.",
                    error_at=now(),
                )
                _write(store, data)
                raise

    return run


def status(store):
    path = store.root / "backup-status.json"
    return (
        json.loads(path.read_text())
        if path.exists()
        else {"local": None, "external": None}
    )


def _write(store, data):
    target = store.root / "backup-status.json"
    with tempfile.NamedTemporaryFile(mode="w", dir=store.root, delete=False) as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        pending = Path(stream.name)
    pending.chmod(0o600)
    os.replace(pending, target)


def verify(path):
    path = Path(path)
    with tempfile.TemporaryDirectory(prefix="pokeprice-restore-check-") as tmp:
        summary = restore_backup(path, Path(tmp) / "collection")
    return {
        "path": str(path.resolve()),
        "name": path.name,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "verified_at": now(),
        "copies": summary["copies"],
    }


@serialized
def daily(store, *, force=False):
    date = datetime.now(ZoneInfo("Europe/Paris")).strftime("%Y-%m-%d")
    folder = store.root.parent / "backups"
    target = folder / f"daily-{date}.zip"
    # Reusing a completed daily archive makes scheduler retries idempotent.
    if force or not target.exists():
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            pending = Path(tmp) / "collection.zip"
            backup(store, pending)
            verified = verify(pending)
            os.replace(pending, target)
        verified.update(path=str(target.resolve()), name=target.name)
    else:
        verified = verify(target)
    data = status(store)
    data.update(local=verified, last_error=None)
    _write(store, data)
    # Only daily archives managed here are eligible; manual backups remain intact.
    for old in sorted(folder.glob("daily-????-??-??.zip"), reverse=True)[7:]:
        old.unlink()
    return verified


@serialized
def record_external(
    store,
    path,
    file_id,
    size,
    folder_id=DRIVE_FOLDER,
    *,
    expected_sha256=None,
    verification="metadata-size",
    remote_name=None,
):
    verified = verify(path)
    if expected_sha256 is not None and verified["sha256"] != expected_sha256:
        raise ValueError(
            "La sauvegarde locale a changé pendant le transfert. Ne pas marquer cette copie comme à jour."
        )
    if int(size) != verified["bytes"] or folder_id != DRIVE_FOLDER:
        raise ValueError(
            "La copie Drive ne correspond pas à la sauvegarde ou au dossier privé."
        )
    data = status(store)
    data["external"] = {
        **verified,
        "file_id": file_id,
        "folder_id": folder_id,
        "uploaded_at": now(),
        "verification": verification,
        "remote_name": remote_name or verified["name"],
        "url": f"https://drive.google.com/file/d/{file_id}/view",
    }
    data.update(last_error=None)
    _write(store, data)
    return data["external"]


def public_status(store):
    data = status(store)
    for key in ("local", "external"):
        if data.get(key):
            data[key] = {k: v for k, v in data[key].items() if k != "path"}
    data["drive_folder_url"] = f"https://drive.google.com/drive/folders/{DRIVE_FOLDER}"
    return data


@serialized
def record_failure(store):
    data = status(store)
    data.update(
        last_error="La dernière copie Drive a échoué ou n’a pas pu être vérifiée.",
        error_at=now(),
    )
    _write(store, data)
    return public_status(store)
