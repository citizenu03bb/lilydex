"""Read-only collection inspection and bounded deletion of obsolete derivatives.

Only regular, single-link files named by PublicMedia may be removed. Sources,
the collection database and unknown cache entries are never modified.
"""

from contextlib import closing
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

from .public_media import PRESETS, cache_digest

MANAGED = re.compile(r"[0-9a-f]{64}\.(?:jpg|webp)\Z")
DAY = 86400


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _references(database):
    # Do not construct Store: maintenance must not initialize or migrate a base.
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute("SELECT photo, back_photo FROM copies").fetchall()
    # Protect every current copy, including offline, reserved or deleted ones.
    return {name for row in rows for name in row if name}


def _protected(root, references):
    photos = root / "photos"
    if photos.is_symlink():
        raise ValueError("Le dossier photos doit être un dossier réel.")
    protected = set()
    identities = {}
    for name in sorted(references):
        if not isinstance(name, str) or Path(name).name != name or name in (".", ".."):
            raise ValueError("Référence de photo invalide : nettoyage annulé.")
        source = photos / name
        # Refuse ambiguous/missing references instead of guessing which keys to retain.
        with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("Source de photo non régulière : nettoyage annulé.")
            payload = stream.read()
            after = os.fstat(stream.fileno())
        if _identity(before) != _identity(after) or _identity(after) != _identity(source.lstat()):
            raise ValueError("Une source change pendant l'analyse : nettoyage annulé.")
        identities[name] = _identity(after)
        for size in PRESETS:
            for format, suffix in (("jpeg", ".jpg"), ("webp", ".webp")):
                protected.add(cache_digest(payload, size, format) + suffix)
    return protected, identities


def prune_public_media(directory, *, apply=False, min_age_days=30,
                       max_files=200, max_bytes=64 * 1024 * 1024, now=None):
    """Report first; --apply removes only old, unreferenced, unchanged derivatives.

    The age floor cannot be disabled. Limits bound each invocation; another run
    can remove the remaining obsolete entries. No database writes or migrations.
    """
    if min_age_days < 30 or max_files < 1 or max_bytes < 1:
        raise ValueError("Conservez au moins 30 jours et des plafonds strictement positifs.")
    root = Path(directory).resolve()
    database = root / "collection.sqlite3"
    if database.is_symlink() or not database.is_file():
        raise ValueError("Une base existante et non symbolique est requise.")
    cache = root / "public-media"
    result = {"root": str(cache), "apply": apply, "min_age_days": min_age_days,
              "max_files": max_files, "max_bytes": max_bytes,
              "files": 0, "bytes": 0, "ignored": 0, "protected": 0,
              "eligible_files": 0, "eligible_bytes": 0, "planned": [],
              "deleted_files": 0, "deleted_bytes": 0, "changed_files": 0,
              "already_running": False, "budget_exhausted": False}
    try:
        descriptor = os.open(cache, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return result  # Do not create a cache just to maintain it.
    try:
        if apply:
            import fcntl

            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                result["already_running"] = True
                return result
        cutoff = (time.time() if now is None else now) - min_age_days * DAY
        old = []
        for name in os.listdir(descriptor):
            try:
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not MANAGED.fullmatch(name) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                result["ignored"] += 1
                continue
            result["files"] += 1
            result["bytes"] += info.st_size
            if info.st_mtime <= cutoff:
                old.append((name, info))
        if not old:
            return result  # Most daily passes avoid opening or hashing the collection.
        references = _references(database)
        protected, identities = _protected(root, references)
        result["protected"] = sum(name in protected for name, _ in old)
        eligible = sorted(((name, info) for name, info in old if name not in protected),
                          key=lambda entry: (entry[1].st_mtime_ns, entry[0]))
        result["eligible_files"] = len(eligible)
        result["eligible_bytes"] = sum(info.st_size for _, info in eligible)
        selected = []
        planned_bytes = 0
        for name, info in eligible:
            if len(selected) >= max_files or planned_bytes + info.st_size > max_bytes:
                continue
            selected.append((name, info))
            planned_bytes += info.st_size
        result["planned"] = [{"name": name, "bytes": info.st_size} for name, info in selected]
        result["budget_exhausted"] = len(selected) < len(eligible)
        if not apply or not selected:
            return result
        # Re-read live references and source identities immediately before applying.
        if _references(database) != references or any(
            _identity((root / "photos" / name).lstat()) != identity
            for name, identity in identities.items()
        ):
            raise ValueError("Les références changent pendant l'analyse : nettoyage annulé.")
        for name, original in selected:
            try:
                current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                        or _identity(current) != _identity(original)):
                    result["changed_files"] += 1
                    continue
                # Relative unlink never follows a link or a replaced parent path.
                os.unlink(name, dir_fd=descriptor)
                result["deleted_files"] += 1
                result["deleted_bytes"] += current.st_size
            except FileNotFoundError:
                result["changed_files"] += 1
        return result
    finally:
        os.close(descriptor)
