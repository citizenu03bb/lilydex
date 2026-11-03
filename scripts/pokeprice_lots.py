#!/usr/bin/env python3
"""Gestion et rotation des lots de doublons pour Les cartes de Lily (pokeprice).

Sous-commandes CLI :
- analyze : examine les doublons et propose des lots thématiques cohérents.
- status  : inspecte les brouillons de vente actifs et la fenêtre de rotation.
- rotate  : applique la rotation (FIFO sur les anciens brouillons hors vitrine si le
            plafond est atteint, création des nouveaux brouillons).
- compose : compose un lot sur mesure à partir d'une recette ou d'un prompt.
- publish-to-storefront : publie un ou tous les brouillons valides en vitrine.

Seules entrent en lot les cartes à l'identité confirmée, chiffrées, sans revue en
attente et sous le seuil de valeur (mêmes règles que ``AgentService``). Les
cartes sans prix sont listées « à chiffrer » dans le rapport.
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import defaultdict
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

MAX_ROTATION_DRAFTS = 5
DEFAULT_ACTOR = "pokeprice-lots"
# Seuil de valeur d'une carte au-delà duquel elle ne part pas en lot (centimes),
# le même que celui de la liste de la collection.
VALUE_CEILING_CENTS = 1000
# Motifs d'exclusion d'AgentService.exclusions retenus pour le gisement des lots.
# « already_published » n'en fait pas partie : la publication du lot retire
# elle-même les annonces unitaires ; les lots en ligne sont exclus à part.
LOT_EXCLUSIONS = ("identity_unconfirmed", "price_incomplete", "review_needed", "valuable_card")
# Modèle Gemini d'interprétation des prompts, remplaçable par variable d'environnement.
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
GEMINI_MODEL_ENV = "POKEPRICE_LOTS_GEMINI_MODEL"


def gemini_model():
    return os.environ.get(GEMINI_MODEL_ENV) or DEFAULT_GEMINI_MODEL


# Classification thématique des extensions Pokémon
THEME_PATTERNS = [
    ("vintage_wotc", r"^(base[1-5]|gym[12]|neo[1-4]|ecard[1-3])(-|$)"),
    ("dp_platine", r"^(dp[1-7]|pl[1-4])(-|$)"),
    ("hgss", r"^hgss[1-4](-|$)"),
    ("ex_era", r"^ex[1-9]?[0-9](-|$)"),
    ("noir_blanc", r"^bw[1-9]?[0-9](-|$)"),
    ("xy", r"^xy[1-9]?[0-9](-|$)"),
    ("soleil_lune", r"^sm[1-9]?[0-9](-|$)"),
    ("epee_bouclier", r"^swsh[1-9]?[0-9](-|$)"),
]

TRAINER_KEYWORDS = {
    "ball", "potion", "lettre", "prof", "tili", "civière", "recherche", "suppression",
    "stade", "fossile", "communication", "relais", "corde", "ambre", "machine technique",
    "temple", "salle", "club", "centre", "gentillesse de maman", "amelle", "scott", "margie", "fan club",
    "invention", "outil", "poké-", "sbire", "hélio", "galaxie", "rocket", "dresseur", "supporter", "objet"
}



def is_trainer(name):
    lower = (name or "").lower().strip()
    for kw in TRAINER_KEYWORDS:
        if " " in kw or "-" in kw:
            if kw in lower:
                return True
        else:
            if re.search(rf"\b{re.escape(kw)}\b", lower):
                return True
    return False


def is_energy(name, catalog_id):
    lower = name.lower()
    return "énergie" in lower or "energy" in lower


def categorize_card(card):
    """Détermine le thème principal d'une carte."""
    cat = (card["catalog_id"] or "").lower()
    name = (card["name"] or "").strip()
    finish = (card["finish"] or "").lower()

    if finish in ("holo", "reverse", "holo_border"):
        return "brillantes"
    if is_energy(name, cat):
        return "energies"
    if is_trainer(name):
        return "dresseurs"

    for theme, pattern in THEME_PATTERNS:
        if re.search(pattern, cat):
            return theme

    return "divers"


# Échelle de classement des états de conservation (du meilleur au plus dégradé)
CONDITION_RANKS = {
    "M": 1,
    "MT": 1,
    "NM": 2,
    "NM/EX": 3,
    "EX": 3,
    "GD": 4,
    "LP": 5,
    "PL": 6,
    "PO": 7,
}

# Pokémon emblématiques (starters, mascottes, légendaires, évolutions populaires)
ICONIC_POKEMON = {
    "dracaufeu", "charizard", "pikachu", "evoli", "eevee", "mewtwo", "mew",
    "tortank", "blastoise", "bulbizarre", "bulbasaur", "salameche", "salamèche", "charmander",
    "carapuce", "squirtle", "florizarre", "venusaur",
    "ectoplasma", "gengar", "lucario", "rayquaza", "lugia", "ho-oh",
    "aquali", "voltali", "pyroli", "mentali", "noctali", "givrali", "phylali", "nymphali",
    "dracolosse", "dragonite", "ronflex", "snorlax", "leviator", "léviator", "gyarados",
}

# Noms français et anglais des 151 Pokémon originaux de Kanto (1ère génération)
KANTO_POKEMON_NAMES = {
    "bulbizarre", "herbizarre", "florizarre", "bulbasaur", "ivysaur", "venusaur",
    "salameche", "salamèche", "reptincel", "dracaufeu", "charmander", "charmeleon", "charizard",
    "carapuce", "carabaffe", "tortank", "squirtle", "wartortle", "blastoise",
    "chenipan", "chrysacier", "papilusion", "caterpie", "metapod", "butterfree",
    "aspicot", "coconfort", "dardargnan", "weedle", "kakuna", "beedrill",
    "roucool", "roucoups", "roucarnage", "pidgey", "pidgeotto", "pidgeot",
    "rattata", "rattatac", "raticate",
    "piafabec", "rapasdepic", "spearow", "fearow",
    "abo", "arbok", "ekans",
    "pikachu", "raichu",
    "sabelette", "sablaireau", "sandshrew", "sandslash",
    "nidoran", "nidorina", "nidoqueen", "nidorino", "nidoking",
    "melofee", "mélofée", "melodelfe", "mélodelfe", "clefairy", "clefable",
    "goupix", "feunard", "vulpix", "ninetales",
    "rondoudou", "grodoudou", "jigglypuff", "wigglytuff",
    "nosferapti", "nosferalto", "zubat", "golbat",
    "mystherbe", "ortide", "rafflesia", "oddish", "gloom", "vileplume",
    "paras", "parasect",
    "mimitoss", "aeromite", "aéromite", "venonat", "venomoth",
    "taupiqueur", "triopikeur", "diglett", "dugtrio",
    "miaouss", "persian", "meowth",
    "psykokwak", "akwakwak", "psyduck", "golduck",
    "ferosinge", "férosinge", "colossinge", "mankey", "primeape",
    "caninos", "arcanin", "growlithe", "arcanine",
    "ptitard", "tetarte", "têtarte", "tartard", "poliwag", "poliwhirl", "poliwrath",
    "abra", "kadabra", "alakazam",
    "machoc", "machopeur", "mackogneur", "machop", "machoke", "machamp",
    "chetiflor", "chétiflor", "boustiflor", "empiflor", "bellsprout", "weepinbell", "victreebel",
    "tentacool", "tentacruel",
    "racaillou", "gravalanch", "grolem", "geodude", "graveler", "golem",
    "ponyta", "galopa", "rapidash",
    "ramoloss", "flagadoss", "slowpoke", "slowbro",
    "magneti", "magnéti", "magneton", "magnéton", "magnemite",
    "canarticho", "farfetchd",
    "doduo", "dodrio",
    "otaria", "lamantine", "seel", "dewgong",
    "tadmorv", "grotadmorv", "grimer", "muk",
    "kokiyas", "crustabri", "shellder", "cloyster",
    "fantominus", "spectrum", "ectoplasma", "gastly", "haunter", "gengar",
    "onix",
    "soporifik", "hypnomade", "drowzee", "hypno",
    "krabby", "krabboss", "kingler",
    "voltorbe", "electrode", "électrode", "voltorb",
    "noeunoeuf", "noadkoko", "exeggcute", "exeggutor",
    "osselait", "ossatueur", "cubone", "marowak",
    "kicklee", "tygnon", "hitmonlee", "hitmonchan",
    "excelangue", "lickitung",
    "smogo", "smogogo", "koffing", "weezing",
    "rhinocorne", "rhinoferos", "rhinoféros", "rhyhorn", "rhydon",
    "leveinard", "chansey",
    "saquedeneu", "tangela",
    "kangourex", "kangaskhan",
    "hypotrempe", "hypocean", "hypocéan", "horsea", "seadra",
    "poissirene", "poissirène", "poissoroy", "goldeen", "seaking",
    "stari", "staross", "staryu", "starmie",
    "m. mime", "mr. mime",
    "insecateur", "insécateur", "scyther",
    "lippoutou", "jynx",
    "elektek", "élektek", "electabuzz",
    "magmar",
    "scarabrute", "pinsir",
    "tauros",
    "magicarpe", "leviator", "léviator", "magikarp", "gyarados",
    "lokhlass", "lapras",
    "metamorph", "métamorph", "ditto",
    "evoli", "évoli", "eevee",
    "aquali", "voltali", "pyroli", "vaporeon", "jolteon", "flareon",
    "porygon",
    "amonita", "amonistar", "omanyte", "omastar",
    "kabuto", "kabutops",
    "ptera", "ptéra", "aerodactyl",
    "ronflex", "snorlax",
    "artikodin", "elekthor", "électhor", "sulfura", "articuno", "zapdos", "moltres",
    "minidraco", "draco", "dracolosse", "dratini", "dragonair", "dragonite",
    "mewtwo", "mew"
}


def normalize_pokemon_name(name: str) -> str:
    """Extrait le nom de base du Pokémon en minuscules sans ponctuation ni suffixes."""
    cleaned = re.sub(
        r"\b(ex|gx|vmax|vstar|v-union|v|radieux|obscur|lumineux|brillant|d'obscurité|d'or|delta|star|prime|legend|légende)\b",
        "",
        name or "",
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    return " ".join(cleaned.split()).lower()



class ValueIntent(str, Enum):
    UNDERVALUED_GEMS = "undervalued_gems"
    PREMIUM_COLLECTOR = "premium_collector"
    AFFORDABLE_BULK = "affordable_bulk"
    BALANCED = "balanced"


class DiversityStrategy(str, Enum):
    MAXIMIZE_SPECIES = "maximize_species"
    MAXIMIZE_SETS = "maximize_sets"
    ANY = "any"


class HardFilters(BaseModel):
    eras: Optional[List[str]] = Field(None, description="Blocs ciblés: vintage_wotc, dp_platine, hgss, ex_era, noir_blanc, xy, soleil_lune, epee_bouclier")
    min_condition: Optional[str] = Field("GD", description="État minimum acceptable parmi NM, EX, GD, LP, PL, PO")
    finishes: Optional[List[str]] = Field(None, description="Finitions requises parmi normal, holo, reverse, holo_border")
    min_cents: Optional[int] = Field(None, description="Cote minimale par carte en centimes")
    max_cents: Optional[int] = Field(None, description="Cote maximale par carte en centimes")
    exclude_trainers: bool = Field(False, description="Exclure les cartes Dresseurs")
    only_trainers: bool = Field(False, description="Ne retenir que les cartes Dresseurs et Objets utilitaires")
    exclude_energies: bool = Field(True, description="Exclure les cartes Énergies")
    pokemon_names: Optional[List[str]] = Field(None, description="Noms de Pokémon spécifiques ciblés")
    generation: Optional[int] = Field(None, description="Numéro de génération (ex: 1 pour Kanto/151)")


class ScoringHeuristics(BaseModel):
    value_intent: ValueIntent = Field(ValueIntent.BALANCED, description="Intention de valorisation")
    favor_holos_and_reverses: bool = Field(False, description="Privilégier les finitions brillantes")
    prioritize_iconic_pokemon: bool = Field(False, description="Booster les Pokémon emblématiques")


class BundleRules(BaseModel):
    target_count: int = Field(10, description="Nombre de cartes souhaité dans le lot")
    diversity: DiversityStrategy = Field(DiversityStrategy.MAXIMIZE_SPECIES, description="Stratégie de diversité")
    target_discount_percent: int = Field(15, description="Pourcentage de décote commerciale sur le lot")


class LotCompositionRecipe(BaseModel):
    title: str = Field(..., description="Titre vendeur du lot")
    summary: str = Field(..., description="Explication concise du choix de composition")
    filters: HardFilters = Field(default_factory=HardFilters)
    scoring: ScoringHeuristics = Field(default_factory=ScoringHeuristics)
    bundle_rules: BundleRules = Field(default_factory=BundleRules)


def prompt_to_recipe(prompt: str, model_name: Optional[str] = None) -> LotCompositionRecipe:
    """Interprète un prompt en langage naturel pour produire une recette de composition typée."""
    from dotenv import load_dotenv
    from google import genai
    from google.genai import types

    load_dotenv(Path.home() / ".env")
    load_dotenv(Path.cwd() / ".env")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY absente. Définissez la clé ou utilisez l'option --recipe pour fournir une recette JSON directe."
        )

    system_instruction = (
        "Tu es l'assistant expert en cartes Pokémon pour l'application Les cartes de Lily (pokeprice).\n"
        "Ton rôle est d'analyser le prompt d'un utilisateur demandant la composition d'un lot de cartes "
        "et de générer une recette de composition structurée (LotCompositionRecipe).\n\n"
        "Règles d'interprétation :\n"
        "- 'pépites' / 'sous-évaluées' : cibler des cartes en bel état (min_condition='EX' ou 'GD'), "
        "privilégier les finitions brillantes via favor_holos_and_reverses=True (sans forcer finishes=['holo', 'reverse'] comme filtre dur strict sauf si l'utilisateur le demande explicitement), "
        "value_intent='undervalued_gems', exclusion dresseurs/énergies, target_count=5 à 10.\n"
        "- 'première génération' / 'kanto' / '1ère gen' : generation=1, ou eras=['vintage_wotc'], prioritize_iconic_pokemon=True.\n"
        "- 'reverses' / 'brillantes' / 'holos' : si explicitement demandé, finishes=['reverse'] ou finishes=['holo', 'reverse'], favor_holos_and_reverses=True.\n"
        "- 'dresseurs' / 'objets' / 'supporters' / 'stades' : only_trainers=True, exclude_trainers=False, exclude_energies=True, diversity='any'.\n"
        "- Règle stricte sur les prix (min_cents et max_cents) : Ne JAMAIS renseigner min_cents ou max_cents sauf si un montant chiffré précis est explicité dans le prompt (ex: 'à moins de 5€' -> max_cents=500, 'entre 2 et 10 euros' -> min_cents=200, max_cents=1000). Les formulations qualitatives ou relatives telles que 'meilleur marché', 'pas cher', 'meilleur marché-prix', 'économique', 'petits prix' doivent UNIQUEMENT utiliser value_intent='affordable_bulk', en laissant min_cents et max_cents à null.\n"
        "- 'prestige' / 'rares' / 'fortes cotes' : value_intent='premium_collector', min_cents à null sauf montant chiffré explicite.\n"
        "- 'panaché' / 'varié' : diversity='maximize_species' (une seule carte par espèce de Pokémon).\n"
        "- Toujours renseigner un titre attrayant en français et un résumé explicatif."
    )

    client = genai.Client(
        http_options=types.HttpOptions(
            timeout=30000,
            retry_options=types.HttpRetryOptions(attempts=2),
        )
    )
    response = client.models.generate_content(
        model=model_name or gemini_model(),
        contents=[prompt],
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=LotCompositionRecipe,
            temperature=0.2,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        ),
    )
    return LotCompositionRecipe.model_validate_json(response.text)



class _SharedTransaction:
    """Magasin dont les connexions réutilisent une transaction déjà ouverte.

    ``Listings`` ouvre sa propre transaction à chaque écriture. En lui passant ce
    mandataire, dépublication, publication et mise à jour de la vente partagent
    une seule transaction : une erreur n'importe où annule l'ensemble. Les
    lectures de valorisation (``Store.listing``) gardent leur propre connexion.
    """

    def __init__(self, store, db):
        self._store = store
        self._db = db

    def __getattr__(self, name):
        return getattr(self._store, name)

    @contextmanager
    def connect(self, *, write=False):
        # Ni validation ni annulation ici : la transaction englobante décide.
        yield self._db


class LotsEngine:
    def __init__(self, db_path, *, value_ceiling_cents=VALUE_CEILING_CENTS):
        self.db_path = str(db_path)
        self.value_ceiling_cents = value_ceiling_cents
        self._store = None

    def connect(self, write=False):
        uri = f"file:{self.db_path}?mode={'rw' if write else 'ro'}"
        con = sqlite3.connect(uri, uri=True)
        con.row_factory = sqlite3.Row
        return con

    def store(self):
        if self._store is None:
            from pokeprice.inventory import Store

            self._store = Store(str(Path(self.db_path).parent))
        return self._store

    def valued_cards(self):
        """Fiches de la collection avec leur valorisation, comme la liste de gestion."""
        rows = self.store().listing(limit=10**9, threshold_cents=self.value_ceiling_cents)["items"]
        return {r["id"]: r for r in rows}

    @staticmethod
    def lot_exclusions(card):
        """Motifs qui interdisent une carte en lot (règles d'AgentService.exclusions)."""
        if card is None:
            return ["identity_unconfirmed", "price_incomplete"]
        from pokeprice.agent import AgentService

        return [r for r in AgentService.exclusions(card) if r in LOT_EXCLUSIONS]

    def get_busy_copy_ids(self, db):
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

    def classify_pool(self, db):
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
        valued = self.valued_cards()

        # Regrouper par référence et langue
        groups = defaultdict(list)
        for card in all_cards:
            groups[(card["catalog_id"], card["language"])].append(card)

        def copy_collection_rank(c):
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

        result = {"retained": [], "duplicates": [], "album_eligible": [], "excluded": [], "to_price": []}

        def sort_out(card):
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

    def get_duplicates_pool(self, db):
        """Exemplaires conservés en album et doublons éligibles à un lot."""
        pool = self.classify_pool(db)
        return pool["retained"], pool["duplicates"]

    def get_pool(self, db, scope="duplicates"):
        """Retourne le gisement de cartes selon le périmètre demandé (duplicates ou all)."""
        pool = self.classify_pool(db)
        if scope == "all":
            return pool["duplicates"] + pool["album_eligible"]
        return pool["duplicates"]

    def diagnose_stock(self, db, recipe: LotCompositionRecipe):
        """Fournit un diagnostic clair de l'état du stock pour expliquer la pénurie ou l'état partiel."""
        cur = db.cursor()
        busy_ids = self.get_busy_copy_ids(db)

        # Identifier les cartes ciblées par le recipe
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
        groups = defaultdict(list)
        for c in all_matches:
            groups[(c["catalog_id"], c["language"])].append(c)

        retained_ids = set()
        duplicate_ids = set()
        for (cat_id, lang), copies in groups.items():
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
        busy_details = []
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


    def compose_candidate_lots(self, duplicates, max_cards_per_lot=20):
        """Compose des propositions de lots thématiques cohérents."""
        categorized = defaultdict(list)
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

        lots = []
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
    def pool_report(pool, scope="duplicates"):
        """Cartes écartées du gisement et liste « à chiffrer » pour le rapport."""
        def keep(entry):
            return scope == "all" or not entry["from_album"]

        excluded = [e for e in pool["excluded"] if keep(e)]
        to_price = [e for e in pool["to_price"] if keep(e)]
        return {
            "excluded_count": len(excluded),
            "excluded": excluded,
            "to_price_count": len(to_price),
            "to_price": to_price,
        }

    def analyze(self, max_cards_per_lot=20):
        with self.connect(write=False) as db:
            pool = self.classify_pool(db)
        retained, duplicates = pool["retained"], pool["duplicates"]
        candidate_lots = self.compose_candidate_lots(duplicates, max_cards_per_lot=max_cards_per_lot)
        total_excess_cents = sum(c["reference_cents"] or 0 for c in duplicates)

        return {
            "total_retained_cards": len(retained),
            "total_excess_duplicates": len(duplicates),
            "total_excess_reference_cents": total_excess_cents,
            "total_candidate_lots": len(candidate_lots),
            "lots": candidate_lots,
            **self.pool_report(pool),
        }

    @staticmethod
    def online_lot(db, sale_id):
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

    def status(self, max_drafts=MAX_ROTATION_DRAFTS):
        with self.connect(write=False) as db:
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

    def rotate(
        self,
        lots_to_add=None,
        limit_add=None,
        dry_run=False,
        actor=DEFAULT_ACTOR,
        max_drafts=MAX_ROTATION_DRAFTS,
    ):
        """Applique la rotation FIFO pour maintenir au plus ``max_drafts`` brouillons actifs.

        Un brouillon dont le lot est en ligne n'est jamais annulé : l'annuler laisserait
        l'annonce en vitrine sans dossier de vente. Il compte dans le plafond ; s'il ne
        reste pas assez de place, moins de nouveaux lots sont créés.
        """
        if max_drafts < 1:
            raise ValueError("Le plafond de brouillons est d'au moins 1.")
        limit_add = max_drafts if limit_add is None else max(0, limit_add)
        status = self.status(max_drafts)
        existing_drafts = status["active_drafts"]
        online_drafts = [d for d in existing_drafts if d["online_listing_id"]]
        cancellable = [d for d in existing_drafts if not d["online_listing_id"]]

        # Si aucun lot n'est fourni, on analyse pour obtenir les meilleurs candidats
        if lots_to_add is None:
            candidate_lots = self.analyze()["lots"]
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
                    "asking_cents": l["asking_cents"],
                    "total_reference_cents": l["total_reference_cents"],
                }
                for l in selected_new_lots
            ],
            "lots_skipped_for_capacity": [l["title"] for l in skipped_lots],
            "final_projected_drafts": len(existing_drafts) - len(drafts_to_cancel) + len(selected_new_lots),
        }

        if dry_run:
            return report

        store = self.store()
        created = []
        # Une seule transaction : annulations et créations réussissent ou échouent ensemble.
        with store.connect(write=True) as db:
            for d in drafts_to_cancel:
                row = db.execute("SELECT version, status FROM sales WHERE id=?", (d["id"],)).fetchone()
                if not row or row["status"] != "draft":
                    continue
                if self.online_lot(db, d["id"]):
                    raise ValueError(
                        f"Le lot « {d['title']} » vient d'être mis en ligne : relancez la rotation."
                    )
                store.update_sale(
                    d["id"],
                    {"status": "cancelled"},
                    row["version"],
                    actor,
                    "Rotation FIFO : remplacement par un nouveau lot",
                    _db=db,
                )

            for lot in selected_new_lots:
                copy_ids = [c["id"] for c in lot["copies"]]
                values = {
                    "title": lot["title"][:256],
                    "channel": "Lot",
                    "notes": f"Lot généré automatiquement ({lot['theme']}). Valeur de référence : {lot['total_reference_cents']/100:.2f} €.",
                    "amount_cents": lot["asking_cents"],
                    "asking_cents": lot["asking_cents"],
                }
                sale_id = store.create_sale(values, copy_ids, actor, _db=db)
                created.append({"sale_id": sale_id, "title": lot["title"]})

        report["created"] = created
        return report

    def publication_plan(self, db, listings, sale_id):
        """Vérifie qu'un brouillon peut être publié en lot, sans rien écrire.

        Mêmes règles que ``Listings.publish(lot=True)`` (``display_price`` avec le
        plancher appliqué au lot entier), vérifiées pour toutes les cartes avant
        toute dépublication. Lève ``ValueError`` avec la liste des refus.
        """
        from pokeprice.pricing import FLOOR_CENTS, display_price, euros

        sale = db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
        if not sale:
            raise KeyError(f"Vente introuvable : {sale_id}")
        sale = dict(sale)
        if sale["status"] != "draft":
            raise ValueError(f"Seul un brouillon se publie en lot (statut : {sale['status']}).")

        items = [
            dict(r)
            for r in db.execute(
                """
                SELECT c.id, c.name, c.stock_state, c.deleted_at
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

        copy_ids = [it["id"] for it in items]
        cards = listings.cards(copy_ids)
        to_unpublish = []
        for it in items:
            label = f"{it['name']} ({it['id'][:8]})"
            card = cards.get(it["id"])
            if card is None or it["deleted_at"]:
                refusals.append(f"{label} : exemplaire supprimé de la collection.")
                continue
            proposal = display_price(
                card,
                card["valuation"],
                {"amount_cents": FLOOR_CENTS, "mode": "manual", "source": "Prix fixé à la main"},
            )
            if not proposal["publishable"]:
                refusals.append(f"{label} : " + " ".join(proposal["reasons"]))
                continue
            active = listings.active(db, it["id"])
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
            raise ValueError(
                "Lot non publiable, aucune annonce n'a été retirée : " + " ; ".join(refusals)
            )
        return sale, copy_ids, to_unpublish, price_cents

    def publish_to_storefront(self, sale_id, actor=DEFAULT_ACTOR, dry_run=False):
        """Remplace les annonces unitaires des cartes du lot par une annonce de lot.

        Toutes les cartes sont vérifiées avant la moindre écriture ; dépublication,
        publication et mise à jour de la vente se font dans une seule transaction.
        En cas d'erreur, rien n'est écrit et les annonces unitaires restent en ligne.
        """
        from pokeprice.listings import Listings

        store = self.store()
        if dry_run:
            with store.connect() as db:
                sale, copy_ids, to_unpublish, price_cents = self.publication_plan(
                    db, Listings(store), sale_id
                )
        else:
            with store.connect(write=True) as db:
                listings = Listings(_SharedTransaction(store, db))
                sale, copy_ids, to_unpublish, price_cents = self.publication_plan(
                    db, listings, sale_id
                )
                title = sale["title"]
                for l in to_unpublish:
                    listings.unpublish(
                        l["id"], l["version"], actor, f"Regroupement dans le lot vitrine '{title}'"
                    )
                new_listing = listings.publish(
                    copy_ids, actor, price_cents=price_cents, title=title, lot=True
                )
                store.update_sale(
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
        if not dry_run:
            report["published_listing_id"] = new_listing["id"]
        return report

    def publish_all(self, actor=DEFAULT_ACTOR, dry_run=False):
        """Publie chaque brouillon valide qui n'est pas encore en ligne, un par un.

        Chaque lot est atomique : un refus n'empêche pas les autres et ne retire
        aucune annonce unitaire du lot refusé.
        """
        report = {"dry_run": dry_run, "published": [], "refused": [], "skipped": []}
        for draft in reversed(self.status()["active_drafts"]):  # du plus ancien au plus récent
            if draft["online_listing_id"]:
                report["skipped"].append(
                    {"sale_id": draft["id"], "title": draft["title"], "reason": "déjà en ligne"}
                )
                continue
            if not draft["is_valid"]:
                report["skipped"].append(
                    {"sale_id": draft["id"], "title": draft["title"], "reason": "brouillon invalide",
                     "details": draft["invalid_reasons"]}
                )
                continue
            try:
                report["published"].append(
                    self.publish_to_storefront(draft["id"], actor=actor, dry_run=dry_run)
                )
            except (KeyError, ValueError) as exc:
                report["refused"].append(
                    {"sale_id": draft["id"], "title": draft["title"], "reason": str(exc)}
                )
        return report

    def compose_from_recipe(
        self,
        recipe: LotCompositionRecipe,
        duplicates=None,
        pool=None,
        scope="duplicates",
    ):
        """Constitue un lot à partir d'une recette typée (LotCompositionRecipe)."""
        report = None
        if pool is not None:
            candidates_source = pool
        elif duplicates is not None:
            candidates_source = duplicates
        else:
            with self.connect(write=False) as db:
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
            res = {
                "recipe": recipe.model_dump(),
                "lot": None,
                "error": "Aucune carte ne correspond aux critères stricts de la recette.",
                "candidates_count": 0,
                "scope": scope,
            }
            if report:
                res.update(report)
            try:
                with self.connect(write=False) as db:
                    diagnostic = self.diagnose_stock(db, recipe)
                if diagnostic:
                    res["stock_diagnostic"] = diagnostic
            except Exception:
                pass
            return res

        # 2. Scoring & Heuristiques
        def compute_card_score(card):
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
        selected = []
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
        discount = max(0, min(50, recipe.bundle_rules.target_discount_percent))
        raw_asking = total_ref_cents * (1.0 - discount / 100.0)
        asking_cents = max(200, int(round(raw_asking / 50.0) * 50))

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
                with self.connect(write=False) as db:
                    diagnostic = self.diagnose_stock(db, recipe)
                if diagnostic:
                    result["stock_diagnostic"] = diagnostic
            except Exception:
                pass

        return result


    def compose(
        self,
        recipe: LotCompositionRecipe,
        create_draft: bool = False,
        actor: str = DEFAULT_ACTOR,
        prompt: Optional[str] = None,
        dry_run: bool = False,
        scope: str = "duplicates",
    ):
        """Exécute la composition et optionnellement enregistre le brouillon dans sales."""
        result = self.compose_from_recipe(recipe, scope=scope)
        if not result.get("lot"):
            return result

        lot = result["lot"]
        if create_draft:
            if dry_run:
                result["draft_action"] = "dry_run_simulated"
                result["projected_sale_title"] = lot["title"]
                return result

            store = self.store()
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
            with store.connect(write=True) as db:
                sale_id = store.create_sale(values, copy_ids, actor, _db=db)
                result["created_sale_id"] = sale_id
                result["draft_action"] = "created"

        return result


def resolve_db_path(args):
    """Résout le chemin de la base SQLite, toujours donné explicitement par --data."""
    if not args.data:
        raise ValueError("Indiquez la base visée avec --data (aucune base par défaut).")
    p = Path(args.data)
    if p.is_dir():
        return p / "collection.sqlite3"
    return p


def run_remote_command(remote_host, data, subcmd, extra_args):
    """Exécute la commande distante sur le serveur via SSH, sur la base --data indiquée."""
    import shlex

    remote_cmd = [
        "/opt/pokeprice/.venv/bin/python",
        "/opt/pokeprice/scripts/pokeprice_lots.py",
        "--data",
        data,
        "--output",
        f"/tmp/pokeprice_lots_{subcmd}.json",
        subcmd,
    ] + extra_args
    sudo_inner = " ".join(shlex.quote(arg) for arg in remote_cmd)
    full_ssh_cmd = (
        f"cd /tmp && sudo -u pokeprice env HOME=/srv/pokeprice PYTHONPATH=/opt/pokeprice/src {sudo_inner}"
    )
    res = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", remote_host, full_ssh_cmd],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        sys.stderr.write(f"Erreur d'exécution distante :\n{res.stderr}\n")
        sys.exit(1)
    return res.stdout



def main():
    parser = argparse.ArgumentParser(
        description="Génération et rotation de lots de doublons Pokémon pour Les cartes de Lily"
    )
    parser.add_argument(
        "--data",
        required=True,
        help="Dossier ou fichier de la base SQLite visée, toujours explicite "
        "(sur le serveur : /srv/pokeprice/inventory ; pour un essai : une base temporaire)",
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Exécuter sur le serveur distant via SSH (hôte défini dans ~/.config/pokeprice/backup.env), "
        "sur la base --data du serveur",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Fichier de sortie JSON obligatoire pour consigner les résultats",
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="Analyser les doublons et proposer des lots")
    p_analyze.add_argument(
        "--max-per-lot",
        type=int,
        default=20,
        help="Nombre maximum de cartes par lot (défaut: 20)",
    )

    def max_drafts_option(sub):
        sub.add_argument(
            "--max-drafts",
            type=int,
            default=MAX_ROTATION_DRAFTS,
            help=f"Plafond de brouillons actifs (défaut: {MAX_ROTATION_DRAFTS})",
        )

    # status
    p_status = subparsers.add_parser("status", help="Consulter l'état de la fenêtre de rotation des brouillons")
    max_drafts_option(p_status)

    # rotate
    p_rotate = subparsers.add_parser("rotate", help="Appliquer la rotation glissante des brouillons")
    max_drafts_option(p_rotate)
    p_rotate.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Nombre maximal de nouveaux lots à intégrer (défaut: le plafond --max-drafts)",
    )
    p_rotate.add_argument(
        "--dry-run",
        action="store_true",
        help="Simuler la rotation sans modifier la base de données",
    )
    p_rotate.add_argument(
        "--actor",
        default=DEFAULT_ACTOR,
        help="Identifiant de l'auteur inscrit dans les événements (défaut: pokeprice-lots)",
    )

    # compose
    p_comp = subparsers.add_parser(
        "compose",
        help="Composer un lot de doublons sur-mesure à partir d'un prompt naturel ou d'une recette",
    )
    p_comp.add_argument(
        "--prompt",
        help="Prompt en langage naturel (ex: 'trouve-moi les pépites sous-évaluées')",
    )
    p_comp.add_argument(
        "--recipe",
        help="Chemin vers un fichier JSON ou chaîne JSON contenant une recette LotCompositionRecipe",
    )
    p_comp.add_argument(
        "--create-draft",
        action="store_true",
        help="Créer un brouillon de vente dans la base pour ce lot",
    )
    p_comp.add_argument(
        "--dry-run",
        action="store_true",
        help="Simuler sans écriture en base de données",
    )
    p_comp.add_argument(
        "--actor",
        default=DEFAULT_ACTOR,
        help="Identifiant de l'auteur inscrit dans les événements (défaut: pokeprice-lots)",
    )
    p_comp.add_argument(
        "--scope",
        choices=["duplicates", "all"],
        default="duplicates",
        help="Périmètre de cartes éligibles : 'duplicates' (défaut, uniquement doublons libres) ou 'all' (inclut cartes d'album)",
    )

    # publish-to-storefront
    p_pub = subparsers.add_parser(
        "publish-to-storefront",
        help="Publier un lot en vitrine publique (avec dépublication unitaire automatique)",
    )
    target = p_pub.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--sale-id",
        help="Identifiant UUID du lot de vente à publier en vitrine",
    )
    target.add_argument(
        "--all",
        action="store_true",
        help="Publier chaque brouillon valide qui n'est pas encore en ligne",
    )
    p_pub.add_argument(
        "--dry-run",
        action="store_true",
        help="Simuler la publication sans modifier la base de données",
    )
    p_pub.add_argument(
        "--actor",
        default=DEFAULT_ACTOR,
        help="Identifiant de l'auteur inscrit dans les événements (défaut: pokeprice-lots)",
    )

    args = parser.parse_args()

    # Si exécution distante demandée
    if args.remote:
        env_file = Path.home() / ".config/pokeprice/backup.env"
        if not env_file.exists():
            sys.stderr.write(f"Fichier de configuration introuvable : {env_file}\n")
            sys.exit(1)
        remote_host = None
        for line in env_file.read_text().splitlines():
            if line.startswith("POKEPRICE_OCI_HOST="):
                remote_host = line.split("=", 1)[1].strip()
        if not remote_host:
            sys.stderr.write("POKEPRICE_OCI_HOST non défini dans backup.env\n")
            sys.exit(1)

        extra = []
        if args.subcommand == "analyze" and hasattr(args, "max_per_lot"):
            extra.extend(["--max-per-lot", str(args.max_per_lot)])
        elif args.subcommand == "status":
            extra.extend(["--max-drafts", str(args.max_drafts)])
        elif args.subcommand == "rotate":
            extra.extend(["--max-drafts", str(args.max_drafts)])
            if args.dry_run:
                extra.append("--dry-run")
            if args.limit is not None:
                extra.extend(["--limit", str(args.limit)])
            if args.actor:
                extra.extend(["--actor", args.actor])
        elif args.subcommand == "compose":
            if args.prompt and not args.recipe:
                # Interprétation du prompt en local avec GEMINI_API_KEY du poste de pilotage
                print(f"Interprétation locale du prompt via Gemini : '{args.prompt}'...")
                local_recipe = prompt_to_recipe(args.prompt)
                extra.extend(["--recipe", local_recipe.model_dump_json()])
            elif args.recipe:
                recipe_raw = args.recipe
                if not recipe_raw.strip().startswith("{") and len(recipe_raw) < 255:
                    recipe_path = Path(recipe_raw)
                    if recipe_path.exists():
                        recipe_raw = recipe_path.read_text(encoding="utf-8")
                extra.extend(["--recipe", recipe_raw])
            else:
                sys.stderr.write("Erreur: Indiquez --prompt ou --recipe pour compose.\n")
                sys.exit(1)

            if args.create_draft:
                extra.append("--create-draft")
            if args.dry_run:
                extra.append("--dry-run")
            if args.actor:
                extra.extend(["--actor", args.actor])
            if hasattr(args, "scope") and args.scope:
                extra.extend(["--scope", args.scope])

        elif args.subcommand == "publish-to-storefront":
            if args.all:
                extra.append("--all")
            else:
                extra.extend(["--sale-id", args.sale_id])
            if args.dry_run:
                extra.append("--dry-run")
            if args.actor:
                extra.extend(["--actor", args.actor])


        # Exécuter à distance
        run_remote_command(remote_host, args.data, args.subcommand, extra)
        # Télécharger ou lire le JSON distant
        read_cmd = f"ssh -o BatchMode=yes '{remote_host}' 'sudo -u pokeprice cat /tmp/pokeprice_lots_{args.subcommand}.json'"
        json_res = subprocess.run(read_cmd, shell=True, capture_output=True, text=True)
        if json_res.returncode == 0 and json_res.stdout.strip():
            result = json.loads(json_res.stdout)
        else:
            sys.stderr.write("Impossible de récupérer le JSON de sortie distant.\n")
            sys.exit(1)
    else:
        db_path = resolve_db_path(args)
        if not Path(db_path).exists():
            sys.stderr.write(f"Base de données introuvable : {db_path}\n")
            sys.exit(1)

        engine = LotsEngine(db_path)
        if args.subcommand == "analyze":
            result = engine.analyze(max_cards_per_lot=args.max_per_lot)
        elif args.subcommand == "status":
            result = engine.status(max_drafts=args.max_drafts)
        elif args.subcommand == "rotate":
            result = engine.rotate(
                limit_add=args.limit,
                dry_run=args.dry_run,
                actor=args.actor,
                max_drafts=args.max_drafts,
            )
        elif args.subcommand == "compose":
            if not args.prompt and not args.recipe:
                sys.stderr.write("Erreur: Indiquez --prompt ou --recipe pour la commande compose.\n")
                sys.exit(1)

            if args.recipe:
                recipe_raw = args.recipe
                if not recipe_raw.strip().startswith("{") and len(recipe_raw) < 255:
                    recipe_path = Path(recipe_raw)
                    if recipe_path.exists():
                        recipe_raw = recipe_path.read_text(encoding="utf-8")
                recipe_data = json.loads(recipe_raw)
                recipe = LotCompositionRecipe.model_validate(recipe_data)

            else:
                recipe = prompt_to_recipe(args.prompt)

            result = engine.compose(
                recipe=recipe,
                create_draft=args.create_draft,
                actor=args.actor,
                prompt=args.prompt,
                dry_run=args.dry_run,
                scope=getattr(args, "scope", "duplicates"),
            )
        elif args.subcommand == "publish-to-storefront":
            if args.all:
                result = engine.publish_all(actor=args.actor, dry_run=args.dry_run)
            else:
                try:
                    result = engine.publish_to_storefront(
                        sale_id=args.sale_id,
                        actor=args.actor,
                        dry_run=args.dry_run,
                    )
                except (KeyError, ValueError) as exc:
                    sys.stderr.write(f"Publication refusée : {exc}\n")
                    sys.exit(1)

    out_p = Path(args.output)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"Succès ! Résultat écrit dans : {out_p.resolve()}")


if __name__ == "__main__":
    main()
