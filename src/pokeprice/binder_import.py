"""Binder import: pages photographed, cut, read and turned into copies to check.

One service for the server's command line and the management app (decision
0047). The page is the unit of work; each pocket moves through recorded steps,
each of them safe to run again:

    cut → read → created → checked        (or empty, retake, failed)

A page whose pockets are all settled is handed to the review agent, then done.
The state lives in ``binder_imports.sqlite3`` next to the collection, created on
first use: the collection's schema is untouched. Photos go to the store's
reserve by fingerprint. A copy's id derives from the import, the page and the
pocket, and is created once: a resumed import never duplicates a copy.

The web process only records uploads; ``step()`` does the work, in the
background worker (``pokeprice-manage binder-worker``) or the command line.
"""

import hashlib
import io
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from PIL import Image

from .gemini_usage import metering
from .inventory import Conflict, now
from .photo_batches import slice_page_photo
from .photo_processing import prepare_photo

FILENAME = "binder_imports.sqlite3"
GRIDS = ("3x3", "2x2", "3x4", "4x3", "single")
DEFAULT_BUDGET_EUR = 3.0
BUDGET_VARIABLE = "POKEPRICE_IMPORT_BUDGET_EUR"
MAX_PHOTO_BYTES = 15 * 1024 * 1024
CHUNK_BYTES = 512 * 1024
MAX_ATTEMPTS = 3  # A pocket failing this often while others pass is retaken.
MAX_BACKOFF = 1800
LEASE_SECONDS = 120
ACTOR = "system:import"
# A pocket's states; the last four are settled.
PENDING = ("cut", "read", "created")
SETTLED = ("checked", "empty", "retake", "failed")
# Decision 0047: an edition enters « Référentiel à compléter » at the value
# threshold of S2 or from this many copies in the collection.
REFERENCE_COPIES = 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY, album_id TEXT NOT NULL,
    grid TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active','paused_budget','closed')),
    budget_eur REAL NOT NULL, initial_budget_eur REAL NOT NULL,
    retry_at REAL NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
    last_success_at REAL NOT NULL DEFAULT 0, notified_at REAL NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS pages(import_id TEXT NOT NULL REFERENCES imports(id),
    page INTEGER NOT NULL, photo TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('received','cut','done','error')),
    error TEXT NOT NULL DEFAULT '', review_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL, PRIMARY KEY(import_id, page));
CREATE TABLE IF NOT EXISTS pockets(import_id TEXT NOT NULL REFERENCES imports(id),
    page INTEGER NOT NULL, position INTEGER NOT NULL, photo TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('page','card')),
    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
    retry_at REAL NOT NULL DEFAULT 0, first_failure_at REAL NOT NULL DEFAULT 0,
    reading_json TEXT NOT NULL DEFAULT '{}', copy_id TEXT, copy_version INTEGER,
    error TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
    PRIMARY KEY(import_id, page, position));
CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY, import_id TEXT NOT NULL
    REFERENCES imports(id), page INTEGER NOT NULL, position INTEGER NOT NULL,
    size INTEGER NOT NULL, sha256 TEXT NOT NULL, received INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id TEXT NOT NULL, page INTEGER NOT NULL, position INTEGER NOT NULL,
    step TEXT NOT NULL, model TEXT NOT NULL, input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL, month TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS lease(name TEXT PRIMARY KEY, holder TEXT NOT NULL,
    until REAL NOT NULL);
"""


class BudgetReached(Conflict):
    pass


def edition_key(card):
    """An edition for the print reference queue: set and language."""
    return (card.get("set_name") or "", card.get("language") or "")


def is_imported(card, import_id=None):
    prefix = "binder:" + (f"{import_id}:" if import_id else "")
    return str(card.get("source_key") or "").startswith(prefix)


def reference_stats(rows):
    """Per edition: copies in the collection and the highest stake of an imported one."""
    stats: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        stat = stats.setdefault(edition_key(row), {"copies": 0, "risk": None})
        stat["copies"] += 1
        risk = (row.get("valuation") or {}).get("risk_cents")
        if is_imported(row) and risk is not None:
            stat["risk"] = max(stat["risk"] or 0, risk)
    return stats


def reference_queued(stat, threshold_cents):
    """Decision 0047: an edition a binder brings is worth a proof at the value
    threshold, or once the collection holds enough of it; otherwise it is counted."""
    if stat["copies"] >= REFERENCE_COPIES:
        return "copies"
    if stat["risk"] is not None and stat["risk"] >= threshold_cents:
        return "value"
    return None


def budget_from_env(environ):
    raw = (environ.get(BUDGET_VARIABLE) or "").strip()
    if not raw:
        return DEFAULT_BUDGET_EUR
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        raise ValueError(f"{BUDGET_VARIABLE} : montant en euros attendu.") from None
    if not 0 < value <= 100:
        raise ValueError(f"{BUDGET_VARIABLE} : entre 0 et 100 €.")
    return value


def copy_id_for(import_id, page, position):
    """The copy of a pocket: the same id however often the step runs."""
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"pokeprice:binder:{import_id}:{page}:{position}")
    )


def month_of(moment):
    return datetime.fromtimestamp(moment, timezone.utc).strftime("%Y-%m")


def euros(value):
    return f"{value:.2f} €".replace(".", ",")


def check_photo(data):
    """A JPEG, PNG or WebP of reasonable size; the cutting validates the rest."""
    if not data or len(data) > MAX_PHOTO_BYTES:
        raise ValueError("Photo vide ou trop lourde (15 Mo au plus).")
    if not (
        data[:3] == b"\xff\xd8\xff"
        or data[:8] == b"\x89PNG\r\n\x1a\n"
        or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    ):
        raise ValueError("Photo JPEG, PNG ou WebP requise.")


class BinderImports:
    """Imports of binders into the store, page by page.

    ``reader(photo)`` returns ``(observation, raw)`` like ``intake.read_photo``:
    a ``ValueError`` means the pocket shows no readable front, any other error
    is transient. ``lookup(query)`` is ``intake.catalogue_candidates``.
    ``checks(copy_id)`` runs the intake checks (finish, edition, condition).
    ``review(copy_ids, apply)`` runs the review agent and returns its report;
    ``apply()`` says whether it writes (the ``agent_review_apply`` setting).
    ``notify(title, body)`` reaches the administrator.
    """

    def __init__(
        self,
        store,
        *,
        reader=None,
        lookup=None,
        suggest=None,
        checks=None,
        review=None,
        apply=None,
        notify=None,
        gate=None,
        default_budget_eur=DEFAULT_BUDGET_EUR,
        pricing=None,
        eur_per_usd=None,
        clock=time.time,
        holder=None,
    ):
        if reader is None or lookup is None:
            from .intake import catalogue_candidates, read_photo

            reader = reader or read_photo
            lookup = lookup or catalogue_candidates
        self.store, self.reader, self.lookup = store, reader, lookup
        self.suggest, self.checks, self.review = suggest, checks, review
        self.apply = apply or (lambda: False)
        self.notify, self.gate = notify, gate
        self.default_budget = default_budget_eur
        # The chat's price grid and rate (decision 0039), read here: importing the
        # assistant at module load would load it with the web app (test_web_context).
        from .assistant import DEFAULT_EUR_PER_USD, load_pricing

        self.pricing = load_pricing() if pricing is None else pricing
        self.rate = DEFAULT_EUR_PER_USD if eur_per_usd is None else eur_per_usd
        self.clock = clock
        self.holder = holder or str(uuid.uuid4())
        self.path = store.root / FILENAME
        self.uploads_dir = store.root / "binder-uploads"
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
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

    # -- Imports -------------------------------------------------------------

    def create(self, actor, *, album_id=None, album_name=None, grid="3x3", budget_eur=None):
        """A new import into an existing album, or a new album by name."""
        if grid not in GRIDS:
            raise ValueError("Grille inconnue : " + ", ".join(GRIDS) + ".")
        budget = self.default_budget if budget_eur is None else float(budget_eur)
        if not 0 < budget <= 100:
            raise ValueError("Budget entre 0 et 100 €.")
        with self.store.connect(write=True) as db:
            if album_id:
                if not db.execute("SELECT 1 FROM albums WHERE id=?", (album_id,)).fetchone():
                    raise KeyError("Album inconnu.")
            else:
                name = (album_name or "").strip()
                if not name or len(name) > 120:
                    raise ValueError("Nom d’album requis (120 caractères au plus).")
                found = db.execute("SELECT id FROM albums WHERE name=?", (name,)).fetchone()
                if found:
                    album_id = found[0]
                else:
                    album_id = str(uuid.uuid4())
                    db.execute("INSERT INTO albums VALUES(?,?)", (album_id, name))
        import_id = str(uuid.uuid4())
        with self.connect(write=True) as db:
            db.execute(
                "INSERT INTO imports(id,album_id,grid,created_by,created_at,budget_eur,"
                "initial_budget_eur) VALUES(?,?,?,?,?,?,?)",
                (import_id, album_id, grid, actor, now(), budget, budget),
            )
        return self.get(import_id)

    def row(self, db, import_id):
        found = db.execute("SELECT * FROM imports WHERE id=?", (import_id,)).fetchone()
        if not found:
            raise KeyError("Import inconnu.")
        return dict(found)

    def cost(self, db, import_id, page=None):
        """Estimated euros of the Gemini calls, at the price of their month."""
        query = (
            "SELECT model,month,SUM(input_tokens) i,SUM(output_tokens) o,COUNT(*) n "
            "FROM usage WHERE import_id=?"
        )
        args = [import_id]
        if page is not None:
            query += " AND page=?"
            args.append(page)
        from .assistant import price_of

        usd, calls, unpriced = 0.0, 0, set()
        for r in db.execute(query + " GROUP BY model,month", args):
            calls += r["n"]
            price = price_of(self.pricing, r["model"], r["month"])
            if price is None:
                unpriced.add(r["model"])
                continue
            usd += (r["i"] * price["input"] + r["o"] * price["output"]) / 1_000_000
        return {"eur": round(usd * self.rate, 4), "calls": calls, "unpriced_models": sorted(unpriced)}

    def get(self, import_id):
        """The import, its pages in binder order, its cost and its report."""
        with self.connect() as db:
            item = self.row(db, import_id)
            pages = [dict(r) for r in db.execute(
                "SELECT * FROM pages WHERE import_id=? ORDER BY page", (import_id,))]
            pockets = [dict(r) for r in db.execute(
                "SELECT * FROM pockets WHERE import_id=? ORDER BY page,position", (import_id,))]
            item["cost"] = self.cost(db, import_id)
            page_costs = {p["page"]: self.cost(db, import_id, p["page"])["eur"] for p in pages}
        with self.store.connect() as db:
            album = db.execute("SELECT name FROM albums WHERE id=?", (item["album_id"],)).fetchone()
        item["album"] = album[0] if album else ""
        by_page: dict[int, list] = {}
        for pocket in pockets:
            pocket["reading"] = json.loads(pocket.pop("reading_json"))
            by_page.setdefault(pocket["page"], []).append(pocket)
        for page in pages:
            page["review"] = json.loads(page.pop("review_json"))
            page["pockets"] = by_page.get(page["page"], [])
            page["cost_eur"] = page_costs[page["page"]]
        item["pages"] = pages
        counts: dict[str, int] = {}
        for pocket in pockets:
            counts[pocket["status"]] = counts.get(pocket["status"], 0) + 1
        item["counts"] = counts
        item["progress"] = {
            "pockets": len(pockets),
            "settled": sum(p["status"] in SETTLED for p in pockets),
            "pages_done": sum(p["status"] == "done" for p in pages),
        }
        return item

    def report(self, import_id, threshold_cents=1000):
        """The editions this import brings to « Référentiel à compléter », and the tally."""
        from collections import Counter

        with self.connect() as db:
            album_id = self.row(db, import_id)["album_id"]
        rows = self.store.listing(limit=10**9, threshold_cents=threshold_cents)["items"]
        stats = reference_stats(rows)
        mine = [r for r in rows if r["album_id"] == album_id and is_imported(r, import_id)
                and r["reference_resolution"]["coverage_needed"]]
        queued: list[dict[str, Any]] = []
        tally: Counter[str] = Counter()
        for key in dict.fromkeys(edition_key(r) for r in mine):
            copies = sum(edition_key(r) == key for r in mine)
            reason = reference_queued(stats[key], threshold_cents)
            if reason:
                queued.append({"set_name": key[0], "language": key[1], "reason": reason,
                               "imported": copies, "collection": stats[key]["copies"],
                               "risk_cents": stats[key]["risk"]})
            else:
                tally["editions"] += 1
                tally["copies"] += copies
        return {"threshold_cents": threshold_cents, "queued": queued,
                "tally": {"editions": tally["editions"], "copies": tally["copies"]}}

    def listing(self, limit=20):
        with self.connect() as db:
            ids = [r[0] for r in db.execute(
                "SELECT id FROM imports ORDER BY created_at DESC LIMIT ?", (limit,))]
        return [self.get(i) for i in ids]

    def continue_budget(self, import_id, actor):
        """The administrator's yes: one more initial budget, and the import goes on."""
        with self.connect(write=True) as db:
            item = self.row(db, import_id)
            if item["status"] != "paused_budget":
                raise Conflict("Cet import n’attend pas de décision de budget.")
            budget = item["budget_eur"] + item["initial_budget_eur"]
            db.execute(
                "UPDATE imports SET status='active',budget_eur=?,notified_at=0,note=? WHERE id=?",
                (budget, f"Budget porté à {euros(budget)} par {actor}.", import_id),
            )
        return self.get(import_id)

    def close(self, import_id, actor):
        with self.connect(write=True) as db:
            self.row(db, import_id)
            db.execute(
                "UPDATE imports SET status='closed',note=? WHERE id=?",
                (f"Import clos par {actor}.", import_id),
            )
        return self.get(import_id)

    # -- Photos and resumable uploads ----------------------------------------

    def begin_upload(self, import_id, page, position, size, sha256):
        """Announce a photo: position 0 is the whole page, otherwise one pocket.

        The same photo announced again is the same upload: its received offset
        tells the phone where to resume.
        """
        sha256 = (sha256 or "").lower()
        if not (isinstance(size, int) and 0 < size <= MAX_PHOTO_BYTES):
            raise ValueError("Photo vide ou trop lourde (15 Mo au plus).")
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise ValueError("Empreinte SHA-256 attendue.")
        self.check_place(import_id, page, position)
        with self.connect(write=True) as db:
            found = db.execute(
                "SELECT * FROM uploads WHERE import_id=? AND page=? AND position=? AND sha256=? "
                "AND size=?",
                (import_id, page, position, sha256, size),
            ).fetchone()
            if found:
                return self.upload_state(dict(found))
            upload_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO uploads(id,import_id,page,position,size,sha256,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (upload_id, import_id, page, position, size, sha256, self.clock()),
            )
        return {"id": upload_id, "received": 0, "size": size, "done": False}

    @staticmethod
    def upload_state(row):
        return {"id": row["id"], "received": row["received"], "size": row["size"],
                "done": bool(row["done"])}

    def check_place(self, import_id, page, position):
        with self.connect() as db:
            item = self.row(db, import_id)
        if item["status"] == "closed":
            raise Conflict("Import clos.")
        if not (isinstance(page, int) and 1 <= page <= 1000):
            raise ValueError("Numéro de page invalide (1 à 1000).")
        slots = self.slots(item["grid"])
        if not (isinstance(position, int) and 0 <= position <= slots):
            raise ValueError(f"Pochette invalide (1 à {slots}, ou 0 pour la page).")
        if position and item["grid"] != "single":
            with self.connect() as db:
                if not db.execute(
                    "SELECT 1 FROM pages WHERE import_id=? AND page=?", (import_id, page)
                ).fetchone():
                    raise Conflict("Photographiez d’abord la page entière.")

    @staticmethod
    def slots(grid):
        rows, cols = (1, 1) if grid == "single" else map(int, grid.split("x"))
        return rows * cols

    def put_chunk(self, upload_id, offset, data):
        """Append a chunk at the announced offset; the last one registers the photo."""
        if len(data) > CHUNK_BYTES * 2:
            raise ValueError("Morceau trop gros.")
        with self.connect(write=True) as db:
            found = db.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
            if not found:
                raise KeyError("Téléversement inconnu.")
            upload = dict(found)
            if upload["done"] or offset != upload["received"]:
                # A chunk sent twice (the answer was lost): say where we are.
                return self.upload_state(upload)
            if offset + len(data) > upload["size"]:
                raise ValueError("Le morceau dépasse la taille annoncée.")
            self.uploads_dir.mkdir(mode=0o700, exist_ok=True)
            partial = self.uploads_dir / (upload_id + ".part")
            with open(partial, "r+b" if partial.exists() else "wb") as handle:
                handle.seek(offset)
                handle.write(data)
                handle.truncate()
            upload["received"] = offset + len(data)
            db.execute("UPDATE uploads SET received=? WHERE id=?", (upload["received"], upload_id))
        if upload["received"] < upload["size"]:
            return self.upload_state(upload)
        payload = partial.read_bytes()
        if hashlib.sha256(payload).hexdigest() != upload["sha256"]:
            with self.connect(write=True) as db:
                db.execute("UPDATE uploads SET received=0 WHERE id=?", (upload_id,))
            partial.unlink(missing_ok=True)
            raise ValueError("Photo altérée pendant l’envoi : elle repart du début.")
        self.add_photo(upload["import_id"], upload["page"], upload["position"], payload)
        with self.connect(write=True) as db:
            db.execute("UPDATE uploads SET done=1 WHERE id=?", (upload_id,))
        partial.unlink(missing_ok=True)
        return {**self.upload_state(upload), "done": True}

    def add_photo(self, import_id, page, position, data):
        """Register a page photo (position 0) or a pocket photo; a retake resets the steps."""
        check_photo(data)
        self.check_place(import_id, page, position)
        with self.connect() as db:
            grid = self.row(db, import_id)["grid"]
        if grid == "single" and position == 0:
            position = 1
        if position:
            # One card: oriented and resized by the same cutting, as one pocket.
            try:
                _, ((_, data),) = slice_page_photo(data, grid="single")
            except ValueError as error:
                raise ValueError(str(error)) from None
        stamp = now()
        if position == 0:
            # The raw page waits outside the photo reserve (and its backups): the
            # worker cuts it, keeps a reduced page and removes the raw file.
            self.uploads_dir.mkdir(mode=0o700, exist_ok=True)
            name = "raw:page-" + hashlib.sha256(data).hexdigest() + ".bin"
            target = self.uploads_dir / name[4:]
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(target)
        else:
            name = self.store.save_photo(data)
        with self.connect(write=True) as db:
            if position == 0:
                db.execute(
                    "INSERT INTO pages(import_id,page,photo,status,updated_at) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(import_id,page) DO UPDATE SET photo=excluded.photo,"
                    "status='received',error='',review_json='{}',updated_at=excluded.updated_at",
                    (import_id, page, name, "received", stamp),
                )
                return {"page": page, "photo": name}
            db.execute(
                "INSERT INTO pages(import_id,page,photo,status,updated_at) VALUES(?,?,?,'cut',?) "
                "ON CONFLICT(import_id,page) DO UPDATE SET status=CASE WHEN status='done' "
                "THEN 'cut' ELSE status END,review_json='{}',updated_at=excluded.updated_at",
                (import_id, page, name, stamp),
            )
            self.reset_pocket(db, import_id, page, position, name, "card", stamp)
        return {"page": page, "position": position, "photo": name}

    @staticmethod
    def reset_pocket(db, import_id, page, position, photo, source, stamp):
        db.execute(
            "INSERT INTO pockets(import_id,page,position,photo,source,status,updated_at) "
            "VALUES(?,?,?,?,?,'cut',?) ON CONFLICT(import_id,page,position) DO UPDATE SET "
            "photo=excluded.photo,source=excluded.source,status='cut',attempts=0,retry_at=0,"
            "first_failure_at=0,error='',updated_at=excluded.updated_at",
            (import_id, page, position, photo, source, stamp),
        )

    def mark_empty(self, import_id, page, position, actor):
        """A person says the pocket is empty: nothing to create, the page can finish."""
        with self.connect(write=True) as db:
            found = db.execute(
                "SELECT status,copy_id FROM pockets WHERE import_id=? AND page=? AND position=?",
                (import_id, page, position),
            ).fetchone()
            if not found:
                raise KeyError("Pochette inconnue.")
            if found["copy_id"]:
                raise Conflict("Un exemplaire existe pour cette pochette : mettez-le à la corbeille.")
            db.execute(
                "UPDATE pockets SET status='empty',error=?,updated_at=? WHERE import_id=? "
                "AND page=? AND position=?",
                (f"Pochette vide, d’après {actor}.", now(), import_id, page, position),
            )
        return self.get(import_id)

    # -- The work ------------------------------------------------------------

    def claim(self):
        """One worker at a time: the command line and the service share the lease."""
        moment = self.clock()
        with self.connect(write=True) as db:
            found = db.execute("SELECT holder,until FROM lease WHERE name='worker'").fetchone()
            if found and found["holder"] != self.holder and found["until"] > moment:
                return False
            db.execute(
                "INSERT INTO lease VALUES('worker',?,?) ON CONFLICT(name) DO UPDATE SET "
                "holder=excluded.holder,until=excluded.until",
                (self.holder, moment + LEASE_SECONDS),
            )
        return True

    def release(self):
        with self.connect(write=True) as db:
            db.execute("DELETE FROM lease WHERE name='worker' AND holder=?", (self.holder,))

    def next_work(self):
        """The first thing to do, in binder order, among active imports ready to run."""
        moment = self.clock()
        with self.connect() as db:
            for item in db.execute(
                "SELECT * FROM imports WHERE status='active' AND retry_at<=? ORDER BY created_at",
                (moment,),
            ):
                import_id = item["id"]
                page = db.execute(
                    "SELECT page FROM pages WHERE import_id=? AND status='received' "
                    "ORDER BY page LIMIT 1",
                    (import_id,),
                ).fetchone()
                if page:
                    return ("page", import_id, page[0], 0)
                # Binder order, but a pocket that failed waits behind the fresh ones:
                # a bad photo never holds up its neighbours.
                pocket = db.execute(
                    "SELECT page,position,status FROM pockets WHERE import_id=? AND status IN "
                    "('cut','read','created') AND retry_at<=? ORDER BY attempts>0,page,position "
                    "LIMIT 1",
                    (import_id, moment),
                ).fetchone()
                if pocket:
                    return (pocket["status"], import_id, pocket["page"], pocket["position"])
                page = db.execute(
                    "SELECT p.page FROM pages p WHERE p.import_id=? AND p.status='cut' AND NOT "
                    "EXISTS(SELECT 1 FROM pockets k WHERE k.import_id=p.import_id AND "
                    "k.page=p.page AND k.status IN ('cut','read','created')) ORDER BY p.page LIMIT 1",
                    (import_id,),
                ).fetchone()
                if page:
                    return ("review", import_id, page[0], 0)
        return None

    def step(self):
        """Do one step of work; returns what was done, or None when idle or not ours."""
        if not self.claim():
            return None
        work = self.next_work()
        if work is None:
            return None
        kind, import_id, page, position = work
        handler = {
            "page": self.cut,
            "cut": self.read,
            "read": self.create_copy,
            "created": self.check,
            "review": self.review_page,
        }[kind]
        try:
            handler(import_id, page, position)
        except BudgetReached:
            return ("budget", import_id, page, position)
        except Exception as error:  # noqa: BLE001 - One bad step never loops the worker.
            self.step_failed(kind, import_id, page, position, error)
        return work

    def step_failed(self, kind, import_id, page, position, error):
        """An unexpected error: the pocket waits like after a reading failure; a page says it."""
        message = str(error) if isinstance(error, (Conflict, ValueError, KeyError)) else type(error).__name__
        if position:
            self.failed(import_id, page, position, message)
            return
        with self.connect(write=True) as db:
            if kind == "page":
                db.execute(
                    "UPDATE pages SET status='error',error=?,updated_at=? WHERE import_id=? AND page=?",
                    (message, now(), import_id, page),
                )
            else:  # The review: the page is done, the agent's report says why it is empty.
                db.execute(
                    "UPDATE pages SET status='done',review_json=?,updated_at=? WHERE import_id=? "
                    "AND page=?",
                    (json.dumps({"applied": False, "error": message}), now(), import_id, page),
                )

    def run_until_idle(self, limit=None):
        """Steps until nothing is left to do now; for the command line and tests."""
        done: list = []
        while limit is None or len(done) < limit:
            work = self.step()
            if work is None:
                break
            done.append(work)
            if work[0] == "budget":
                break
        return done

    def cut(self, import_id, page, _position=0):
        with self.connect() as db:
            item = self.row(db, import_id)
            photo = db.execute(
                "SELECT photo FROM pages WHERE import_id=? AND page=?", (import_id, page)
            ).fetchone()[0]
        raw = self.uploads_dir / photo[4:] if photo.startswith("raw:") else None
        data = (raw or self.store.photos / photo).read_bytes()
        stamp = now()
        try:
            page_bytes, pockets = slice_page_photo(data, grid=item["grid"])
        except ValueError as error:
            with self.connect(write=True) as db:
                db.execute(
                    "UPDATE pages SET status='error',error=?,updated_at=? WHERE import_id=? AND page=?",
                    (str(error) + " Reprenez la photo de la page.", stamp, import_id, page),
                )
            if raw:
                raw.unlink(missing_ok=True)
            return
        reduced = self.store.save_photo(page_bytes)
        names = [(pos, self.store.save_photo(cell)) for pos, cell in pockets]
        with self.connect(write=True) as db:
            current = db.execute(
                "SELECT photo FROM pages WHERE import_id=? AND page=?", (import_id, page)
            ).fetchone()[0]
            if current != photo:
                return  # Retaken meanwhile: the new photo is cut next.
            for position, name in names:
                self.reset_pocket(db, import_id, page, position, name, "page", stamp)
            db.execute(
                "UPDATE pages SET status='cut',photo=?,error='',updated_at=? WHERE import_id=? "
                "AND page=?",
                (reduced, stamp, import_id, page),
            )
        if raw:
            raw.unlink(missing_ok=True)

    def pocket(self, db, import_id, page, position):
        return dict(db.execute(
            "SELECT * FROM pockets WHERE import_id=? AND page=? AND position=?",
            (import_id, page, position),
        ).fetchone())

    def update_pocket(self, import_id, page, position, **values):
        values["updated_at"] = now()
        columns = ",".join(f"{k}=?" for k in values)
        with self.connect(write=True) as db:
            db.execute(
                f"UPDATE pockets SET {columns} WHERE import_id=? AND page=? AND position=?",
                (*values.values(), import_id, page, position),
            )

    def spend_check(self, import_id):
        """Before a Gemini call: at the budget, the import stops and asks."""
        with self.connect(write=True) as db:
            item = self.row(db, import_id)
            spent = self.cost(db, import_id)["eur"]
            if spent < item["budget_eur"]:
                return
            db.execute(
                "UPDATE imports SET status='paused_budget',note=? WHERE id=?",
                (f"Budget de {euros(item['budget_eur'])} atteint ({euros(spent)}) : "
                 "continuer demande l’accord d’un administrateur.", import_id),
            )
            first = not item["notified_at"]
            if first:
                db.execute("UPDATE imports SET notified_at=? WHERE id=?", (self.clock(), import_id))
        if first and self.notify:
            try:
                self.notify(
                    f"Import : budget Gemini atteint ({euros(spent)})",
                    f"L’import du classeur est en pause au budget de {euros(item['budget_eur'])}. "
                    "Les pages restent prêtes : continuez depuis la gestion.",
                )
            except Exception:  # noqa: BLE001 - A notification never breaks the import.
                pass
        raise BudgetReached("Budget atteint.")

    def metered(self, import_id, page, position, step, call):
        """Run ``call`` and record the tokens of its Gemini calls, failed ones included."""
        with metering() as calls:
            try:
                return call()
            finally:
                if calls:
                    moment = self.clock()
                    with self.connect(write=True) as db:
                        db.executemany(
                            "INSERT INTO usage(import_id,page,position,step,model,input_tokens,"
                            "output_tokens,month,at) VALUES(?,?,?,?,?,?,?,?,?)",
                            [(import_id, page, position, step, c["model"], c["input_tokens"],
                              c["output_tokens"], month_of(moment), moment) for c in calls],
                        )

    def failed(self, import_id, page, position, error):
        """A transient failure: the pocket and the import wait, then try again."""
        moment = self.clock()
        with self.connect(write=True) as db:
            pocket = self.pocket(db, import_id, page, position)
            item = self.row(db, import_id)
            attempts = pocket["attempts"] + 1
            first = pocket["first_failure_at"] or moment
            delay = min(MAX_BACKOFF, 60 * 2 ** min(item["failures"], 10))
            # Its neighbours passed since it first failed: this photo is the cause.
            retake = attempts >= MAX_ATTEMPTS and item["last_success_at"] > first
            db.execute(
                "UPDATE pockets SET attempts=?,first_failure_at=?,retry_at=?,error=?,status=?,"
                "updated_at=? WHERE import_id=? AND page=? AND position=?",
                (attempts, first, moment + delay, error,
                 "failed" if retake else pocket["status"], now(), import_id, page, position),
            )
            db.execute(
                "UPDATE imports SET failures=failures+1,retry_at=?,note=? WHERE id=?",
                (moment + delay, f"Lecture indisponible, nouvel essai dans {delay // 60} min.",
                 import_id),
            )

    def succeeded(self, import_id):
        with self.connect(write=True) as db:
            db.execute(
                "UPDATE imports SET failures=0,retry_at=0,last_success_at=?,note='' WHERE id=? "
                "AND status='active'",
                (self.clock(), import_id),
            )

    def read(self, import_id, page, position):
        """Read the pocket (energy gate, then Gemini) and search the catalogue."""
        with self.connect() as db:
            pocket = self.pocket(db, import_id, page, position)
        original = (self.store.photos / pocket["photo"]).read_bytes()
        prepared, processing = prepare_photo(original)
        gated = None
        if self.gate is not None:
            with Image.open(io.BytesIO(prepared)) as image:
                gated = self.gate.check(image.convert("RGB"))
        if gated:
            from .energy_gate import gated_note

            reading = {"gated": gated, "note": gated_note(gated), "processing": processing,
                       "prepared": self.store.save_photo(prepared)}
            self.update_pocket(import_id, page, position, status="read",
                               reading_json=json.dumps(reading, ensure_ascii=False))
            self.succeeded(import_id)
            return
        self.spend_check(import_id)
        try:
            observation, raw = self.metered(
                import_id, page, position, "read", lambda: self.reader(prepared)
            )
        except ValueError as error:
            # Gemini answered: no readable front. Empty pocket, back or bad crop.
            self.update_pocket(
                import_id, page, position, status="retake",
                error="Pochette vide ou recto illisible : reprenez la carte, ou marquez la "
                "pochette vide. " + str(error)[:300],
            )
            self.succeeded(import_id)
            return
        except Exception as error:  # noqa: BLE001 - Provider errors stay generic.
            self.failed(import_id, page, position,
                        str(error) if isinstance(error, RuntimeError) else type(error).__name__)
            return
        query = {k: observation[k] for k in ("name", "number", "language", "hp")}
        search = self.lookup(query)
        if not search.get("candidates") and self.suggest and query["name"].strip():
            try:
                search = {**search, **self.suggest(prepared, query), "exact": False}
            except Exception:  # noqa: BLE001 - A suggestion is a help, never a blocker.
                pass
        reading = {
            "observation": observation,
            "raw_response": raw,
            "search": {"query": query, **search},
            "processing": processing,
            "prepared": self.store.save_photo(prepared),
        }
        self.update_pocket(import_id, page, position, status="read",
                           reading_json=json.dumps(reading, ensure_ascii=False))
        self.succeeded(import_id)

    def values_for(self, item, page, position, reading):
        """The copy a reading describes: an exact edition is kept, never confirmed."""
        base = {
            "album_id": item["album_id"],
            "page": page,
            "position": position,
            "identification_status": "review",
            "source_key": f"binder:{item['id']}:{page}:{position}",
        }
        if reading.get("gated"):
            return {**base, "name": "Énergie de base", "set_name": "", "number": "",
                    "language": "unknown", "notes": reading["note"]}, None
        observation, search = reading["observation"], reading["search"]
        candidates = search.get("candidates") or []
        chosen = candidates[0] if search.get("exact") and len(candidates) == 1 else None
        language = observation["language"] if observation["language"] in (
            "fr", "en", "ja", "de", "es", "it", "pt", "ko", "zh") else "unknown"
        values = {
            **base,
            "name": observation["name"].strip()[:256] or "À identifier",
            "set_name": "",
            "number": observation["number"].strip()[:80],
            "language": language,
            "hp": observation["hp"],
            "notes": (observation.get("notes") or "")[:2000],
        }
        if chosen:
            values.update(
                name=chosen["name"], set_name=chosen["set_name"], number=chosen["number"],
                language=chosen["language"], catalog_id=chosen["id"],
                hp=chosen["hp"] if isinstance(chosen.get("hp"), int) else observation["hp"],
            )
        return values, chosen

    def create_copy(self, import_id, page, position):
        """Create (once) or update the pocket's copy, « à vérifier »."""
        with self.connect() as db:
            item = self.row(db, import_id)
            pocket = self.pocket(db, import_id, page, position)
        reading = json.loads(pocket["reading_json"])
        values, chosen = self.values_for(item, page, position, reading)
        evidence = {
            "type": "binder-import",
            "import_id": import_id,
            "page": page,
            "position": position,
            "model": None if reading.get("gated") else "gemini",
            "observation": reading.get("observation"),
            "raw_response": reading.get("raw_response", ""),
            "searches": [reading["search"]] if reading.get("search") else [],
            "gated": reading.get("gated"),
            "chosen_catalog_id": chosen["id"] if chosen else None,
            "chosen_proposed_by": (chosen or {}).get("proposed_by", "catalogue") if chosen else None,
            "exact_catalogue_match": bool(chosen),
            "human_confirmed": False,
            "photo_preparation": {
                "original_photo": pocket["photo"],
                "prepared_photo": reading["prepared"],
                "processing": reading.get("processing"),
            },
        }
        copy_id = pocket["copy_id"] or copy_id_for(import_id, page, position)
        with self.store.connect() as db:
            existing = db.execute(
                "SELECT version,photo,identification_status FROM copies WHERE id=?", (copy_id,)
            ).fetchone()
        if existing is None:
            card = self.store.create_copy(
                {**values, "photo": reading["prepared"], "photo_original": pocket["photo"]},
                ACTOR,
                f"Import du classeur, page {page}, pochette {position}",
                copy_id=copy_id,
                evidence=evidence,
            )
        elif existing["photo"] == reading["prepared"]:
            # The step ran before the state was saved: the copy is already there.
            with self.store.connect() as db:
                card = self.store.get(db, copy_id)
        else:
            # A retake: the new photo replaces the old one. The identity follows the
            # new reading only while nobody touched the copy since the import wrote it.
            changes = {"photo": reading["prepared"], "photo_original": pocket["photo"],
                       "condition_confirmed": False}
            untouched = (existing["version"] == pocket["copy_version"]
                         and existing["identification_status"] == "review")
            if untouched:
                changes.update({k: v for k, v in values.items()
                                if k not in ("album_id", "page", "position", "source_key")})
                changes.setdefault("catalog_id", None)
            try:
                card = self.store.patch(
                    copy_id, changes, existing["version"], ACTOR,
                    f"Import du classeur : nouvelle photo, page {page}, pochette {position}",
                    evidence=evidence,
                )
            except Conflict as error:
                self.update_pocket(import_id, page, position, status="retake", error=str(error))
                return
        self.update_pocket(import_id, page, position, status="created", copy_id=copy_id,
                           copy_version=card["version"])

    def check(self, import_id, page, position):
        """The intake checks on the new copy: finish, edition, condition."""
        with self.connect() as db:
            pocket = self.pocket(db, import_id, page, position)
        if self.checks is not None:
            self.spend_check(import_id)
            try:
                self.metered(import_id, page, position, "checks",
                             lambda: self.checks(pocket["copy_id"]))
            except Exception as error:  # noqa: BLE001 - The checks log their own failures.
                self.failed(import_id, page, position, type(error).__name__)
                return
        with self.store.connect() as db:
            version = self.store.get(db, pocket["copy_id"])["version"]
        self.update_pocket(import_id, page, position, status="checked", copy_version=version)
        self.succeeded(import_id)

    def review_page(self, import_id, page, _position=0):
        """The review agent on the page's copies, written only when the setting allows."""
        with self.connect() as db:
            ids = [r[0] for r in db.execute(
                "SELECT copy_id FROM pockets WHERE import_id=? AND page=? AND status='checked' "
                "ORDER BY position", (import_id, page))]
        report: dict[str, Any] = {"applied": False, "confirmed": 0, "photo_requests": 0, "skipped": 0}
        if self.review is not None and ids:
            apply = bool(self.apply())
            result = self.review(ids, apply)
            report = {
                "applied": apply,
                "run_id": result.get("run_id"),
                "confirmed": len(result.get("confirmed", [])),
                "photo_requests": len(result.get("photo_requests", [])),
                "skipped": len(result.get("skipped", [])),
                "would_confirm": [c["copy_id"] for c in result.get("confirmed", [])],
            }
        with self.connect(write=True) as db:
            db.execute(
                "UPDATE pages SET status='done',review_json=?,updated_at=? WHERE import_id=? "
                "AND page=?",
                (json.dumps(report), now(), import_id, page),
            )
