"""Recette de composition d'un lot : filtres, heuristiques et règles d'assemblage."""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


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
    target_discount_percent: int = Field(0, description="Pourcentage de décote commerciale sur le lot, plafonné par le plancher anti-bradage")


class LotCompositionRecipe(BaseModel):
    title: str = Field(..., description="Titre vendeur du lot")
    summary: str = Field(..., description="Explication concise du choix de composition")
    filters: HardFilters = Field(default_factory=HardFilters)  # type: ignore[arg-type]  # mypy sans greffon pydantic
    scoring: ScoringHeuristics = Field(default_factory=ScoringHeuristics)  # type: ignore[arg-type]  # mypy sans greffon pydantic
    bundle_rules: BundleRules = Field(default_factory=BundleRules)  # type: ignore[arg-type]  # mypy sans greffon pydantic
