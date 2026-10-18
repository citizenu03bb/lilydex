import shutil
import subprocess
from datetime import date, timedelta
from typing import ClassVar

import pytest

from pokeprice import drive_backup
from pokeprice.daily_backup import _write, status
from pokeprice.inventory import Store

RealDrive = drive_backup.Drive  # The backend fixture swaps in a fake.


def metadata(file_id, size=None):
    return {
        "id": file_id,
        "trashed": False,
        "shared": False,
        "permissions": [{"type": "user", "role": "owner"}],
        "parents": [drive_backup.DRIVE_FOLDER],
        "size": size,
        "mimeType": "application/zip"
        if size is not None
        else "application/vnd.google-apps.folder",
    }


@pytest.fixture
def backend(tmp_path, monkeypatch):
    class FakeDrive:
        private = staticmethod(drive_backup.Drive.private)
        uploads = 0
        uncertain = False
        corrupt = False
        shared = False
        changed = False
        files: ClassVar[dict] = {}
        sizes: ClassVar[list] = []
        # Archives already in the Drive folder, by id, and those sent to the trash.
        others: ClassVar[dict] = {}
        trashed: ClassVar[list] = []
        trash_fails = False

        def __init__(self, binary, remote):
            pass

        def prepare(self):
            folder = metadata(drive_backup.DRIVE_FOLDER)
            folder["shared"] = self.shared
            self.private(folder)

        def metadata(self, file_id):
            if file_id == drive_backup.DRIVE_FOLDER:
                return metadata(file_id)
            return metadata(file_id, next(iter(self.files.values())).stat().st_size)

        def archives(self):
            current = [{"id": "file-id", "name": n, "parents": [drive_backup.DRIVE_FOLDER]} for n in self.files]
            return current + [
                {"id": i, "name": n, "parents": [drive_backup.DRIVE_FOLDER]}
                for i, n in self.others.items()
            ]

        def trash(self, file):
            if self.trash_fails:
                raise RuntimeError("Drive indisponible")
            type(self).trashed.append(file["name"])

        def find(self, name):
            return (
                metadata("file-id", self.files[name].stat().st_size)
                if name in self.files
                else None
            )

        def transfer(self, operation, source, destination, *flags, size=0):
            type(self).sizes.append(size)
            if destination.startswith("gdrive:"):
                type(self).uploads += 1
                name = destination.split(":", 1)[1]
                remote = tmp_path / name
                shutil.copyfile(source, remote)
                self.files[name] = remote
                if self.uncertain:
                    type(self).uncertain = False
                    raise RuntimeError("Réponse perdue après transfert")
            else:
                shutil.copyfile(self.files[source.split(":", 1)[1]], destination)
                if self.corrupt:
                    with open(destination, "ab") as stream:
                        stream.write(b"corruption")
                if self.changed:
                    local = status(store)["local"]["path"]
                    with open(local, "ab") as stream:
                        stream.write(b"new local bytes")

    store = Store(tmp_path / "inventory")
    monkeypatch.setattr(drive_backup, "Drive", FakeDrive)
    drive_backup.create_key()
    return store, FakeDrive


def test_upload_restores_and_retry_has_no_duplicate(backend):
    store, drive = backend
    first = drive_backup.upload_daily(store, binary="fake")
    second = drive_backup.upload_daily(store, binary="fake")
    assert drive.uploads == 1
    assert first["file_id"] == second["file_id"]
    assert first["verification"] == "download-decrypt-sha256-restore"
    assert status(store)["last_error"] is None


def test_upload_and_check_download_announce_the_archive_size(backend):
    store, drive = backend
    result = drive_backup.upload_daily(store, binary="fake")
    assert drive.sizes == [result["bytes"]] * 2


def test_rclone_deadline_grows_with_archive_size(monkeypatch):
    seen = []

    def run(command, **options):
        seen.append(options["timeout"])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(drive_backup.subprocess, "run", run)
    rclone = RealDrive("rclone", "gdrive")
    for size in (1_000, 790_906_664, 50_000_000_000):
        rclone.transfer("copyto", "source.zip", "gdrive:target.zip", size=size)
    small, server_daily, huge = seen
    assert small == drive_backup.RCLONE_FLOOR == 240
    # The 17 October archive must fit even on a slow 2 Mbit/s home uplink.
    assert server_daily >= 790_906_664 / 250_000
    assert huge == drive_backup.RCLONE_CEILING


def test_rclone_timeout_keeps_the_drive_folder_out_of_the_error(monkeypatch):
    def run(command, **options):
        raise subprocess.TimeoutExpired(command, options["timeout"])

    monkeypatch.setattr(drive_backup.subprocess, "run", run)
    with pytest.raises(RuntimeError) as failure:
        RealDrive("rclone", "gdrive").transfer("lsjson", "gdrive:")
    assert drive_backup.DRIVE_FOLDER not in str(failure.value)
    assert failure.value.__suppress_context__


def archive_names(days, today=date(2026, 10, 17)):
    return [f"daily-{today - timedelta(days=n)}-{'a' * 64}.zip" for n in range(days)]


def test_retention_keeps_a_week_daily_then_weeks_then_months():
    names = archive_names(400) + ["collection-avant-amelioration.zip", "notes.txt"]
    kept = drive_backup.retained(names)
    days = sorted(date.fromisoformat(n[6:16]) for n in kept)
    assert set(archive_names(7)) <= kept  # the last seven days, one by one
    weeks = {d.isocalendar()[:2] for d in days}
    months = {(d.year, d.month) for d in days}
    assert len(weeks) >= 8 and len(months) == 12
    assert days[0] > date(2025, 10, 17) and len(kept) <= 7 + 8 + 12
    # Only archive names are ever candidates; anything else is left alone.
    assert drive_backup.retained(["collection-avant-amelioration.zip"]) == set()


def test_successful_upload_trashes_archives_beyond_retention(backend):
    store, drive = backend
    old = archive_names(60, today=date(2026, 10, 16))
    drive.others.update({f"old-{i}": n for i, n in enumerate(old)})
    drive.others["keep-me"] = "collection-avant-amelioration.zip"
    result = drive_backup.upload_daily(store, binary="fake")
    kept = drive_backup.retained([*old, result["remote_name"]])
    assert set(drive.trashed) == set(old) - kept and drive.trashed
    assert result["remote_name"] not in drive.trashed
    assert "collection-avant-amelioration.zip" not in drive.trashed
    assert result["retention"] == {"trashed": len(drive.trashed)}


def test_failed_retention_does_not_undo_a_verified_copy(backend):
    store, drive = backend
    drive.others.update({f"old-{i}": n for i, n in enumerate(archive_names(400))})
    drive.trash_fails = True
    result = drive_backup.upload_daily(store, binary="fake")
    assert result["verification"] == "download-decrypt-sha256-restore"
    assert "error" in result["retention"] and status(store)["last_error"] is None


def test_uncertain_upload_is_found_before_retry(backend):
    store, drive = backend
    drive.uncertain = True
    with pytest.raises(RuntimeError):
        drive_backup.upload_daily(store, binary="fake")
    assert status(store)["last_error"]
    drive_backup.upload_daily(store, binary="fake")
    assert drive.uploads == 1


@pytest.mark.parametrize("failure", ["corrupt", "changed"])
def test_corrupt_download_or_changed_local_does_not_mark_success(backend, failure):
    store, drive = backend
    drive_backup.upload_daily(store, binary="fake")
    previous = status(store)["external"]
    setattr(drive, failure, True)
    with pytest.raises(ValueError):
        drive_backup.upload_daily(store, binary="fake")
    assert status(store)["external"] == previous
    assert status(store)["last_error"]


def test_shared_folder_blocks_upload(backend):
    store, drive = backend
    drive.shared = True
    with pytest.raises(ValueError):
        drive_backup.upload_daily(store, binary="fake")
    assert drive.uploads == 0
    assert status(store)["external"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"shared": True},
        {"trashed": True},
        {"permissions": []},
        {"permissions": [{"type": "anyone", "role": "reader"}]},
        {
            "permissions": [
                {"type": "user", "role": "owner"},
                {"type": "user", "role": "reader"},
            ]
        },
    ],
)
def test_private_check_requires_owner_only(change):
    with pytest.raises(ValueError):
        drive_backup.Drive.private({**metadata("folder"), **change})


def test_drive_only_receives_the_archive_encrypted(backend):
    store, drive = backend
    result = drive_backup.upload_daily(store, binary="fake")
    sent = drive.files[result["remote_name"]].read_bytes()
    assert result["remote_name"].endswith(".zip.age")
    assert sent.startswith(b"age-encryption.org/v1") and b"PK\x03\x04" not in sent[:4096]


def test_an_old_plain_copy_is_not_reused_once_encryption_is_on(backend):
    store, drive = backend
    first = drive_backup.upload_daily(store, binary="fake")
    data = status(store)
    data["external"]["remote_name"] = first["remote_name"].removesuffix(".age")
    _write(store, data)
    again = drive_backup.upload_daily(store, binary="fake")
    assert again["remote_name"] == first["remote_name"] and drive.uploads == 1


def test_no_upload_without_the_key_or_with_a_readable_key(backend):
    store, drive = backend
    key = drive_backup.key_path()
    key.chmod(0o644)
    with pytest.raises(ValueError):
        drive_backup.upload_daily(store, binary="fake")
    key.unlink()
    with pytest.raises(RuntimeError, match="backup-key"):
        drive_backup.upload_daily(store, binary="fake")
    assert drive.uploads == 0 and status(store)["last_error"]


def test_the_key_is_created_once_and_never_shown(tmp_path):
    first = drive_backup.create_key()
    again = drive_backup.create_key()
    assert first["created"] and not again["created"]
    assert first["recipient"] == again["recipient"] and first["recipient"].startswith("age1")
    assert "AGE-SECRET-KEY" not in str(first)
    assert drive_backup.key_path().stat().st_mode & 0o777 == 0o600


def test_retention_counts_encrypted_and_former_plain_copies():
    names = [n + ".age" for n in archive_names(30)] + archive_names(30, today=date(2026, 9, 17))
    kept = drive_backup.retained(names)
    assert {n for n in names[:7]} <= kept and kept <= set(names)
