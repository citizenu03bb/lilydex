"""Transactional collection store. The OCR reports remain immutable import sources."""

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .library import normalized


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
            elif version not in (1, 2, 3, 4, 5, 6, 7, 8):
                raise ValueError("Version de base incompatible.")
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
            db.execute("PRAGMA journal_mode=WAL")

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
        self, query="", album="", stock="", status="", limit=60, offset=0, variant=""
    ):
        with self.connect() as db:
            # Latest TCGdex snapshot of each copy, for alert badges and filters.
            snapshots = {
                r[0]: json.loads(r[1])
                for r in db.execute(
                    "SELECT copy_id,after_json FROM events WHERE id IN (SELECT max(id) FROM events WHERE kind='price-snapshot' GROUP BY copy_id)"
                )
            }
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT c.*, a.name album,s.raw_json original_aliases FROM copies c JOIN albums a ON a.id=c.album_id LEFT JOIN sources s ON s.copy_id=c.id WHERE (c.deleted_at!='')=? ORDER BY c.name COLLATE NOCASE, c.album_id,c.page,c.position,c.id",
                    (stock == "deleted",),
                )
            ]
        selected = []
        terms = normalized(query).split()
        for row in rows:
            snapshot = snapshots.get(row["id"]) or {}
            row["price_alerts"] = len(snapshot.get("warnings") or [])
            row["variant_check"] = bool(row["foil"] and snapshot.get("variant_check"))
            original = json.loads(row.pop("original_aliases") or "{}")
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
                    not variant
                    or (variant == "standard" and not row["foil"])
                    or (variant == "foil" and row["foil"])
                    or (variant == "check" and row["variant_check"])
                    or (variant == "stamped" and row["stamp"])
                )
            ):
                selected.append(row)
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
            "reference_total_cents": sum(r["reference_cents"] or 0 for r in selected),
            "without_price": sum(r["reference_cents"] is None for r in selected),
        }

    def summary(self):
        with self.connect() as db:
            albums = [
                dict(r)
                for r in db.execute(
                    "SELECT a.id,a.name,COUNT(c.id) copies FROM albums a LEFT JOIN copies c ON c.album_id=a.id AND c.deleted_at='' GROUP BY a.id ORDER BY a.name"
                )
            ]
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT identification_status,reference_cents,edition_id,stock_state FROM copies WHERE deleted_at=''"
                )
            ]
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
                    and r["reference_cents"] is None
                    for r in rows
                ),
                "available": sum(r["stock_state"] == "available" for r in rows),
                "albums": albums,
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
        self, copy_id, changes, version, actor, reason, *, evidence=None, _db=None
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
            "foil",
            "stamp",
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
            if any(after[k] != before[k] for k in identity):
                after.update(reference_cents=None, price_source="", price_date="")
            if after["identification_status"] != "confirmed":
                after.update(reference_cents=None, price_source="", price_date="")
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
            fields = sorted(allowed | {"edition_id", "version", "updated_at"})
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
                self.event(
                    db,
                    copy_id,
                    actor,
                    "photo-preparation"
                    if photo_preparation
                    else "condition-validation"
                    if condition_validation
                    else "identification",
                    "Préparation locale de la photo et validation humaine"
                    if photo_preparation
                    else "État proposé confronté à la carte et validé humainement"
                    if condition_validation
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
            "foil": False,
            "stamp": "",
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
        self, query="", album="", stock="", status="", limit=40, offset=0, variant=""
    ):
        data = self.listing(query, album, stock, status, 1000000, variant=variant)
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
