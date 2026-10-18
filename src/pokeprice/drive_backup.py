"""Deterministic private Drive copies using an existing rclone OAuth remote.

Archives leave the laptop encrypted with age (X25519): Drive only ever holds
`.zip.age` files. The key stays on the laptop, in the configuration folder;
without it no copy on Drive can be read, so it needs an offline copy too.
Recovery without this code: `age -d -i backup-key.txt archive.zip.age > archive.zip`.
"""

import fcntl
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import pyrage
import requests

from .daily_backup import (
    DRIVE_FOLDER,
    daily,
    record_external,
    record_failure,
    serialized,
    status,
    verify,
)


# rclone gets as long as a slow ~2 Mbit/s home uplink needs for the archive:
# a fixed 240 s stopped the 790 MB archive of 17 October three times.
RCLONE_MIN_RATE = 250_000  # bytes per second
RCLONE_FLOOR, RCLONE_CEILING = 240, 3 * 3600


def transfer_timeout(size):
    return min(RCLONE_CEILING, max(RCLONE_FLOOR, math.ceil(size / RCLONE_MIN_RATE)))


# Plain .zip names are the copies sent before encryption; retention ages them out.
ARCHIVE = re.compile(r"(?:oci-)?daily-(\d{4}-\d{2}-\d{2})(?:-[a-f0-9]{64})?\.zip(?:\.age)?")
# Kept on Drive: the last week day by day, then one per week, then one per month.
KEEP_DAILY, KEEP_WEEKLY, KEEP_MONTHLY = 7, 8, 12


def retained(names):
    """Archive names to keep: every archive of a kept day; other names never count."""
    by_day = {}
    for name in names:
        match = ARCHIVE.fullmatch(name)
        if match:
            by_day.setdefault(date.fromisoformat(match[1]), set()).add(name)
    days = sorted(by_day, reverse=True)
    kept = set(days[:KEEP_DAILY])
    for period, count in (
        (lambda day: day.isocalendar()[:2], KEEP_WEEKLY),
        (lambda day: (day.year, day.month), KEEP_MONTHLY),
    ):
        newest = {}
        for day in days:
            newest.setdefault(period(day), day)
        kept.update(sorted(newest.values(), reverse=True)[:count])
    return {name for day in kept for name in by_day[day]}


def prune(drive, current):
    """Send archives beyond retention to the Drive trash (recoverable 30 days)."""
    files = [f for f in drive.archives() if ARCHIVE.fullmatch(f["name"])]
    kept = retained([f["name"] for f in files]) | {current}
    stale = [f for f in files if f["name"] not in kept]
    for file in stale:
        drive.trash(file)
    return len(stale)


class Drive:
    def __init__(self, binary, remote):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", remote):
            raise ValueError("Nom de remote rclone invalide.")
        self.binary, self.remote = str(binary), remote

    def run(self, *args, timeout=RCLONE_FLOOR):
        try:
            result = subprocess.run(
                [self.binary, *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            # The command line names the private Drive folder: keep it out of logs.
            raise RuntimeError(
                f"rclone {args[0]} a dépassé le délai de {timeout} s."
            ) from None
        if result.returncode:
            # Never emit config dumps or OAuth tokens in logs or exceptions.
            raise RuntimeError(f"rclone {args[0]} a échoué (code {result.returncode}).")
        return result.stdout

    def transfer(self, *args, size=0):
        return self.run(
            *args,
            "--drive-root-folder-id",
            DRIVE_FOLDER,
            "--contimeout",
            "15s",
            "--timeout",
            "60s",
            "--retries",
            "1",
            "--low-level-retries",
            "2",
            timeout=transfer_timeout(size),
        )

    def prepare(self):
        if not DRIVE_FOLDER:
            raise ValueError(
                "Dossier Drive non configuré : renseignez POKEPRICE_DRIVE_FOLDER ou ~/.config/pokeprice/drive_folder."
            )
        # Listing refreshes OAuth through rclone before reading the access token.
        self.transfer("lsjson", f"{self.remote}:", "--max-depth", "1")
        config = json.loads(self.run("config", "dump"))[self.remote]
        if config.get("type") != "drive":
            raise ValueError("Le remote doit être de type Google Drive.")
        token = config.get("token", {})
        if isinstance(token, str):
            token = json.loads(token)
        self.authorization = "Bearer " + token["access_token"]
        folder = self.metadata(DRIVE_FOLDER)
        self.private(folder)
        if folder.get("mimeType") != "application/vnd.google-apps.folder":
            raise ValueError("La destination n'est pas un dossier Drive.")

    def api(self, path, params):
        response = requests.get(
            "https://www.googleapis.com/drive/v3/" + path,
            params=params,
            headers={"Authorization": self.authorization},
            timeout=30,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Contrôle Drive impossible (HTTP {response.status_code})."
            )
        return response.json()

    def metadata(self, file_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
            raise ValueError("Identifiant Drive invalide.")
        return self.api(
            "files/" + file_id,
            {
                "fields": "id,name,size,parents,mimeType,trashed,shared,permissions(type,role)",
            },
        )

    @staticmethod
    def private(metadata):
        permissions = metadata.get("permissions", [])
        if (
            metadata.get("trashed") is not False
            or metadata.get("shared") is not False
            or len(permissions) != 1
            or permissions[0] != {"type": "user", "role": "owner"}
        ):
            raise ValueError("Confidentialité Drive non confirmée ; transfert bloqué.")

    def archives(self):
        files, token = [], None
        while True:
            params = {
                "q": f"'{DRIVE_FOLDER}' in parents and trashed = false",
                "fields": "files(id,name,parents),nextPageToken",
                "pageSize": 1000,
            }
            if token:
                params["pageToken"] = token
            result = self.api("files", params)
            files += result.get("files", [])
            token = result.get("nextPageToken")
            if not token:
                return files

    def trash(self, file):
        if not ARCHIVE.fullmatch(file["name"]) or file.get("parents") != [DRIVE_FOLDER]:
            raise ValueError("Seules les archives du dossier de sauvegarde sont élaguées.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", file["id"]):
            raise ValueError("Identifiant Drive invalide.")
        response = requests.patch(
            "https://www.googleapis.com/drive/v3/files/" + file["id"],
            json={"trashed": True},
            headers={"Authorization": self.authorization},
            timeout=30,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Mise à la corbeille impossible (HTTP {response.status_code}).")

    def find(self, name):
        if not re.fullmatch(r"(?:oci-)?daily-[0-9-]+(?:-[a-f0-9]{64})?\.zip(?:\.age)?", name):
            raise ValueError("Nom de sauvegarde invalide.")
        result = self.api(
            "files",
            {
                "q": f"'{DRIVE_FOLDER}' in parents and name = '{name}' and trashed = false",
                "fields": "files(id),nextPageToken",
                "pageSize": 100,
            },
        )
        files = result.get("files", [])
        if result.get("nextPageToken") or len(files) > 1:
            raise ValueError(
                "Plusieurs archives portent ce nom ; aucun transfert effectué."
            )
        return self.metadata(files[0]["id"]) if files else None


def key_path():
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config / "pokeprice" / "backup-key.txt"


def create_key(path=None):
    """Create the laptop's backup key once, in the age key file format."""
    path = Path(path or key_path())
    created = not path.exists()
    if created:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        identity = pyrage.x25519.Identity.generate()
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as key:
            key.write(f"# public key: {identity.to_public()}\n{identity}\n")
    # Only the public half is ever shown.
    return {"path": str(path), "recipient": str(load_key(path).to_public()), "created": created}


def load_key(path=None):
    path = Path(path or key_path())
    if not path.exists():
        raise RuntimeError(
            "Clé de chiffrement des sauvegardes absente : lancez pokeprice-manage backup-key."
        )
    if path.stat().st_mode & 0o077:
        raise ValueError("La clé de chiffrement doit être en mode 0600.")
    lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()]
    secret = next((l for l in lines if l.startswith("AGE-SECRET-KEY-")), None)
    if not secret:
        raise ValueError("Fichier de clé de chiffrement illisible.")
    return pyrage.x25519.Identity.from_str(secret)


@serialized
def snapshot(store, destination):
    local = status(store)["local"]
    shutil.copyfile(local["path"], destination)
    destination.chmod(0o600)
    captured = verify(destination)
    if captured["sha256"] != local["sha256"]:
        raise ValueError("La sauvegarde a changé avant sa copie stable.")
    return local


def upload_daily(store, *, binary=None, remote="gdrive"):
    return upload(store, lambda: daily(store), binary=binary, remote=remote)


def upload_server(mirror, host, *, binary=None, remote="gdrive", ssh="ssh"):
    """Send the server's verified daily archive, never one built on the laptop."""
    from .server_backup import pull_latest

    return upload(
        mirror, lambda: pull_latest(mirror, host, ssh=ssh), binary=binary, remote=remote
    )


def upload(store, produce, *, binary=None, remote="gdrive"):
    binary = binary or shutil.which("rclone")
    with (store.root / "drive-backup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if not binary:
                raise RuntimeError("rclone introuvable.")
            identity = load_key()
            produce()
            drive = Drive(binary, remote)
            drive.prepare()
            with tempfile.TemporaryDirectory(prefix="pokeprice-drive-") as temporary:
                captured = Path(temporary) / "upload.zip"
                local = snapshot(store, captured)
                sealed = Path(temporary) / "upload.zip.age"
                pyrage.encrypt_file(str(captured), str(sealed), [identity.to_public()])
                # Reuse an encrypted copy already sent only when its content identity agrees.
                previous = status(store).get("external") or {}
                if previous.get("sha256") == local["sha256"] and str(
                    previous.get("remote_name", "")
                ).endswith(".age"):
                    name = previous["remote_name"]
                else:
                    name = Path(local["name"]).stem + "-" + local["sha256"] + ".zip.age"
                file = drive.find(name)
                if file is None:
                    drive.transfer(
                        "copyto",
                        str(sealed),
                        f"{remote}:{name}",
                        "--immutable",
                        size=local["bytes"],
                    )
                    file = drive.find(name)
                if not file:
                    raise ValueError("Archive distante introuvable après le transfert.")
                drive.private(file)
                # A copy sent earlier has another random header: only the payload
                # size (nonce, plain bytes, a tag per 64 KiB chunk) is fixed.
                payload = 16 + local["bytes"] + 16 * max(1, math.ceil(local["bytes"] / 65536))
                if (
                    file.get("parents") != [DRIVE_FOLDER]
                    or not 0 < int(file.get("size", -1)) - payload <= 1024
                    or str(file.get("mimeType", "")).startswith("application/vnd.google-apps")
                ):
                    raise ValueError("Métadonnées de l'archive distante incohérentes.")
                fetched = Path(temporary) / "download.zip.age"
                drive.transfer(
                    "copyto", f"{remote}:{name}", str(fetched), size=local["bytes"]
                )
                downloaded = Path(temporary) / "download.zip"
                try:
                    pyrage.decrypt_file(str(fetched), str(downloaded), [identity])
                except (pyrage.DecryptError, OSError):  # a truncated or altered stream
                    raise ValueError("L'archive distante ne se déchiffre pas avec la clé.") from None
                restored = verify(downloaded)
                if restored["sha256"] != local["sha256"]:
                    raise ValueError(
                        "Le SHA-256 téléchargé diffère de l'archive locale."
                    )
                # A long transfer can outlive the hour-long OAuth token: refresh it.
                drive.prepare()
                # Recheck permissions after downloading and before marking success.
                drive.private(drive.metadata(DRIVE_FOLDER))
                drive.private(drive.metadata(file["id"]))
                result = record_external(
                    store,
                    local["path"],
                    file["id"],
                    local["bytes"],
                    expected_sha256=local["sha256"],
                    verification="download-decrypt-sha256-restore",
                    remote_name=name,
                )
            # Only after a verified copy; a failure here leaves that copy valid.
            try:
                result["retention"] = {"trashed": prune(drive, name)}
            except Exception:
                result["retention"] = {
                    "error": "Rétention non appliquée ; nouvel essai à la prochaine copie."
                }
            return result
        except Exception:
            record_failure(store)
            raise
