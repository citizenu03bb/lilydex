import hashlib
import os
import shutil
import subprocess
from typing import ClassVar

import pytest

from pokeprice import drive_backup, server_backup
from pokeprice.daily_backup import status
from pokeprice.inventory import Store
from pokeprice.inventory_backup import backup


@pytest.fixture
def server_archive(tmp_path):
    # The live collection exists only on the server; this one plays its part.
    archive = tmp_path / "server" / "daily-2026-10-17.zip"
    backup(Store(tmp_path / "server-inventory"), archive)
    return archive


@pytest.fixture
def server(server_archive, monkeypatch):
    class FakeServer:
        fetches = 0
        corrupt = False

        def __init__(self, host, ssh="ssh"):
            self.host = host

        def latest(self):
            return {
                "name": server_archive.name,
                "bytes": server_archive.stat().st_size,
                "sha256": hashlib.sha256(server_archive.read_bytes()).hexdigest(),
            }

        def fetch(self, name, destination, size):
            assert name == server_archive.name
            type(self).fetches += 1
            shutil.copyfile(server_archive, destination)
            if self.corrupt:
                with open(destination, "ab") as stream:
                    stream.write(b"corruption")

    monkeypatch.setattr(server_backup, "Server", FakeServer)
    return FakeServer


@pytest.fixture
def drive(tmp_path, monkeypatch):
    class FakeDrive:
        private = staticmethod(drive_backup.Drive.private)
        files: ClassVar[dict] = {}
        uploads = 0

        def __init__(self, binary, remote):
            pass

        def prepare(self):
            pass

        def metadata(self, file_id):
            if file_id == drive_backup.DRIVE_FOLDER:
                return {
                    "trashed": False,
                    "shared": False,
                    "permissions": [{"type": "user", "role": "owner"}],
                }
            return self.find(next(iter(self.files)))

        def find(self, name):
            if name not in self.files:
                return None
            return {
                "id": "file-id",
                "trashed": False,
                "shared": False,
                "permissions": [{"type": "user", "role": "owner"}],
                "parents": [drive_backup.DRIVE_FOLDER],
                "size": self.files[name].stat().st_size,
                "mimeType": "application/zip",
            }

        def transfer(self, operation, source, destination, *flags, size=0):
            if destination.startswith("gdrive:"):
                type(self).uploads += 1
                name = destination.split(":", 1)[1]
                self.files[name] = tmp_path / "drive" / name
                self.files[name].parent.mkdir(exist_ok=True)
                shutil.copyfile(source, self.files[name])
            else:
                shutil.copyfile(self.files[source.split(":", 1)[1]], destination)

    FakeDrive.files = {}
    monkeypatch.setattr(drive_backup, "Drive", FakeDrive)
    return FakeDrive


def test_drive_receives_the_server_archive_not_the_laptop_base(
    tmp_path, server, drive, server_archive
):
    laptop = tmp_path / "laptop" / "inventory"
    mirror = server_backup.Mirror(tmp_path / "laptop" / "oci-backups")
    result = drive_backup.upload_server(
        mirror, "opc@203.0.113.7", binary="fake", remote="gdrive"
    )
    expected = hashlib.sha256(server_archive.read_bytes()).hexdigest()
    assert result["sha256"] == expected
    assert result["verification"] == "download-sha256-restore"
    # The Drive name says where the archive comes from and cannot meet a laptop daily.
    assert result["remote_name"] == f"oci-daily-2026-10-17-{expected}.zip"
    assert list(drive.files) == [result["remote_name"]]
    assert (mirror.root / "oci-daily-2026-10-17.zip").exists()
    assert status(mirror)["local"]["source"] == {
        "host": "opc@203.0.113.7",
        "name": "daily-2026-10-17.zip",
    }
    assert not laptop.exists()
    assert not (tmp_path / "laptop" / "backups").exists()


def test_retry_neither_pulls_nor_uploads_twice(tmp_path, server, drive):
    mirror = server_backup.Mirror(tmp_path / "oci-backups")
    first = drive_backup.upload_server(mirror, "opc@203.0.113.7", binary="fake")
    second = drive_backup.upload_server(mirror, "opc@203.0.113.7", binary="fake")
    assert server.fetches == 1
    assert drive.uploads == 1
    assert first["file_id"] == second["file_id"]
    assert status(mirror)["last_error"] is None


def test_corrupt_pull_leaves_no_archive_and_no_success(tmp_path, server, drive):
    mirror = server_backup.Mirror(tmp_path / "oci-backups")
    server.corrupt = True
    with pytest.raises(ValueError):
        drive_backup.upload_server(mirror, "opc@203.0.113.7", binary="fake")
    assert drive.uploads == 0
    assert list(mirror.root.glob("*.zip*")) == []
    assert status(mirror)["external"] is None
    assert status(mirror)["last_error"]


def test_local_retention_keeps_only_recent_server_archives(tmp_path, server, drive):
    mirror = server_backup.Mirror(tmp_path / "oci-backups")
    for day in range(10, 15):
        (mirror.root / f"oci-daily-2026-10-{day}.zip").write_bytes(b"old")
    server_backup.pull(mirror, server("opc@203.0.113.7"), keep=3)
    assert sorted(path.name for path in mirror.root.glob("oci-daily-*.zip")) == [
        "oci-daily-2026-10-13.zip",
        "oci-daily-2026-10-14.zip",
        "oci-daily-2026-10-17.zip",
    ]


def test_mirror_refuses_a_collection_folder(tmp_path):
    Store(tmp_path / "inventory")
    with pytest.raises(ValueError):
        server_backup.Mirror(tmp_path / "inventory")


@pytest.mark.parametrize("host", ["-oProxyCommand=sh", "opc@host;rm", "host", ""])
def test_server_host_is_strict(host):
    with pytest.raises(ValueError):
        server_backup.Server(host)


def ssh_replies(monkeypatch, replies):
    commands = []

    def run(command, **options):
        commands.append(command)
        if options.get("stdout") not in (None, subprocess.PIPE):
            options["stdout"].write(b"archive bytes")
            return subprocess.CompletedProcess(command, 0, None, b"")
        return subprocess.CompletedProcess(command, 0, replies.pop(0).encode(), b"")

    monkeypatch.setattr(server_backup.subprocess, "run", run)
    return commands


def test_server_picks_latest_daily_with_its_identity(monkeypatch):
    digest = "a" * 64
    commands = ssh_replies(
        monkeypatch,
        [
            "",
            "daily-2026-10-16.zip\ndaily-2026-10-17.zip\ndaily-2026-10-15.zip\n",
            f"{digest}  /srv/pokeprice/backups/daily-2026-10-17.zip\n790906663\n",
        ],
    )
    latest = server_backup.Server("opc@203.0.113.7").latest()
    assert latest == {
        "name": "daily-2026-10-17.zip",
        "bytes": 790906663,
        "sha256": digest,
    }
    # The server backup runs first, so a late nightly job is awaited, not missed.
    assert commands[0][-1] == "sudo systemctl start pokeprice-backup.service"
    assert all("BatchMode=yes" in command for command in commands)


def test_server_ignores_unexpected_names(monkeypatch):
    ssh_replies(monkeypatch, ["", "daily-2026-10-17.zip;reboot\nnotes.txt\n"])
    with pytest.raises(ValueError):
        server_backup.Server("opc@203.0.113.7").latest()


def test_ssh_timeout_and_failure_stay_terse(monkeypatch):
    def run(command, **options):
        raise subprocess.TimeoutExpired(command, options["timeout"])

    monkeypatch.setattr(server_backup.subprocess, "run", run)
    with pytest.raises(RuntimeError) as failure:
        server_backup.Server("opc@203.0.113.7").latest()
    assert "systemctl" not in str(failure.value)
    assert failure.value.__suppress_context__


def test_cli_never_opens_the_laptop_collection(
    tmp_path, monkeypatch, capsys, server, drive
):
    from pokeprice import manage

    stale = tmp_path / "inventory"
    monkeypatch.setattr(
        "sys.argv",
        [
            "pokeprice-manage",
            "--data",
            str(stale),
            "backup-server-drive",
            "--host",
            "opc@203.0.113.7",
            "--mirror",
            str(tmp_path / "oci-backups"),
            "--rclone",
            "fake",
        ],
    )
    manage.main()
    assert not stale.exists()
    assert drive.uploads == 1
    # stdout goes to the journal, which must not name the private folder.
    assert drive_backup.DRIVE_FOLDER not in capsys.readouterr().out


def test_interrupted_pull_leaves_no_readable_part_file(tmp_path, server, monkeypatch):
    def drop(self, name, destination, size):
        destination.write_bytes(b"partial archive")
        raise RuntimeError("Connexion perdue")

    monkeypatch.setattr(server, "fetch", drop)
    mirror = server_backup.Mirror(tmp_path / "oci-backups")
    with pytest.raises(RuntimeError):
        server_backup.pull(mirror, server("opc@203.0.113.7"))
    assert mirror.root.stat().st_mode & 0o777 == 0o700
    assert not list(mirror.root.glob("*.zip*"))


def test_real_fetch_creates_a_private_part_file(tmp_path, monkeypatch):
    ssh_replies(monkeypatch, [])
    previous = os.umask(0o022)
    try:
        server_backup.Server("opc@203.0.113.7").fetch(
            "daily-2026-10-17.zip", tmp_path / "part", 13
        )
    finally:
        os.umask(previous)
    assert (tmp_path / "part").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "part").read_bytes() == b"archive bytes"
