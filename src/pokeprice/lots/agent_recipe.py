"""Recette de lot reçue par l'API agent : validation stricte et empreinte du plan.

Le script ``pokeprice_lots`` garde sa recette permissive (``recipe.py``) ; un agent
passe par ce modèle-ci, plus étroit : champs inconnus refusés, types stricts,
longueurs bornées et aucun lien ni balise dans le texte libre, qui finit en titre
d'annonce publique. ``to_recipe`` la convertit vers la recette du moteur.
"""

import hashlib
import json
import re
from collections.abc import Sequence
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .recipe import LotCompositionRecipe

MAX_LIST_ITEMS = 20
MAX_TITLE_LENGTH = 120
MAX_SUMMARY_LENGTH = 500
MAX_TARGET_COUNT = 50  # le moteur plafonne déjà la cible à 50 cartes
MAX_CENTS = 1_000_000

# Lien, adresse, balise ou caractère de contrôle : rien de cela dans une annonce.
UNSAFE_TEXT = re.compile(
    r"[<>@\x00-\x1f\x7f]|://|\bwww\.|\b[a-z0-9-]+\.(?:com|fr|net|org|io|eu|be|ch|me|co|ly|gg|shop|xyz)\b",
    re.IGNORECASE,
)
NAME = re.compile(r"^[^\W\d_][\w .'’♀♂-]{0,39}$")
ERA = re.compile(r"^[a-z0-9_]{1,40}$")


def safe_text(value: str) -> str:
    if UNSAFE_TEXT.search(value):
        raise ValueError("Ni lien, ni adresse, ni balise, ni caractère de contrôle.")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)


class AgentFilters(StrictModel):
    eras: Optional[list[str]] = Field(None, max_length=MAX_LIST_ITEMS)
    min_condition: Optional[Literal["M", "MT", "NM", "EX", "GD", "LP", "PL", "PO"]] = "GD"
    finishes: Optional[list[Literal["normal", "non_holo", "holo", "reverse", "holo_border"]]] = Field(
        None, max_length=MAX_LIST_ITEMS
    )
    min_cents: Optional[int] = Field(None, ge=0, le=MAX_CENTS)
    max_cents: Optional[int] = Field(None, ge=0, le=MAX_CENTS)
    exclude_trainers: bool = False
    only_trainers: bool = False
    exclude_energies: bool = True
    pokemon_names: Optional[list[str]] = Field(None, max_length=MAX_LIST_ITEMS)
    generation: Optional[int] = Field(None, ge=1, le=9)

    @field_validator("eras")
    @classmethod
    def known_shape_eras(cls, values: Optional[list[str]]) -> Optional[list[str]]:
        for value in values or []:
            if not ERA.fullmatch(value):
                raise ValueError("Un bloc s'écrit en minuscules, chiffres et _ (40 caractères au plus).")
        return values

    @field_validator("pokemon_names")
    @classmethod
    def plain_names(cls, values: Optional[list[str]]) -> Optional[list[str]]:
        for value in values or []:
            if not NAME.fullmatch(value.strip()):
                raise ValueError("Un nom de Pokémon tient en 40 lettres, espaces, points, tirets ou apostrophes.")
        return values


class AgentScoring(StrictModel):
    value_intent: Literal["undervalued_gems", "premium_collector", "affordable_bulk", "balanced"] = "balanced"
    favor_holos_and_reverses: bool = False
    prioritize_iconic_pokemon: bool = False


class AgentBundleRules(StrictModel):
    target_count: int = Field(10, ge=1, le=MAX_TARGET_COUNT)
    diversity: Literal["maximize_species", "maximize_sets", "any"] = "maximize_species"
    # Le moteur ramène toujours la décote sous la marge du plancher anti-bradage.
    target_discount_percent: int = Field(0, ge=0, le=100)


class AgentRecipe(StrictModel):
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    summary: str = Field("", max_length=MAX_SUMMARY_LENGTH)
    filters: AgentFilters = Field(default_factory=AgentFilters)  # type: ignore[arg-type]  # mypy sans greffon pydantic
    scoring: AgentScoring = Field(default_factory=AgentScoring)  # type: ignore[arg-type]  # mypy sans greffon pydantic
    bundle_rules: AgentBundleRules = Field(default_factory=AgentBundleRules)  # type: ignore[arg-type]  # mypy sans greffon pydantic

    @field_validator("title", "summary")
    @classmethod
    def no_link_or_markup(cls, value: str) -> str:
        return safe_text(value)


def to_recipe(recipe: AgentRecipe) -> LotCompositionRecipe:
    """La recette du moteur, avec les mêmes valeurs."""
    return LotCompositionRecipe.model_validate(recipe.model_dump())


def plan_id(
    recipe: AgentRecipe,
    copies: Sequence[tuple[str, int]],
    bonus: Sequence[tuple[str, int]],
    asking_cents: int,
    margin: int,
    value_ceiling_cents: int,
) -> str:
    """Empreinte d'un plan : elle change dès qu'une carte, une version, le prix, la marge ou le plafond change."""
    payload: dict[str, Any] = {
        "recipe": recipe.model_dump(mode="json"),
        "copies": [[c, v] for c, v in copies],
        "bonus": [[c, v] for c, v in bonus],
        "asking_cents": asking_cents,
        "margin": margin,
        "value_ceiling_cents": value_ceiling_cents,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()
