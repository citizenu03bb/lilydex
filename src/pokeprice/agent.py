"""Album-scoped agent access: reads, sale drafts and operator-approved corrections."""

import hashlib
import json
import re
import secrets
import time
import uuid
from collections import Counter, defaultdict

from .inventory import Conflict, now

SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS agent_grants(
 id TEXT PRIMARY KEY, name TEXT NOT NULL,
 owner_id TEXT NOT NULL REFERENCES users(id), album_id TEXT NOT NULL REFERENCES albums(id),
 token_hash TEXT UNIQUE, permissions_json TEXT NOT NULL, client TEXT NOT NULL,
 value_ceiling_cents INTEGER NOT NULL CHECK(value_ceiling_cents>0),
 expires_at INTEGER NOT NULL, revoked_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agent_drafts(
 sale_id TEXT PRIMARY KEY REFERENCES sales(id), grant_id TEXT NOT NULL REFERENCES agent_grants(id),
 request_key TEXT NOT NULL, content_sha256 TEXT NOT NULL, request_id TEXT NOT NULL,
 snapshot_json TEXT NOT NULL, response_json TEXT NOT NULL,
 amount_known INTEGER NOT NULL DEFAULT 0 CHECK(amount_known IN (0,1)), created_at TEXT NOT NULL,
 UNIQUE(grant_id,request_key));
PRAGMA user_version=18;
COMMIT;
"""
PERMISSIONS = frozenset(
    {"copies:read", "photos:read", "drafts:create", "corrections:apply"}
)
MAX_ALBUM_COPIES = 2000
MAX_DRAFT_COPIES = 20
CARD_FIELDS = (
    "id",
    "version",
    "name",
    "set_name",
    "number",
    "language",
    "catalog_id",
    "album_id",
    "album",
    "page",
    "position",
    "identification_status",
    "condition",
    "condition_confirmed",
    "finish",
    "foil",
    "variant_confirmed",
    "stamp",
    "stamp_state",
    "distribution",
    "distribution_state",
    "stock_state",
    "reference_cents",
    "price_source",
    "price_date",
)
VALUATION_FIELDS = (
    "trend_cents",
    "prudent_cents",
    "sale_estimate_cents",
    "risk_cents",
    "risk_incomplete",
    "is_valuable",
    "needs_review",
    "market_unstable",
)


class AgentError(ValueError):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code = status, code


def digest(body):
    return hashlib.sha256(body.encode()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def disable_tokens(db):
    """Also handles archives from before agent access existed."""
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='agent_grants'").fetchone():
        db.execute(
            "UPDATE agent_grants SET token_hash=NULL,revoked_at=CASE WHEN revoked_at='' THEN ? ELSE revoked_at END",
            (now(),),
        )


class AgentService:
    def __init__(self, store):
        self.store = store

    def issue(
        self,
        name,
        owner,
        album,
        *,
        permissions=("copies:read",),
        days=7,
        client="",
        value_ceiling_cents=1000,
    ):
        permissions = set(permissions) | {"copies:read"}
        if not permissions <= PERMISSIONS or not 1 <= days <= 30:
            raise ValueError(
                "Permissions ou expiration agent invalides (1 à 30 jours)."
            )
        if (
            not name.strip()
            or len(name) > 120
            or not client.strip()
            or len(client) > 500
        ):
            raise ValueError("Indiquez un nom et le client destinataire des données.")
        if not 1 <= value_ceiling_cents <= 1000000:
            raise ValueError("Plafond de valeur invalide.")
        token = "pp_agent_" + secrets.token_urlsafe(32)
        grant_id = str(uuid.uuid4())
        with self.store.connect(write=True) as db:
            user = db.execute(
                "SELECT id,role FROM users WHERE username=? AND disabled=0 AND status='active'",
                (owner,),
            ).fetchone()
            if not user or user["role"] not in ("admin", "editor", "reader"):
                raise ValueError("Compte délégant de gestion actif requis.")
            if "drafts:create" in permissions and user["role"] == "reader":
                raise ValueError("Un lecteur ne peut pas déléguer la création de lots.")
            if "corrections:apply" in permissions and user["role"] == "reader":
                raise ValueError("Un lecteur ne peut pas déléguer des corrections.")
            if not db.execute("SELECT 1 FROM albums WHERE id=?", (album,)).fetchone():
                raise ValueError("Album inconnu.")
            db.execute(
                "INSERT INTO agent_grants VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    grant_id,
                    name.strip(),
                    user["id"],
                    album,
                    digest(token),
                    canonical(sorted(permissions)),
                    client.strip(),
                    value_ceiling_cents,
                    int(time.time()) + days * 86400,
                    "",
                    now(),
                ),
            )
        return {
            "id": grant_id,
            "token": token,
            "album_id": album,
            "permissions": sorted(permissions),
            "expires_in_days": days,
        }

    def grants(self):
        with self.store.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT g.id,g.name,g.album_id,g.client,g.permissions_json,g.expires_at,g.revoked_at,"
                    "g.created_at,u.username owner FROM agent_grants g JOIN users u ON u.id=g.owner_id "
                    "ORDER BY g.created_at,g.id"
                )
            ]

    def revoke(self, grant_id):
        with self.store.connect(write=True) as db:
            changed = db.execute(
                "UPDATE agent_grants SET revoked_at=?,token_hash=NULL WHERE id=?",
                (now(), grant_id),
            ).rowcount
            if not changed:
                raise KeyError("Accès agent inconnu.")
        return {"id": grant_id, "revoked": True}

    @staticmethod
    def authorize(db, token_hash, permission="copies:read"):
        row = db.execute(
            "SELECT g.*,u.role FROM agent_grants g JOIN users u ON u.id=g.owner_id "
            "WHERE g.token_hash=? AND g.revoked_at='' AND g.expires_at>? "
            "AND u.disabled=0 AND u.status='active' AND u.role IN ('admin','editor','reader')",
            (token_hash, int(time.time())),
        ).fetchone()
        if not row:
            raise AgentError(
                401, "unauthenticated", "Accès agent absent, expiré ou révoqué."
            )
        grant = dict(row)
        grant["permissions"] = set(json.loads(grant["permissions_json"]))
        if grant["role"] == "reader":
            grant["permissions"].discard("drafts:create")
            grant["permissions"].discard("corrections:apply")
        if permission not in grant["permissions"]:
            raise AgentError(403, "forbidden", "Opération non déléguée à cet agent.")
        return grant

    @staticmethod
    def scoped_card(db, grant, copy_id):
        row = db.execute(
            "SELECT c.*,a.name album FROM copies c JOIN albums a ON a.id=c.album_id "
            "WHERE c.id=? AND c.album_id=? AND c.deleted_at=''",
            (copy_id, grant["album_id"]),
        ).fetchone()
        if not row:
            raise AgentError(404, "not_found", "Exemplaire introuvable.")
        return dict(row)

    def facts(self, db, grant):
        """One read snapshot, whitelisted output; private notes never affect search."""
        rows = db.execute(
            "SELECT c.*,a.name album FROM copies c JOIN albums a ON a.id=c.album_id "
            "WHERE c.album_id=? AND c.deleted_at='' ORDER BY c.page,c.position,c.id LIMIT ?",
            (grant["album_id"], MAX_ALBUM_COPIES + 1),
        ).fetchall()
        if len(rows) > MAX_ALBUM_COPIES:
            raise AgentError(
                422,
                "album_too_large",
                "Album limité à 2 000 exemplaires pour ce pilote.",
            )
        context = self.store.valuation_context(db)
        published = {
            r[0] for r in db.execute("SELECT copy_id FROM listing_items WHERE active=1")
        }
        output = []
        for row in rows:
            card = dict(row)
            metadata = self.store.category_metadata(card, context)
            card["reference_resolution"] = self.store.reference.decision_for(
                db, card, metadata
            )
            source = db.execute(
                "SELECT raw_json FROM sources WHERE copy_id=?", (card["id"],)
            ).fetchone()
            valuation = self.store.valuation(
                card,
                context,
                json.loads(source[0]) if source else None,
                threshold_cents=grant["value_ceiling_cents"],
            )
            projected = {k: card[k] for k in CARD_FIELDS}
            projected["published"] = card["id"] in published
            projected["has_front"] = bool(card["photo"])
            projected["has_back"] = bool(card["back_photo"])
            projected["valuation"] = {k: valuation[k] for k in VALUATION_FIELDS}
            # Codes suffice for the client; raw model responses and free text stay private.
            projected["valuation"]["review_codes"] = [
                r["code"] for r in valuation["reasons"]
            ]
            output.append(projected)
        return output

    @staticmethod
    def group_key(card):
        if (
            not card["catalog_id"]
            or not card["finish"]
            or not card["variant_confirmed"]
            or card["stamp_state"] == "unobserved"
            or card["distribution_state"] == "unobserved"
        ):
            return None
        return tuple(
            card[k]
            for k in (
                "catalog_id",
                "language",
                "finish",
                "stamp_state",
                "stamp",
                "distribution_state",
                "distribution",
            )
        )

    @staticmethod
    def exclusions(card):
        result = []
        value = card["valuation"]
        if card["stock_state"] != "available":
            result.append("stock_unavailable")
        if card["published"]:
            result.append("already_published")
        if card["identification_status"] != "confirmed":
            result.append("identity_unconfirmed")
        if AgentService.group_key(card) is None:
            result.append("physical_details_unknown")
        if value["risk_incomplete"] or value["prudent_cents"] is None:
            result.append("price_incomplete")
        if value["needs_review"]:
            result.append("review_needed")
        if value["is_valuable"]:
            result.append("valuable_card")
        return result

    def prepare(self, cards, *, keep=1, maximum=20, language=""):
        groups = defaultdict(list)
        excluded = []
        for card in cards:
            reasons = self.exclusions(card)
            if language and card["language"] != language:
                reasons.append("other_language")
            if reasons:
                excluded.append({"copy": card, "reasons": reasons})
            else:
                groups[self.group_key(card)].append(card)
        selected, retained = [], []
        for group in groups.values():
            retained.extend(group[:keep])
            for card in group[keep:]:
                if len(selected) < maximum:
                    selected.append(card)
                else:
                    excluded.append({"copy": card, "reasons": ["lot_limit"]})
        return {
            "selected": selected,
            "retained": retained,
            "excluded": excluded,
            "keep_per_reference": keep,
            "maximum": maximum,
            "selection_rule": "Premiers exemplaires dans l’ordre page/pochette conservés ; seules les variantes documentées sont regroupées.",
            "reference_subtotal_cents": sum(
                c["valuation"]["prudent_cents"] for c in selected
            )
            if selected
            else None,
            "currency": "EUR",
            "asking_cents": None,
            "description": self.description(selected),
        }

    @staticmethod
    def description(cards):
        finishes = {
            "non_holo": "mate",
            "holo": "illustration holographique",
            "holo_border": "bordure holographique",
            "reverse": "reverse",
            "special": "spéciale",
        }
        lines = [f"Lot de {len(cards)} carte(s) Pokémon — brouillon à relire."]
        for card in cards:
            grade = (
                card["condition"]
                if card["condition_confirmed"] and card["condition"]
                else "état à vérifier"
            )
            marks = "".join(
                f" ; {label} : {card[field]}"
                for field, label in (
                    ("stamp", "tampon"),
                    ("distribution", "marque de distribution"),
                )
                if card.get(field + "_state") == "present"
            )
            lines.append(
                f"- {card['name']} · {card['set_name']} · {card['number']} · {card['language'].upper()} ; {grade} ; finition {finishes.get(card['finish'], 'à vérifier')}{marks}."
            )
        lines.append(
            "Prix demandé, livraison et paiement à préciser. Aucun exemplaire réservé."
        )
        return "\n".join(lines)

    def create_draft(self, token_hash, key, payload, request_id):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", key):
            raise AgentError(
                422, "invalid_key", "Clé Idempotency-Key requise (1 à 120 caractères)."
            )
        fingerprint = digest(canonical(payload))
        with self.store.connect(write=True) as db:
            grant = self.authorize(db, token_hash, "drafts:create")
            previous = db.execute(
                "SELECT * FROM agent_drafts WHERE grant_id=? AND request_key=?",
                (grant["id"], key),
            ).fetchone()
            if previous:
                if previous["content_sha256"] != fingerprint:
                    raise AgentError(
                        409,
                        "idempotency_conflict",
                        "Clé déjà utilisée pour un autre contenu.",
                    )
                self.check_draft_scope(db, grant, previous)
                return json.loads(previous["response_json"])
            if (
                db.execute(
                    "SELECT count(*) FROM agent_drafts WHERE grant_id=?", (grant["id"],)
                ).fetchone()[0]
                >= 100
            ):
                raise AgentError(
                    429,
                    "draft_limit",
                    "Limite de 100 brouillons par délégation atteinte.",
                )
            requested = payload["copies"]
            if not 1 <= len(requested) <= MAX_DRAFT_COPIES:
                raise ValueError("Un lot contient de 1 à 20 exemplaires.")
            if len({item["id"] for item in requested}) != len(requested):
                raise ValueError("Sélectionnez des exemplaires distincts.")
            facts = self.facts(db, grant)
            by_id = {c["id"]: c for c in facts}
            selected = []
            for item in requested:
                card = by_id.get(item["id"])
                if card is None:
                    raise AgentError(404, "not_found", "Exemplaire introuvable.")
                if card["version"] != item["expected_version"]:
                    raise Conflict("Une fiche a changé. Préparez de nouveau le lot.")
                if self.exclusions(card):
                    raise Conflict(
                        "Une carte est indisponible, à vérifier ou exclue du lot prudent."
                    )
                selected.append(card)
            available = Counter(
                self.group_key(c) for c in facts if not self.exclusions(c)
            )
            chosen = Counter(self.group_key(c) for c in selected)
            if any(
                available[k] - n < payload.get("keep_per_reference", 1)
                for k, n in chosen.items()
            ):
                raise Conflict(
                    "Conservez le nombre demandé d’exemplaires de chaque référence dans l’album."
                )
            sale_id = self.store.create_sale(
                {"title": payload["title"], "amount_cents": 0},
                [c["id"] for c in selected],
                "agent:" + grant["id"],
                _db=db,
            )
            snapshot = {
                "copies": selected,
                "description": payload["description"] or self.description(selected),
                "reason": payload["reason"],
                "origin": "agent",
                "delegated_by": grant["owner_id"],
            }
            response = {
                "id": sale_id,
                "status": "draft",
                "copy_ids": [c["id"] for c in selected],
                "amount_cents": None,
                "asking_cents": None,
                "created_at": now(),
                "request_id": request_id,
            }
            db.execute(
                "INSERT INTO agent_drafts(sale_id,grant_id,request_key,content_sha256,request_id,"
                "snapshot_json,response_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    sale_id,
                    grant["id"],
                    key,
                    fingerprint,
                    request_id,
                    canonical(snapshot),
                    canonical(response),
                    response["created_at"],
                ),
            )
            return response

    def check_draft_scope(self, db, grant, row):
        if row["grant_id"] != grant["id"]:
            raise AgentError(404, "not_found", "Brouillon introuvable.")
        snapshot = json.loads(row["snapshot_json"])
        for card in snapshot["copies"]:
            self.scoped_card(db, grant, card["id"])
        return snapshot

    def get_draft(self, db, grant, sale_id):
        row = db.execute(
            "SELECT * FROM agent_drafts WHERE sale_id=?", (sale_id,)
        ).fetchone()
        if row is None:
            raise AgentError(404, "not_found", "Brouillon introuvable.")
        snapshot = self.check_draft_scope(db, grant, row)
        versions = {
            c["id"]: self.scoped_card(db, grant, c["id"])["version"]
            for c in snapshot["copies"]
        }
        sale = db.execute("SELECT status FROM sales WHERE id=?", (sale_id,)).fetchone()
        return {
            **json.loads(row["response_json"]),
            "status": sale[0],
            "copies": snapshot["copies"],
            "description": snapshot["description"],
            "reason": snapshot["reason"],
            "origin": "agent",
            "stale": any(versions[c["id"]] != c["version"] for c in snapshot["copies"]),
        }
