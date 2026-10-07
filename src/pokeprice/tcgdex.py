"""
TCGdex API client with French language support, Cardmarket EUR pricing,
disk caching, and fuzzy card number snapping.
"""

import json
import os
import re
import urllib.parse
import urllib.request
import unicodedata
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

CACHE_DIR = os.path.expanduser("~/.cache/pokeprice")
CACHE_FILE = os.path.join(CACHE_DIR, "tcgdex_cache.json")


def strip_accents(s: str) -> str:
    """Removes accents and lowercases string for robust matching."""
    return (
        "".join(
            c
            for c in unicodedata.normalize("NFD", s)
            if unicodedata.category(c) != "Mn"
        )
        .lower()
        .strip()
    )


@dataclass
class CardPriceInfo:
    card_id: str
    name: str
    set_name: str
    card_number: str
    rarity: str
    is_holo_detected: bool
    cm_trend_eur: Optional[float]
    cm_avg_eur: Optional[float]
    cm_low_eur: Optional[float]
    cm_trend_holo_eur: Optional[float]
    cm_recommended_eur: Optional[float]
    tcg_market_usd: Optional[float]
    tcg_reverse_usd: Optional[float]
    image_url: Optional[str]
    cardmarket_id: Optional[int]
    hp: Optional[int] = None
    language: str = ""
    match_method: str = ""
    pricing_updated: str = ""
    price_field: str = ""


class TCGdexClient:
    def __init__(
        self,
        language: str = "fr",
        use_cache: bool = True,
        *,
        offline: bool = False,
        cache_file: Optional[str] = None,
    ):
        self.language = language
        self.base_url = f"https://api.tcgdex.net/v2/{language}"
        self.use_cache = use_cache
        self.offline = offline
        self.cache_file = cache_file or CACHE_FILE
        self.last_match_reason = ""
        self.cache: Dict[str, Any] = {}
        self.name_map: Dict[str, str] = {}
        if self.use_cache:
            self._load_cache()
        self._init_name_map()

    def _init_name_map(self):
        """Builds accent-insensitive mapping to official French card names."""
        cached_map = self.cache.get("__name_map__")
        if cached_map:
            self.name_map = cached_map
        else:
            cards_list = self._get_json(f"{self.base_url}/cards")
            if cards_list and isinstance(cards_list, list):
                for c in cards_list:
                    official = c.get("name", "")
                    if official:
                        norm = strip_accents(official)
                        if norm not in self.name_map:
                            self.name_map[norm] = official
                if self.use_cache:
                    self.cache["__name_map__"] = self.name_map
                    self._save_cache()

        jp_aliases = {
            "メガニウム": "Méganium",
            "リザードン": "Dracaufeu",
            "ピカチュウ": "Pikachu",
            "ミュウツー": "Mewtwo",
            "フシギバナ": "Florizarre",
            "カメックス": "Tortank",
        }
        for k, v in jp_aliases.items():
            self.name_map[k] = v

    def _load_cache(self):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
        except Exception:
            self.cache = {}

    def _save_cache(self):
        try:
            os.makedirs(
                os.path.dirname(os.path.abspath(self.cache_file)), exist_ok=True
            )
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False)
        except Exception:
            pass

    def _get_json(self, url: str) -> Optional[Any]:
        if self.use_cache and url in self.cache:
            return self.cache[url]

        if self.offline:
            return None

        req = urllib.request.Request(
            url, headers={"User-Agent": "pokeprice/0.1.0 (Pokemon Card Scanner)"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if self.use_cache:
                    self.cache[url] = data
                    self._save_cache()
                return data
        except Exception as e:
            return None

    @staticmethod
    def clean_name(name: str) -> str:
        """Strips levels, numbers, and extra symbols for database search."""
        # Strip evolution reminder clauses, e.g. "Mackogneur, Placez Mackogneur sur..."
        cleaned = re.sub(r",.*$", "", name)
        # Strip levels: 'NIV. 25', '(NIV. 24)', 'NIV.X', 'LV. 50'
        cleaned = re.sub(
            r"[\(\[\s]*(?:niv|lv)\.?\s*([xX]|\d+)[\)\]\s]*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        # Strip trailing punctuation, extra spaces, brackets
        cleaned = cleaned.strip(" -_#(),.[]")
        return cleaned

    @staticmethod
    def extract_level(name: str) -> Optional[str]:
        """Extracts level identifier like '31', '42', 'X' from card name."""
        match = re.search(r"(?:niv|lv)\.?\s*([xX]|\d+)", name, flags=re.IGNORECASE)
        return match.group(1).upper() if match else None

    @staticmethod
    def parse_card_number(card_num_str: str) -> tuple[Optional[str], Optional[int]]:
        """Parses numerator and denominator from '15/114' or '4/106'."""
        if not card_num_str:
            return None, None
        match = re.search(r"(\w+)\s*/\s*(\d+)", card_num_str)
        if match:
            return match.group(1).lstrip("0") or "0", int(match.group(2))
        # Plain number without slash
        plain = re.search(r"\b(\w+)\b", card_num_str)
        if plain:
            return plain.group(1).lstrip("0") or "0", None
        return None, None

    def search_card(
        self, name: str, raw_number: str = "", is_holo: bool = False, hp: int = 0
    ) -> Optional[CardPriceInfo]:
        """
        Searches for a card in the TCGdex database, applying fuzzy snapping,
        level matching, and HP verification.
        """
        import difflib

        self.last_match_reason = (
            "Identité non résolue : aucune correspondance vérifiée."
        )
        original = self.clean_name(name)
        if not original:
            return None
        norm = strip_accents(original)
        resolved = self.name_map.get(norm, original)

        def exact_candidates(base, query):
            found = self._get_json(f"{base}/cards?name={urllib.parse.quote(query)}")
            if not isinstance(found, list):
                return []
            return [
                c
                for c in found
                if isinstance(c, dict)
                and strip_accents(self.clean_name(c.get("name", "")))
                == strip_accents(self.clean_name(query))
            ]

        query_base = self.base_url
        candidates = exact_candidates(query_base, resolved)
        name_method = "exact"
        if not candidates and self.language != "en":
            query_base = "https://api.tcgdex.net/v2/en"
            candidates = exact_candidates(query_base, original)
        if not candidates:
            # Fuzzy correction is a proposal, never a replacement for exact English names.
            close = difflib.get_close_matches(
                norm, self.name_map.keys(), n=2, cutoff=0.85
            )
            if not close:
                return None
            if len(close) > 1:
                scores = [difflib.SequenceMatcher(None, norm, c).ratio() for c in close]
                if scores[0] - scores[1] < 0.05:
                    self.last_match_reason = (
                        "Nom ambigu : plusieurs corrections possibles."
                    )
                    return None
            query_base = self.base_url
            candidates = exact_candidates(query_base, self.name_map[close[0]])
            name_method = "name-corrected"
        if not candidates:
            return None

        num, denom = self.parse_card_number(raw_number)
        level = self.extract_level(name)
        details = []
        fetched = set()
        unavailable = set()

        def load_candidates(items):
            for candidate in items:
                cid = candidate.get("id")
                if cid in fetched:
                    continue
                fetched.add(cid)
                detail = self._get_json(f"{query_base}/cards/{cid}")
                if not isinstance(detail, dict):
                    unavailable.add(cid)
                    continue
                official_hp = detail.get("hp")
                if hp > 0 and official_hp is not None and str(official_hp) != str(hp):
                    continue
                official_level = self.extract_level(detail.get("name", ""))
                if level and official_level and official_level != level:
                    continue
                details.append(detail)

        # Exact lookup needs only cards sharing the numerator, not every printing.
        numbered = (
            [
                c
                for c in candidates
                if (str(c.get("localId", "")).lstrip("0") or "0").lower() == num.lower()
            ]
            if num
            else []
        )
        load_candidates(numbered if num else candidates)

        def numerator(d):
            return str(d.get("localId", "")).lstrip("0").lower() or "0"

        def denominator(d):
            return ((d.get("set") or {}).get("cardCount") or {}).get("official")

        selected = []
        method = name_method
        if num and denom:
            selected = [
                d
                for d in details
                if numerator(d) == num.lower() and denominator(d) == denom
            ]
            if selected and unavailable:
                self.last_match_reason = (
                    "Éditions candidates indisponibles : vérification nécessaire."
                )
                return None
            if not selected:
                load_candidates(candidates)
                # Snap only a unique denominator candidate corroborated by supplied HP.
                selected = [
                    d
                    for d in details
                    if denominator(d) == denom
                    and (hp <= 0 or str(d.get("hp")) == str(hp))
                ]
                method = "number-corrected"
        elif num:
            selected = [d for d in details if numerator(d) == num.lower()]
            method = "partial-number"
        elif hp > 0:
            selected = [d for d in details if str(d.get("hp")) == str(hp)]
            method = "hp-only"
        else:
            selected = details
            method = "name-only"
        # Multiple printings remain unresolved even if one has an image.
        unique = {d.get("id"): d for d in selected}
        if len(unique) != 1:
            self.last_match_reason = "Identité non résolue : références contradictoires ou plusieurs éditions possibles."
            return None
        detail = next(iter(unique.values()))
        info = self._build_price_info(detail, is_holo_detected=is_holo)
        info.language = query_base.rsplit("/", 1)[-1]
        info.match_method = method if name_method == "exact" else name_method
        self.last_match_reason = (
            ""
            if info.match_method == "exact"
            else "Correspondance proposée : vérifier la référence sur la photo."
        )
        return info

    def get_card_by_id(
        self, card_id: str, is_holo: bool = False, language: Optional[str] = None
    ) -> Optional[CardPriceInfo]:
        """Fetches card info directly by TCGdex ID (e.g. 'dp4-4')."""
        lookup_language = language or self.language
        if lookup_language not in ("fr", "en"):
            raise ValueError("Langue de catalogue non prise en charge")
        card_detail = self._get_json(
            f"https://api.tcgdex.net/v2/{lookup_language}/cards/{card_id}"
        )
        if not card_detail:
            return None
        info = self._build_price_info(card_detail, is_holo_detected=is_holo)
        info.language = lookup_language
        return info

    def _build_price_info(self, data: dict, is_holo_detected: bool) -> CardPriceInfo:
        pricing = data.get("pricing") or {}
        cm = pricing.get("cardmarket", {}) or {}
        tcg = pricing.get("tcgplayer", {}) or {}

        # Cardmarket values (EUR)
        trend = cm.get("trend")
        avg = cm.get("avg")
        low = cm.get("low")
        trend_holo = cm.get("trend-holo") or cm.get("avg-holo")

        # TCGplayer values (USD)
        tcg_norm = tcg.get("normal", {}) or {}
        tcg_rev = tcg.get("reverse-holofoil", {}) or {}
        tcg_holo = tcg.get("holofoil", {}) or {}

        tcg_market = tcg_norm.get("marketPrice") or tcg_holo.get("marketPrice")
        tcg_reverse = tcg_rev.get("marketPrice")

        # Pick recommended value:
        # If holo/reverse detected and a holo trend exists, use it; otherwise standard trend
        if is_holo_detected and trend_holo:
            recommended = trend_holo
            price_field = "trend-holo" if cm.get("trend-holo") else "avg-holo"
        elif trend is not None:
            recommended = trend
            price_field = "trend"
        elif avg is not None:
            recommended = avg
            price_field = "avg"
        else:
            recommended = low
            price_field = "low" if low is not None else ""

        set_info = data.get("set", {}) or {}
        set_count = set_info.get("cardCount", {}) or {}
        official_num = f"{data.get('localId')}/{set_count.get('official', '?')}"

        img_url = data.get("image")
        if not img_url:
            cid = data.get("id")
            if cid:
                en_card = self._get_json(f"https://api.tcgdex.net/v2/en/cards/{cid}")
                if en_card and isinstance(en_card, dict) and en_card.get("image"):
                    img_url = en_card.get("image")

        return CardPriceInfo(
            card_id=data.get("id", ""),
            name=data.get("name", ""),
            set_name=set_info.get("name", "Unknown Set"),
            card_number=official_num,
            rarity=data.get("rarity", "Inconnue"),
            is_holo_detected=is_holo_detected,
            cm_trend_eur=trend,
            cm_avg_eur=avg,
            cm_low_eur=low,
            cm_trend_holo_eur=trend_holo,
            cm_recommended_eur=recommended,
            tcg_market_usd=tcg_market,
            tcg_reverse_usd=tcg_reverse,
            image_url=img_url,
            cardmarket_id=(data.get("thirdParty") or {}).get("cardmarket"),
            hp=data.get("hp"),
            language=self.language,
            pricing_updated=cm.get("updated", ""),
            price_field=price_field,
        )
