"""Occasional backups are kept a while, and a backup never fills the disk."""

import os
import time
from collections import namedtuple

import pytest

from pokeprice import daily_backup, inventory_backup
from pokeprice.daily_backup import prune_occasional
from pokeprice.inventory import Store

DAY = 86400


def touch(folder, name, age_days, now):
    path = folder / name
    path.write_bytes(b"x")
    os.utime(path, (now - age_days * DAY, now - age_days * DAY))
    return path


def test_occasional_backups_keep_the_latest_two_and_three_days(tmp_path):
    now = 1_800_000_000
    for i, age in enumerate((1, 2.5, 30, 40, 50)):
        touch(tmp_path, f"before-lot-{i}.zip", age, now)
    touch(tmp_path, "recent-extra.zip", 0.5, now)
    touch(tmp_path, "daily-2026-01-01.zip", 300, now)
    for i in range(7):
        touch(tmp_path, f"before-schema{i}.sqlite3", i, now)
        touch(tmp_path, f"before-move-batch-{i}.sqlite3", i, now)
        touch(tmp_path, f"before-photo-batch-{i}.sqlite3", i, now)
    removed = prune_occasional(tmp_path, now)
    left = sorted(p.name for p in tmp_path.iterdir())
    # Latest two (half a day, 1 day) stay; beyond them, 2.5 days stays and older goes.
    assert {"before-lot-0.zip", "recent-extra.zip", "before-lot-1.zip"} <= set(left)
    assert "before-lot-2.zip" not in left and "before-lot-4.zip" not in left
    assert "daily-2026-01-01.zip" in left  # Daily archives have their own rule.
    assert sum(n.startswith("before-schema") for n in left) == 5
    assert sum(n.startswith("before-move-batch") for n in left) == 5
    assert sum(n.startswith("before-photo-batch") for n in left) == 5
    assert set(removed) == {"before-lot-2.zip", "before-lot-3.zip", "before-lot-4.zip",
                            "before-schema5.sqlite3", "before-schema6.sqlite3",
                            "before-move-batch-5.sqlite3", "before-move-batch-6.sqlite3",
                            "before-photo-batch-5.sqlite3", "before-photo-batch-6.sqlite3"}


def test_a_backup_is_refused_before_writing_when_the_disk_is_short(tmp_path, monkeypatch):
    store = Store(tmp_path / "inventory")
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(inventory_backup.shutil, "disk_usage", lambda _: usage(10, 9, 1024))
    target = tmp_path / "backups" / "lot.zip"
    with pytest.raises(OSError, match="Espace disque insuffisant"):
        inventory_backup.backup(store, target)
    assert not target.exists()


def test_old_archives_make_room_before_the_daily_archive_is_written(tmp_path, monkeypatch):
    store = Store(tmp_path / "inventory")
    folder = tmp_path / "backups"
    folder.mkdir()
    for day in range(1, 6):
        (folder / f"daily-2000-01-{day:02d}.zip").touch()
    now = time.time()
    touch(folder, "before-lot.zip", 30, now)
    touch(folder, "before-lot-2.zip", 20, now)
    touch(folder, "before-lot-3.zip", 10, now)
    seen = {}

    def write(_store, destination):
        seen["left"] = sorted(p.name for p in folder.iterdir() if p.is_file())
        raise OSError("Espace disque insuffisant")

    monkeypatch.setattr(daily_backup, "backup", write)
    with pytest.raises(OSError):
        daily_backup.daily(store)
    # One slot stays free for the new archive; the oldest occasional one is gone.
    assert seen["left"] == [
        "before-lot-2.zip",
        "before-lot-3.zip",
        "daily-2000-01-04.zip",
        "daily-2000-01-05.zip",
    ]
