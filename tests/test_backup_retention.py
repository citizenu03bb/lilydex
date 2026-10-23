"""Occasional backups are kept a while, and a backup never fills the disk."""

import os
from collections import namedtuple

import pytest

from pokeprice import inventory_backup
from pokeprice.daily_backup import prune_occasional
from pokeprice.inventory import Store

DAY = 86400


def touch(folder, name, age_days, now):
    path = folder / name
    path.write_bytes(b"x")
    os.utime(path, (now - age_days * DAY, now - age_days * DAY))
    return path


def test_occasional_backups_keep_the_latest_three_and_two_weeks(tmp_path):
    now = 1_800_000_000
    for i, age in enumerate((1, 20, 30, 40, 50)):
        touch(tmp_path, f"before-lot-{i}.zip", age, now)
    touch(tmp_path, "recent-extra.zip", 2, now)
    touch(tmp_path, "daily-2026-01-01.zip", 300, now)
    for i in range(7):
        touch(tmp_path, f"before-schema{i}.sqlite3", i, now)
    removed = prune_occasional(tmp_path, now)
    left = sorted(p.name for p in tmp_path.iterdir())
    # Latest three (1, 2 and 20 days) stay; older than 14 days beyond them go.
    assert {"before-lot-0.zip", "recent-extra.zip", "before-lot-1.zip"} <= set(left)
    assert "before-lot-2.zip" not in left and "before-lot-4.zip" not in left
    assert "daily-2026-01-01.zip" in left  # Daily archives have their own rule.
    assert sum(n.startswith("before-schema") for n in left) == 5
    assert set(removed) == {"before-lot-2.zip", "before-lot-3.zip", "before-lot-4.zip",
                            "before-schema5.sqlite3", "before-schema6.sqlite3"}


def test_a_backup_is_refused_before_writing_when_the_disk_is_short(tmp_path, monkeypatch):
    store = Store(tmp_path / "inventory")
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(inventory_backup.shutil, "disk_usage", lambda _: usage(10, 9, 1024))
    target = tmp_path / "backups" / "lot.zip"
    with pytest.raises(OSError, match="Espace disque insuffisant"):
        inventory_backup.backup(store, target)
    assert not target.exists()
