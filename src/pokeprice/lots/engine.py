"""Moteur des lots de doublons : gisement, propositions, rotation et publication.

Chaque méthode travaille sur une connexion que l'appelant lui donne, avec le
magasin de la collection : le moteur n'ouvre ni base ni transaction. L'appelant
décide donc de ce qui se fait ensemble, en lecture ou dans une seule transaction
d'écriture.

Seules entrent en lot les cartes à l'identité confirmée, chiffrées, sans revue en
attente et sous le seuil de valeur (mêmes règles que ``AgentService``). Les
cartes sans prix sont listées « à chiffrer » dans le rapport.
"""

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from ..floor_requests import SharedTransaction, record
from ..listings import FloorRefusal, Listings, is_agent
from ..pricing import FLOOR_CENTS, display_price, euros, lot_floor_cents, lot_max_margin
from ..reservations import shipping_quote
from .recipe import DiversityStrategy, LotCompositionRecipe, ValueIntent
from .themes import (
    CONDITION_RANKS,
    ICONIC_POKEMON,
    KANTO_POKEMON_NAMES,
    THEME_PATTERNS,
    categorize_card,
    is_energy,
    is_trainer,
    normalize_pokemon_name,
)

Card = dict[str, Any]

MAX_ROTATION_DRAFTS = 5
# Énergies en vrac offertes par lot, au plus : assez pour faire plaisir, et
# il en reste pour les lots suivants (décision 0041).
BONUS_MAX_PER_LOT = 10
DEFAULT_ACTOR = "pokeprice-lots"
# Seuil de valeur d'une carte au-delà duquel elle ne part pas en lot (centimes),
# le même que celui de la liste de la collection.
VALUE_CEILING_CENTS = 1000
# Motifs d'exclusion d'AgentService.exclusions retenus pour le gisement des lots.
# « already_published » n'en fait pas partie : la publication du lot retire
# elle-même les annonces unitaires ; les lots en ligne sont exclus à part.
LOT_EXCLUSIONS = ("identity_unconfirmed", "price_incomplete", "review_needed", "valuable_card")
MANUAL_PRICE = {"amount_cents": FLOOR_CENTS, "mode": "manual", "source": "Prix fixé à la main"}


def bonus_room(card_count: int, asking_cents: int, cap: int = BONUS_MAX_PER_LOT) -> int:
    """Énergies qu'un lot peut offrir sans changer ses frais de port (décision 0041).

    Le calcul est celui de la réservation (``shipping_quote``) : poids des cartes
    et de l'emballage, recommandé dès le seuil de valeur. Une énergie de plus ne
    doit changer ni le tarif ni le service.
    """
    base = shipping_quote(card_count, asking_cents)
    room = 0
    while room < cap:
        quote = shipping_quote(card_count + room + 1, asking_cents)
        if (quote["shipping_cents"], quote["service"]) != (base["shipping_cents"], base["service"]):
            break
        room += 1
    return room


def bonus_title(title: str, count: int) -> str:
    if not count:
        return title
    suffix = " + 1 énergie offerte" if count == 1 else f" + {count} énergies offertes"
    return title[: 256 - len(suffix)] + suffix


@dataclass
class RotationPlan:
    """Rotation calculée : le rapport, les brouillons à annuler et les lots à créer."""

    report: dict[str, Any]
    cancel: list[Card] = field(default_factory=list)
    create: list[Card] = field(default_factory=list)


class LotsEngine:
    def __init__(self, store: Any, *, value_ceiling_cents: int = VALUE_CEILING_CENTS) -> None:
        self.store = store
        self.value_ceiling_cents = value_ceiling_cents

    # -- Lectures de la collection --------------------------------------------

    def valued_cards(self, db: sqlite3.Connection) -> dict[str, Card]:
        """Fiches de la collection avec leur valorisation, comme la liste de gestion."""
        rows = self.store.listing(limit=10**9, threshold_cents=self.value_ceiling_cents, _db=db)["items"]
        return {r["id"]: r for r in rows}

    def cards(self, db: sqlite3.Connection, copy_ids: list[str]) -> dict[str, Card]:
        """Exemplaires avec leur valorisation, comme ``Listings.cards``, sur cette connexion."""
        wanted = set(copy_ids)
        rows = self.store.listing(limit=10**9, _db=db)["items"]
        return {r["id"]: r for r in rows if r["id"] in wanted}

    @staticmethod
    def lot_exclusions(card: Optional[Card]) -> list[str]:
        """Motifs qui interdisent une carte en lot (règles d'AgentService.exclusions)."""
        if card is None:
            return ["identity_unconfirmed", "price_incomplete"]
        from ..agent import AgentService

        return [r for r in AgentService.exclusions(card) if r in LOT_EXCLUSIONS]

    @staticmethod
    def get_busy_copy_ids(db: sqlite3.Connection) -> set[str]:
        """Récupère les identifiants des exemplaires déjà engagés dans des ventes ou lots en ligne."""
        cur = db.cursor()
        cur.execute("""
            SELECT copy_id FROM sale_items si
            JOIN sales s ON s.id = si.sale_id
            WHERE s.status IN ('draft', 'reserved')
            UNION
            SELECT li.copy_id FROM listing_items li
            JOIN listings l ON l.id = li.listing_id
            WHERE l.state = 'online' AND li.active = 1
              AND li.listing_id IN (
                  SELECT listing_id FROM listing_items WHERE active = 1 GROUP BY listing_id HAVING count(*) > 1
              )
        """)
        return {r[0] for r in cur.fetchall()}

    # -- Gisement ---------------------------------------------------------------

    def classify_pool(self, db: sqlite3.Connection) -> dict[str, list[Card]]:
        """Répartit les exemplaires disponibles entre album, gisement, exclus et « à chiffrer ».

        Règles d'intégrité :
        1. Le meilleur exemplaire (état de conservation le plus neuf, puis plus belle finition)
           est toujours conservé en priorité dans la collection de Lily, qu'il soit chiffré ou non.
        2. Les exemplaires déjà engagés dans un brouillon actif ou un lot en ligne sont exclus
           du gisement disponible pour éviter tout double-booking.
        3. Une carte n'entre en lot que si son identité est confirmée, son prix connu, sans
           revue en attente et sous le seuil de valeur. Les cartes sans prix vont dans la
           liste « à chiffrer », jamais en lot.
        """
        busy_ids = self.get_busy_copy_ids(db)
        cur = db.cursor()

        cur.execute("""
            SELECT id, version, catalog_id, name, set_name, number, language,
                   album_id, page, position, condition, finish, reference_cents,
                   photo, stock_state, deleted_at
            FROM copies
            WHERE deleted_at = '' AND stock_state = 'available'
              AND catalog_id IS NOT NULL AND catalog_id != ''
            ORDER BY page, position, id
        """)
        all_cards = [dict(r) for r in cur.fetchall()]
        valued = self.valued_cards(db)

        # Regrouper par référence et langue
        groups: defaultdict[tuple[str, str], list[Card]] = defaultdict(list)
        for card in all_cards:
            groups[(card["catalog_id"], card["language"])].append(card)

        def copy_collection_rank(c: Card) -> tuple[Any, ...]:
            # Classement de préservation : état le plus neuf en premier (rank plus bas = meilleur)
            cond_rank = CONDITION_RANKS.get((c.get("condition") or "GD").upper(), 4)
            # Finition : holo (0) > holo_border (1) > reverse (2) > normal/autre (3)
            finish = (c.get("finish") or "normal").lower()
            if finish == "holo":
                finish_rank = 0
            elif finish == "holo_border":
                finish_rank = 1
            elif finish == "reverse":
                finish_rank = 2
            else:
                finish_rank = 3
            return (cond_rank, finish_rank, c.get("page") or 999, c.get("position") or 999, c.get("id") or "")

        result: dict[str, list[Card]] = {
            "retained": [], "duplicates": [], "album_eligible": [], "excluded": [], "to_price": [],
        }

        def sort_out(card: Card) -> bool:
            """Range une carte libre dans le gisement, ou dans les exclus et « à chiffrer »."""
            reasons = self.lot_exclusions(valued.get(card["id"]))
            if not reasons:
                return True
            entry = {
                "id": card["id"],
                "name": card["name"],
                "set_name": card["set_name"],
                "number": card["number"],
                "language": card["language"],
                "page": card.get("page"),
                "position": card.get("position"),
                "from_album": card["from_album"],
                "reasons": reasons,
            }
            result["excluded"].append(entry)
            if "price_incomplete" in reasons:
                result["to_price"].append(entry)
            return False

        for copies in groups.values():
            copies.sort(key=copy_collection_rank)
            best = {**copies[0], "from_album": True}  # conservé dans l'album
            result["retained"].append(best)
            if best["id"] not in busy_ids and sort_out(best):
                result["album_eligible"].append(best)
            for dup in copies[1:]:
                dup_item = {**dup, "from_album": False}
                if dup_item["id"] not in busy_ids and sort_out(dup_item):
                    result["duplicates"].append(dup_item)
        return result

    def get_duplicates_pool(self, db: sqlite3.Connection) -> tuple[list[Card], list[Card]]:
        """Exemplaires conservés en album et doublons éligibles à un lot."""
        pool = self.classify_pool(db)
        return pool["retained"], pool["duplicates"]

    def get_pool(self, db: sqlite3.Connection, scope: str = "duplicates") -> list[Card]:
        """Retourne le gisement de cartes selon le périmètre demandé (duplicates ou all)."""
        pool = self.classify_pool(db)
        if scope == "all":
            return pool["duplicates"] + pool["album_eligible"]
        return pool["duplicates"]

    def diagnose_stock(self, db: sqlite3.Connection, recipe: LotCompositionRecipe) -> dict[str, Any]:
        """Fournit un diagnostic clair de l'état du stock pour expliquer la pénurie ou l'état partiel."""
        cur = db.cursor()
        busy_ids = self.get_busy_copy_ids(db)

        # Identifier les cartes ciblées par le recipe
        params: list[str]
        if recipe.filters.pokemon_names:
            names = [pn.strip() for pn in recipe.filters.pokemon_names if pn.strip()]
            clause = " OR ".join(["c.name LIKE ?" for _ in names])
            params = [f"%{n}%" for n in names]
            where_sql = f"WHERE c.deleted_at = '' AND ({clause})"
            criteria_str = f"pokemon_names={names}"
        elif recipe.filters.only_trainers:
            where_sql = "WHERE c.deleted_at = ''"
            params = []
            criteria_str = "only_trainers (Dresseurs & Objets)"
        elif recipe.filters.generation == 1:
            where_sql = "WHERE c.deleted_at = ''"
            params = []
            criteria_str = "generation=1 (Kanto)"
        elif recipe.filters.finishes:
            finishes = [f.lower() for f in recipe.filters.finishes]
            clause = " OR ".join(["lower(c.finish) = ?" for _ in finishes])
            params = finishes
            where_sql = f"WHERE c.deleted_at = '' AND ({clause})"
            criteria_str = f"finishes={finishes}"
        else:
            where_sql = "WHERE c.deleted_at = ''"
            params = []
            criteria_str = "general"

        cur.execute(f"""
            SELECT c.id, c.catalog_id, c.name, c.set_name, c.language, c.condition, c.finish, c.reference_cents, c.page, c.position
            FROM copies c
            {where_sql}
        """, params)
        all_matches = [dict(r) for r in cur.fetchall()]

        if recipe.filters.only_trainers:
            all_matches = [c for c in all_matches if is_trainer(c.get("name") or "")]

        # Si generation==1 et pas de noms précis, filtrer avec KANTO_POKEMON_NAMES
        if recipe.filters.generation == 1 and not recipe.filters.pokemon_names:
            filtered = []
            for c in all_matches:
                clean_name = normalize_pokemon_name(c.get("name") or "")
                c_theme = categorize_card(c)
                c_set = (c.get("set_name") or "").lower()
                if clean_name in KANTO_POKEMON_NAMES or c_theme == "vintage_wotc" or "151" in c_set:
                    filtered.append(c)
            all_matches = filtered

        total_in_collection = len(all_matches)

        # Regrouper pour identifier exemplaires retenus vs doublons
        groups: defaultdict[tuple[str, str], list[Card]] = defaultdict(list)
        for c in all_matches:
            groups[(c["catalog_id"], c["language"])].append(c)

        retained_ids = set()
        duplicate_ids = set()
        for copies in groups.values():
            copies.sort(key=lambda x: (
                CONDITION_RANKS.get((x.get("condition") or "GD").upper(), 4),
                x.get("page") or 999,
                x.get("position") or 999,
                x.get("id") or "",
            ))
            retained_ids.add(copies[0]["id"])
            for dup in copies[1:]:
                duplicate_ids.add(dup["id"])

        busy_matching = [c for c in all_matches if c["id"] in busy_ids]
        busy_details: list[str] = []
        if busy_matching:
            b_ids = [c["id"] for c in busy_matching]
            placeholders = ",".join("?" * len(b_ids))
            cur.execute(f"""
                SELECT si.copy_id, s.title, s.status, s.id
                FROM sale_items si
                JOIN sales s ON s.id = si.sale_id
                WHERE si.copy_id IN ({placeholders}) AND s.status IN ('draft', 'reserved')
                UNION
                SELECT li.copy_id, l.title, l.state, l.id
                FROM listing_items li
                JOIN listings l ON l.id = li.listing_id
                WHERE li.copy_id IN ({placeholders}) AND l.state = 'online' AND li.active = 1
            """, b_ids + b_ids)
            for r in cur.fetchall():
                busy_details.append(f"{r[1]} ({r[2]}, réf {r[3][:8]}...)")
            busy_details = list(dict.fromkeys(busy_details))

        available_dups = [c for c in all_matches if c["id"] in duplicate_ids and c["id"] not in busy_ids]

        return {
            "criteria": criteria_str,
            "total_in_collection": total_in_collection,
            "retained_for_album": len(retained_ids),
            "busy_in_other_lots": len(busy_matching),
            "busy_details": busy_details,
            "available_duplicates": len(available_dups),
        }

    # -- Propositions de lots ---------------------------------------------------

    def compose_candidate_lots(self, duplicates: list[Card], max_cards_per_lot: int = 20) -> list[Card]:
        """Compose des propositions de lots thématiques cohérents."""
        categorized: defaultdict[str, list[Card]] = defaultdict(list)
        for card in duplicates:
            theme = categorize_card(card)
            categorized[theme].append(card)

        theme_titles = {
            "vintage_wotc": "Doublons Vintage Wizards of the Coast (1999-2000)",
            "dp_platine": "Doublons Bloc Diamant & Perle & Platine (Sinnoh)",
            "dresseurs": "Lot Dresseurs & Objets Utilitaires",
            "hgss": "Doublons HeartGold SoulSilver (Johto)",
            "brillantes": "Mini-lot Cartes Brillantes (Holo / Reverse)",
            "ex_era": "Doublons Bloc EX (Génération 3)",
            "noir_blanc": "Doublons Bloc Noir & Blanc",
            "soleil_lune": "Doublons Bloc Soleil & Lune",
            "energies": "Lot Vrac Énergies de Base",
            "divers": "Lot Découverte Cartes Variées",
        }

        lots: list[Card] = []
        for theme, cards in categorized.items():
            if not cards:
                continue

            # Éviter si possible les doublons identiques au sein d'un même lot
            # pour offrir un lot diversifié à l'acheteur
            seen_refs = set()
            unique_in_lot = []
            spillover = []
            for c in cards:
                ref_key = (c["catalog_id"], c["finish"])
                if ref_key not in seen_refs:
                    seen_refs.add(ref_key)
                    unique_in_lot.append(c)
                else:
                    spillover.append(c)

            pool = unique_in_lot + spillover

            # Découper en sous-lots de taille raisonnable (10 à 25 cartes)
            for i in range(0, len(pool), max_cards_per_lot):
                chunk = pool[i : i + max_cards_per_lot]
                if len(chunk) < 3 and lots:
                    # Si un résidu est trop petit (< 3 cartes), on ne crée pas un mini-lot dérisoire
                    continue

                sub_suffix = f" (Partie {i // max_cards_per_lot + 1})" if len(pool) > max_cards_per_lot else ""
                title = theme_titles.get(theme, f"Lot {theme}") + sub_suffix

                total_ref_cents = sum(c["reference_cents"] or 0 for c in chunk)
                # Prix demandé suggéré : arrondi au demi-euro supérieur
                asking_cents = max(200, (total_ref_cents // 50 + (1 if total_ref_cents % 50 else 0)) * 50)

                lots.append({
                    "theme": theme,
                    "title": title,
                    "count": len(chunk),
                    "total_reference_cents": total_ref_cents,
                    "asking_cents": asking_cents,
                    "copies": [
                        {
                            "id": c["id"],
                            "version": c["version"],
                            "name": c["name"],
                            "set_name": c["set_name"],
                            "number": c["number"],
                            "finish": c["finish"],
                            "reference_cents": c["reference_cents"],
                            "photo": c.get("photo") or "",
                            "page": c.get("page"),
                            "position": c.get("position"),
                            "from_album": bool(c.get("from_album", False)),
                        }
                        for c in chunk
                    ],
                })

        # Trier les lots par attractivité/valeur décroissante
        lots.sort(key=lambda l: (len(l["copies"]) >= 5, l["total_reference_cents"]), reverse=True)
        return lots

    @staticmethod
    def pool_report(pool: dict[str, list[Card]], scope: str = "duplicates") -> dict[str, Any]:
        """Cartes écartées du gisement et liste « à chiffrer » pour le rapport."""
        def keep(entry: Card) -> bool:
            return scope == "all" or not entry["from_album"]

        excluded = [e for e in pool["excluded"] if keep(e)]
        to_price = [e for e in pool["to_price"] if keep(e)]
        return {
            "excluded_count": len(excluded),
            "excluded": excluded,
            "to_price_count": len(to_price),
            "to_price": to_price,
        }

    def bulk_bonus_pool(self, db: sqlite3.Connection) -> list[Card]:
        """Énergies en vrac libres pour un bonus, dans l'ordre du classeur (décision 0041).

        En vrac (fiche 0015), disponibles, prises dans aucun brouillon ni lot en
        ligne, et publiables à prix fixé à la main, comme à la publication du lot.
        """
        busy = self.get_busy_copy_ids(db)
        rows = db.execute("""
            SELECT id, version, name, set_name, number, language, album_id, page,
                   position, condition, finish, photo
            FROM copies
            WHERE deleted_at = '' AND stock_state = 'available'
            ORDER BY album_id, page, position, id
        """).fetchall()
        free = [dict(r) for r in rows if r["id"] not in busy]
        cards = self.cards(db, [c["id"] for c in free])
        pool = []
        for c in free:
            card = cards.get(c["id"])
            if not card or card["reference_cents"] or not (card["valuation"] or {}).get("bulk"):
                continue
            if display_price(card, card["valuation"], MANUAL_PRICE)["publishable"]:
                pool.append(c)
        return pool

    @staticmethod
    def add_bonus(lots: list[Card], pool: list[Card]) -> list[Card]:
        """Complète chaque lot d'énergies offertes, sans changer sa tranche postale."""
        pool = list(pool)
        for lot in lots:
            paid = [c for c in lot["copies"] if not c.get("bonus")]
            room = min(bonus_room(len(lot["copies"]), lot["asking_cents"]), len(pool))
            bonus, pool = pool[:room], pool[room:]
            lot["copies"] = paid + [
                {
                    "id": c["id"],
                    "version": c["version"],
                    "name": c["name"],
                    "set_name": c["set_name"],
                    "number": c["number"],
                    "finish": c.get("finish") or "",
                    "reference_cents": 0,
                    "photo": c.get("photo") or "",
                    "page": c.get("page"),
                    "position": c.get("position"),
                    "from_album": False,
                    "bonus": True,
                }
                for c in bonus
            ]
            lot["bonus_count"] = len(bonus)
            lot["count"] = len(lot["copies"])
            lot["title"] = bonus_title(lot["title"], len(bonus))
        return lots

    def analyze(self, db: sqlite3.Connection, max_cards_per_lot: int = 20) -> dict[str, Any]:
        pool = self.classify_pool(db)
        bonus_pool = self.bulk_bonus_pool(db)
        retained, duplicates = pool["retained"], pool["duplicates"]
        candidate_lots = self.compose_candidate_lots(duplicates, max_cards_per_lot=max_cards_per_lot)
        self.add_bonus(candidate_lots, bonus_pool)
        total_excess_cents = sum(c["reference_cents"] or 0 for c in duplicates)

        return {
            "total_retained_cards": len(retained),
            "total_excess_duplicates": len(duplicates),
            "total_excess_reference_cents": total_excess_cents,
            "total_candidate_lots": len(candidate_lots),
            "bonus_energies": sum(l["bonus_count"] for l in candidate_lots),
            "lots": candidate_lots,
            **self.pool_report(pool),
        }

    # -- Brouillons et rotation -------------------------------------------------

    @staticmethod
    def online_lot(db: sqlite3.Connection, sale_id: str) -> Optional[Card]:
        """Annonce de lot en ligne qui porte les cartes de cette vente, s'il y en a une."""
        row = db.execute(
            """
            SELECT l.id, l.title FROM listings l
            JOIN listing_items li ON li.listing_id = l.id AND li.active = 1
            JOIN sale_items si ON si.copy_id = li.copy_id
            WHERE si.sale_id = ? AND l.state = 'online'
              AND (SELECT count(*) FROM listing_items x WHERE x.listing_id = l.id AND x.active = 1) > 1
            LIMIT 1
            """,
            (sale_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def tool_made(db: sqlite3.Connection, sale_id: str) -> bool:
        """Vente créée comme lot par l'outil des lots ou par un agent, pas par une personne.

        Le canal passe de « Lot » à « Vitrine » à la publication : c'est donc l'événement
        de création qui fait foi (auteur et canal d'origine), pas la ligne actuelle.
        """
        row = db.execute(
            "SELECT actor, after_json FROM sale_events WHERE sale_id=? ORDER BY id LIMIT 1",
            (sale_id,),
        ).fetchone()
        if not row or not is_agent(row["actor"]):
            return False
        try:
            created = json.loads(row["after_json"])
        except ValueError:
            return False
        return isinstance(created, dict) and created.get("channel") == "Lot"

    def status(self, db: sqlite3.Connection, max_drafts: int = MAX_ROTATION_DRAFTS) -> dict[str, Any]:
        cur = db.cursor()
        cur.execute("""
            SELECT id, title, status, amount_cents, asking_cents, created_at, updated_at
            FROM sales
            ORDER BY created_at DESC
        """)
        all_sales = [dict(r) for r in cur.fetchall()]

        drafts = []
        for s in all_sales:
            if s["status"] == "draft":
                cur.execute("""
                    SELECT c.id, c.name, c.stock_state, c.deleted_at
                    FROM sale_items si
                    JOIN copies c ON c.id = si.copy_id
                    WHERE si.sale_id = ?
                """, (s["id"],))
                items = [dict(r) for r in cur.fetchall()]
                invalid_items = [
                    it for it in items
                    if it["deleted_at"] or it["stock_state"] != "available"
                ]
                s["items_count"] = len(items)
                s["is_valid"] = len(invalid_items) == 0
                s["invalid_reasons"] = [
                    f"{it['name']} ({it['id'][:8]}): stock={it['stock_state']}"
                    for it in invalid_items
                ]
                online = self.online_lot(db, s["id"])
                s["online_listing_id"] = online["id"] if online else None
                drafts.append(s)

        return {
            "max_drafts": max_drafts,
            "active_drafts_count": len(drafts),
            "online_drafts_count": sum(1 for d in drafts if d["online_listing_id"]),
            "capacity_available": max(0, max_drafts - len(drafts)),
            "active_drafts": drafts,
            "total_sales_history": len(all_sales),
        }

    def plan_rotation(
        self,
        db: sqlite3.Connection,
        lots_to_add: Optional[list[Card]] = None,
        limit_add: Optional[int] = None,
        max_drafts: int = MAX_ROTATION_DRAFTS,
        dry_run: bool = False,
    ) -> RotationPlan:
        """Calcule la rotation FIFO qui maintient au plus ``max_drafts`` brouillons actifs.

        Un brouillon dont le lot est en ligne n'est jamais annulé : l'annuler laisserait
        l'annonce en vitrine sans dossier de vente. Il compte dans le plafond ; s'il ne
        reste pas assez de place, moins de nouveaux lots sont créés.
        """
        if max_drafts < 1:
            raise ValueError("Le plafond de brouillons est d'au moins 1.")
        limit_add = max_drafts if limit_add is None else max(0, limit_add)
        status = self.status(db, max_drafts)
        existing_drafts = status["active_drafts"]
        online_drafts = [d for d in existing_drafts if d["online_listing_id"]]
        cancellable = [d for d in existing_drafts if not d["online_listing_id"]]

        # Si aucun lot n'est fourni, on analyse pour obtenir les meilleurs candidats
        if lots_to_add is None:
            candidate_lots = self.analyze(db)["lots"]
        else:
            candidate_lots = lots_to_add

        room = max(0, max_drafts - len(online_drafts))
        selected_new_lots = candidate_lots[: min(limit_add, room)]
        skipped_lots = candidate_lots[len(selected_new_lots): limit_add]

        total_after = len(existing_drafts) + len(selected_new_lots)
        excess = max(0, total_after - max_drafts)

        # Priorité de purge : les brouillons invalides (zombies) sont éliminés en premier,
        # puis les plus anciens ; jamais un brouillon dont le lot est en ligne.
        invalid_drafts = [d for d in cancellable if not d.get("is_valid", True)]
        valid_drafts = [d for d in cancellable if d.get("is_valid", True)]
        drafts_to_cancel = invalid_drafts[:excess]
        remaining = excess - len(drafts_to_cancel)
        if remaining > 0:
            drafts_to_cancel.extend(list(reversed(valid_drafts))[:remaining])

        report = {
            "dry_run": dry_run,
            "max_drafts": max_drafts,
            "initial_active_drafts": len(existing_drafts),
            "drafts_to_cancel": [
                {
                    "id": d["id"],
                    "title": d["title"],
                    "created_at": d["created_at"],
                    "is_valid": d.get("is_valid", True),
                }
                for d in drafts_to_cancel
            ],
            "online_drafts_kept": [
                {"id": d["id"], "title": d["title"], "online_listing_id": d["online_listing_id"]}
                for d in online_drafts
            ],
            "lots_to_create": [
                {
                    "title": l["title"],
                    "count": l["count"],
                    "bonus_count": l.get("bonus_count", 0),
                    "asking_cents": l["asking_cents"],
                    "total_reference_cents": l["total_reference_cents"],
                }
                for l in selected_new_lots
            ],
            "lots_skipped_for_capacity": [l["title"] for l in skipped_lots],
            "final_projected_drafts": len(existing_drafts) - len(drafts_to_cancel) + len(selected_new_lots),
        }
        return RotationPlan(report, drafts_to_cancel, selected_new_lots)

    def apply_rotation(self, db: sqlite3.Connection, plan: RotationPlan, actor: str = DEFAULT_ACTOR) -> list[Card]:
        """Annule et crée les brouillons du plan, dans la transaction d'écriture ``db``.

        Annulations et créations réussissent ou échouent ensemble : l'appelant
        valide ou annule la transaction.
        """
        created = []
        for d in plan.cancel:
            row = db.execute("SELECT version, status FROM sales WHERE id=?", (d["id"],)).fetchone()
            if not row or row["status"] != "draft":
                continue
            if self.online_lot(db, d["id"]):
                raise ValueError(
                    f"Le lot « {d['title']} » vient d'être mis en ligne : relancez la rotation."
                )
            self.store.update_sale(
                d["id"],
                {"status": "cancelled"},
                row["version"],
                actor,
                "Rotation FIFO : remplacement par un nouveau lot",
                _db=db,
            )

        for lot in plan.create:
            copy_ids = [c["id"] for c in lot["copies"]]
            values = {
                "title": lot["title"][:256],
                "channel": "Lot",
                "notes": (
                    f"Lot généré automatiquement ({lot['theme']}). "
                    f"Valeur de référence : {lot['total_reference_cents']/100:.2f} €."
                ),
                "amount_cents": lot["asking_cents"],
                "asking_cents": lot["asking_cents"],
            }
            sale_id = self.store.create_sale(values, copy_ids, actor, _db=db)
            created.append({"sale_id": sale_id, "title": lot["title"]})
        return created

    # -- Publication en vitrine -------------------------------------------------

    def publication_plan(self, db: sqlite3.Connection, sale_id: str) -> tuple[Card, list[str], list[Card], int]:
        """Vérifie qu'un brouillon peut être publié en lot, sans rien écrire.

        Mêmes règles que ``Listings.publish(lot=True)`` (``display_price`` avec le
        plancher appliqué au lot entier), vérifiées pour toutes les cartes avant
        toute dépublication. Lève ``ValueError`` avec la liste des refus.
        """
        sale_row = db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
        if not sale_row:
            raise KeyError(f"Vente introuvable : {sale_id}")
        sale = dict(sale_row)
        if sale["status"] != "draft":
            raise ValueError(f"Seul un brouillon se publie en lot (statut : {sale['status']}).")

        items = [
            dict(r)
            for r in db.execute(
                """
                SELECT c.id, c.name, c.stock_state, c.deleted_at, c.reference_cents
                FROM sale_items si
                JOIN copies c ON c.id = si.copy_id
                WHERE si.sale_id = ?
                ORDER BY si.rowid
                """,
                (sale_id,),
            )
        ]
        if len(items) < 2:
            raise ValueError("Un lot réunit au moins deux exemplaires.")
        online = self.online_lot(db, sale_id)
        if online:
            raise ValueError(f"Ce lot est déjà en ligne (annonce {online['id']}).")

        price_cents = sale["amount_cents"] or sale["asking_cents"]
        if not price_cents:
            raise ValueError("Fixez le prix du lot avant de le publier.")
        refusals = []
        if price_cents < FLOOR_CENTS:
            refusals.append(f"Un lot se vend au moins {euros(FLOOR_CENTS / 100)}.")
        # Plancher anti-bradage, sur les cotes du jour : une baisse de prix ne passe
        # pas en douce si les cotes ont monté depuis le brouillon.
        # Une cote nulle ne vaut pas mieux qu'une cote absente : elle annulerait le plancher.
        copy_ids = [it["id"] for it in items]
        cards = self.cards(db, copy_ids)

        def offered(it: Card) -> bool:
            # Une énergie en vrac offerte n'a pas de cote à protéger (décision 0041).
            card = cards.get(it["id"])
            return bool(card and (card["valuation"] or {}).get("bulk"))

        unrated = [it for it in items if not it["reference_cents"] and not offered(it)]
        if not any(it["reference_cents"] for it in items):
            unrated = unrated or items
        if unrated:
            refusals.append(
                f"{len(unrated)} carte(s) sans cote : impossible de vérifier que le lot n'est pas bradé."
            )
        floor_refusal = None
        floor = 0
        margin = lot_max_margin(db)
        if not unrated:
            floor = lot_floor_cents(sum(it["reference_cents"] or 0 for it in items), margin)
            if price_cents < floor:
                floor_refusal = (
                    f"Prix du lot {euros(price_cents / 100)} sous le plancher anti-bradage de "
                    f"{euros(floor / 100)} (somme des cotes moins {margin} %)."
                )
                refusals.append(floor_refusal)

        to_unpublish = []
        for it in items:
            label = f"{it['name']} ({it['id'][:8]})"
            card = cards.get(it["id"])
            if card is None or it["deleted_at"]:
                refusals.append(f"{label} : exemplaire supprimé de la collection.")
                continue
            proposal = display_price(card, card["valuation"], MANUAL_PRICE)
            if not proposal["publishable"]:
                refusals.append(f"{label} : " + " ".join(proposal["reasons"]))
                continue
            active = Listings.active(db, it["id"])
            if active:
                count = db.execute(
                    "SELECT count(*) FROM listing_items WHERE listing_id=? AND active=1",
                    (active["id"],),
                ).fetchone()[0]
                if count > 1:
                    refusals.append(f"{label} : déjà dans le lot en ligne « {active['title']} ».")
                    continue
                to_unpublish.append(active)
        if refusals:
            message = "Lot non publiable, aucune annonce n'a été retirée : " + " ; ".join(refusals)
            if refusals == [floor_refusal]:
                # Seul le plancher bloque : la décision revient à une personne (décision 0030).
                refs = {it["id"]: it["reference_cents"] or 0 for it in items}
                raise FloorRefusal(
                    message,
                    {
                        "copy_ids": copy_ids,
                        "lot": True,
                        "title": sale["title"],
                        "price_cents": price_cents,
                        "floor_cents": floor,
                        "references": [{"copy_id": c, "reference_cents": refs[c]} for c in copy_ids],
                        "total_reference_cents": sum(refs.values()),
                        "margin": margin,
                        "refusal": floor_refusal,
                        "reason": f"Lot « {sale['title']} » composé par l'outil de lots, prix demandé sous le plancher.",
                    },
                )
            raise ValueError(message)
        return sale, copy_ids, to_unpublish, price_cents

    def publish_lot(
        self, db: sqlite3.Connection, sale_id: str, actor: str = DEFAULT_ACTOR, dry_run: bool = False
    ) -> dict[str, Any]:
        """Remplace les annonces unitaires des cartes du lot par une annonce de lot.

        Toutes les cartes sont vérifiées avant la moindre écriture. Hors essai à
        blanc, ``db`` est une transaction d'écriture : dépublication, publication
        et mise à jour de la vente s'y font ensemble, et l'appelant l'annule en
        cas d'erreur. Un refus au seul plancher lève ``FloorRefusal`` : la demande
        de dérogation s'enregistre après l'annulation (``record_floor_refusal``).
        """
        sale, copy_ids, to_unpublish, price_cents = self.publication_plan(db, sale_id)
        new_listing = None
        if not dry_run:
            listings = Listings(SharedTransaction(self.store, db))
            title = sale["title"]
            for l in to_unpublish:
                listings.unpublish(
                    l["id"], l["version"], actor, f"Regroupement dans le lot vitrine '{title}'"
                )
            new_listing = listings.publish(
                copy_ids, actor, price_cents=price_cents, title=title, lot=True
            )
            self.store.update_sale(
                sale_id,
                {
                    "channel": "Vitrine",
                    "notes": ((sale["notes"] or "") + f"\nPublié en vitrine : annonce {new_listing['id']}").strip(),
                },
                sale["version"],
                actor,
                "Publication du lot en vitrine publique",
                _db=db,
            )

        report = {
            "dry_run": dry_run,
            "sale_id": sale_id,
            "title": sale["title"],
            "price_cents": price_cents,
            "copies_count": len(copy_ids),
            "unpublish_count": len(to_unpublish),
            "unpublish_listings": [
                {"id": l["id"], "title": l["title"], "version": l["version"]}
                for l in to_unpublish
            ],
        }
        if new_listing is not None:
            report["published_listing_id"] = new_listing["id"]
        return report

    def record_floor_refusal(self, refusal: FloorRefusal, actor: str, sale_id: str) -> None:
        """Enregistre la demande de dérogation d'un agent, une fois la transaction annulée."""
        if is_agent(actor):
            refusal.request_id = record(self.store, refusal.details, actor, sale_id=sale_id)

    # -- Composition sur mesure -------------------------------------------------

    def compose_from_recipe(
        self,
        db: sqlite3.Connection,
        recipe: LotCompositionRecipe,
        duplicates: Optional[list[Card]] = None,
        pool: Optional[list[Card]] = None,
        scope: str = "duplicates",
    ) -> dict[str, Any]:
        """Constitue un lot à partir d'une recette typée (LotCompositionRecipe)."""
        report = None
        if pool is not None:
            candidates_source = pool
        elif duplicates is not None:
            candidates_source = duplicates
        else:
            classified = self.classify_pool(db)
            candidates_source = classified["duplicates"]
            if scope == "all":
                candidates_source = candidates_source + classified["album_eligible"]
            report = self.pool_report(classified, scope)

        # 1. Filtres durs (Hard Filters)
        candidates = []
        min_cond_rank = CONDITION_RANKS.get((recipe.filters.min_condition or "PO").upper(), 7)

        for c in candidates_source:
            # État minimum acceptable
            c_cond = (c.get("condition") or "GD").upper()
            if CONDITION_RANKS.get(c_cond, 4) > min_cond_rank:
                continue

            # Filtrage ou exclusion des dresseurs
            if recipe.filters.only_trainers and not is_trainer(c.get("name") or ""):
                continue
            if recipe.filters.exclude_trainers and is_trainer(c.get("name") or ""):
                continue

            # Exclusion des énergies
            if recipe.filters.exclude_energies and is_energy(c.get("name") or "", c.get("catalog_id") or ""):
                continue

            # Finitions requises
            if recipe.filters.finishes:
                c_finish = (c.get("finish") or "normal").lower()
                req_finishes = [f.lower() for f in recipe.filters.finishes]
                # Traiter normal et non_holo comme équivalents
                if "normal" in req_finishes and "non_holo" not in req_finishes:
                    req_finishes.append("non_holo")
                if "non_holo" in req_finishes and "normal" not in req_finishes:
                    req_finishes.append("normal")
                if c_finish not in req_finishes:
                    continue

            # Plage de prix (en centimes)
            ref_c = c.get("reference_cents") or 0
            if recipe.filters.min_cents is not None and ref_c < recipe.filters.min_cents:
                continue
            if recipe.filters.max_cents is not None and ref_c > recipe.filters.max_cents:
                continue

            # Blocs / Époques (eras)
            if recipe.filters.eras:
                c_theme = categorize_card(c)
                c_cat = (c.get("catalog_id") or "").lower()
                c_set = (c.get("set_name") or "").lower()
                matched_era = False
                for era in recipe.filters.eras:
                    era_low = era.lower()
                    if era_low == c_theme.lower() or era_low in c_cat or era_low in c_set:
                        matched_era = True
                        break
                    for theme_name, pattern in THEME_PATTERNS:
                        if theme_name == era_low and re.search(pattern, c_cat):
                            matched_era = True
                            break
                if not matched_era:
                    continue

            # Génération (ex: 1 pour Kanto)
            if recipe.filters.generation == 1:
                clean_name = normalize_pokemon_name(c.get("name") or "")
                c_theme = categorize_card(c)
                c_set = (c.get("set_name") or "").lower()
                if (
                    clean_name not in KANTO_POKEMON_NAMES
                    and c_theme != "vintage_wotc"
                    and "151" not in c_set
                ):
                    continue

            # Noms spécifiques de Pokémon
            if recipe.filters.pokemon_names:
                clean_name = normalize_pokemon_name(c.get("name") or "")
                if not any(normalize_pokemon_name(pn) in clean_name for pn in recipe.filters.pokemon_names):
                    continue

            candidates.append(c)

        if not candidates:
            res: dict[str, Any] = {
                "recipe": recipe.model_dump(),
                "lot": None,
                "error": "Aucune carte ne correspond aux critères stricts de la recette.",
                "candidates_count": 0,
                "scope": scope,
            }
            if report:
                res.update(report)
            try:
                diagnostic = self.diagnose_stock(db, recipe)
                if diagnostic:
                    res["stock_diagnostic"] = diagnostic
            except Exception:
                pass
            return res

        # 2. Scoring & Heuristiques
        def compute_card_score(card: Card) -> float:
            score = 100.0
            ref = card.get("reference_cents") or 0
            finish = (card.get("finish") or "normal").lower()
            name_clean = normalize_pokemon_name(card.get("name") or "")
            cond = (card.get("condition") or "GD").upper()

            # Intention de valeur
            if recipe.scoring.value_intent == ValueIntent.PREMIUM_COLLECTOR:
                score += ref
            elif recipe.scoring.value_intent == ValueIntent.AFFORDABLE_BULK:
                score += max(0, 2000 - ref)
            elif recipe.scoring.value_intent == ValueIntent.UNDERVALUED_GEMS:
                # Privilégier les cartes attrayantes entre 1€ et 10€ et bon état
                if 100 <= ref <= 1000:
                    score += 500
                if cond in ("NM", "EX", "M", "MT"):
                    score += 300
            elif recipe.scoring.value_intent == ValueIntent.BALANCED:
                score += min(500, ref // 2)

            # Finitions brillantes
            if recipe.scoring.favor_holos_and_reverses:
                if finish in ("holo", "reverse", "holo_border"):
                    score += 400

            # Pokémon emblématiques
            if recipe.scoring.prioritize_iconic_pokemon:
                if name_clean in ICONIC_POKEMON:
                    score += 350

            return score

        candidates.sort(key=compute_card_score, reverse=True)

        # 3. Assemblage & Règles de diversité
        target_count = min(max(1, recipe.bundle_rules.target_count), 50)
        selected: list[Card] = []
        seen_species = set()
        spillover = []

        for c in candidates:
            species = normalize_pokemon_name(c.get("name") or "")
            if recipe.bundle_rules.diversity == DiversityStrategy.MAXIMIZE_SPECIES:
                if species not in seen_species:
                    seen_species.add(species)
                    selected.append(c)
                else:
                    spillover.append(c)
            else:
                selected.append(c)

            if len(selected) >= target_count:
                break

        # Compléter avec le reliquat si nécessaire pour atteindre target_count
        if len(selected) < target_count and spillover:
            for c in spillover:
                selected.append(c)
                if len(selected) >= target_count:
                    break

        # Calcul financier
        total_ref_cents = sum(c.get("reference_cents") or 0 for c in selected)
        # La décote ne descend jamais sous le plancher anti-bradage ; l'arrondi au
        # demi-euro se fait vers le haut pour ne pas repasser dessous.
        discount = max(0, min(lot_max_margin(db), recipe.bundle_rules.target_discount_percent))
        raw_asking = -(-total_ref_cents * (100 - discount) // 100)
        asking_cents = max(200, -(-raw_asking // 50) * 50)

        partial_fill = len(selected) < target_count
        warning = None
        if partial_fill:
            warning = (
                f"Stock insuffisant pour satisfaire la cible de {target_count} carte(s) : "
                f"seule(s) {len(selected)} carte(s) éligible(s) trouvée(s)."
            )

        has_album_copies = any(c.get("from_album") for c in selected)
        lot_data = {
            "title": recipe.title,
            "summary": recipe.summary,
            "count": len(selected),
            "target_count": target_count,
            "partial_fill": partial_fill,
            "scope": scope,
            "contains_album_copies": has_album_copies,
            "total_reference_cents": total_ref_cents,
            "discount_percent": discount,
            "asking_cents": asking_cents,
            "copies": [
                {
                    "id": c["id"],
                    "version": c["version"],
                    "name": c["name"],
                    "set_name": c["set_name"],
                    "number": c["number"],
                    "finish": c.get("finish") or "normal",
                    "condition": c.get("condition") or "",
                    "reference_cents": c.get("reference_cents") or 0,
                    "photo": c.get("photo") or "",
                    "page": c.get("page"),
                    "position": c.get("position"),
                    "from_album": bool(c.get("from_album", False)),
                }
                for c in selected
            ],
        }
        if selected:
            self.add_bonus([lot_data], self.bulk_bonus_pool(db))
        if warning:
            lot_data["warning"] = warning
        elif has_album_copies:
            lot_data["warning"] = "Ce lot inclut des exemplaires prélevés de l'album de collection."

        result = {
            "recipe": recipe.model_dump(),
            "candidates_count": len(candidates),
            "partial_fill": partial_fill,
            "scope": scope,
            "lot": lot_data,
        }
        if report:
            result.update(report)
        if warning:
            result["warning"] = warning
        elif has_album_copies:
            result["warning"] = "Ce lot inclut des exemplaires prélevés de l'album de collection."

        if partial_fill or recipe.filters.pokemon_names:
            try:
                diagnostic = self.diagnose_stock(db, recipe)
                if diagnostic:
                    result["stock_diagnostic"] = diagnostic
            except Exception:
                pass

        return result

    def create_draft(
        self, db: sqlite3.Connection, lot: Card, actor: str = DEFAULT_ACTOR, prompt: Optional[str] = None
    ) -> str:
        """Enregistre le lot composé comme brouillon de vente, dans la transaction ``db``."""
        copy_ids = [c["id"] for c in lot["copies"]]
        notes = (
            f"{lot['summary']} "
            f"(Prompt: '{prompt or 'recette personnalisée'}'). "
            f"Valeur de référence: {lot['total_reference_cents']/100:.2f} €."
        ).strip()
        if lot.get("contains_album_copies"):
            notes += " ATTENTION: Ce lot contient des cartes issues de l'album de collection."

        values = {
            "title": lot["title"][:256],
            "channel": "Lot",
            "notes": notes,
            "amount_cents": lot["asking_cents"],
            "asking_cents": lot["asking_cents"],
        }
        sale_id: str = self.store.create_sale(values, copy_ids, actor, _db=db)
        return sale_id
