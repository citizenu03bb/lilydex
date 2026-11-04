"""Verified copies of the server's daily archive, pulled over SSH to the laptop.

The live collection is on the server; the laptop keeps only these copies and the
Drive token. Nothing here opens a collection database.
"""

import hashlib
import os
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path

from .daily_backup import RESERVE, record_local, serialized, status, tidy_reserve, verify
from .drive_backup import transfer_timeout
from .inventory_backup import (
    PHOTO,
    assemble,
    light_photos,
    private_file,
)

BACKUPS = "/srv/pokeprice/backups"
DAILY = re.compile(r"daily-(\d{4}-\d{2}-\d{2})\.zip")
# Light (v2) archives pulled from the server: a few MB each.
KEEP = 3
# Self-contained archives rebuilt for Drive: ~800 MB each on a nearly full disk.
FULL_KEEP = 1
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

    def run(self, command, *, timeout=120, stdout=subprocess.PIPE, input=None):
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
                input=input,
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

    def fetch_photos(self, photos, folder):
        """Copy the named photos {name: bytes} of the server's reserve into folder."""
        if any(not PHOTO.fullmatch(name) for name in photos):
            raise ValueError("Nom de photo invalide.")
        if not photos:
            return
        # Names go on stdin: thousands of them would not fit a command line.
        with tempfile.TemporaryFile(dir=folder) as stream:
            self.run(
                f"sudo tar -C {BACKUPS}/{RESERVE} -cf - --files-from=-",
                input="".join(name + "\n" for name in photos).encode(),
                timeout=transfer_timeout(sum(photos.values())),
                stdout=stream,
            )
            stream.seek(0)
            receive_photos(stream, photos, folder)


def receive_photos(stream, photos, folder):
    """Write the photos of a tar stream into folder, each checked by its name."""
    received = set()
    with tarfile.open(fileobj=stream, mode="r:") as tar:
        for member in tar:
            name = member.name
            if (
                not member.isfile()
                or name not in photos
                or name in received
                or member.size != photos[name]
            ):
                raise ValueError("Photo inattendue dans le transfert.")
            body = tar.extractfile(member).read()
            if hashlib.sha256(body).hexdigest() != Path(name).stem:
                raise ValueError("Photo altérée pendant le transfert.")
            pending = Path(folder) / f".{name}.part"
            pending.unlink(missing_ok=True)
            try:
                with private_file(pending) as output:
                    output.write(body)
                os.replace(pending, Path(folder) / name)
            finally:
                pending.unlink(missing_ok=True)
            received.add(name)
    if received != set(photos):
        raise ValueError("Photos manquantes dans le transfert.")


def digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@serialized
def pull(mirror, server, *, keep=KEEP):
    remote = server.latest()
    date = DAILY.fullmatch(remote["name"])[1]
    target = mirror.root / ("oci-" + remote["name"])
    light = mirror.root / f"oci-light-{date}.zip"
    known = next(
        (p for p in (light, target) if p.exists() and digest(p) == remote["sha256"]),
        None,
    )
    if known is None:
        pending = mirror.root / f".{target.name}.part"
        try:
            pending.unlink(missing_ok=True)
            server.fetch(remote["name"], pending, remote["bytes"])
            if (
                pending.stat().st_size != remote["bytes"]
                or digest(pending) != remote["sha256"]
            ):
                raise ValueError("L'archive rapatriée diffère de celle du serveur.")
            # Archives written before the reserve hold their photos.
            known = target if light_photos(pending) is None else light
            os.replace(pending, known)
        finally:
            pending.unlink(missing_ok=True)
    if known == light:
        # Only photos the laptop lacks travel; the rebuilt archive is self-contained.
        reserve = mirror.root / RESERVE
        reserve.mkdir(mode=0o700, exist_ok=True)
        photos = light_photos(light)
        server.fetch_photos(
            {n: size for n, size in photos.items() if not (reserve / n).is_file()},
            reserve,
        )
        pending = mirror.root / f".{target.name}.part"
        try:
            pending.unlink(missing_ok=True)
            assemble(light, reserve, pending)
            os.replace(pending, target)
        finally:
            pending.unlink(missing_ok=True)
    verified = verify(target)
    if known == target and verified["sha256"] != remote["sha256"]:
        raise ValueError("L'archive rapatriée a changé pendant sa vérification.")
    verified["source"] = {"host": server.host, "name": remote["name"]}
    if known == light:
        verified["source"]["sha256"] = remote["sha256"]
    record_local(mirror, verified)
    for pattern, count in (
        ("oci-daily-????-??-??.zip", FULL_KEEP),
        ("oci-light-????-??-??.zip", keep),
    ):
        for old in sorted(mirror.root.glob(pattern), reverse=True)[count:]:
            old.unlink()
    tidy_reserve(
        mirror,
        mirror.root / RESERVE,
        [*mirror.root.glob("oci-light-*.zip"), *mirror.root.glob("oci-daily-*.zip")],
    )
    return verified


def pull_latest(mirror, host, *, ssh="ssh", keep=KEEP):
    return pull(mirror, Server(host, ssh), keep=keep)
