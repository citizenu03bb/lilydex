"""Deterministic private Drive copies using an existing rclone OAuth remote."""

import fcntl
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

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


class Drive:
    def __init__(self, binary, remote):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", remote):
            raise ValueError("Nom de remote rclone invalide.")
        self.binary, self.remote = str(binary), remote

    def run(self, *args):
        result = subprocess.run(
            [self.binary, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=240,
        )
        if result.returncode:
            # Never emit config dumps or OAuth tokens in logs or exceptions.
            raise RuntimeError(f"rclone {args[0]} a échoué (code {result.returncode}).")
        return result.stdout

    def transfer(self, *args):
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
        )

    def prepare(self):
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

    def find(self, name):
        if not re.fullmatch(r"daily-[0-9-]+(?:-[a-f0-9]{64})?\.zip", name):
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
    binary = binary or shutil.which("rclone")
    with (store.root / "drive-backup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if not binary:
                raise RuntimeError("rclone introuvable.")
            daily(store)
            drive = Drive(binary, remote)
            drive.prepare()
            with tempfile.TemporaryDirectory(prefix="pokeprice-drive-") as temporary:
                captured = Path(temporary) / "upload.zip"
                local = snapshot(store, captured)
                # Reuse a pre-existing agentic copy only when its content identity agrees.
                previous = status(store).get("external") or {}
                if previous.get("sha256") == local["sha256"]:
                    name = previous.get("remote_name") or previous["name"]
                else:
                    name = Path(local["name"]).stem + "-" + local["sha256"] + ".zip"
                file = drive.find(name)
                if file is None:
                    drive.transfer(
                        "copyto", str(captured), f"{remote}:{name}", "--immutable"
                    )
                    file = drive.find(name)
                if not file:
                    raise ValueError("Archive distante introuvable après le transfert.")
                drive.private(file)
                if (
                    file.get("parents") != [DRIVE_FOLDER]
                    or int(file.get("size", -1)) != local["bytes"]
                    or file.get("mimeType") != "application/zip"
                ):
                    raise ValueError("Métadonnées de l'archive distante incohérentes.")
                downloaded = Path(temporary) / "download.zip"
                drive.transfer("copyto", f"{remote}:{name}", str(downloaded))
                restored = verify(downloaded)
                if restored["sha256"] != local["sha256"]:
                    raise ValueError(
                        "Le SHA-256 téléchargé diffère de l'archive locale."
                    )
                # Recheck permissions after downloading and before marking success.
                drive.private(drive.metadata(DRIVE_FOLDER))
                drive.private(drive.metadata(file["id"]))
                return record_external(
                    store,
                    local["path"],
                    file["id"],
                    local["bytes"],
                    expected_sha256=local["sha256"],
                    verification="download-sha256-restore",
                    remote_name=name,
                )
        except Exception:
            record_failure(store)
            raise
