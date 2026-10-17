"""Verified copies of the server's daily archive, pulled over SSH to the laptop.

The live collection is on the server; the laptop keeps only these copies and the
Drive token. Nothing here opens a collection database.
"""

import hashlib
import os
import re
import subprocess
from pathlib import Path

from .daily_backup import record_local, serialized, status, verify
from .drive_backup import transfer_timeout

BACKUPS = "/srv/pokeprice/backups"
DAILY = re.compile(r"daily-(\d{4}-\d{2}-\d{2})\.zip")
KEEP = 3  # ~800 MB each on a nearly full laptop disk; the server keeps seven.
# The server backup restores its archive as a check before returning.
BACKUP_TIMEOUT = 30 * 60


class Mirror:
    """State folder for pulled archives, never a collection folder."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        if (self.root / "collection.sqlite3").exists():
            raise ValueError("Le miroir ne peut pas être un dossier de collection.")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)


class Server:
    def __init__(self, host, ssh="ssh"):
        # A strict user@host keeps ssh options and shell syntax out of the target.
        if not re.fullmatch(r"[a-z_][a-z0-9_-]*@[A-Za-z0-9][A-Za-z0-9.-]*", host):
            raise ValueError("Hôte SSH invalide (attendu : utilisateur@hôte).")
        self.host, self.ssh = host, str(ssh)

    def run(self, command, *, timeout=120, stdout=subprocess.PIPE):
        try:
            result = subprocess.run(
                [
                    self.ssh,
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=15",
                    "--",
                    self.host,
                    command,
                ],
                stdout=stdout,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Le serveur n'a pas répondu dans le délai de {timeout} s."
            ) from None
        if result.returncode:
            raise RuntimeError(
                f"Commande serveur en échec (code {result.returncode})."
            )
        return result.stdout.decode() if result.stdout is not None else ""

    def latest(self):
        # Starting the oneshot waits for tonight's run, or re-verifies today's archive.
        self.run(
            "sudo systemctl start pokeprice-backup.service", timeout=BACKUP_TIMEOUT
        )
        # The folder belongs to the service user: list it through sudo, not a glob.
        listing = self.run(
            f"sudo find {BACKUPS} -maxdepth 1 -type f"
            " -name 'daily-????-??-??.zip' -printf '%f\\n'"
        )
        names = [name for name in listing.split() if DAILY.fullmatch(name)]
        if not names:
            raise ValueError("Aucune sauvegarde quotidienne sur le serveur.")
        name = max(names)
        path = f"{BACKUPS}/{name}"
        identity = self.run(
            f"sudo sha256sum -- {path} && sudo stat -c %s -- {path}",
            timeout=BACKUP_TIMEOUT,
        ).split()
        if len(identity) != 3 or not re.fullmatch(r"[a-f0-9]{64}", identity[0]):
            raise ValueError("Empreinte de l'archive du serveur illisible.")
        return {"name": name, "bytes": int(identity[2]), "sha256": identity[0]}

    def fetch(self, name, destination, size):
        if not DAILY.fullmatch(name):
            raise ValueError("Nom de sauvegarde invalide.")
        with open(
            destination, "wb", opener=lambda path, flags: os.open(path, flags, 0o600)
        ) as stream:
            self.run(
                f"sudo cat -- {BACKUPS}/{name}",
                timeout=transfer_timeout(size),
                stdout=stream,
            )


def digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@serialized
def pull(mirror, server, *, keep=KEEP):
    remote = server.latest()
    target = mirror.root / ("oci-" + remote["name"])
    if not (target.exists() and digest(target) == remote["sha256"]):
        pending = mirror.root / f".{target.name}.part"
        try:
            pending.unlink(missing_ok=True)
            server.fetch(remote["name"], pending, remote["bytes"])
            if (
                pending.stat().st_size != remote["bytes"]
                or digest(pending) != remote["sha256"]
            ):
                raise ValueError("L'archive rapatriée diffère de celle du serveur.")
            os.replace(pending, target)
        finally:
            pending.unlink(missing_ok=True)
    verified = verify(target)
    if verified["sha256"] != remote["sha256"]:
        raise ValueError("L'archive rapatriée a changé pendant sa vérification.")
    verified["source"] = {"host": server.host, "name": remote["name"]}
    record_local(mirror, verified)
    for old in sorted(mirror.root.glob("oci-daily-????-??-??.zip"), reverse=True)[
        keep:
    ]:
        old.unlink()
    return verified


def pull_latest(mirror, host, *, ssh="ssh", keep=KEEP):
    return pull(mirror, Server(host, ssh), keep=keep)
