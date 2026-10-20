"""Project one backup album into a disposable store, without its real accounts."""

import hashlib
import json
import os
import re
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

from pokeprice.agent import AgentService
from pokeprice.inventory import Store
from pokeprice.webapp import UserCreate, add_user


def private_write(path, body):
    path = Path(path)
    with open(path, "xb", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        stream.write(body)


def fingerprints(store):
    with store.connect() as db:
        names = [
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        result = {}
        for name in names:
            digest = hashlib.sha256()
            count = 0
            for row in db.execute('SELECT * FROM "' + name + '" ORDER BY rowid'):
                digest.update(
                    json.dumps(
                        tuple(row), ensure_ascii=False, separators=(",", ":")
                    ).encode()
                )
                digest.update(b"\n")
                count += 1
            result[name] = {"rows": count, "sha256": digest.hexdigest()}
        return result


def priority_cards(facts, maximum=5):
    eligible = [
        c
        for c in facts
        if c["stock_state"] == "available"
        and c["has_front"]
        and c["valuation"]["needs_review"]
        and c["valuation"]["risk_cents"] is not None
    ]
    eligible.sort(
        key=lambda c: (-c["valuation"]["risk_cents"], c["page"], c["position"], c["id"])
    )
    chosen, seen = [], set()
    for card in eligible:
        if card["name"] not in seen:
            chosen.append(card)
            seen.add(card["name"])
            if len(chosen) == maximum:
                break
    return chosen


def projected_album(archive, expected_sha256, album_id, private_root):
    archive, private_root = Path(archive), Path(private_root)
    with archive.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected_sha256:
        raise ValueError("L'archive ne correspond pas à l'empreinte fixée.")
    source_root = private_root / "source"
    source_root.mkdir(mode=0o700)
    destination = Store(private_root / "album")
    with zipfile.ZipFile(archive) as backup:
        manifest = json.loads(backup.read("manifest.json"))

        def verified_body(name):
            body = backup.read(name)
            if hashlib.sha256(body).hexdigest() != manifest["files"][name]:
                raise ValueError("Somme de contrôle invalide dans l'archive.")
            return body

        private_write(
            source_root / "collection.sqlite3", verified_body("collection.sqlite3")
        )
        # Migrate a temporary database, never the archived or running collection.
        source_store = Store(source_root)
        with (
            closing(sqlite3.connect(source_root / "collection.sqlite3")) as source,
            destination.connect(write=True) as target,
        ):
            source.row_factory = sqlite3.Row
            album = source.execute(
                "SELECT * FROM albums WHERE id=?", (album_id,)
            ).fetchone()
            if not album:
                raise ValueError("Album absent de l'archive.")
            copies = [
                dict(r)
                for r in source.execute(
                    "SELECT * FROM copies WHERE album_id=? AND deleted_at=''",
                    (album_id,),
                )
            ]
            if not copies:
                raise ValueError("Album vide.")
            ids = {c["id"] for c in copies}
            editions = {c["edition_id"] for c in copies}
            catalogs = {c["catalog_id"] for c in copies}

            def insert(table, rows):
                columns = [
                    r[1] for r in target.execute("PRAGMA table_info(" + table + ")")
                ]
                for row in rows:
                    keys = [k for k in columns if k in row]
                    target.execute(
                        'INSERT OR REPLACE INTO "'
                        + table
                        + '" ('
                        + ",".join(keys)
                        + ") VALUES("
                        + ",".join("?" for _ in keys)
                        + ")",
                        [row[k] for k in keys],
                    )

            insert("albums", [dict(album)])
            insert(
                "editions",
                [
                    dict(r)
                    for r in source.execute("SELECT * FROM editions")
                    if r["id"] in editions
                ],
            )
            for table in (
                "catalog_names",
                "catalog_lookups",
                "reference_engines",
                "reference_rulesets",
            ):
                insert(
                    table, [dict(r) for r in source.execute("SELECT * FROM " + table)]
                )
            # Private notes never contribute to the delegated facts or ranking.
            insert("copies", [{**c, "notes": ""} for c in copies])
            for table in (
                "sources",
                "prices",
                "condition_assessments",
                "reference_decisions",
                "reference_quotes",
                "reference_quote_events",
                "verifications",
            ):
                insert(
                    table,
                    [
                        dict(r)
                        for r in source.execute("SELECT * FROM " + table)
                        if r["copy_id"] in ids
                    ],
                )
            events = []
            for row in source.execute("SELECT * FROM events ORDER BY id"):
                event = dict(row)
                if event["copy_id"] in ids:
                    events.append(event)
                elif (
                    event["kind"] == "market-product"
                    and json.loads(event["after_json"]).get("catalog_id") in catalogs
                ):
                    # This verdict is catalogue-wide; preserve it without copying
                    # an unrelated card merely to satisfy its historical FK.
                    events.append({**event, "copy_id": None})
            insert("events", events)
            listing_items = [
                dict(r)
                for r in source.execute("SELECT * FROM listing_items")
                if r["copy_id"] in ids
            ]
            listing_ids = {r["listing_id"] for r in listing_items}
            insert(
                "listings",
                [
                    dict(r)
                    for r in source.execute("SELECT * FROM listings")
                    if r["id"] in listing_ids
                ],
            )
            insert("listing_items", listing_items)
            if target.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Projection incohérente des références.")

        # Keep immutable rule evidence so the projection does not change pricing.
        for name in manifest["files"]:
            if re.fullmatch(
                r"reference_documents/[a-f0-9]{64}\.(pdf|json|html|jpg|png)", name
            ):
                body = verified_body(name)
                for root in (source_root, destination.root):
                    path = root / name
                    path.parent.mkdir(mode=0o700, exist_ok=True)
                    private_write(path, body)
        photos = {
            c[field] for c in copies for field in ("photo", "back_photo") if c[field]
        }
        for name in photos:
            if not re.fullmatch(r"[a-f0-9]{64}\.jpg", name):
                raise ValueError("Nom de photo non qualifié.")
            private_write(destination.photos / name, verified_body("photos/" + name))

    destination = Store(destination.root)
    grant_context = {"album_id": album_id, "value_ceiling_cents": 1000}
    with source_store.connect() as db:
        expected_facts = AgentService(source_store).facts(db, grant_context)
    with destination.connect() as db:
        facts = AgentService(destination).facts(db, grant_context)
        for table in ("users", "sessions", "requests", "intake_drafts", "sales"):
            if db.execute("SELECT count(*) FROM " + table).fetchone()[0]:
                raise ValueError("Des comptes ou opérations réels ont été copiés.")
    if expected_facts != facts:
        raise ValueError("La projection de l'album a changé les faits ou les valeurs.")
    with destination.connect(write=True) as db:
        add_user(
            db,
            UserCreate(
                username="eval-reader", password=os.urandom(32).hex(), role="reader"
            ),
        )
    return (
        destination,
        facts,
        {
            "archive_sha256": actual,
            "archive_created_at": manifest["created_at"],
            "album_id": album_id,
            "album_name": album["name"],
            "copies": len(facts),
            "photos": len(photos),
            "facts_equal_to_source": True,
            "original_accounts_copied": False,
            "original_sessions_copied": False,
        },
    )
