"""Lecture de l'outil des lots par l'API agent : gisement, état, plan et publication.

Aucune de ces routes n'écrit. Chacune autorise l'accès et lit sur une seule
connexion, dans une seule transaction de lecture, puis appelle ``LotsEngine``
avec elle. Le plafond de valeur vient de l'accès (``lots_ceiling_cents``) ; la
marge et le plancher viennent de la base ; le périmètre est celui des doublons :
rien dans une requête ne règle un auteur, une marge, un plancher, un périmètre
ni un plafond de brouillons.
"""

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request

from .agent import AgentError, AgentService, lots_ceiling_cents
from .floor_requests import events as floor_events
from .listings import FloorRefusal
from .lots import MAX_ROTATION_DRAFTS, LotsEngine
from .lots.agent_recipe import AgentRecipe, StrictModel, plan_id, to_recipe
from .pricing import FLOOR_CENTS, lot_floor_cents, lot_max_margin

READ = "lots:read"
# Le gisement et le plan relisent toute la collection : plafond par accès et par minute.
HEAVY_PER_MINUTE = 6
# Listes d'exclusions renvoyées au plus ; les totaux restent exacts.
LIST_CAP = 200
SALE_ID = r"^[A-Za-z0-9-]{1,64}$"

Card = dict[str, Any]


class PlanRequest(StrictModel):
    recipe: AgentRecipe


def capped(report: Card) -> Card:
    """Listes « exclues » et « à chiffrer » tronquées, avec leurs totaux et un drapeau."""
    for key in ("excluded", "to_price"):
        if key in report:
            entries = report[key]
            report[key] = entries[:LIST_CAP]
            report[key + "_truncated"] = len(entries) > LIST_CAP
    return report


def blocked_by(status: Card) -> list[dict[str, str]]:
    """Ce qui empêche un nouveau lot aujourd'hui, du plus au moins bloquant."""
    reasons = []
    if status["online_drafts_count"] >= status["max_drafts"]:
        reasons.append(
            {
                "code": "online_lots_fill_cap",
                "detail": "Les lots en ligne occupent tout le plafond : la rotation n'en annule aucun.",
            }
        )
    if status["active_drafts_count"] >= status["max_drafts"]:
        reasons.append(
            {
                "code": "draft_cap_reached",
                "detail": f"Plafond de {status['max_drafts']} brouillons actifs atteint, lots en ligne compris.",
            }
        )
    return reasons


def waiver_state(db: sqlite3.Connection, sale_id: str) -> dict[str, Any] | None:
    """La dernière demande de dérogation au plancher pour cette vente, ouverte ou décidée."""
    requests, decisions = floor_events(db)
    mine = [r for r in requests if r.get("sale_id") == sale_id]
    if not mine:
        return None
    last = mine[-1]
    decision = decisions.get(last["id"])
    return {
        "id": last["id"],
        "state": "decided" if decision else "open",
        "decision": decision["decision"] if decision else None,
        "price_cents": last["price_cents"],
        "floor_cents": last["floor_cents"],
        "requested_at": last["requested_at"],
    }


def install_lots(
    api: APIRouter,
    service: AgentService,
    principal: Any,
    heavy: Callable[[str], None],
) -> None:
    """Ajoute les routes de lecture des lots au routeur agent (``principal`` sur chacune)."""

    @contextmanager
    def reading(request: Request) -> Iterator[tuple[sqlite3.Connection, LotsEngine, Card]]:
        # Autorisation et lecture sur la même connexion et le même instantané.
        with service.store.connect() as db:
            db.execute("BEGIN")
            grant = service.authorize(db, request.state.agent_token_hash, READ)
            yield db, LotsEngine(service.store, value_ceiling_cents=lots_ceiling_cents(grant)), grant

    @api.get("/lots/pool")
    def lots_pool(
        request: Request,
        max_per_lot: int = Query(default=20, ge=3, le=50),
        grant: Any = principal,
    ) -> Card:
        with reading(request) as (db, engine, grant):
            heavy(grant["id"])
            result = capped(engine.analyze(db, max_cards_per_lot=max_per_lot))
        return {
            **result,
            "scope": "duplicates",
            "max_per_lot": max_per_lot,
            "value_ceiling_cents": engine.value_ceiling_cents,
            "request_id": request.state.agent_request_id,
        }

    @api.get("/lots/status")
    def lots_status(request: Request, grant: Any = principal) -> Card:
        with reading(request) as (db, engine, grant):
            status = engine.status(db, MAX_ROTATION_DRAFTS)
            for draft in status["active_drafts"]:
                draft["tool_made"] = engine.tool_made(db, draft["id"])
                if not draft["tool_made"]:
                    # Le brouillon d'une personne compte dans le plafond, sans en dire le titre.
                    draft["title"] = None
        drafts = status["active_drafts"]
        return {
            **status,
            "cap_used": status["active_drafts_count"],
            "tool_made_drafts_count": sum(1 for d in drafts if d["tool_made"]),
            "blocked_by": blocked_by(status),
            "request_id": request.state.agent_request_id,
        }

    @api.post("/lots/plan")
    def lots_plan(values: PlanRequest, request: Request, grant: Any = principal) -> Card:
        with reading(request) as (db, engine, grant):
            heavy(grant["id"])
            result = capped(engine.compose_from_recipe(db, to_recipe(values.recipe), scope="duplicates"))
            margin = lot_max_margin(db)
        diagnostic = result.get("stock_diagnostic")
        if diagnostic:
            # Ces titres peuvent être ceux de brouillons faits à la main : seul le nombre reste.
            diagnostic.pop("busy_details", None)
        lot = result.get("lot")
        identifier = None
        if lot:
            paid = [c for c in lot["copies"] if not c.get("bonus")]
            bonus = [c for c in lot["copies"] if c.get("bonus")]
            lot["copies"], lot["bonus"] = paid, bonus
            lot["margin"] = margin
            lot["floor_cents"] = max(FLOOR_CENTS, lot_floor_cents(lot["total_reference_cents"], margin))
            identifier = plan_id(
                values.recipe,
                [(c["id"], c["version"]) for c in paid],
                [(c["id"], c["version"]) for c in bonus],
                lot["asking_cents"],
                margin,
                engine.value_ceiling_cents,
            )
        return {
            **result,
            "recipe": values.recipe.model_dump(mode="json"),
            "plan_id": identifier,
            "value_ceiling_cents": engine.value_ceiling_cents,
            "request_id": request.state.agent_request_id,
        }

    @api.get("/lots/{sale_id}/publication")
    def lots_publication(
        sale_id: Annotated[str, Path(pattern=SALE_ID)],
        request: Request,
        grant: Any = principal,
    ) -> Card:
        with reading(request) as (db, engine, grant):
            if not engine.tool_made(db, sale_id):
                raise AgentError(404, "not_found", "Aucun lot de l'outil des lots à cet identifiant.")
            verdict: Card = {"sale_id": sale_id}
            try:
                sale, copy_ids, to_unpublish, price_cents = engine.publication_plan(db, sale_id)
            except FloorRefusal as refused:
                details = refused.details
                verdict.update(
                    publishable=False,
                    floor_refused=True,
                    refusal=str(refused),
                    price_cents=details["price_cents"],
                    floor_cents=details["floor_cents"],
                    total_reference_cents=details["total_reference_cents"],
                    margin=details["margin"],
                )
            except ValueError as refused:
                verdict.update(publishable=False, floor_refused=False, refusal=str(refused))
            else:
                verdict.update(
                    publishable=True,
                    floor_refused=False,
                    title=sale["title"],
                    version=sale["version"],
                    price_cents=price_cents,
                    copies_count=len(copy_ids),
                    copy_ids=copy_ids,
                    unpublish_count=len(to_unpublish),
                    unpublish_listings=[
                        {"id": item["id"], "title": item["title"], "version": item["version"]}
                        for item in to_unpublish
                    ],
                )
            verdict["waiver"] = waiver_state(db, sale_id)
        return {**verdict, "request_id": request.state.agent_request_id}
