"""Publication de lots par l'API agent : publier, retirer, faire tourner les lots en ligne.

Mêmes règles que les écritures de ``lots:compose`` (``agent_lots_compose``) :
une seule transaction ``BEGIN IMMEDIATE`` par écriture, qui autorise, rejoue la
clé d'idempotence, compte les quotas, revalide et écrit ; auteur
``agent:<accès>``. Seuls les brouillons et les annonces de lot de l'outil des
lots se publient, se retirent ou tournent ; jamais un brouillon fait à la main,
jamais une annonce d'une seule carte.

La publication repasse, dans la transaction, chaque carte payante aux règles
d'entrée en lot avec le plafond de l'accès (``publication_plan`` avec
``agent_rules``) : un plan préalable n'est jamais une garantie. Un prix sous le
plancher du jour est relevé au plancher, jamais refusé pour une dérogation
humaine (décision du propriétaire) ; le plancher absolu de 0,50 € tient
toujours. Aucune route ne touche aux accès, à la marge, à l'âge de rotation ni
aux dérogations.
"""

import sqlite3
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Header, Path, Request
from pydantic import Field

from .agent import AgentError, lots_ceiling_cents, require
from .agent_lots_compose import (
    COMPOSE,
    PUBLISH,
    SALE_ID,
    Card,
    Counts,
    LotsComposer,
    actor_of,
    check_draft_quota,
    check_publish_quota,
    draft_count,
    due_online,
    floor_cents,
    sale_copy_ids,
)
from .floor_requests import SharedTransaction
from .inventory import Conflict
from .listings import FloorRefusal, Listings, is_agent
from .lots import MAX_ROTATION_DRAFTS, LotsEngine, RotationPlan
from .lots.agent_recipe import StrictModel, safe_text
from .lots.settings import lot_rotation_days
from .pricing import lot_max_margin


class PublishRequest(StrictModel):
    expected_version: int = Field(ge=1)
    # Comme la rotation, un appel sans avis contraire ne fait qu'un essai à blanc.
    dry_run: bool = True


class UnpublishRequest(StrictModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


def stale(detail: str) -> AgentError:
    return AgentError(409, "stale_plan", detail)


class LotsPublisher(LotsComposer):
    """Les écritures de ``lots:publish`` et la rotation des lots en ligne échus."""

    # -- Garde-fous communs -----------------------------------------------------

    @staticmethod
    def own_draft_to_publish(db: sqlite3.Connection, sale_id: str, version: int) -> sqlite3.Row:
        """Brouillon de l'outil des lots, pas encore en ligne, à la version attendue."""
        if not LotsEngine.tool_made(db, sale_id):
            raise AgentError(404, "not_found", "Aucun lot de l'outil des lots à cet identifiant.")
        row: sqlite3.Row = db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
        if row["status"] != "draft":
            raise AgentError(409, "not_draft", f"Ce lot n'est plus un brouillon (statut : {row['status']}).")
        if LotsEngine.online_lot(db, sale_id):
            raise AgentError(409, "online_lot", "Ce lot est déjà en ligne.")
        if row["version"] != version:
            raise Conflict("La vente a changé. Rechargez-la.")
        return row

    @staticmethod
    def own_listing(db: sqlite3.Connection, listing_id: str) -> sqlite3.Row:
        """Annonce de lot en ligne publiée par l'outil des lots ou un agent, deux cartes au moins."""
        row: Optional[sqlite3.Row] = db.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
        active = db.execute(
            "SELECT count(*) FROM listing_items WHERE listing_id=? AND active=1", (listing_id,)
        ).fetchone()[0]
        if not row or not is_agent(row["published_by"] or "") or (row["state"] == "online" and active < 2):
            raise AgentError(404, "not_found", "Aucune annonce de lot de l'outil des lots à cet identifiant.")
        if row["state"] != "online":
            raise AgentError(409, "not_online", "Cette annonce est déjà retirée de la vitrine.")
        return row

    @staticmethod
    def lot_sales(db: sqlite3.Connection, listing_id: str) -> list[sqlite3.Row]:
        """Ventes en cours qui portent les cartes de cette annonce."""
        return list(
            db.execute(
                """
                SELECT DISTINCT s.id, s.status, s.version FROM sales s
                JOIN sale_items si ON si.sale_id = s.id
                JOIN listing_items li ON li.copy_id = si.copy_id AND li.active = 1
                WHERE li.listing_id = ? AND s.status IN ('draft', 'reserved')
                ORDER BY s.id
                """,
                (listing_id,),
            )
        )

    @staticmethod
    def publish_draft(engine: LotsEngine, db: sqlite3.Connection, sale_id: str, actor: str, dry_run: bool = False) -> Card:
        """``publish_lot`` avec les règles d'un agent ; ses refus deviennent des erreurs codées."""
        try:
            report = engine.publish_lot(db, sale_id, actor, dry_run, agent_rules=True)
        except (AgentError, Conflict):
            raise
        except FloorRefusal as refused:  # Jamais attendu : le prix est relevé avant.
            raise AgentError(409, "floor_refused", str(refused)) from refused
        except ValueError as refused:
            raise AgentError(422, "not_publishable", str(refused)) from refused
        report["raised_to_floor"] = report["price_cents"] > (report["previous_price_cents"] or 0)
        return report

    # -- Publication ------------------------------------------------------------

    def publish(self, token_hash: str, key: str, sale_id: str, values: PublishRequest, request_id: str) -> Card:
        op = "publish"
        payload = {"sale_id": sale_id, **values.model_dump(mode="json")}
        if values.dry_run:
            # Un essai à blanc lit un instantané et n'écrit rien, pas même sa clé.
            self.check_key(key)
            fingerprint = self.fingerprint(op, payload)
            with self.denials(op) as seen, self.store.connect() as db:
                db.execute("BEGIN")
                grant = self.service.authorize(db, token_hash, PUBLISH)
                seen["grant"] = grant
                self.heavy(grant["id"])
                replayed = self.replay(db, actor_of(grant), key, fingerprint)
                if replayed is not None:
                    return replayed
                engine = LotsEngine(self.store, value_ceiling_cents=lots_ceiling_cents(grant))
                self.own_draft_to_publish(db, sale_id, values.expected_version)
                report = self.publish_draft(engine, db, sale_id, actor_of(grant), dry_run=True)
            return {**report, "request_id": request_id}

        def work(db: sqlite3.Connection, grant: Card, engine: LotsEngine) -> tuple[Card, Counts]:
            actor = actor_of(grant)
            self.own_draft_to_publish(db, sale_id, values.expected_version)
            check_publish_quota(db, actor)
            report = self.publish_draft(engine, db, sale_id, actor)
            version = db.execute("SELECT version FROM sales WHERE id=?", (sale_id,)).fetchone()[0]
            return {**report, "version": version, "request_id": request_id}, {"published": 1}

        return self.run(token_hash, op, key, payload, work, heavy=True, permissions=(PUBLISH,))

    # -- Retrait ----------------------------------------------------------------

    def unpublish(self, token_hash: str, listing_id: str, values: UnpublishRequest, request_id: str) -> Card:
        """Retire une annonce de lot de l'outil et annule son brouillon : les cartes reviennent au gisement.

        Dans la même transaction, chaque carte d'au moins 1 € au prix du jour
        relevé au plancher revient en annonce unitaire (décision 0045) ; les
        autres restent libres, sans annonce, pour la prochaine composition.
        """

        def work(db: sqlite3.Connection, grant: Card, engine: LotsEngine) -> tuple[Card, Counts]:
            actor = actor_of(grant)
            reason = safe_text(values.reason)
            listing = self.own_listing(db, listing_id)
            if listing["version"] != values.expected_version:
                raise Conflict("L'annonce a changé. Rechargez-la avant de la retirer.")
            sales = self.lot_sales(db, listing_id)
            for row in sales:
                if row["status"] != "draft":
                    raise AgentError(409, "sale_in_progress", "Une vente de ce lot est en cours : il reste en vitrine.")
                if not engine.tool_made(db, row["id"]):
                    raise AgentError(409, "hand_made_sale", "Une vente faite à la main porte ces cartes : rien n'est retiré.")
            copies = [
                r[0] for r in db.execute("SELECT copy_id FROM listing_items WHERE listing_id=? AND active=1", (listing_id,))
            ]
            listings = Listings(SharedTransaction(self.store, db))
            after = listings.unpublish(listing_id, values.expected_version, actor, "Retrait par l'agent : " + reason)
            for row in sales:
                self.store.update_sale(
                    row["id"], {"status": "cancelled"}, row["version"], actor,
                    "Lot retiré de la vitrine par l'agent : " + reason, _db=db,
                )
            relist = engine.relist_released(db, copies, actor)
            return {
                "listing_id": listing_id,
                "state": after["state"],
                "version": after["version"],
                "cancelled": [row["id"] for row in sales],
                "released_copies": copies,
                **relist,
                "request_id": request_id,
            }, {}

        payload = {"listing_id": listing_id, **values.model_dump(mode="json")}
        return self.run(token_hash, "unpublish", None, payload, work, permissions=(PUBLISH,))

    # -- Rotation des lots en ligne ---------------------------------------------

    def plan_online(self, db: sqlite3.Connection, engine: LotsEngine, due: list[Card]) -> list[Card]:
        """Un remplaçant par lot échu, du plus ancien au plus récent, sans carte en commun.

        Le remplaçant est une autre proposition : parmi les lots possibles, celui
        qui reprend le moins de cartes payantes du lot remplacé (à égalité,
        l'ordre du moteur). Si le seul possible reprend exactement les mêmes
        cartes payantes, le lot reste en ligne (``no_fresh_replacement``).
        """
        assigned: set[str] = set()
        plans = []
        for lot in due:
            old_ids = sale_copy_ids(db, lot["sale_id"])
            old_paid = {
                r[0]
                for r in db.execute(
                    f"SELECT id FROM copies WHERE id IN ({','.join('?' for _ in old_ids)}) "
                    "AND coalesce(reference_cents, 0) > 0",
                    old_ids,
                )
            }
            candidates = engine.analyze(db, released=frozenset(old_ids))["lots"]
            possible = []
            for candidate in candidates:
                taken = {c["id"] for c in candidate["copies"]} & assigned
                paid = {c["id"] for c in candidate["copies"] if not c.get("bonus")}
                if len(paid) >= 2 and not taken:
                    possible.append((len(paid & old_paid), paid, candidate))
            choice, skip = None, "no_replacement"
            if possible:
                _, paid, best = min(possible, key=lambda p: p[0])  # min garde le premier à égalité.
                if paid == old_paid:
                    skip = "no_fresh_replacement"
                else:
                    choice = best
            entry = {**lot, "copies": old_ids, "replacement": choice, "skip": skip}
            if choice is not None:
                ids = [c["id"] for c in choice["copies"]]
                assigned.update(ids)
                # La place d'une carte dans le gisement dépend aussi des autres
                # exemplaires de sa référence : leurs versions se revérifient sous le verrou.
                marks = ",".join("?" for _ in ids)
                entry["versions"] = {
                    r[0]: r[1]
                    for r in db.execute(
                        f"""
                        SELECT c.id, c.version FROM copies c
                        WHERE c.id IN ({marks}) OR EXISTS (
                            SELECT 1 FROM copies x WHERE x.id IN ({marks})
                              AND x.catalog_id = c.catalog_id AND x.language = c.language
                              AND coalesce(x.catalog_id, '') != ''
                        )
                        """,
                        [*ids, *ids],
                    )
                }
            plans.append(entry)
        return plans

    @staticmethod
    def line(entry: Card) -> Card:
        choice = entry["replacement"]
        return {
            "sale_id": entry["sale_id"],
            "listing_id": entry["listing_id"],
            "age_days": entry["age_days"],
            "price_cents": entry["price_cents"],
            "replacement": None
            if choice is None
            else {
                "title": choice["title"],
                "count": choice["count"],
                "asking_cents": choice["asking_cents"],
                "copies": [{"id": c["id"], "version": c["version"]} for c in choice["copies"]],
            },
        }

    def replace(self, token_hash: str, key: str, entry: Card) -> Card:
        """Retire un lot en ligne échu, annule son brouillon, puis compose et publie son remplaçant.

        Tout se fait dans une seule transaction, le retrait d'abord : un échec
        laisse le lot en ligne tel qu'il était. Les cartes du lot retiré que le
        remplaçant ne reprend pas reviennent en annonce unitaire quand elles
        valent 1 € au moins (décision 0045) ; ces annonces ne comptent pas dans
        le quota des lots publiés.
        """
        lot = dict(entry["replacement"])
        sale_id, listing_id = entry["sale_id"], entry["listing_id"]

        def work(db: sqlite3.Connection, grant: Card, engine: LotsEngine) -> tuple[Card, Counts]:
            actor = actor_of(grant)
            row = db.execute("SELECT status, version FROM sales WHERE id=?", (sale_id,)).fetchone()
            if not row or row["status"] != "draft" or row["version"] != entry["version"] or not engine.tool_made(db, sale_id):
                raise stale("Le lot à remplacer a changé : relancez la rotation.")
            online = engine.online_lot(db, sale_id)
            listing = db.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
            if not online or online["id"] != listing_id or not is_agent(listing["published_by"] or ""):
                raise stale("Le lot à remplacer n'est plus en ligne : relancez la rotation.")
            check_draft_quota(db, actor, 1)
            check_publish_quota(db, actor)
            days = entry["age_days"]
            Listings(SharedTransaction(self.store, db)).unpublish(
                listing_id, listing["version"], actor, f"Rotation : lot en ligne depuis {days} jours, remplacé"
            )
            self.store.update_sale(
                sale_id, {"status": "cancelled"}, row["version"], actor,
                "Rotation des lots en ligne : remplacé par un nouveau lot", _db=db,
            )
            ids = [c["id"] for c in lot["copies"]]
            marks = ",".join("?" for _ in entry["versions"])
            current = dict(
                db.execute(f"SELECT id, version FROM copies WHERE id IN ({marks})", list(entry["versions"])).fetchall()
            )
            if current != entry["versions"] or engine.get_busy_copy_ids(db) & set(ids):
                raise stale("Une carte du remplaçant n'est plus libre : relancez la rotation.")
            if draft_count(db) + 1 > MAX_ROTATION_DRAFTS:
                raise AgentError(
                    409, "draft_cap", f"Plafond de {MAX_ROTATION_DRAFTS} brouillons actifs atteint, lots en ligne compris."
                )
            # Jamais sous le plancher du jour, relu sous le verrou.
            lot["asking_cents"] = max(lot["asking_cents"], floor_cents(db, ids, lot_max_margin(db)))
            created = engine.apply_rotation(db, RotationPlan({}, [], [lot]), actor)[0]
            report = self.publish_draft(engine, db, created["sale_id"], actor)
            relist = engine.relist_released(db, sale_copy_ids(db, sale_id), actor, kept=frozenset(ids))
            return {
                "replaced_sale_id": sale_id,
                "replaced_listing_id": listing_id,
                "age_days": days,
                "sale_id": created["sale_id"],
                "listing_id": report["published_listing_id"],
                "title": report["title"],
                "price_cents": report["price_cents"],
                "copies_count": report["copies_count"],
                **relist,
            }, {"drafts_created": 1, "published": 1}

        payload = {"sale_id": sale_id, "listing_id": listing_id}
        return self.run(
            token_hash, "rotate-online", f"{key}/online/{sale_id}", payload, work,
            permissions=(COMPOSE, PUBLISH), internal_key=True,
        )

    def rotate_online(self, token_hash: str, key: str, grant: Card, dry_run: bool) -> Card:
        """Les lots en ligne de l'outil plus vieux que l'âge de rotation, remplacés un par un.

        Sans ``lots:publish``, rien : ils restent signalés dans ``due_online``.
        """
        if PUBLISH not in grant["permissions"]:
            return {}
        with self.store.connect() as db:
            db.execute("BEGIN")
            grant = self.service.authorize(db, token_hash, COMPOSE)
            require(grant, PUBLISH)
            engine = LotsEngine(self.store, value_ceiling_cents=lots_ceiling_cents(grant))
            plans = self.plan_online(db, engine, due_online(db, lot_rotation_days(db)))
        report: Card = {"planned": [self.line(p) for p in plans]}
        if dry_run:
            return {"online_rotation": report}
        report.update(replaced=[], failed=[], skipped=[])
        stop: Optional[AgentError] = None
        for entry in plans:
            where = {"sale_id": entry["sale_id"], "listing_id": entry["listing_id"]}
            if entry["replacement"] is None:
                report["skipped"].append({**where, "code": entry["skip"]})
                continue
            if stop is not None:
                report["skipped"].append({**where, "code": stop.code})
                continue
            try:
                report["replaced"].append(self.replace(token_hash, key, entry))
            except AgentError as refused:
                if refused.status in (401, 403):
                    raise
                if refused.status == 429:
                    stop = refused
                    report["skipped"].append({**where, "code": refused.code})
                else:
                    report["failed"].append({**where, "code": refused.code, "detail": str(refused)})
            except Conflict as refused:
                report["failed"].append({**where, "code": "version_conflict", "detail": str(refused)})
        return {"online_rotation": report}


def install_publish(api: APIRouter, publisher: LotsPublisher, principal: Any) -> None:
    """Ajoute les routes de ``lots:publish`` au routeur agent."""
    IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=120)]
    SaleId = Annotated[str, Path(pattern=SALE_ID)]
    ListingId = Annotated[str, Path(pattern=SALE_ID)]

    @api.post("/lots/{sale_id}/publish")
    def lots_publish(
        sale_id: SaleId, values: PublishRequest, request: Request, key: IdempotencyKey, grant: Any = principal
    ) -> Card:
        return publisher.publish(request.state.agent_token_hash, key, sale_id, values, request.state.agent_request_id)

    @api.post("/lots/{listing_id}/unpublish")
    def lots_unpublish(listing_id: ListingId, values: UnpublishRequest, request: Request, grant: Any = principal) -> Card:
        return publisher.unpublish(request.state.agent_token_hash, listing_id, values, request.state.agent_request_id)
