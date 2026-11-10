"""Interprétation d'un prompt en recette de lot, par Gemini, sur le poste de pilotage.

Le serveur n'importe jamais ce module : la recette lui arrive déjà typée. La
bibliothèque Gemini se charge à l'appel, pas à l'import.
"""

import os
from pathlib import Path
from typing import Optional

from .lots.recipe import LotCompositionRecipe

# Modèle Gemini d'interprétation des prompts, remplaçable par variable d'environnement.
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
GEMINI_MODEL_ENV = "POKEPRICE_LOTS_GEMINI_MODEL"


def gemini_model() -> str:
    return os.environ.get(GEMINI_MODEL_ENV) or DEFAULT_GEMINI_MODEL


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
        contents=[prompt],  # type: ignore[arg-type]  # une liste de str est acceptée à l'exécution
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
    return LotCompositionRecipe.model_validate_json(response.text or "")
