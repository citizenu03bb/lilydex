"""Photos kept once in a reserve, light v2 archives and self-contained rebuilds."""

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import zipfile

import pytest
from PIL import Image
from test_agent_control import add_copy
from test_drive_backup import backend  # noqa: F401  (fixture)

from pokeprice import daily_backup, drive_backup, inventory_backup, server_backup
from pokeprice.inventory import Store
from pokeprice.inventory_backup import (
    assemble,
    backup,
    photo_names,
    prune_reserve,
    restore_backup,
)


def picture(color):
    output = io.BytesIO()
    Image.new("RGB", (30, 40), color).save(output, "JPEG")
    return output.getvalue()


def collection(root, colors=("red", "blue")):
    store = Store(root)
    with store.connect(write=True) as db:
        db.execute("INSERT INTO albums VALUES('a','Album A')")
    for n, color in enumerate(colors, 1):
        card = add_copy(store, n)
        name = store.save_photo(picture(color))
        store.patch(card["id"], {"photo": name}, card["version"], "owner", "Photo")
    return store


def manifest(path):
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read("manifest.json")), archive.namelist()


def test_light_archive_lists_photos_and_restores_from_the_reserve(tmp_path):
    store = collection(tmp_path / "inventory")
    reserve = tmp_path / "backups" / "photos"
    archive = tmp_path / "backups" / "lot.zip"
    backup(store, archive, reserve=reserve)
    data, names = manifest(archive)
    assert data["format"] == "pokeprice-inventory-v2"
    assert not any(name.startswith("photos/") for name in names)
    live = sorted(p.name for p in store.photos.glob("*.jpg"))
    assert sorted(data["photos"]) == live
    # Hard links: the reserve costs no room on the same disk.
    for name in live:
        assert os.path.samefile(reserve / name, store.photos / name)
    summary = restore_backup(archive, tmp_path / "restored")
    assert summary["copies"] == 2
    for name in live:
        assert (tmp_path / "restored" / "photos" / name).read_bytes() == (
            store.photos / name
        ).read_bytes()


def test_v1_archives_still_restore_without_a_reserve(tmp_path):
    store = collection(tmp_path / "inventory")
    archive = tmp_path / "elsewhere" / "full.zip"
    backup(store, archive)
    data, names = manifest(archive)
    assert data["format"] == "pokeprice-inventory-v1"
    assert sum(name.startswith("photos/") for name in names) == 2
    assert restore_backup(archive, tmp_path / "restored")["copies"] == 2


def test_light_restore_refuses_a_missing_or_altered_reserve(tmp_path):
    store = collection(tmp_path / "inventory")
    reserve = tmp_path / "backups" / "photos"
    archive = tmp_path / "backups" / "lot.zip"
    backup(store, archive, reserve=reserve)
    moved = tmp_path / "moved.zip"
    shutil.copyfile(archive, moved)
    with pytest.raises(ValueError, match="--photos"):
        restore_backup(moved, tmp_path / "a")
    # An explicit reserve works from anywhere.
    assert restore_backup(moved, tmp_path / "b", reserve)["copies"] == 2
    victim = sorted(reserve.glob("*.jpg"))[0]
    copy = tmp_path / "copy"
    shutil.copytree(reserve, copy)
    (copy / victim.name).write_bytes(b"altered")
    with pytest.raises(ValueError, match="altérée"):
        restore_backup(archive, tmp_path / "c", copy)
    (copy / victim.name).unlink()
    with pytest.raises(ValueError, match="absente"):
        restore_backup(archive, tmp_path / "d", copy)
    assert not any((tmp_path / name).exists() for name in "acd")


def test_rebuilt_archive_is_self_contained_and_deterministic(tmp_path):
    store = collection(tmp_path / "inventory")
    reserve = tmp_path / "backups" / "photos"
    light = tmp_path / "backups" / "lot.zip"
    backup(store, light, reserve=reserve)
    assemble(light, reserve, tmp_path / "one.zip")
    assemble(light, reserve, tmp_path / "two.zip")
    assert (tmp_path / "one.zip").read_bytes() == (tmp_path / "two.zip").read_bytes()
    full = tmp_path / "alone" / "full.zip"
    full.parent.mkdir()
    shutil.move(tmp_path / "one.zip", full)
    shutil.rmtree(reserve)
    data, _ = manifest(full)
    assert data["format"] == "pokeprice-inventory-v1"
    assert restore_backup(full, tmp_path / "restored")["copies"] == 2


def test_rebuild_refuses_an_altered_reserve_photo(tmp_path):
    store = collection(tmp_path / "inventory")
    reserve = tmp_path / "reserve"
    light = tmp_path / "lot.zip"
    backup(store, light, reserve=reserve)
    victim = sorted(reserve.glob("*.jpg"))[0]
    victim.unlink()
    victim.write_bytes(b"altered")
    with pytest.raises(ValueError, match="altérée"):
        assemble(light, reserve, tmp_path / "full.zip")
    assert not (tmp_path / "full.zip").exists()


def test_reserve_pruning_keeps_what_archives_or_the_store_need(tmp_path):
    store = collection(tmp_path / "inventory")
    folder = tmp_path / "backups"
    backup(store, folder / "lot.zip", reserve=folder / "photos")
    orphan = folder / "photos" / (hashlib.sha256(b"gone").hexdigest() + ".jpg")
    orphan.write_bytes(b"gone")
    kept = photo_names(folder / "lot.zip")
    (folder / "broken.zip").write_bytes(b"not a zip")
    with pytest.raises(zipfile.BadZipFile):
        prune_reserve(folder / "photos", folder.glob("*.zip"))
    assert orphan.exists()
    (folder / "broken.zip").unlink()
    assert prune_reserve(folder / "photos", folder.glob("*.zip")) == [orphan.name]
    assert {p.name for p in (folder / "photos").glob("*.jpg")} == kept
    # Without any archive, live photos still stay.
    (folder / "lot.zip").unlink()
    live = [p.name for p in store.photos.glob("*.jpg")]
    assert prune_reserve(folder / "photos", [], keep=live) == []


def test_reserve_copies_when_a_hard_link_is_impossible(tmp_path, monkeypatch):
    store = collection(tmp_path / "inventory")

    def refuse(source, target):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(inventory_backup.os, "link", refuse)
    backup(store, tmp_path / "lot.zip", reserve=tmp_path / "photos")
    for photo in store.photos.glob("*.jpg"):
        copy = tmp_path / "photos" / photo.name
        assert not os.path.samefile(copy, photo)
        assert copy.read_bytes() == photo.read_bytes()
        assert copy.stat().st_mode & 0o777 == 0o600
    assert not list((tmp_path / "photos").glob(".*"))


def test_daily_archive_is_light_and_checked_against_the_reserve(tmp_path):
    store = collection(tmp_path / "inventory")
    first = daily_backup.daily(store)
    data, names = manifest(first["path"])
    assert data["format"] == "pokeprice-inventory-v2"
    assert len(data["photos"]) == 2
    assert first["copies"] == 2
    reserve = tmp_path / "backups" / "photos"
    assert len(list(reserve.glob("*.jpg"))) == 2
    # A rerun checks today's archive again through the reserve beside it.
    assert daily_backup.daily(store)["sha256"] == first["sha256"]


@pytest.fixture
def light_server(tmp_path, monkeypatch):
    """A server whose nightly archive is light, with its reserve of photos."""
    store = collection(tmp_path / "server" / "inventory")
    folder = tmp_path / "server" / "backups"

    class FakeServer:
        fetched: list = []
        day = "2026-11-04"

        def __init__(self, host, ssh="ssh"):
            self.host = host

        @property
        def archive(self):
            return folder / f"daily-{self.day}.zip"

        def latest(self):
            if not self.archive.exists():
                backup(store, self.archive, reserve=folder / "photos")
            return {
                "name": self.archive.name,
                "bytes": self.archive.stat().st_size,
                "sha256": hashlib.sha256(self.archive.read_bytes()).hexdigest(),
            }

        def fetch(self, name, destination, size):
            shutil.copyfile(folder / name, destination)

        def fetch_photos(self, photos, destination):
            type(self).fetched.append(sorted(photos))
            for name in photos:
                shutil.copyfile(folder / "photos" / name, destination / name)

    FakeServer.fetched = []
    monkeypatch.setattr(server_backup, "Server", FakeServer)
    FakeServer.store = store
    return FakeServer


def test_pull_fetches_only_new_photos_and_rebuilds_a_full_archive(
    tmp_path, light_server
):
    mirror = server_backup.Mirror(tmp_path / "laptop")
    first = server_backup.pull(mirror, light_server("opc@203.0.113.7"))
    assert [len(batch) for batch in light_server.fetched] == [2]
    full = mirror.root / "oci-daily-2026-11-04.zip"
    assert first["path"] == str(full)
    assert manifest(full)[0]["format"] == "pokeprice-inventory-v1"
    light_sha = hashlib.sha256(
        (mirror.root / "oci-light-2026-11-04.zip").read_bytes()
    ).hexdigest()
    assert first["source"]["sha256"] == light_sha
    # A retry fetches nothing again and rebuilds the same bytes.
    again = server_backup.pull(mirror, light_server("opc@203.0.113.7"))
    assert again["sha256"] == first["sha256"]
    assert [len(batch) for batch in light_server.fetched] == [2, 0]
    # The next night only the new photo travels.
    light_server.store.save_photo(picture("green"))
    light_server.day = "2026-11-05"
    server_backup.pull(mirror, light_server("opc@203.0.113.7"))
    assert [len(batch) for batch in light_server.fetched] == [2, 0, 1]
    assert sorted(p.name for p in mirror.root.glob("oci-*.zip")) == [
        "oci-daily-2026-11-05.zip",
        "oci-light-2026-11-04.zip",
        "oci-light-2026-11-05.zip",
    ]
    assert len(list((mirror.root / "photos").glob("*.jpg"))) == 3
    shutil.rmtree(mirror.root / "photos")
    restored = restore_backup(
        mirror.root / "oci-daily-2026-11-05.zip", tmp_path / "restored"
    )
    assert restored["copies"] == 2


def test_drive_receives_the_rebuilt_self_contained_archive(
    tmp_path, light_server, monkeypatch
):
    sent = {}

    class FakeDrive:
        private = staticmethod(drive_backup.Drive.private)

        def __init__(self, binary, remote):
            pass

        def prepare(self):
            pass

        def metadata(self, file_id):
            return {
                "trashed": False,
                "shared": False,
                "permissions": [{"type": "user", "role": "owner"}],
            }

        def archives(self):
            return []

        def find(self, name):
            if name not in sent:
                return None
            return {
                **self.metadata(name),
                "id": "file-id",
                "parents": [drive_backup.DRIVE_FOLDER],
                "size": sent[name].stat().st_size,
                "mimeType": "application/octet-stream",
            }

        def transfer(self, operation, source, destination, *flags, size=0):
            if destination.startswith("gdrive:"):
                name = destination.split(":", 1)[1]
                sent[name] = tmp_path / "drive" / name
                sent[name].parent.mkdir(exist_ok=True)
                shutil.copyfile(source, sent[name])
            else:
                shutil.copyfile(sent[source.split(":", 1)[1]], destination)

    monkeypatch.setattr(drive_backup, "Drive", FakeDrive)
    drive_backup.create_key()
    mirror = server_backup.Mirror(tmp_path / "laptop")
    result = drive_backup.upload_server(mirror, "opc@203.0.113.7", binary="fake")
    assert result["verification"] == "download-decrypt-sha256-restore"
    assert result["remote_name"].startswith("oci-daily-2026-11-04-")
    # The encrypted copy decrypts to an archive that needs no reserve.
    plain = tmp_path / "plain.zip"
    import pyrage

    pyrage.decrypt_file(
        str(sent[result["remote_name"]]), str(plain), [drive_backup.load_key()]
    )
    assert manifest(plain)[0]["format"] == "pokeprice-inventory-v1"
    assert restore_backup(plain, tmp_path / "restored")["copies"] == 2


def tar_of(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as tar:
        for name, body in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    stream.seek(0)
    return stream


def test_received_photos_are_checked_by_their_name(tmp_path):
    body = picture("red")
    name = hashlib.sha256(body).hexdigest() + ".jpg"
    server_backup.receive_photos(tar_of({name: body}), {name: len(body)}, tmp_path)
    assert (tmp_path / name).read_bytes() == body
    assert (tmp_path / name).stat().st_mode & 0o777 == 0o600
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError, match="altérée"):
        server_backup.receive_photos(
            tar_of({name: b"x" * len(body)}), {name: len(body)}, other
        )
    with pytest.raises(ValueError, match="inattendue"):
        server_backup.receive_photos(
            tar_of({"../evil.jpg": body}), {name: len(body)}, other
        )
    with pytest.raises(ValueError, match="manquantes"):
        server_backup.receive_photos(tar_of({}), {name: len(body)}, other)
    assert not list(other.iterdir())


def test_photo_names_travel_on_stdin_never_on_the_command_line(tmp_path, monkeypatch):
    body = picture("red")
    name = hashlib.sha256(body).hexdigest() + ".jpg"
    calls = []

    def run(command, **options):
        calls.append((command, options["input"]))
        options["stdout"].write(tar_of({name: body}).read())
        return subprocess.CompletedProcess(command, 0, None, b"")

    monkeypatch.setattr(server_backup.subprocess, "run", run)
    server_backup.Server("opc@203.0.113.7").fetch_photos({name: len(body)}, tmp_path)
    command, stdin = calls[0]
    assert command[-1] == (
        "sudo tar -C /srv/pokeprice/backups/photos -cf - --files-from=-"
    )
    assert stdin == (name + "\n").encode()
    assert (tmp_path / name).read_bytes() == body
    with pytest.raises(ValueError):
        server_backup.Server("opc@203.0.113.7").fetch_photos(
            {"x; reboot": 1}, tmp_path
        )


def test_manual_backup_is_light_in_the_backups_folder_only(tmp_path, monkeypatch):
    from pokeprice import manage

    collection(tmp_path / "inventory")
    for output in ([], [str(tmp_path / "out" / "full.zip")]):
        monkeypatch.setattr(
            "sys.argv",
            ["pokeprice-manage", "--data", str(tmp_path / "inventory"), "backup"]
            + output,
        )
        manage.main()
    (light,) = (tmp_path / "backups").glob("collection-*.zip")
    assert manifest(light)[0]["format"] == "pokeprice-inventory-v2"
    assert manifest(tmp_path / "out" / "full.zip")[0]["format"] == (
        "pokeprice-inventory-v1"
    )


def test_single_machine_drive_copy_is_the_self_contained_rebuild(backend):
    store, drive = backend
    for color in ("red", "blue"):
        store.save_photo(picture(color))
    result = drive_backup.upload_daily(store, binary="fake")
    assert status_format(drive.files[result["remote_name"]]) == "pokeprice-inventory-v1"
    again = drive_backup.upload_daily(store, binary="fake")
    assert drive.uploads == 1 and again["file_id"] == result["file_id"]


def status_format(sealed):
    import pyrage

    plain = sealed.with_suffix(".plain")
    pyrage.decrypt_file(str(sealed), str(plain), [drive_backup.load_key()])
    return manifest(plain)[0]["format"]
