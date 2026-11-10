"""Lots de doublons : moteur, recette et thèmes.

Le moteur (``engine``) travaille sur le magasin de la collection et une
connexion fournie par l'appelant. L'interprétation d'un prompt par Gemini vit à
part, dans ``pokeprice.lots_prompt``, que le serveur n'importe pas.
"""

from .engine import (
    BONUS_MAX_PER_LOT,
    DEFAULT_ACTOR,
    LOT_EXCLUSIONS,
    MAX_ROTATION_DRAFTS,
    VALUE_CEILING_CENTS,
    LotsEngine,
    RotationPlan,
    bonus_room,
    bonus_title,
)
from .recipe import (
    BundleRules,
    DiversityStrategy,
    HardFilters,
    LotCompositionRecipe,
    ScoringHeuristics,
    ValueIntent,
)

__all__ = [
    "BONUS_MAX_PER_LOT",
    "DEFAULT_ACTOR",
    "LOT_EXCLUSIONS",
    "MAX_ROTATION_DRAFTS",
    "VALUE_CEILING_CENTS",
    "BundleRules",
    "DiversityStrategy",
    "HardFilters",
    "LotCompositionRecipe",
    "LotsEngine",
    "RotationPlan",
    "ScoringHeuristics",
    "ValueIntent",
    "bonus_room",
    "bonus_title",
]
