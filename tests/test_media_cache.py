from contextlib import closing
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

import pytest

from pokeprice import manage, media_cache
from pokeprice.media_cache import prune_public_media
from pokeprice.public_media import PRESETS, cache_digest

NOW = time.time()
OLD = NOW - 31 * 86400


def collection(tmp_path):
    (tmp_path / "photos").mkdir()
    (tmp_path / "public-media").mkdir()
    with closing(sqlite3.connect(tmp_path / "collection.sqlite3")) as db:
        db.execute("CREATE TABLE copies(photo TEXT, back_photo TEXT)")
        db.execute("INSERT INTO copies VALUES('front.jpg','back.jpg')")
        db.commit()
    for name in ("front.jpg", "back.jpg", "private-original.jpg"):
        (tmp_path / "photos" / name).write_bytes((name + " synthetic source").encode())
    return tmp_path


def cached(root, name=None, *, payload=b"cache", old=True):
    path = root / "public-media" / (name or ("a" * 64 + ".jpg"))
    path.write_bytes(payload)
    if old:
        os.utime(path, (OLD, OLD))
    return path


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and not p.is_symlink() and "public-media" not in p.parts}


def test_dry_run_plans_only_old_unreferenced_managed_files(tmp_path):
    root = collection(tmp_path)
    old = cached(root)
    recent = cached(root, "b" * 64 + ".webp", old=False)
    unknown = cached(root, "notes.txt")
    before = snapshot(root)
    report = prune_public_media(root, now=NOW)
    assert report["apply"] is False
    assert report["files"] == 2 and report["ignored"] == 1
    assert report["planned"] == [{"name": old.name, "bytes": old.stat().st_size}]
    assert report["deleted_files"] == 0
    assert old.exists() and recent.exists() and unknown.exists()
    assert snapshot(root) == before
    assert "front.jpg" not in json.dumps(report)


def test_apply_protects_front_back_and_all_current_encoding_presets(tmp_path):
    root = collection(tmp_path)
    protected = []
    for name in ("front.jpg", "back.jpg"):
        payload = (root / "photos" / name).read_bytes()
        for size in PRESETS:
            for fmt, suffix in (("jpeg", ".jpg"), ("webp", ".webp")):
                protected.append(cached(root, cache_digest(payload, size, fmt) + suffix))
    obsolete = cached(root)
    before = snapshot(root)
    report = prune_public_media(root, apply=True, now=NOW)
    assert report["protected"] == len(protected)
    assert report["deleted_files"] == 1 and report["deleted_bytes"] == len(b"cache")
    assert not obsolete.exists() and all(p.exists() for p in protected)
    assert snapshot(root) == before


@pytest.mark.parametrize("max_files,max_bytes,expected", [(1, 100, 1), (10, 5, 1), (10, 4, 0)])
def test_file_and_byte_budgets_are_respected(tmp_path, max_files, max_bytes, expected):
    root = collection(tmp_path)
    for letter in "abc":
        cached(root, letter * 64 + ".jpg")
    report = prune_public_media(root, apply=True, max_files=max_files, max_bytes=max_bytes, now=NOW)
    assert report["deleted_files"] == expected
    assert report["deleted_bytes"] <= max_bytes
    assert report["budget_exhausted"] is True
    assert len(list((root / "public-media").iterdir())) == 3 - expected


def test_links_subdirectories_and_unknown_names_are_left_alone(tmp_path):
    root = collection(tmp_path)
    original = root / "photos" / "private-original.jpg"
    link = root / "public-media" / ("c" * 64 + ".jpg")
    link.symlink_to(original)
    hardlink = root / "public-media" / ("d" * 64 + ".webp")
    os.link(original, hardlink)
    directory = root / "public-media" / ("e" * 64 + ".jpg")
    directory.mkdir()
    (directory / "keep").write_text("keep")
    temporary = cached(root, "writer.tmp")
    before = snapshot(root)
    report = prune_public_media(root, apply=True, now=NOW)
    assert report["ignored"] == 4 and report["deleted_files"] == 0
    assert link.is_symlink() and hardlink.exists() and temporary.exists()
    assert (directory / "keep").read_text() == "keep"
    assert snapshot(root) == before


def test_symlink_cache_directory_is_rejected(tmp_path):
    root = collection(tmp_path)
    (root / "public-media").rmdir()
    (root / "public-media").symlink_to(root / "photos", target_is_directory=True)
    before = snapshot(root)
    with pytest.raises(OSError):
        prune_public_media(root, apply=True, now=NOW)
    assert snapshot(root) == before


def test_reference_change_aborts_before_any_deletion(monkeypatch, tmp_path):
    root = collection(tmp_path)
    candidate = cached(root)
    read = media_cache._references
    calls = 0

    def changed(database):
        nonlocal calls
        calls += 1
        if calls == 2:
            with closing(sqlite3.connect(database)) as db:
                db.execute("UPDATE copies SET photo='private-original.jpg'")
                db.commit()
        return read(database)

    monkeypatch.setattr(media_cache, "_references", changed)
    with pytest.raises(ValueError, match="références changent"):
        prune_public_media(root, apply=True, now=NOW)
    assert candidate.exists()


def test_replaced_candidate_is_not_followed_or_deleted(monkeypatch, tmp_path):
    root = collection(tmp_path)
    candidate = cached(root)
    original = root / "photos" / "private-original.jpg"
    before = original.read_bytes()
    read = media_cache._references
    calls = 0

    def replaced(database):
        nonlocal calls
        calls += 1
        if calls == 2:
            candidate.unlink()
            candidate.symlink_to(original)
        return read(database)

    monkeypatch.setattr(media_cache, "_references", replaced)
    report = prune_public_media(root, apply=True, now=NOW)
    assert report["changed_files"] == 1 and report["deleted_files"] == 0
    assert candidate.is_symlink() and original.read_bytes() == before


def test_missing_reference_fails_closed_before_deleting(tmp_path):
    root = collection(tmp_path)
    candidate = cached(root)
    (root / "photos" / "front.jpg").unlink()
    with pytest.raises(FileNotFoundError):
        prune_public_media(root, apply=True, now=NOW)
    assert candidate.exists()


def test_concurrent_cleanup_does_not_start_another_pass(tmp_path):
    root = collection(tmp_path)
    candidate = cached(root)
    descriptor = os.open(root / "public-media", os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = prune_public_media(root, apply=True, now=NOW)
    finally:
        os.close(descriptor)
    assert report["already_running"] and candidate.exists()


@pytest.mark.parametrize("options", [{"min_age_days": 29}, {"max_files": 0}, {"max_bytes": -1}])
def test_unsafe_options_are_rejected_without_writes(tmp_path, options):
    root = collection(tmp_path)
    candidate = cached(root)
    with pytest.raises(ValueError):
        prune_public_media(root, apply=True, **options)
    assert candidate.exists()


def test_missing_database_or_cache_is_never_created(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(ValueError):
        prune_public_media(missing, apply=True)
    assert not missing.exists()
    root = collection(tmp_path)
    (root / "public-media").rmdir()
    report = prune_public_media(root, apply=True)
    assert report["files"] == report["deleted_files"] == 0
    assert not (root / "public-media").exists()


def test_cli_requires_explicit_data_and_never_constructs_store(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["pokeprice-manage", "public-media-cache"])
    monkeypatch.setattr(manage, "Store", lambda *_: pytest.fail("Store must not be constructed"))
    with pytest.raises(SystemExit) as error:
        manage.main()
    assert error.value.code == 2
    assert not (tmp_path / "data").exists()
    capsys.readouterr()
    root = collection(tmp_path)
    candidate = cached(root)
    monkeypatch.setattr(sys, "argv", ["pokeprice-manage", "--data", str(root), "public-media-cache"])
    manage.main()
    report = json.loads(capsys.readouterr().out)
    assert report["apply"] is False and candidate.exists()


def test_current_cache_key_keeps_its_existing_encoding_contract():
    from hashlib import sha256
    from pokeprice.public_media import VERSION, JPEG_QUALITY, WEBP_QUALITY

    parameters = f"{VERSION}:view:jpeg:{JPEG_QUALITY}:{WEBP_QUALITY}".encode()
    assert cache_digest(b"photo", "view", "jpeg") == sha256(parameters + b"\0photo").hexdigest()


def test_read_only_wal_database_protects_recently_committed_references(tmp_path):
    root = collection(tmp_path)
    source = root / "photos" / "late.jpg"
    source.write_bytes(b"recently committed source")
    live = cached(root, cache_digest(source.read_bytes(), "view", "jpeg") + ".jpg")
    stale = cached(root)
    with closing(sqlite3.connect(root / "collection.sqlite3")) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO copies VALUES('late.jpg',NULL)")
        writer.commit()
        paths = [p for p in root.iterdir() if p.name.startswith("collection.sqlite3")]
        before = {p.name: p.read_bytes() for p in paths if not p.name.endswith("-shm")}
        try:
            for path in paths:
                path.chmod(0o444)
            report = prune_public_media(root, apply=True, now=NOW)
            assert live.exists() and not stale.exists()
            assert report["protected"] == 1
            assert {p.name: p.read_bytes() for p in paths if not p.name.endswith("-shm")} == before
        finally:
            for path in paths:
                if path.exists():
                    path.chmod(0o600)
