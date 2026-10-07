import shutil
from typing import ClassVar

import pytest

from pokeprice import drive_backup
from pokeprice.daily_backup import status
from pokeprice.inventory import Store


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

        def find(self, name):
            return (
                metadata("file-id", self.files[name].stat().st_size)
                if name in self.files
                else None
            )

        def transfer(self, operation, source, destination, *flags):
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
    return store, FakeDrive


def test_upload_restores_and_retry_has_no_duplicate(backend):
    store, drive = backend
    first = drive_backup.upload_daily(store, binary="fake")
    second = drive_backup.upload_daily(store, binary="fake")
    assert drive.uploads == 1
    assert first["file_id"] == second["file_id"]
    assert first["verification"] == "download-sha256-restore"
    assert status(store)["last_error"] is None


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
