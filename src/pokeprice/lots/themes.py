"""Thèmes, états et noms de Pokémon qui servent à ranger les cartes en lots."""

import re
from collections.abc import Mapping
from typing import Any

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


def is_trainer(name: str | None) -> bool:
    lower = (name or "").lower().strip()
    for kw in TRAINER_KEYWORDS:
        if " " in kw or "-" in kw:
            if kw in lower:
                return True
        else:
            if re.search(rf"\b{re.escape(kw)}\b", lower):
                return True
    return False


def is_energy(name: str, catalog_id: str) -> bool:
    lower = name.lower()
    return "énergie" in lower or "energy" in lower


def categorize_card(card: Mapping[str, Any]) -> str:
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
