"""Read-only reference audit and explicitly versioned decision records.

The first rules release is an audit release. It does not replace the legacy
price selection, certify inherited quotes, or rewrite physical observations.
"""

import json
import hashlib
import sqlite3
from contextlib import nullcontext
from collections import Counter
from importlib.resources import files
from pathlib import Path

from .print_reference import (
    ENGINE_VERSION,
    InvalidReference,
    canonical,
    copy_observations,
    load_ruleset,
    quote_selection,
    resolve,
    validate_ruleset,
)


# Engine sources whose semantics match the golden vectors of their version
# (tests/fixtures/engine_vectors.json). A source edit that keeps the semantics
# adds its digest here; a semantic change requires a new ENGINE_VERSION.
ENGINE_SOURCES = {
    "2": {"70126324f8cb088fa38685e371a1ee15832126aec15060f28ff204506911dbcc"},
}


def engine_source():
    return files("pokeprice").joinpath("print_reference.py").read_text()


def engine_digest(source=None):
    return hashlib.sha256((source or engine_source()).encode()).hexdigest()


def inputs_for(card, snapshot=None, disputes=(), available_documents=None):
    return {
        "identity": {
            k: card.get(k)
            for k in ("catalog_id", "language", "number", "identification_status")
        },
        "observations": copy_observations(card),
        "catalogue": snapshot,
        "disputes": list(disputes),
        "available_documents": available_documents,
    }


def legacy_quote(card):
    if card.get("reference_cents") is None:
        return None
    return {
        "binding_key": None,
        "metric": "manual_reference"
        if not (card.get("price_source") or "").startswith("TCGdex")
        else "unknown",
        "amount_cents": card["reference_cents"],
        "currency": "EUR",
        "source": card.get("price_source", ""),
        "observed_at": card.get("price_date", ""),
        "copy_version": card.get("version"),
    }


class ReferenceService:
    def __init__(self, store=None, ruleset=None, archive_root=None):
        self.store = store
        self.archive_root = (
            Path(archive_root)
            if archive_root
            else store.root / "reference_documents"
            if store
            else None
        )
        self._document_cache = (None, [])
        self.error = None
        try:
            self.ruleset = ruleset or load_ruleset()
        except InvalidReference as exc:
            self.ruleset = None
            self.error = str(exc)

    def available_documents(self):
        if not self.archive_root or not self.archive_root.exists():
            return []
        paths = sorted(
            p
            for p in self.archive_root.iterdir()
            if p.is_file() and p.suffix in (".pdf", ".json", ".html")
        )
        signature = tuple(
            (p.name, p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ctime_ns)
            for p in paths
        )
        if signature != self._document_cache[0]:
            self._document_cache = (
                signature,
                sorted(
                    {
                        p.stem
                        for p in paths
                        if hashlib.sha256(p.read_bytes()).hexdigest() == p.stem
                    }
                ),
            )
        return self._document_cache[1].copy()

    def decision(self, card, snapshot=None, disputes=(), selection=None):
        if self.ruleset is None:
            return {
                "mode": "audit",
                "print_status": "uncovered",
                "market_status": "uncovered",
                "pricing_eligible": False,
                "selected_binding_key": None,
                "foil_projection": None,
                "coverage_needed": True,
                "reason_codes": ["invalid_reference"],
                "diagnostic": self.error,
                "price_selection": quote_selection(
                    selection["quote"] if selection else legacy_quote(card),
                    {"pricing_eligible": False},
                    selection["state"] if selection else "active",
                ),
            }
        result = resolve(
            **inputs_for(card, snapshot, disputes, self.available_documents()),
            ruleset=self.ruleset,
        )
        return {
            **result,
            "mode": "audit",
            "coverage_needed": result["market_status"] != "verified",
            "price_selection": quote_selection(
                selection["quote"], result, selection["state"]
            )
            if selection
            else quote_selection(legacy_quote(card), result),
        }

    def decision_for(self, db, card, snapshot=None):
        from .quote_ledger import current

        return self.decision(
            card, snapshot, self.disputes(db, card["id"]), current(db, card["id"])
        )

    def dispute(self, copy_id, expected_version, active, affects, actor, reason):
        """Record a dispute; a bound price it blocks is suspended in the journal."""
        from .inventory import Conflict, now
        from .quote_ledger import current, suspend

        with self.store.connect(write=True) as db:
            before = self.disputes(db, copy_id)
            card = self.store.get(db, copy_id)
            if card["version"] != expected_version or card["deleted_at"]:
                raise Conflict("La fiche a changé. Rechargez-la avant de contester.")
            record = {
                "active": active,
                "affects": affects,
                "actor": actor,
                "reason": reason,
                "created_at": now(),
                "copy_version": expected_version + 1,
            }
            selection = current(db, copy_id)
            resolution = self.decision(card, disputes=[record])
            if (
                selection
                and selection["state"] == "active"
                and quote_selection(selection["quote"], resolution)["state"] != "active"
            ):
                after = suspend(
                    self.store, db, card, selection, resolution, actor, reason
                )
            else:
                db.execute(
                    "UPDATE copies SET version=version+1,updated_at=? WHERE id=?",
                    (now(), copy_id),
                )
                after = self.store.get(db, copy_id)
            self.store.event(
                db, copy_id, actor, "reference-dispute", reason, before, record
            )
            return {
                **after,
                "reference_resolution": self.decision(
                    after,
                    self.store.category_snapshot(db, after),
                    [record],
                    current(db, copy_id),
                ),
            }

    @staticmethod
    def disputes(db, copy_id):
        row = db.execute(
            "SELECT after_json FROM events WHERE copy_id=? AND kind='reference-dispute' ORDER BY id DESC LIMIT 1",
            (copy_id,),
        ).fetchone()
        return [json.loads(row[0])] if row else []

    def record(self, copy_id, expected_version, actor, reason, *, _db=None):
        """Record reproducible inputs/result, without changing any copy field."""
        from .inventory import Conflict, now

        if not reason.strip() or not actor.strip():
            raise ValueError("Auteur et motif requis.")
        if self.ruleset is None:
            raise InvalidReference(self.error)
        with self.store.connect(write=True) if _db is None else nullcontext(_db) as db:
            card = self.store.get(db, copy_id)
            if card["version"] != expected_version or card["deleted_at"]:
                raise Conflict("La fiche a changé. Relancez l’audit.")
            inputs = inputs_for(
                card,
                self.store.category_snapshot(db, card),
                self.disputes(db, copy_id),
                self.available_documents(),
            )
            result = resolve(**inputs, ruleset=self.ruleset)
            source = engine_source()
            # The ruleset row keeps its first engine only for older readers; each
            # decision names the exact engine that produced it.
            db.execute(
                "INSERT OR IGNORE INTO reference_rulesets VALUES(?,?,?,?,?)",
                (
                    self.ruleset.hash,
                    self.ruleset.content,
                    ENGINE_VERSION,
                    source,
                    now(),
                ),
            )
            db.execute(
                "INSERT OR IGNORE INTO reference_engines VALUES(?,?,?,?)",
                (engine_digest(source), ENGINE_VERSION, source, now()),
            )
            cursor = db.execute(
                "INSERT INTO reference_decisions(copy_id,copy_version,rules_hash,inputs_json,result_json,actor,reason,created_at,engine_sha256) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    copy_id,
                    expected_version,
                    self.ruleset.hash,
                    canonical(inputs),
                    canonical(result),
                    actor,
                    reason,
                    now(),
                    engine_digest(source),
                ),
            )
            return {
                "id": cursor.lastrowid,
                "copy_version": expected_version,
                "resolution": result,
            }

    def replay(self, decision_id):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT d.*,r.content_json,e.engine_version FROM reference_decisions d JOIN reference_rulesets r ON r.hash=d.rules_hash LEFT JOIN reference_engines e ON e.sha256=d.engine_sha256 WHERE d.id=?",
                (decision_id,),
            ).fetchone()
        if row is None:
            raise KeyError("Décision introuvable.")
        # Archived code is never executed: only a registered compatible engine replays.
        compatible = ENGINE_SOURCES.get(ENGINE_VERSION, set())
        if (
            row["engine_version"] != ENGINE_VERSION
            or row["engine_sha256"] not in compatible
            or engine_digest() not in compatible
        ):
            return {
                "id": decision_id,
                "status": "unreproducible",
                "reason": "engine_unavailable",
                "recorded_result": json.loads(row["result_json"]),
            }
        rules = validate_ruleset(json.loads(row["content_json"]))
        result = resolve(**json.loads(row["inputs_json"]), ruleset=rules)
        needed = {
            rules.data["evidence"][i]["document_sha256"] for i in result["evidence_ids"]
        }
        missing = sorted(needed - set(self.available_documents()))
        return {
            "id": decision_id,
            "status": "reproduced"
            if rules.hash == row["rules_hash"]
            and canonical(result) == row["result_json"]
            else "mismatch",
            "resolution": result,
            "proof_status": "unavailable" if missing else "available",
            "missing_documents": missing,
        }

    def audit(self, db=None):
        if db is None:
            with self.store.connect() as connection:
                return self.audit(connection)
        db.execute("BEGIN") if not db.in_transaction else None
        groups = {}
        counts = Counter()
        items = []
        has_quotes = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='reference_quote_events'"
        ).fetchone()
        verified_amounts = []
        for row in db.execute("SELECT * FROM copies WHERE deleted_at='' ORDER BY id"):
            card = dict(row)
            result = (
                self.decision_for(db, card)
                if has_quotes
                else self.decision(card, disputes=self.disputes(db, card["id"]))
            )
            state = result["price_selection"]["state"]
            quote = result["price_selection"]["quote"]
            if has_quotes:
                from .quote_ledger import current

                journal = current(db, card["id"])
                # A computed suspension not yet journaled: `reference-recheck --apply`.
                counts["recheck_needed"] += bool(
                    journal and journal["state"] == "active" and state != "active"
                )
            if state == "active" and quote and quote.get("currency") == "EUR":
                verified_amounts.append(quote["amount_cents"])
            counts[state] += 1
            counts["coverage_needed"] += result["coverage_needed"]
            counts["copies"] += 1
            key = (
                (card.get("catalog_id") or "unidentified").rsplit("-", 1)[0],
                card["language"],
            )
            group = groups.setdefault(
                key,
                {
                    "set_id": key[0],
                    "language": key[1],
                    "copies": 0,
                    "coverage_needed": 0,
                    "missing_prices": 0,
                },
            )
            group["copies"] += 1
            group["coverage_needed"] += result["coverage_needed"]
            group["missing_prices"] += card["reference_cents"] is None
            items.append(
                {
                    "copy_id": card["id"],
                    "expected_version": card["version"],
                    "name": card["name"],
                    "resolution": result,
                }
            )
        return {
            "mode": "audit",
            "activation_ready": False,
            "diagnostic": self.error,
            "rules_hash": self.ruleset.hash if self.ruleset else None,
            "counts": dict(counts),
            "groups": [groups[k] for k in sorted(groups)],
            "items": items,
            "verified_reference_total_cents": sum(verified_amounts)
            if verified_amounts
            else None,
        }


def audit_directory(directory, ruleset=None):
    """CLI audit must not initialize, migrate or modify the collection database."""
    database = Path(directory).resolve() / "collection.sqlite3"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        return ReferenceService(
            ruleset=ruleset,
            archive_root=Path(directory).resolve() / "reference_documents",
        ).audit(db)


def archive_document(directory, document):
    """Store a source once by content hash, beside the collection and in its backups."""
    source = Path(document)
    if source.suffix not in (".pdf", ".json", ".html"):
        raise ValueError("Pièce acceptée : PDF, HTML ou JSON.")
    body = source.read_bytes()
    checksum = hashlib.sha256(body).hexdigest()
    target = Path(directory).resolve() / "reference_documents"
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = target / (checksum + source.suffix)
    if not path.exists():
        path.write_bytes(body)
        path.chmod(0o600)
    return {"document_sha256": checksum, "path": str(path), "bytes": len(body)}
