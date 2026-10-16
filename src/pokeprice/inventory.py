"""Transactional collection store. The OCR reports remain immutable import sources."""

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import closing, contextmanager, nullcontext
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .library import normalized
from .valuation import (
    ESTIMATE_FIELDS,
    assess,
    assess_binding,
    candidates_from_evidence,
    totals,
)
from .variant_pricing import category, compatible_quote, pricing_issue

SCHEMA_VERSION = 14


def now():
    return datetime.now(timezone.utc).isoformat()


def cents(value):
    if value is None or value == "":
        return None
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0 or amount > Decimal(10000000):
        raise ValueError("Montant invalide.")
    return int((amount * 100).quantize(Decimal(1)))


class Conflict(ValueError):
    pass


SCHEMA = """
CREATE TABLE albums(id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE editions(id TEXT PRIMARY KEY, name TEXT NOT NULL, set_name TEXT NOT NULL,
 number TEXT NOT NULL, language TEXT NOT NULL, catalog_id TEXT, confirmed INTEGER NOT NULL);
CREATE TABLE copies(id TEXT PRIMARY KEY, source_key TEXT NOT NULL UNIQUE,
 edition_id TEXT NOT NULL REFERENCES editions(id), name TEXT NOT NULL, set_name TEXT NOT NULL,
 number TEXT NOT NULL, language TEXT NOT NULL, catalog_id TEXT, hp INTEGER,
 identification_status TEXT NOT NULL CHECK(identification_status IN ('confirmed','review','unresolved','failed')),
 condition TEXT NOT NULL, condition_confirmed INTEGER NOT NULL DEFAULT 0,
 foil INTEGER NOT NULL, album_id TEXT NOT NULL REFERENCES albums(id), page INTEGER NOT NULL CHECK(page>0),
 position INTEGER NOT NULL CHECK(position>0), notes TEXT NOT NULL DEFAULT '', photo TEXT,
 reference_cents INTEGER CHECK(reference_cents>=0), price_source TEXT NOT NULL DEFAULT '',
 price_date TEXT NOT NULL DEFAULT '', stock_state TEXT NOT NULL DEFAULT 'available'
 CHECK(stock_state IN ('available','reserved','sold')), version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 CHECK(identification_status='confirmed' OR reference_cents IS NULL));
CREATE INDEX copies_edition ON copies(edition_id);
CREATE TABLE sources(copy_id TEXT PRIMARY KEY REFERENCES copies(id), raw_json TEXT NOT NULL,
 sha256 TEXT NOT NULL, imported_at TEXT NOT NULL);
CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','editor','reader')),
 created_at TEXT NOT NULL);
CREATE TABLE sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 expires_at INTEGER NOT NULL);
CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT, copy_id TEXT REFERENCES copies(id),
 actor TEXT NOT NULL, kind TEXT NOT NULL, reason TEXT NOT NULL, before_json TEXT NOT NULL,
 after_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE prices(id INTEGER PRIMARY KEY AUTOINCREMENT, copy_id TEXT NOT NULL REFERENCES copies(id),
 amount_cents INTEGER, currency TEXT NOT NULL DEFAULT 'EUR', source TEXT NOT NULL,
 observed_at TEXT NOT NULL, variant TEXT NOT NULL, actor TEXT NOT NULL);
CREATE TABLE imports(id INTEGER PRIMARY KEY AUTOINCREMENT, manifest TEXT NOT NULL,
 result_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE sales(id TEXT PRIMARY KEY, title TEXT NOT NULL, channel TEXT NOT NULL DEFAULT '',
 listing_url TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','reserved','sold','shipped','completed','cancelled','returned')),
 amount_cents INTEGER NOT NULL CHECK(amount_cents>=0), fees_cents INTEGER NOT NULL DEFAULT 0 CHECK(fees_cents>=0),
 shipping_charged_cents INTEGER NOT NULL DEFAULT 0 CHECK(shipping_charged_cents>=0),
 shipping_cost_cents INTEGER NOT NULL DEFAULT 0 CHECK(shipping_cost_cents>=0),
 packing_cents INTEGER NOT NULL DEFAULT 0 CHECK(packing_cents>=0), paid INTEGER NOT NULL DEFAULT 0,
 version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE sale_items(sale_id TEXT NOT NULL REFERENCES sales(id), copy_id TEXT NOT NULL REFERENCES copies(id),
 active INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(sale_id,copy_id));
CREATE UNIQUE INDEX single_reservation ON sale_items(copy_id) WHERE active=1;
CREATE TABLE sale_events(id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id TEXT NOT NULL REFERENCES sales(id),
 actor TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
PRAGMA user_version=1;
"""


# Grid cards are about 280 px wide; the card ratio is 63 × 88 mm.
THUMBNAIL_SIZE = (280, 392)


class Store:
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.photos = self.root / "photos"
        self.photos.mkdir(exist_ok=True)
        self.database = self.root / "collection.sqlite3"
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                db.executescript(SCHEMA)
            elif version not in range(1, SCHEMA_VERSION + 1):
                raise ValueError("Version de base incompatible.")
            elif version < SCHEMA_VERSION:
                self.snapshot_before_migration(db, version)
            if db.execute("PRAGMA user_version").fetchone()[0] == 1:
                db.executescript(
                    "BEGIN IMMEDIATE; ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0; PRAGMA user_version=2; COMMIT;"
                )
            if db.execute("PRAGMA user_version").fetchone()[0] == 2:
                db.executescript(
                    "BEGIN IMMEDIATE; ALTER TABLE sales ADD COLUMN refund_cents INTEGER NOT NULL DEFAULT 0 CHECK(refund_cents>=0); PRAGMA user_version=3; COMMIT;"
                )
            if db.execute("PRAGMA user_version").fetchone()[0] == 3:
                db.executescript(
                    "BEGIN IMMEDIATE; ALTER TABLE sales ADD COLUMN asking_cents INTEGER CHECK(asking_cents>=0); ALTER TABLE sales ADD COLUMN target_cents INTEGER CHECK(target_cents>=0); ALTER TABLE sales ADD COLUMN minimum_cents INTEGER CHECK(minimum_cents>=0); PRAGMA user_version=4; COMMIT;"
                )
            if db.execute("PRAGMA user_version").fetchone()[0] == 4:
                db.executescript("""
                    BEGIN IMMEDIATE;
                    ALTER TABLE copies ADD COLUMN photo_original TEXT;
                    ALTER TABLE copies ADD COLUMN back_photo TEXT;
                    ALTER TABLE copies ADD COLUMN back_photo_original TEXT;
                    CREATE TABLE condition_assessments(
                        id TEXT PRIMARY KEY,
                        copy_id TEXT NOT NULL REFERENCES copies(id),
                        actor TEXT NOT NULL, created_at TEXT NOT NULL,
                        model TEXT NOT NULL, protocol TEXT NOT NULL,
                        photos_json TEXT NOT NULL, result_json TEXT NOT NULL,
                        raw_response TEXT NOT NULL
                    );
                    CREATE INDEX condition_assessments_copy ON condition_assessments(copy_id,created_at);
                    PRAGMA user_version=5;
                    COMMIT;
                """)
            if db.execute("PRAGMA user_version").fetchone()[0] == 5:
                db.executescript("""
                    BEGIN IMMEDIATE;
                    ALTER TABLE copies ADD COLUMN deleted_at TEXT NOT NULL DEFAULT '';
                    PRAGMA user_version=6;
                    COMMIT;
                """)
            if db.execute("PRAGMA user_version").fetchone()[0] == 6:
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE intake_drafts(token TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL REFERENCES users(id), expires_at REAL NOT NULL,
                        data_json TEXT NOT NULL);
                    CREATE TABLE capture_sessions(id TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL REFERENCES users(id), album_id TEXT NOT NULL REFERENCES albums(id),
                        status TEXT NOT NULL CHECK(status IN ('active','paused','closed')),
                        slots INTEGER NOT NULL CHECK(slots BETWEEN 1 AND 100),
                        data_json TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                    CREATE UNIQUE INDEX one_active_capture ON capture_sessions(owner_id) WHERE status='active';
                    CREATE TABLE photo_batches(id TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL REFERENCES users(id), data_json TEXT NOT NULL,
                        status TEXT NOT NULL CHECK(status IN ('preview','applied','undone')),
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                    PRAGMA user_version=7;
                    COMMIT;
                """)
            if db.execute("PRAGMA user_version").fetchone()[0] == 7:
                # Text of a set logo or stamp printed on the artwork (promo variant).
                db.executescript("""
                    BEGIN IMMEDIATE;
                    ALTER TABLE copies ADD COLUMN stamp TEXT NOT NULL DEFAULT '';
                    PRAGMA user_version=8;
                    COMMIT;
                """)
            if db.execute("PRAGMA user_version").fetchone()[0] == 8:
                # Edition names per language, fetched once; lookups cache TCGdex answers.
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE catalog_names(catalog_id TEXT NOT NULL, language TEXT NOT NULL,
                        name TEXT NOT NULL, source TEXT NOT NULL, fetched_at TEXT NOT NULL,
                        PRIMARY KEY(catalog_id, language));
                    CREATE TABLE catalog_lookups(key TEXT PRIMARY KEY, found INTEGER NOT NULL,
                        value TEXT, checked_at TEXT NOT NULL);
                    PRAGMA user_version=9;
                    COMMIT;
                """)
            if db.execute("PRAGMA user_version").fetchone()[0] == 9:
                db.executescript("""
                    BEGIN IMMEDIATE;
                    ALTER TABLE copies ADD COLUMN finish TEXT NOT NULL DEFAULT ''
                        CHECK(finish IN ('','non_holo','holo','holo_border','reverse','special'));
                    ALTER TABLE copies ADD COLUMN variant_confirmed INTEGER NOT NULL DEFAULT 0;
                    ALTER TABLE copies ADD COLUMN variant_verified_at TEXT NOT NULL DEFAULT '';
                    ALTER TABLE copies ADD COLUMN variant_verified_by TEXT NOT NULL DEFAULT '';
                    ALTER TABLE copies ADD COLUMN variant_observation TEXT NOT NULL DEFAULT '';
                    PRAGMA user_version=10;
                    COMMIT;
                """)
            if db.execute("PRAGMA user_version").fetchone()[0] == 10:
                # No legacy text or global attestation proves a newly added mark state.
                db.executescript("""
                    BEGIN IMMEDIATE;
                    ALTER TABLE copies ADD COLUMN stamp_state TEXT NOT NULL DEFAULT 'unobserved'
                        CHECK(stamp_state IN ('unobserved','absent','present'));
                    ALTER TABLE copies ADD COLUMN distribution TEXT NOT NULL DEFAULT '';
                    ALTER TABLE copies ADD COLUMN distribution_state TEXT NOT NULL DEFAULT 'unobserved'
                        CHECK(distribution_state IN ('unobserved','absent','present'));
                    ALTER TABLE copies ADD COLUMN observation_provenance TEXT NOT NULL DEFAULT '{}';
                    CREATE TABLE reference_rulesets(hash TEXT PRIMARY KEY, content_json TEXT NOT NULL,
                        engine_version TEXT NOT NULL, engine_source TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE TABLE reference_decisions(id INTEGER PRIMARY KEY AUTOINCREMENT,
                        copy_id TEXT NOT NULL REFERENCES copies(id), copy_version INTEGER NOT NULL,
                        rules_hash TEXT NOT NULL REFERENCES reference_rulesets(hash),
                        inputs_json TEXT NOT NULL, result_json TEXT NOT NULL,
                        actor TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE INDEX reference_decisions_copy ON reference_decisions(copy_id,id);
                    PRAGMA user_version=11;
                    COMMIT;
                """)
            if db.execute("PRAGMA user_version").fetchone()[0] == 11:
                # Also accept the development v11 databases which already had this journal.
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS reference_quotes(id TEXT PRIMARY KEY, copy_id TEXT NOT NULL REFERENCES copies(id),
                        payload_json TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS reference_quote_events(id INTEGER PRIMARY KEY AUTOINCREMENT,
                        copy_id TEXT NOT NULL REFERENCES copies(id), quote_id TEXT REFERENCES reference_quotes(id),
                        state TEXT NOT NULL CHECK(state IN ('active','suspended','revoked')),
                        copy_version INTEGER NOT NULL, resolution_json TEXT NOT NULL,
                        actor TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE INDEX IF NOT EXISTS reference_quote_events_copy ON reference_quote_events(copy_id,id);
                    PRAGMA user_version=12;
                    COMMIT;
                """)
            if db.execute("PRAGMA user_version").fetchone()[0] == 12:
                self.attach_decision_engines(db)
            if db.execute("PRAGMA user_version").fetchone()[0] == 13:
                # Independent checks (M2): a reading and its proposal, never an applied change.
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS verifications(id TEXT PRIMARY KEY,
                        copy_id TEXT NOT NULL REFERENCES copies(id), kind TEXT NOT NULL,
                        source TEXT NOT NULL, model TEXT NOT NULL, protocol TEXT NOT NULL,
                        actor TEXT NOT NULL, created_at TEXT NOT NULL,
                        photos_json TEXT NOT NULL, card_json TEXT NOT NULL,
                        result_json TEXT NOT NULL, proposal_json TEXT NOT NULL,
                        raw_response TEXT NOT NULL, usage_json TEXT NOT NULL);
                    CREATE INDEX IF NOT EXISTS verifications_copy ON verifications(copy_id,kind,created_at);
                    PRAGMA user_version=14;
                    COMMIT;
                """)
            db.execute("PRAGMA journal_mode=WAL")
        from .reference_service import ReferenceService

        self.reference = ReferenceService(self)

    def snapshot_before_migration(self, db, version):
        """Keep the database as it was; a failed copy stops the migration."""
        folder = self.root.parent / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = folder / f"before-schema{SCHEMA_VERSION}-from{version}-{stamp}.sqlite3"
        temporary = target.with_name(target.name + ".tmp")
        try:
            with closing(sqlite3.connect(temporary)) as copy:
                db.backup(copy)
                # A single self-contained file, readable without -wal/-shm files.
                copy.execute("PRAGMA journal_mode=DELETE")
                if (
                    copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or copy.execute("PRAGMA user_version").fetchone()[0] != version
                ):
                    raise ValueError("Copie avant migration incohérente.")
            temporary.chmod(0o600)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    @staticmethod
    def attach_decision_engines(db):
        """Schema 13: each decision names its engine, no longer its ruleset's first one.

        Older decisions keep the only engine recorded for them, from their ruleset row.
        """
        import hashlib

        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute(
                "CREATE TABLE IF NOT EXISTS reference_engines(sha256 TEXT PRIMARY KEY,"
                " engine_version TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            columns = {
                r[1] for r in db.execute("PRAGMA table_info(reference_decisions)")
            }
            if "engine_sha256" not in columns:
                db.execute(
                    "ALTER TABLE reference_decisions ADD COLUMN engine_sha256 TEXT NOT NULL DEFAULT ''"
                )
            for row in db.execute(
                "SELECT hash,engine_version,engine_source,created_at FROM reference_rulesets"
            ).fetchall():
                digest = hashlib.sha256(row[2].encode()).hexdigest()
                db.execute(
                    "INSERT OR IGNORE INTO reference_engines VALUES(?,?,?,?)",
                    (digest, row[1], row[2], row[3]),
                )
                db.execute(
                    "UPDATE reference_decisions SET engine_sha256=? WHERE rules_hash=? AND engine_sha256=''",
                    (digest, row[0]),
                )
            db.execute("PRAGMA user_version=13")
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise

    @contextmanager
    def connect(self, *, write=False):
        db = sqlite3.connect(self.database, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.create_function("normalized", 1, normalized)
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def get(db, copy_id):
        row = db.execute(
            "SELECT c.*, a.name album FROM copies c JOIN albums a ON a.id=c.album_id WHERE c.id=?",
            (copy_id,),
        ).fetchone()
        if not row:
            raise KeyError("Exemplaire introuvable.")
        return dict(row)

    @staticmethod
    def edition(db, card):
        if card["identification_status"] != "confirmed":
            key = ["unresolved", card["id"]]
        elif card.get("catalog_id"):
            key = [card["language"], card["catalog_id"]]
        else:
            key = [
                card["language"],
                normalized(card["name"]),
                normalized(card["set_name"]),
                card["number"],
            ]
        edition_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "pokeprice:edition:" + json.dumps(key, ensure_ascii=False),
            )
        )
        db.execute(
            "INSERT OR IGNORE INTO editions VALUES(?,?,?,?,?,?,?)",
            (
                edition_id,
                card["name"],
                card["set_name"],
                card["number"],
                card["language"],
                card.get("catalog_id"),
                int(card["identification_status"] == "confirmed"),
            ),
        )
        return edition_id

    def save_photo(self, payload):
        name = hashlib.sha256(payload).hexdigest() + ".jpg"
        target = self.photos / name
        if not target.exists():
            temporary = self.photos / (str(uuid.uuid4()) + ".tmp")
            temporary.write_bytes(payload)
            temporary.replace(target)
        return name

    def thumbnail(self, name):
        """Small copy of a stored photo for the grid, cached outside photos/.

        The cache is derived data: backups skip it and it rebuilds on demand.
        """
        from PIL import Image

        target = self.root / "thumbnails" / name
        if not target.exists():
            target.parent.mkdir(exist_ok=True)
            with Image.open(self.photos / name) as image:
                image = image.convert("RGB")
                image.thumbnail(THUMBNAIL_SIZE)
                temporary = target.parent / (str(uuid.uuid4()) + ".tmp")
                image.save(temporary, "JPEG", quality=82, optimize=True)
            temporary.replace(target)
        return target

    @staticmethod
    def event(db, copy_id, actor, kind, reason, before, after):
        db.execute(
            "INSERT INTO events(copy_id,actor,kind,reason,before_json,after_json,created_at) VALUES(?,?,?,?,?,?,?)",
            (
                copy_id,
                actor,
                kind,
                reason,
                json.dumps(before, ensure_ascii=False),
                json.dumps(after, ensure_ascii=False),
                now(),
            ),
        )

    @staticmethod
    def observe_price(db, card, actor):
        db.execute(
            "INSERT INTO prices(copy_id,amount_cents,source,observed_at,variant,actor) VALUES(?,?,?,?,?,?)",
            (
                card["id"],
                card["reference_cents"],
                card["price_source"],
                card["price_date"],
                "foil" if card["foil"] else "normal",
                actor,
            ),
        )

    def listing(
        self,
        query="",
        album="",
        stock="",
        status="",
        limit=60,
        offset=0,
        variant="",
        sort="name",
        review="",
        threshold_cents=1000,
    ):
        with self.connect() as db:
            valuation_context = self.valuation_context(db)
            # Latest TCGdex snapshot of each copy, for alert badges and filters.
            snapshots = {
                copy_id: value[1]
                for copy_id, value in valuation_context["price-snapshot"].items()
            }
            names = {
                r[0]: r[1]
                for r in db.execute(
                    "SELECT catalog_id, group_concat(name, ' ') FROM catalog_names GROUP BY catalog_id"
                )
            }
            disputes = {
                r["copy_id"]: [json.loads(r["after_json"])]
                for r in db.execute(
                    "SELECT copy_id,after_json FROM events WHERE kind='reference-dispute' ORDER BY id"
                )
            }
            from .quote_ledger import current

            quote_selections = {
                r["id"]: current(db, r["id"])
                for r in db.execute("SELECT id FROM copies")
            }
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT c.*, a.name album,s.raw_json original_aliases FROM copies c JOIN albums a ON a.id=c.album_id LEFT JOIN sources s ON s.copy_id=c.id WHERE (c.deleted_at!='')=? ORDER BY "
                    # Binder order: one pass through each album, page after page.
                    + (
                        "a.name COLLATE NOCASE, c.album_id, c.page, c.position, c.id"
                        if sort == "binder"
                        else "c.name COLLATE NOCASE, c.album_id,c.page,c.position,c.id"
                    ),
                    (stock == "deleted",),
                )
            ]
        selected = []
        terms = normalized(query).split()
        for row in rows:
            snapshot = snapshots.get(row["id"]) or {}
            metadata = self.category_metadata(row, valuation_context)
            issue = pricing_issue(row, metadata)
            row["price_category"] = category(row, metadata)
            row["reference_resolution"] = self.reference.decision(
                row,
                metadata,
                disputes.get(row["id"], ()),
                quote_selections.get(row["id"]),
            )
            row["price_alerts"] = sum(
                not (
                    row["variant_confirmed"]
                    and not issue
                    and warning.startswith(
                        (
                            "TCGdex ne connaît pas de version Foil",
                            "L’autre variante cote",
                        )
                    )
                )
                for warning in (snapshot.get("warnings") or [])
            )
            row["variant_catalog_warning"] = bool(
                row["foil"]
                and snapshot.get("catalog_id") == row["catalog_id"]
                and snapshot.get("variant_check")
            )
            row["variant_check"] = bool(
                row["variant_catalog_warning"] and not row["variant_confirmed"]
            )
            # Edition names in several languages (TCGdex, fetched once): "Dracaufeu"
            # finds an English "Charizard" and the other way round.
            row["catalog_names"] = names.get(row["catalog_id"], "")
            original = json.loads(row.pop("original_aliases") or "{}")
            row["valuation"] = self.valuation(
                row, valuation_context, original, threshold_cents=threshold_cents
            )
            row["search_aliases"] = " ".join(
                str(original.get(k) or "")
                for k in ("OCR_Name", "Identified_Name", "Nom_Verifie")
            )
            haystack = normalized(
                " ".join(
                    str(row[k] or "")
                    for k in (
                        "name",
                        "set_name",
                        "number",
                        "language",
                        "album",
                        "notes",
                        "stamp",
                        "source_key",
                        "search_aliases",
                        "catalog_names",
                    )
                )
            )
            matches = all(
                re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", haystack)
                if len(t) == 1 and t.isalpha()
                else t in haystack
                for t in terms
            )
            if (
                matches
                and (not album or row["album_id"] == album)
                and (not stock or stock == "deleted" or row["stock_state"] == stock)
                and (not status or row["identification_status"] == status)
                and (
                    not review
                    or (
                        row["reference_resolution"]["coverage_needed"]
                        if review == "coverage"
                        else row["valuation"]["needs_review"]
                    )
                )
                and (
                    not variant
                    or (variant == "standard" and not row["foil"])
                    or (variant == "foil" and row["foil"])
                    or (variant == "check" and row["variant_check"])
                    # M0 audit: Foil never checked by eye, with or without alert.
                    or (
                        variant == "unverified"
                        and row["foil"]
                        and not row["variant_confirmed"]
                    )
                    or (variant == "stamped" and row["stamp"])
                )
            ):
                selected.append(row)
        if sort in ("price", "price_asc"):
            # The prudent value shown on each card, computed above; the SQL
            # order (name) breaks ties and unknown prices always come last.
            known = [r for r in selected if r["valuation"]["prudent_cents"] is not None]
            known.sort(
                key=lambda r: r["valuation"]["prudent_cents"], reverse=sort == "price"
            )
            selected = known + [
                r for r in selected if r["valuation"]["prudent_cents"] is None
            ]
        return {
            "items": selected[offset : offset + limit],
            "total": len(selected),
            "editions": len(
                {
                    r["edition_id"]
                    for r in selected
                    if r["identification_status"] == "confirmed"
                }
            ),
            "available": sum(
                r["stock_state"] == "available" and not r["deleted_at"]
                for r in selected
            ),
            "reference_total_cents": sum(
                (r["reference_cents"] or 0)
                for r in selected
                if not r["valuation"]["price_variant_issue"]
            ),
            "without_price": sum(
                r["reference_cents"] is None
                or bool(r["valuation"]["price_variant_issue"])
                for r in selected
            ),
            "valuation_totals": totals(selected),
        }

    @staticmethod
    def market_verdicts(db):
        """Latest human verdict on the Cardmarket product, per catalogue id."""
        result = {}
        for row in db.execute(
            "SELECT after_json FROM events WHERE kind='market-product' ORDER BY id"
        ):
            record = json.loads(row[0])
            result[record["catalog_id"]] = record
        return result

    @staticmethod
    def valuation_context(db):
        latest = list(
            db.execute(
                "SELECT id,copy_id,kind,after_json FROM events WHERE id IN "
                "(SELECT max(id) FROM events WHERE kind IN ('price-snapshot','sale-estimate','identification') GROUP BY copy_id,kind)"
            )
        )
        context = {
            kind: {} for kind in ("price-snapshot", "sale-estimate", "identification")
        }
        context["bound-quotes"] = {}
        for row in db.execute(
            "SELECT copy_id,payload_json FROM reference_quotes ORDER BY rowid"
        ):
            context["bound-quotes"].setdefault(row["copy_id"], []).append(
                json.loads(row["payload_json"])
            )
        for event in latest:
            context[event["kind"]][event["copy_id"]] = (
                event["id"],
                json.loads(event["after_json"]),
            )
        invalidated = {}
        context["category_corrections"] = set()
        for event in db.execute(
            "SELECT id,copy_id,before_json,after_json FROM events WHERE kind='correction' ORDER BY id"
        ):
            before, after = (
                json.loads(event["before_json"]),
                json.loads(event["after_json"]),
            )
            if before.get("foil") != after.get("foil"):
                context["category_corrections"].add(event["copy_id"])
            if any(before.get(k) != after.get(k) for k in ESTIMATE_FIELDS):
                invalidated[event["copy_id"]] = event["id"]
        for copy_id, (event_id, _) in list(context["sale-estimate"].items()):
            if invalidated.get(copy_id, 0) > event_id:
                del context["sale-estimate"][copy_id]
        context["market-product"] = Store.market_verdicts(db)
        from .edition_check import edition_conflicts
        from .verification import latest_conflicts, latest_language_conflicts

        context["variant-readings"] = latest_conflicts(db)
        context["language-readings"] = latest_language_conflicts(db)
        context["edition-readings"] = edition_conflicts(db)
        context["catalog"] = {}
        context["variant-catalogue"] = {}
        for row in db.execute(
            "SELECT key,value FROM catalog_lookups WHERE found=1 AND key LIKE 'variant:%'"
        ):
            _, language, catalog_id = row["key"].split(":", 2)
            metadata = json.loads(row["value"])
            if metadata.get("catalog_id") == catalog_id:
                context["variant-catalogue"][(catalog_id, language)] = metadata
        for card in db.execute("SELECT id,catalog_id,language,price_date FROM copies"):
            event_id, snapshot = context["price-snapshot"].get(card["id"], (0, {}))
            if (
                card["price_date"]
                and card["catalog_id"]
                and snapshot.get("catalog_id") == card["catalog_id"]
            ):
                key = (card["catalog_id"], card["language"])
                if event_id > context["catalog"].get(key, (0, {}))[0]:
                    context["catalog"][key] = (event_id, snapshot)
        return context

    @staticmethod
    def category_metadata(card, context):
        snapshot = context["price-snapshot"].get(card["id"], (0, None))[1]
        if snapshot and snapshot.get("catalog_id") == card.get("catalog_id"):
            return snapshot
        return context["variant-catalogue"].get(
            (card.get("catalog_id"), card.get("language"))
        )

    @staticmethod
    def valuation(card, context, source=None, *, threshold_cents=1000):
        result = Store.price_valuation(
            card, context, source, threshold_cents=threshold_cents
        )
        conflicts = context.get("variant-readings", {}).get(card["id"])
        if conflicts:
            result["reasons"] = result["reasons"] + [
                {
                    "code": "variant_reading",
                    "label": "Lecture de la finition en désaccord : " + conflicts[0],
                }
            ]
            result["needs_review"] = True
        conflicts = context.get("edition-readings", {}).get(card["id"])
        if conflicts:
            result["reasons"] = result["reasons"] + [
                {
                    "code": "edition_reading",
                    "label": "Contrôle de l’édition en désaccord : " + conflicts[0],
                }
            ]
            result["needs_review"] = True
        conflicts = context.get("language-readings", {}).get(card["id"])
        if conflicts:
            result["reasons"] = result["reasons"] + [
                {
                    "code": "language_reading",
                    "label": "Langue du texte en désaccord : " + conflicts[0],
                }
            ]
            result["needs_review"] = True
        return result

    @staticmethod
    def price_valuation(card, context, source=None, *, threshold_cents=1000):
        resolution = card.get("reference_resolution") or {}
        selected_quote = resolution.get("price_selection", {}).get("quote") or {}
        if selected_quote.get("binding_key"):
            return assess_binding(
                card,
                resolution,
                context["bound-quotes"].get(card["id"], []),
                threshold_cents=threshold_cents,
            )
        source = source or {}
        evidence = context["identification"].get(card["id"], (0, {}))[1]
        if "searches" not in evidence:
            evidence = source
        candidates = candidates_from_evidence(card, evidence)
        if (
            not evidence.get("searches")
            and source.get("TCGdex_ID")
            and all(
                source.get(old) == card.get(current)
                for old, current in (
                    ("Identified_Name", "name"),
                    ("Numero_Officiel", "number"),
                    ("Langue_Carte", "language"),
                )
            )
        ):
            candidates = [
                {
                    "id": source["TCGdex_ID"],
                    "source": "Rapport d’origine",
                    "price_snapshot": {
                        "catalog_id": source["TCGdex_ID"],
                        "updated": source.get("Date_Prix"),
                        "raw": {
                            "cardmarket": {
                                "trend": source.get("Tendance_EUR"),
                                "trend-holo": source.get("Tendance_Holo_EUR"),
                            }
                        },
                    },
                }
            ]
        priced = {}
        for candidate in candidates:
            candidate = dict(candidate)
            pricing = candidate.get("pricing")
            if isinstance(pricing, dict) and isinstance(
                pricing.get("cardmarket"), dict
            ):
                candidate["price_snapshot"] = {
                    "catalog_id": candidate["id"],
                    "raw": pricing,
                    "variants": candidate.get("variants"),
                    "updated": pricing["cardmarket"].get("updated"),
                }
            cached = context["catalog"].get((candidate["id"], card["language"]))
            if cached and (
                cached[1].get("updated") or cached[1].get("observed_at") or ""
            ) >= (candidate.get("price_snapshot", {}).get("updated") or ""):
                candidate["price_snapshot"] = cached[1]
            priced[candidate["id"]] = candidate
        return assess(
            {
                **card,
                "category_was_changed": card["id"] in context["category_corrections"],
            },
            context["price-snapshot"].get(card["id"], (0, None))[1],
            context["sale-estimate"].get(card["id"], (0, None))[1],
            list(priced.values()),
            threshold_cents=threshold_cents,
            category_snapshot=Store.category_metadata(card, context),
            market_verdict=context.get("market-product", {}).get(
                card.get("catalog_id")
            ),
        )

    def summary(self, threshold_cents=1000):
        data = self.listing(limit=1000000, threshold_cents=threshold_cents)
        with self.connect() as db:
            albums = [
                dict(r)
                for r in db.execute(
                    "SELECT a.id,a.name,COUNT(c.id) copies FROM albums a LEFT JOIN copies c ON c.album_id=a.id AND c.deleted_at='' GROUP BY a.id ORDER BY a.name"
                )
            ]
            rows = data["items"]
            return {
                "copies": len(rows),
                "editions": len(
                    {
                        r["edition_id"]
                        for r in rows
                        if r["identification_status"] == "confirmed"
                    }
                ),
                "confirmed": sum(
                    r["identification_status"] == "confirmed" for r in rows
                ),
                "unresolved": sum(
                    r["identification_status"] != "confirmed" for r in rows
                ),
                "confirmed_without_price": sum(
                    r["identification_status"] == "confirmed"
                    and (
                        r["reference_cents"] is None
                        or bool(r["valuation"]["price_variant_issue"])
                    )
                    for r in rows
                ),
                "available": sum(r["stock_state"] == "available" for r in rows),
                "albums": albums,
                "valuation_totals": data["valuation_totals"],
            }

    def set_deleted(self, copy_id, deleted, version, actor, reason):
        """Move an available copy to/from trash, retaining all sources and history."""
        if not reason.strip():
            raise ValueError("Précisez le motif.")
        with self.connect(write=True) as db:
            before = self.get(db, copy_id)
            if before["version"] != version:
                raise Conflict("La fiche a changé. Rechargez-la avant de modifier.")
            if bool(before["deleted_at"]) == deleted:
                raise Conflict("Cet exemplaire est déjà dans cet état.")
            if deleted:
                linked = db.execute(
                    "SELECT 1 FROM sale_items i JOIN sales s ON s.id=i.sale_id "
                    "WHERE i.copy_id=? AND s.status NOT IN ('cancelled','returned') LIMIT 1",
                    (copy_id,),
                ).fetchone()
                if before["stock_state"] != "available" or linked:
                    raise Conflict(
                        "Cet exemplaire appartient à un lot en cours ou est réservé/vendu. "
                        "Annulez d’abord le lot avant de le supprimer."
                    )
            timestamp = now()
            db.execute(
                "UPDATE copies SET deleted_at=?,version=version+1,updated_at=? WHERE id=?",
                (timestamp if deleted else "", timestamp, copy_id),
            )
            after = self.get(db, copy_id)
            self.event(
                db,
                copy_id,
                actor,
                "trash" if deleted else "restore",
                reason,
                before,
                after,
            )
            return after

    def patch(
        self,
        copy_id,
        changes,
        version,
        actor,
        reason,
        *,
        evidence=None,
        _db=None,
        _category_snapshot=None,
    ):
        allowed = {
            "name",
            "set_name",
            "number",
            "language",
            "catalog_id",
            "hp",
            "identification_status",
            "condition",
            "condition_confirmed",
            "finish",
            "variant_confirmed",
            "variant_observation",
            "foil",
            "stamp",
            "stamp_state",
            "distribution",
            "distribution_state",
            "album_id",
            "page",
            "position",
            "notes",
            "reference_cents",
            "price_source",
            "price_date",
            "photo",
            "photo_original",
            "back_photo",
            "back_photo_original",
        }
        if changes.keys() - allowed:
            raise ValueError("Champs non modifiables.")
        with self.connect(write=True) if _db is None else nullcontext(_db) as db:
            before = self.get(db, copy_id)
            if before["deleted_at"]:
                raise Conflict("Restaurez cet exemplaire avant de le modifier.")
            if before["version"] != version:
                raise Conflict("La fiche a changé. Rechargez-la avant de modifier.")
            after = {**before, **changes}
            for key in ("photo", "back_photo"):
                if key in changes and key + "_original" not in changes:
                    after[key + "_original"] = None
            if not db.execute(
                "SELECT 1 FROM albums WHERE id=?", (after["album_id"],)
            ).fetchone():
                raise ValueError("Album inconnu.")
            identity = (
                "name",
                "set_name",
                "number",
                "language",
                "catalog_id",
                "foil",
                "stamp",
            )
            if (
                any(after[k] != before[k] for k in ("number", "set_name", "language"))
                and after["catalog_id"] == before["catalog_id"]
            ):
                after["catalog_id"] = None
            snapshot = _category_snapshot or self.category_snapshot(db, after)
            decision = category(after, snapshot)
            if decision["mode"] == "automatic":
                after["foil"] = decision["foil"]
            if (
                after["foil"] != before["foil"]
                and changes.get("reference_cents") is not None
                and _category_snapshot is None
            ):
                raise ValueError(
                    "La catégorie calculée change : enregistrez la finition puis relevez un nouveau prix pour cette catégorie."
                )
            if any(after[k] != before[k] for k in identity) or (
                after["finish"] != before["finish"]
                and not compatible_quote(before, after, snapshot)
            ):
                after.update(reference_cents=None, price_source="", price_date="")
                # A price refresh supplies a new quote for the calculated category.
                if _category_snapshot is not None:
                    after.update(
                        {
                            k: changes[k]
                            for k in ("reference_cents", "price_source", "price_date")
                            if k in changes
                        }
                    )
            if after["identification_status"] != "confirmed":
                after.update(reference_cents=None, price_source="", price_date="")
            if changes.get("reference_cents") is not None and (
                issue := pricing_issue(after, snapshot)
            ):
                raise ValueError(issue)
            physical_identity = tuple(
                k for k in identity if k != "foil" or decision["mode"] != "automatic"
            )
            variant_changed = any(
                after[k] != before[k] for k in physical_identity
            ) or any(
                after[k] != before[k]
                for k in (
                    "finish",
                    "stamp_state",
                    "distribution",
                    "distribution_state",
                    "photo",
                    "photo_original",
                    "identification_status",
                )
            )
            if variant_changed and "variant_confirmed" not in changes:
                after["variant_confirmed"] = False
            self.validate_variant(after)
            after["observation_provenance"] = self.mark_provenance(
                after, before, changes, actor, reason
            )
            if after["variant_confirmed"] and (
                variant_changed or not before["variant_confirmed"]
            ):
                after.update(variant_verified_at=now(), variant_verified_by=actor)
            elif not after["variant_confirmed"]:
                after.update(variant_verified_at="", variant_verified_by="")
            from .quote_ledger import reconcile

            reconcile(self, db, before, after, changes, actor, reason)
            if (
                after["condition"] != before["condition"]
                and "condition_confirmed" not in changes
            ):
                after["condition_confirmed"] = False
            if any(
                after[k] != before[k]
                for k in (
                    "photo",
                    "back_photo",
                    "photo_original",
                    "back_photo_original",
                )
            ):
                after["condition_confirmed"] = False
            after["edition_id"] = self.edition(db, after)
            after["version"] = before["version"] + 1
            after["updated_at"] = now()
            fields = sorted(
                allowed
                | {
                    "edition_id",
                    "version",
                    "updated_at",
                    "variant_verified_at",
                    "variant_verified_by",
                    "observation_provenance",
                }
            )
            db.execute(
                "UPDATE copies SET "
                + ",".join(f"{k}=?" for k in fields)
                + " WHERE id=?",
                [after[k] for k in fields] + [copy_id],
            )
            self.event(db, copy_id, actor, "correction", reason, before, after)
            if evidence is not None:
                photo_preparation = evidence.get("type") == "photo-preparation"
                condition_validation = evidence.get("type") == "condition-validation"
                variant_validation = evidence.get("type") == "variant-validation"
                self.event(
                    db,
                    copy_id,
                    actor,
                    "photo-preparation"
                    if photo_preparation
                    else "condition-validation"
                    if condition_validation
                    else "variant-validation"
                    if variant_validation
                    else "identification",
                    "Préparation locale de la photo et validation humaine"
                    if photo_preparation
                    else "État proposé confronté à la carte et validé humainement"
                    if condition_validation
                    else "Finition lue confrontée à la carte et décidée humainement"
                    if variant_validation
                    else "Lecture assistée et confirmation humaine",
                    {},
                    evidence,
                )
            if any(
                after[k] != before[k]
                for k in ("reference_cents", "price_source", "price_date", "foil")
            ):
                self.observe_price(db, after, actor)
            return self.get(db, copy_id)

    @staticmethod
    def validate_variant(card):
        for field in ("stamp", "distribution"):
            state = card.get(field + "_state", "unobserved")
            value = (card.get(field) or "").strip()
            if state not in ("unobserved", "absent", "present"):
                raise ValueError("État d’observation inconnu.")
            if (state == "present" and not value) or (state == "absent" and value):
                raise ValueError(
                    "Marque présente : précisez le texte ; marque absente : laissez le texte vide."
                )
        if card.get("finish", "") not in (
            "",
            "non_holo",
            "holo",
            "holo_border",
            "reverse",
            "special",
        ):
            raise ValueError("Finition inconnue.")
        if not card.get("variant_confirmed"):
            return
        if card["identification_status"] != "confirmed" or not card.get("finish"):
            raise ValueError(
                "Confirmez l’identité et renseignez la finition observée avant de valider la variante."
            )
        if (card["finish"] == "non_holo" and card["foil"]) or (
            card["finish"] == "reverse" and not card["foil"]
        ):
            raise ValueError(
                "La catégorie de prix ne correspond pas à la finition observée (non holo : Standard ; reverse : Foil)."
            )

    @staticmethod
    def mark_provenance(card, before, changes, actor, reason):
        provenance = json.loads(before.get("observation_provenance") or "{}")
        for field in ("finish", "stamp", "distribution"):
            if any(
                k in changes and card.get(k) != before.get(k)
                for k in (field, field + "_state")
            ):
                provenance[field] = {
                    "actor": actor,
                    "observed_at": now(),
                    "reason": reason,
                    "state": ("present" if card.get("finish") else "unobserved")
                    if field == "finish"
                    else card.get(field + "_state", "unobserved"),
                    "text": card.get(field, ""),
                    "origin": "maintenance" if actor.startswith("system:") else "human",
                }
        return json.dumps(provenance, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def category_snapshot(db, card):
        """Use recorded catalogue metadata, never a client-supplied category."""
        for row in db.execute(
            "SELECT e.after_json FROM events e JOIN copies c ON c.id=e.copy_id "
            "WHERE e.kind='price-snapshot' AND (c.id=? OR (c.catalog_id=? AND c.language=?)) ORDER BY e.id DESC",
            (card.get("id", ""), card.get("catalog_id"), card.get("language")),
        ):
            snapshot = json.loads(row[0])
            if (
                card.get("catalog_id")
                and snapshot.get("catalog_id") == card["catalog_id"]
            ):
                return snapshot
        row = db.execute(
            "SELECT value FROM catalog_lookups WHERE key=? AND found=1",
            (f"variant:{card.get('language', '')}:{card.get('catalog_id', '')}",),
        ).fetchone()
        if row:
            snapshot = json.loads(row[0])
            if (
                card.get("catalog_id")
                and snapshot.get("catalog_id") == card["catalog_id"]
            ):
                return snapshot
        return None

    @staticmethod
    def duplicates(db, values, exclude_id=""):
        photos = {values.get("photo"), values.get("photo_original")} - {None, ""}
        result = []
        for row in db.execute(
            "SELECT c.*,a.name album FROM copies c JOIN albums a ON a.id=c.album_id WHERE c.deleted_at='' AND c.id!=?",
            (exclude_id,),
        ):
            matches = []
            if all(row[k] == values.get(k) for k in ("album_id", "page", "position")):
                matches.append("Emplacement déjà occupé")
            if photos & {row["photo"], row["photo_original"]}:
                matches.append("Même photo de recto")
            if matches:
                result.append(
                    {
                        k: row[k]
                        for k in (
                            "id",
                            "name",
                            "number",
                            "album",
                            "page",
                            "position",
                            "version",
                            "photo",
                        )
                    }
                )
                result[-1]["reasons"] = matches
                result[-1]["acknowledgment"] = f"{row['id']}:{row['version']}"
        return result

    def create_copy(
        self,
        values,
        actor,
        reason,
        *,
        copy_id=None,
        evidence=None,
        duplicate_acknowledgments=None,
        _db=None,
    ):
        copy_id = copy_id or str(uuid.uuid4())
        card = {
            "id": copy_id,
            "source_key": "manual:" + copy_id,
            "catalog_id": None,
            "hp": None,
            "identification_status": "review",
            "condition": "",
            "condition_confirmed": False,
            "finish": "",
            "variant_confirmed": False,
            "variant_verified_at": "",
            "variant_verified_by": "",
            "variant_observation": "",
            "foil": False,
            "stamp": "",
            "stamp_state": "unobserved",
            "distribution": "",
            "distribution_state": "unobserved",
            "observation_provenance": "{}",
            "notes": "",
            "photo": None,
            "photo_original": None,
            "back_photo": None,
            "back_photo_original": None,
            "reference_cents": None,
            "price_source": "",
            "price_date": "",
            "stock_state": "available",
            "version": 1,
            "created_at": now(),
            "updated_at": now(),
            **values,
        }
        with self.connect(write=True) if _db is None else nullcontext(_db) as db:
            if db.execute("SELECT 1 FROM copies WHERE id=?", (copy_id,)).fetchone():
                return self.get(db, copy_id)
            if duplicate_acknowledgments is not None:
                required = {r["acknowledgment"] for r in self.duplicates(db, card)}
                if not required.issubset(set(duplicate_acknowledgments)):
                    raise Conflict(
                        "Un emplacement est occupé ou une photo existe déjà. Vérifiez les alertes et confirmez un exemplaire distinct."
                    )
            if not db.execute(
                "SELECT 1 FROM albums WHERE id=?", (card["album_id"],)
            ).fetchone():
                raise ValueError("Album inconnu.")
            snapshot = self.category_snapshot(db, card)
            decision = category(card, snapshot)
            if decision["mode"] == "automatic":
                card["foil"] = decision["foil"]
            self.validate_variant(card)
            card["observation_provenance"] = self.mark_provenance(
                card, {}, values, actor, reason
            )
            card["variant_verified_at"] = now() if card["variant_confirmed"] else ""
            card["variant_verified_by"] = actor if card["variant_confirmed"] else ""
            card["edition_id"] = self.edition(db, card)
            db.execute(
                "INSERT INTO copies("
                + ",".join(card)
                + ") VALUES("
                + ",".join("?" for _ in card)
                + ")",
                list(card.values()),
            )
            self.event(db, copy_id, actor, "acquisition", reason, {}, card)
            if evidence is not None:
                raw = json.dumps(evidence, ensure_ascii=False)
                db.execute(
                    "INSERT INTO sources VALUES(?,?,?,?)",
                    (copy_id, raw, hashlib.sha256(raw.encode()).hexdigest(), now()),
                )
            return self.get(db, copy_id)

    def grouped(
        self,
        query="",
        album="",
        stock="",
        status="",
        limit=40,
        offset=0,
        variant="",
        sort="name",
        review="",
        threshold_cents=1000,
    ):
        data = self.listing(
            query,
            album,
            stock,
            status,
            1000000,
            variant=variant,
            sort=sort,
            review=review,
            threshold_cents=threshold_cents,
        )
        groups = {}
        for card in data["items"]:
            group = groups.setdefault(
                card["edition_id"],
                {
                    "id": card["edition_id"],
                    "name": card["name"],
                    "set_name": card["set_name"],
                    "number": card["number"],
                    "language": card["language"],
                    "copies": [],
                },
            )
            group["copies"].append(card)
        for group in groups.values():
            group["quantity"] = len(group["copies"])
            with self.connect() as db:
                all_copies = list(
                    db.execute(
                        "SELECT stock_state FROM copies WHERE edition_id=? AND (deleted_at!='')=?",
                        (group["id"], stock == "deleted"),
                    )
                )
            group["global_quantity"] = len(all_copies)
            group["stock_counts"] = {
                s: sum(c["stock_state"] == s for c in all_copies)
                for s in ("available", "reserved", "sold")
            }
        data.update(
            items=list(groups.values())[offset : offset + limit],
            copies_total=data["total"],
            total=len(groups),
        )
        return data

    def create_sale(self, values, copy_ids, actor):
        if not copy_ids or len(copy_ids) != len(set(copy_ids)):
            raise ValueError("Sélectionnez des exemplaires distincts.")
        sale_id = str(uuid.uuid4())
        sale = {
            "id": sale_id,
            "title": values["title"],
            "channel": values.get("channel", ""),
            "listing_url": values.get("listing_url", ""),
            "notes": values.get("notes", ""),
            "amount_cents": values["amount_cents"],
            "asking_cents": values.get("asking_cents"),
            "target_cents": values.get("target_cents"),
            "minimum_cents": values.get("minimum_cents"),
            "status": "draft",
            "created_at": now(),
            "updated_at": now(),
        }
        with self.connect(write=True) as db:
            for copy_id in copy_ids:
                card = self.get(db, copy_id)
                if card["deleted_at"]:
                    raise Conflict("Un exemplaire a été supprimé de la collection.")
                if card["stock_state"] != "available":
                    raise Conflict("Un exemplaire est déjà réservé ou vendu.")
            db.execute(
                "INSERT INTO sales("
                + ",".join(sale)
                + ") VALUES("
                + ",".join("?" for _ in sale)
                + ")",
                list(sale.values()),
            )
            db.executemany(
                "INSERT INTO sale_items(sale_id,copy_id) VALUES(?,?)",
                [(sale_id, c) for c in copy_ids],
            )
            db.execute(
                "INSERT INTO sale_events(sale_id,actor,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?)",
                (
                    sale_id,
                    actor,
                    "{}",
                    json.dumps(sale, ensure_ascii=False),
                    "Création du brouillon",
                    now(),
                ),
            )
        return sale_id

    def sales(self):
        with self.connect() as db:
            result = []
            for row in db.execute("SELECT * FROM sales ORDER BY created_at DESC"):
                sale = dict(row)
                sale["items"] = [
                    self.get(db, r[0])
                    for r in db.execute(
                        "SELECT copy_id FROM sale_items WHERE sale_id=?", (sale["id"],)
                    )
                ]
                sale["net_cents"] = (
                    sale["amount_cents"]
                    + sale["shipping_charged_cents"]
                    - sale["fees_cents"]
                    - sale["shipping_cost_cents"]
                    - sale["packing_cents"]
                    - sale["refund_cents"]
                )
                result.append(sale)
            return result

    def update_sale(self, sale_id, changes, version, actor, reason):
        transitions = {
            "draft": {"reserved", "cancelled"},
            "reserved": {"sold", "cancelled"},
            "sold": {"shipped", "completed", "returned"},
            "shipped": {"completed", "returned"},
            "completed": {"returned"},
            "cancelled": set(),
            "returned": set(),
        }
        allowed = {
            "status",
            "amount_cents",
            "fees_cents",
            "shipping_charged_cents",
            "shipping_cost_cents",
            "packing_cents",
            "refund_cents",
            "asking_cents",
            "target_cents",
            "minimum_cents",
            "paid",
            "channel",
            "listing_url",
            "notes",
        }
        if changes.keys() - allowed:
            raise ValueError("Champs de vente non modifiables.")
        with self.connect(write=True) as db:
            row = db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
            if not row:
                raise KeyError("Vente introuvable.")
            before = dict(row)
            if before["version"] != version:
                raise Conflict("La vente a changé. Rechargez-la.")
            after = {**before, **changes}
            old, new = before["status"], after["status"]
            if old != new:
                if new not in transitions[old]:
                    raise Conflict("Transition de vente interdite.")
                copy_ids = [
                    r[0]
                    for r in db.execute(
                        "SELECT copy_id FROM sale_items WHERE sale_id=?", (sale_id,)
                    )
                ]
                for copy_id in copy_ids:
                    card = self.get(db, copy_id)
                    target = card["stock_state"]
                    if new == "reserved":
                        if card["deleted_at"]:
                            raise Conflict(
                                "Un exemplaire a été supprimé de la collection."
                            )
                        if target != "available":
                            raise Conflict("Un exemplaire est déjà réservé ou vendu.")
                        target = "reserved"
                    elif new == "sold":
                        if target != "reserved":
                            raise Conflict("Stock incompatible avec la vente.")
                        target = "sold"
                    elif new in ("cancelled", "returned"):
                        target = "available"
                    if new != "cancelled" or old != "draft":
                        db.execute(
                            "UPDATE copies SET stock_state=?,version=version+1,updated_at=?,condition_confirmed=CASE WHEN ? THEN 0 ELSE condition_confirmed END WHERE id=?",
                            (target, now(), new == "returned", copy_id),
                        )
                        self.event(
                            db,
                            copy_id,
                            actor,
                            "stock",
                            reason,
                            card,
                            self.get(db, copy_id),
                        )
                if new in ("reserved", "cancelled", "returned"):
                    db.execute(
                        "UPDATE sale_items SET active=? WHERE sale_id=?",
                        (int(new == "reserved"), sale_id),
                    )
            after.update(version=version + 1, updated_at=now())
            fields = sorted(allowed | {"version", "updated_at"})
            db.execute(
                "UPDATE sales SET "
                + ",".join(f"{k}=?" for k in fields)
                + " WHERE id=?",
                [after[k] for k in fields] + [sale_id],
            )
            db.execute(
                "INSERT INTO sale_events(sale_id,actor,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?)",
                (sale_id, actor, json.dumps(before), json.dumps(after), reason, now()),
            )
        return after
