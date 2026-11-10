"""Composition de lots par l'API agent : créer, faire tourner, annuler, relever.

Chaque écriture suit le même ordre, dans une seule transaction
``BEGIN IMMEDIATE`` : autorisation ``lots:compose``, recherche de la clé
d'idempotence, quotas, validations recalculées sur cette connexion, écritures.
Les écritures se sérialisant, deux compositions concurrentes ne prennent jamais
le même exemplaire : la seconde voit le premier brouillon et son plan change.

Rien dans une requête ne choisit les cartes, le bonus, l'auteur, la marge, le
plancher, le périmètre ni le plafond de brouillons. Le prix ne descend jamais
sous le plancher anti-bradage du jour : un prix calculé dessous y est relevé.
Seuls les brouillons de l'outil des lots s'annulent, et jamais celui dont le lot
est en ligne.

Ni table ni migration : les opérations réussies sont des événements
``lot-op`` (clé, opération, empreinte de la requête, réponse) et les refus des
événements ``lot-denied``, tous sans exemplaire (``copy_id`` NULL). Les quotas
du jour se comptent sur eux.
"""

import json
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Header, Path, Request
from pydantic import Field

from .agent import AgentError, AgentService, canonical, digest, lots_ceiling_cents
from .inventory import Conflict, now
from .lots import MAX_ROTATION_DRAFTS, LotsEngine, RotationPlan
from .lots.agent_recipe import MAX_CENTS, AgentRecipe, StrictModel, lot_plan_id, safe_text, split_bonus, to_recipe
from .lots.settings import lot_rotation_days
from .pricing import FLOOR_CENTS, lot_floor_cents, lot_max_margin

COMPOSE = "lots:compose"
OP_EVENT = "lot-op"
DENIED_EVENT = "lot-denied"
# Quotas par accès et par jour (UTC).
DAILY_DRAFTS = 20
DAILY_REFUSALS = 100
KEY = re.compile(r"[A-Za-z0-9_.:-]{1,120}")
SALE_ID = r"^[A-Za-z0-9-]{1,64}$"
# Refus jamais journalisés : sans accès reconnu, ou quand c'est déjà une limite.
UNJOURNALED = {401, 403, 429}

Card = dict[str, Any]
Work = Callable[[sqlite3.Connection, Card, LotsEngine], tuple[Card, int]]


class ComposeRequest(StrictModel):
    recipe: AgentRecipe
    plan_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    asking_cents: Optional[int] = Field(None, ge=1, le=MAX_CENTS)


class RotateRequest(StrictModel):
    dry_run: bool = True
    limit: Optional[int] = Field(None, ge=0, le=MAX_ROTATION_DRAFTS)


class CancelRequest(StrictModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class RaiseRequest(StrictModel):
    expected_version: int = Field(ge=1)
    asking_cents: int = Field(ge=1, le=MAX_CENTS)


def actor_of(grant: Card) -> str:
    return "agent:" + grant["id"]


def today() -> str:
    return now()[:10]


def stored_operation(db: sqlite3.Connection, actor: str, key: str) -> Optional[Card]:
    row = db.execute(
        "SELECT after_json FROM events WHERE kind=? AND actor=? AND copy_id IS NULL "
        "AND json_extract(after_json,'$.key')=? ORDER BY id LIMIT 1",
        (OP_EVENT, actor, key),
    ).fetchone()
    return json.loads(row[0]) if row else None


def drafts_created_today(db: sqlite3.Connection, actor: str) -> int:
    row = db.execute(
        "SELECT coalesce(sum(json_extract(after_json,'$.drafts_created')),0) FROM events "
        "WHERE kind=? AND actor=? AND copy_id IS NULL AND created_at>=?",
        (OP_EVENT, actor, today()),
    ).fetchone()
    return int(row[0])


def refusals_today(db: sqlite3.Connection, actor: str) -> int:
    row = db.execute(
        "SELECT count(*) FROM events WHERE kind=? AND actor=? AND copy_id IS NULL AND created_at>=?",
        (DENIED_EVENT, actor, today()),
    ).fetchone()
    return int(row[0])


def check_draft_quota(db: sqlite3.Connection, actor: str, wanted: int) -> None:
    if wanted and drafts_created_today(db, actor) + wanted > DAILY_DRAFTS:
        raise AgentError(429, "draft_quota", f"Quota de {DAILY_DRAFTS} lots créés par jour atteint pour cet accès.")


def floor_cents(db: sqlite3.Connection, copy_ids: list[str], margin: int) -> int:
    """Plancher du jour d'un lot : la somme des cotes moins la marge, jamais sous 0,50 €."""
    marks = ",".join("?" for _ in copy_ids)
    total = db.execute(
        f"SELECT coalesce(sum(reference_cents),0) FROM copies WHERE id IN ({marks})", copy_ids
    ).fetchone()[0]
    return max(FLOOR_CENTS, lot_floor_cents(int(total), margin))


def draft_count(db: sqlite3.Connection) -> int:
    """Brouillons actifs, lots en ligne compris : ils occupent tous le plafond."""
    return int(db.execute("SELECT count(*) FROM sales WHERE status='draft'").fetchone()[0])


def sale_copy_ids(db: sqlite3.Connection, sale_id: str) -> list[str]:
    return [r[0] for r in db.execute("SELECT copy_id FROM sale_items WHERE sale_id=? ORDER BY rowid", (sale_id,))]


def due_online(db: sqlite3.Connection, days: int) -> list[Card]:
    """Lots en ligne de l'outil, invendus depuis plus de ``days`` jours : signalés, pas touchés."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = db.execute(
        """
        SELECT DISTINCT s.id sale_id, s.version, l.id listing_id, l.title, l.price_cents, l.published_at
        FROM sales s
        JOIN sale_items si ON si.sale_id = s.id
        JOIN listing_items li ON li.copy_id = si.copy_id AND li.active = 1
        JOIN listings l ON l.id = li.listing_id AND l.state = 'online'
        WHERE s.status = 'draft' AND l.published_at < ?
          AND (SELECT count(*) FROM listing_items x WHERE x.listing_id = l.id AND x.active = 1) > 1
        ORDER BY l.published_at, s.id
        """,
        (cutoff,),
    ).fetchall()
    stamp = datetime.now(timezone.utc)
    return [
        {
            **dict(r),
            "age_days": (stamp - datetime.fromisoformat(r["published_at"])).days,
        }
        for r in rows
        if LotsEngine.tool_made(db, r["sale_id"])
    ]


class LotsComposer:
    """Les écritures de ``lots:compose``, chacune dans sa transaction d'écriture."""

    def __init__(self, service: AgentService, heavy: Callable[[str], None]) -> None:
        # ``service`` is None when ``agent_api.schema()`` builds the routes offline.
        self.service = service
        self.heavy = heavy

    @property
    def store(self) -> Any:
        return self.service.store

    # -- Cadre commun -----------------------------------------------------------

    @staticmethod
    def check_key(key: Optional[str]) -> None:
        if key is not None and not KEY.fullmatch(key):
            raise AgentError(422, "invalid_key", "Clé Idempotency-Key requise (1 à 120 caractères).")

    @staticmethod
    def fingerprint(op: str, payload: Card) -> str:
        return digest(canonical({"op": op, "body": payload}))

    @staticmethod
    def replay(db: sqlite3.Connection, actor: str, key: Optional[str], fingerprint: str) -> Optional[Card]:
        """La réponse déjà donnée à cette clé, ou rien ; une autre requête sous la même clé est refusée."""
        if key is None:
            return None
        previous = stored_operation(db, actor, key)
        if previous is None:
            return None
        if previous["request_sha256"] != fingerprint:
            raise AgentError(409, "idempotency_conflict", "Clé déjà utilisée pour une autre requête.")
        return {**previous["response"], "replayed": True}

    @contextmanager
    def denials(self, op: str) -> Iterator[Card]:
        """Journalise un refus après l'annulation de la transaction qui l'a levé."""
        seen: Card = {}
        try:
            yield seen
        except (AgentError, ValueError) as refused:
            status = getattr(refused, "status", 409 if isinstance(refused, Conflict) else 422)
            grant = seen.get("grant")
            if grant and status not in UNJOURNALED:
                code = getattr(refused, "code", "version_conflict" if isinstance(refused, Conflict) else "invalid_request")
                self.deny(actor_of(grant), op, code)
            raise

    def deny(self, actor: str, op: str, code: str) -> None:
        minute = now()[:16]
        with self.store.connect(write=True) as db:
            if refusals_today(db, actor) >= DAILY_REFUSALS:
                return
            if db.execute(
                "SELECT 1 FROM events WHERE kind=? AND actor=? AND copy_id IS NULL AND created_at>=? "
                "AND json_extract(after_json,'$.op')=? AND json_extract(after_json,'$.code')=? "
                "AND json_extract(after_json,'$.minute')=?",
                (DENIED_EVENT, actor, today(), op, code, minute),
            ).fetchone():
                return
            self.store.event(
                db, None, actor, DENIED_EVENT, "Opération de lots refusée.", {},
                {"op": op, "code": code, "minute": minute},
            )

    def run(self, token_hash: str, op: str, key: Optional[str], payload: Card, work: Work, *, heavy: bool = False) -> Card:
        """Autorise, rejoue ou exécute ``work`` et journalise, dans une seule transaction d'écriture."""
        self.check_key(key)
        fingerprint = self.fingerprint(op, payload)
        with self.denials(op) as seen, self.store.connect(write=True) as db:
            grant = self.service.authorize(db, token_hash, COMPOSE)
            seen["grant"] = grant
            if heavy:
                self.heavy(grant["id"])
            actor = actor_of(grant)
            replayed = self.replay(db, actor, key, fingerprint)
            if replayed is not None:
                return replayed
            if refusals_today(db, actor) >= DAILY_REFUSALS:
                raise AgentError(
                    429, "refusal_quota", f"Quota de {DAILY_REFUSALS} refus par jour atteint pour cet accès."
                )
            engine = LotsEngine(self.store, value_ceiling_cents=lots_ceiling_cents(grant))
            response, created = work(db, grant, engine)
            self.store.event(
                db, None, actor, OP_EVENT, "Opération de lots par un agent : " + op, {},
                {"key": key, "op": op, "request_sha256": fingerprint, "response": response, "drafts_created": created},
            )
            return response

    # -- Création ---------------------------------------------------------------

    def compose(self, token_hash: str, key: str, values: ComposeRequest, request_id: str) -> Card:
        def work(db: sqlite3.Connection, grant: Card, engine: LotsEngine) -> tuple[Card, int]:
            # Le plan se recalcule ici, sous le verrou d'écriture : le gisement exclut
            # déjà tout exemplaire pris par un brouillon, une vente réservée ou un lot en ligne.
            result = engine.compose_from_recipe(db, to_recipe(values.recipe), scope="duplicates")
            lot = result.get("lot")
            if not lot:
                raise AgentError(409, "stale_plan", "Plus aucune carte ne répond à la recette : refaites le plan.")
            margin = lot_max_margin(db)
            if lot_plan_id(values.recipe, lot, margin, engine.value_ceiling_cents) != values.plan_id:
                raise AgentError(
                    409, "stale_plan", "Le gisement, une carte, le prix ou la marge a changé : refaites le plan."
                )
            paid, bonus = split_bonus(lot)
            copy_ids = [c["id"] for c in lot["copies"]]
            if len(copy_ids) < 2:
                raise AgentError(422, "lot_too_small", "Un lot réunit au moins deux exemplaires.")
            if lot["contains_album_copies"] or engine.get_busy_copy_ids(db) & set(copy_ids):
                # Défense en profondeur : le gisement des doublons n'en contient jamais.
                raise AgentError(409, "stale_plan", "Une carte du plan n'est plus libre : refaites le plan.")
            if draft_count(db) >= MAX_ROTATION_DRAFTS:
                raise AgentError(
                    409, "draft_cap",
                    f"Plafond de {MAX_ROTATION_DRAFTS} brouillons actifs atteint, lots en ligne compris.",
                )
            check_draft_quota(db, actor_of(grant), 1)
            computed = lot["asking_cents"]
            if values.asking_cents is not None and values.asking_cents < computed:
                raise AgentError(422, "price_lowered", "Le prix demandé ne peut que relever le prix calculé.")
            floor = floor_cents(db, copy_ids, margin)
            price = max(computed, values.asking_cents or 0, floor)
            lot["asking_cents"] = price
            sale_id = engine.create_draft(db, lot, actor_of(grant))
            version = db.execute("SELECT version FROM sales WHERE id=?", (sale_id,)).fetchone()[0]
            return {
                "sale_id": sale_id,
                "status": "draft",
                "version": version,
                "title": lot["title"],
                "plan_id": values.plan_id,
                "asking_cents": price,
                "computed_asking_cents": computed,
                "floor_cents": floor,
                "raised_to_floor": price == floor and floor > max(computed, values.asking_cents or 0),
                "margin": margin,
                "copies": [{"id": c["id"], "version": c["version"]} for c in paid],
                "bonus": [{"id": c["id"], "version": c["version"]} for c in bonus],
                "request_id": request_id,
            }, 1

        return self.run(token_hash, "compose", key, values.model_dump(mode="json"), work, heavy=True)

    # -- Rotation ---------------------------------------------------------------

    def plan(self, db: sqlite3.Connection, grant: Card, engine: LotsEngine, limit: Optional[int], dry_run: bool) -> tuple[RotationPlan, dict[str, int]]:
        """La rotation que l'outil ferait : n'annule que ses propres brouillons, sous le plafond fixe."""
        room = DAILY_DRAFTS - drafts_created_today(db, actor_of(grant))
        wanted = MAX_ROTATION_DRAFTS if limit is None else limit
        plan = engine.plan_rotation(
            db, limit_add=max(0, min(wanted, room)), max_drafts=MAX_ROTATION_DRAFTS, dry_run=dry_run, tool_made_only=True
        )
        margin = lot_max_margin(db)
        for lot, line in zip(plan.create, plan.report["lots_to_create"]):
            floor = floor_cents(db, [c["id"] for c in lot["copies"]], margin)
            lot["asking_cents"] = line["asking_cents"] = max(lot["asking_cents"], floor)
            line["floor_cents"] = floor
        versions = {
            d["id"]: db.execute("SELECT version FROM sales WHERE id=?", (d["id"],)).fetchone()[0] for d in plan.cancel
        }
        return plan, versions

    @staticmethod
    def report(db: sqlite3.Connection, plan: RotationPlan) -> Card:
        report = dict(plan.report)
        # Un brouillon fait à la main garde sa place sans que son titre sorte.
        report["online_drafts_kept"] = [
            {**d, "title": d["title"] if LotsEngine.tool_made(db, d["id"]) else None}
            for d in report["online_drafts_kept"]
        ]
        return report

    def rotate(self, token_hash: str, key: str, values: RotateRequest, request_id: str) -> Card:
        self.check_key(key)
        op = "rotate"
        payload = values.model_dump(mode="json")
        fingerprint = self.fingerprint(op, payload)
        # 1. Le plan se calcule hors du verrou d'écriture, sur un instantané de lecture.
        with self.denials(op) as seen, self.store.connect() as db:
            db.execute("BEGIN")
            grant = self.service.authorize(db, token_hash, COMPOSE)
            seen["grant"] = grant
            self.heavy(grant["id"])
            replayed = self.replay(db, actor_of(grant), key, fingerprint)
            if replayed is not None:
                return replayed
            engine = LotsEngine(self.store, value_ceiling_cents=lots_ceiling_cents(grant))
            plan, versions = self.plan(db, grant, engine, values.limit, values.dry_run)
            days = lot_rotation_days(db)
            preview = {
                **self.report(db, plan),
                "rotation_days": days,
                "due_online": due_online(db, days),
                "request_id": request_id,
            }
        if values.dry_run:
            return preview

        # 2. Tout se revalide et s'écrit dans une seule transaction d'écriture.
        def work(db: sqlite3.Connection, grant: Card, engine: LotsEngine) -> tuple[Card, int]:
            for draft in plan.cancel:
                row = db.execute("SELECT status, version FROM sales WHERE id=?", (draft["id"],)).fetchone()
                if (
                    not row
                    or row["status"] != "draft"
                    or row["version"] != versions[draft["id"]]
                    or not engine.tool_made(db, draft["id"])
                    or engine.online_lot(db, draft["id"])
                ):
                    raise AgentError(409, "stale_plan", "Un brouillon à remplacer a changé : relancez la rotation.")
            pool = engine.classify_pool(db)
            free = {c["id"]: c["version"] for c in pool["duplicates"]}
            offered = {c["id"]: c["version"] for c in engine.bulk_bonus_pool(db)}
            seen_ids: set[str] = set()
            for lot in plan.create:
                for card in lot["copies"]:
                    source = offered if card.get("bonus") else free
                    if source.get(card["id"]) != card["version"] or card["id"] in seen_ids:
                        raise AgentError(409, "stale_plan", "Une carte du plan n'est plus libre : relancez la rotation.")
                    seen_ids.add(card["id"])
            if plan.create and draft_count(db) - len(plan.cancel) + len(plan.create) > MAX_ROTATION_DRAFTS:
                raise AgentError(
                    409, "draft_cap",
                    f"Plafond de {MAX_ROTATION_DRAFTS} brouillons actifs atteint, lots en ligne compris.",
                )
            check_draft_quota(db, actor_of(grant), len(plan.create))
            margin = lot_max_margin(db)
            for lot in plan.create:
                # Le plancher se relit sous le verrou : il ne baisse jamais un prix.
                lot["asking_cents"] = max(lot["asking_cents"], floor_cents(db, [c["id"] for c in lot["copies"]], margin))
            created = engine.apply_rotation(db, plan, actor_of(grant))
            for line, lot in zip(created, plan.create):
                line["asking_cents"] = lot["asking_cents"]
            return {
                **preview,
                "dry_run": False,
                "cancelled": [d["id"] for d in plan.cancel],
                "created": created,
            }, len(created)

        return self.run(token_hash, op, key, payload, work)

    # -- Annulation et relèvement -----------------------------------------------

    @staticmethod
    def own_draft(db: sqlite3.Connection, engine: LotsEngine, sale_id: str, version: int) -> sqlite3.Row:
        """Brouillon de l'outil des lots, hors ligne, à la version attendue."""
        if not engine.tool_made(db, sale_id):
            raise AgentError(404, "not_found", "Aucun lot de l'outil des lots à cet identifiant.")
        row = db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
        if row["status"] != "draft":
            raise AgentError(409, "not_draft", f"Ce lot n'est plus un brouillon (statut : {row['status']}).")
        if engine.online_lot(db, sale_id):
            raise AgentError(409, "online_lot", "Ce lot est en ligne : il se retire d'abord de la vitrine.")
        if row["version"] != version:
            raise Conflict("La vente a changé. Rechargez-la.")
        return row

    def cancel(self, token_hash: str, sale_id: str, values: CancelRequest, request_id: str) -> Card:
        def work(db: sqlite3.Connection, grant: Card, engine: LotsEngine) -> tuple[Card, int]:
            reason = safe_text(values.reason)
            self.own_draft(db, engine, sale_id, values.expected_version)
            self.store.update_sale(
                sale_id, {"status": "cancelled"}, values.expected_version, actor_of(grant),
                "Annulation par l'agent : " + reason, _db=db,
            )
            version = db.execute("SELECT version FROM sales WHERE id=?", (sale_id,)).fetchone()[0]
            return {"sale_id": sale_id, "status": "cancelled", "version": version, "request_id": request_id}, 0

        return self.run(token_hash, "cancel", None, {"sale_id": sale_id, **values.model_dump(mode="json")}, work)

    def raise_price(self, token_hash: str, sale_id: str, values: RaiseRequest, request_id: str) -> Card:
        def work(db: sqlite3.Connection, grant: Card, engine: LotsEngine) -> tuple[Card, int]:
            row = self.own_draft(db, engine, sale_id, values.expected_version)
            current = row["amount_cents"] or row["asking_cents"] or 0
            if values.asking_cents < current:
                raise AgentError(422, "price_lowered", "Un prix ne fait que monter : le nouveau prix est sous l'actuel.")
            margin = lot_max_margin(db)
            floor = floor_cents(db, sale_copy_ids(db, sale_id), margin)
            price = max(values.asking_cents, floor)
            self.store.update_sale(
                sale_id, {"amount_cents": price, "asking_cents": price}, values.expected_version, actor_of(grant),
                "Prix du lot relevé par l'agent", _db=db,
            )
            version = db.execute("SELECT version FROM sales WHERE id=?", (sale_id,)).fetchone()[0]
            return {
                "sale_id": sale_id,
                "status": "draft",
                "version": version,
                "previous_cents": current,
                "asking_cents": price,
                "floor_cents": floor,
                "raised_to_floor": price > values.asking_cents,
                "margin": margin,
                "request_id": request_id,
            }, 0

        return self.run(token_hash, "raise", None, {"sale_id": sale_id, **values.model_dump(mode="json")}, work)


def install_compose(api: APIRouter, service: AgentService, principal: Any, heavy: Callable[[str], None]) -> None:
    """Ajoute les routes d'écriture de ``lots:compose`` au routeur agent."""
    composer = LotsComposer(service, heavy)
    IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=120)]
    SaleId = Annotated[str, Path(pattern=SALE_ID)]

    @api.post("/lots", status_code=201)
    def lots_compose(values: ComposeRequest, request: Request, key: IdempotencyKey, grant: Any = principal) -> Card:
        return composer.compose(request.state.agent_token_hash, key, values, request.state.agent_request_id)

    @api.post("/lots/rotate")
    def lots_rotate(values: RotateRequest, request: Request, key: IdempotencyKey, grant: Any = principal) -> Card:
        return composer.rotate(request.state.agent_token_hash, key, values, request.state.agent_request_id)

    @api.post("/lots/{sale_id}/cancel")
    def lots_cancel(sale_id: SaleId, values: CancelRequest, request: Request, grant: Any = principal) -> Card:
        return composer.cancel(request.state.agent_token_hash, sale_id, values, request.state.agent_request_id)

    @api.post("/lots/{sale_id}/raise")
    def lots_raise(sale_id: SaleId, values: RaiseRequest, request: Request, grant: Any = principal) -> Card:
        return composer.raise_price(request.state.agent_token_hash, sale_id, values, request.state.agent_request_id)
