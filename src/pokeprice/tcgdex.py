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
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List

CACHE_DIR = os.path.expanduser("~/.cache/pokeprice")
CACHE_FILE = os.path.join(CACHE_DIR, "tcgdex_cache.json")


def strip_accents(s: str) -> str:
    """Removes accents and lowercases string for robust matching."""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower().strip()


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


class TCGdexClient:
    def __init__(self, language: str = "fr", use_cache: bool = True):
        self.language = language
        self.base_url = f"https://api.tcgdex.net/v2/{language}"
        self.use_cache = use_cache
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
            return
        
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

    def _load_cache(self):
        try:
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
        except Exception:
            self.cache = {}

    def _save_cache(self):
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False)
        except Exception:
            pass

    def _get_json(self, url: str) -> Optional[Any]:
        if self.use_cache and url in self.cache:
            return self.cache[url]

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "pokeprice/0.1.0 (Pokemon Card Scanner)"}
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
        cleaned = re.sub(r"[\(\[\s]*(?:niv|lv)\.?\s*([xX]|\d+)[\)\]\s]*", "", cleaned, flags=re.IGNORECASE)
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
        self,
        name: str,
        raw_number: str = "",
        is_holo: bool = False,
        hp: int = 0
    ) -> Optional[CardPriceInfo]:
        """
        Searches for a card in the TCGdex database, applying fuzzy snapping,
        level matching, and HP verification.
        """
        import difflib

        clean = self.clean_name(name)
        if not clean:
            return None

        # Resolve unaccented or alternate spellings via name_map & difflib
        norm = strip_accents(clean)
        if norm in self.name_map:
            clean = self.name_map[norm]
        else:
            close = difflib.get_close_matches(norm, self.name_map.keys(), n=1, cutoff=0.7)
            if close:
                clean = self.name_map[close[0]]

        # Query candidates by name in French
        search_url = f"{self.base_url}/cards?name={urllib.parse.quote(clean)}"
        candidates = self._get_json(search_url)

        # Fallback to English endpoint if French yields no results
        query_base = self.base_url
        if not candidates or not isinstance(candidates, list):
            en_url = f"https://api.tcgdex.net/v2/en/cards?name={urllib.parse.quote(clean)}"
            en_candidates = self._get_json(en_url)
            if en_candidates and isinstance(en_candidates, list):
                candidates = en_candidates
                query_base = "https://api.tcgdex.net/v2/en"
            else:
                return None

        # Filter candidates whose clean base name matches
        name_matches = [
            c for c in candidates 
            if self.clean_name(c.get("name", "")).lower() == clean.lower()
        ]
        prioritized_candidates = name_matches if name_matches else candidates

        query_level = self.extract_level(name)
        num, denom = self.parse_card_number(raw_number)
        selected_card_id = None

        # 1. Try exact localId match
        if num:
            matched_num_cands = []
            for c in prioritized_candidates:
                cand_local = str(c.get("localId", "")).lstrip("0") or "0"
                if cand_local.lower() == num.lower():
                    matched_num_cands.append(c)

            if len(matched_num_cands) == 1:
                selected_card_id = matched_num_cands[0]["id"]
            elif len(matched_num_cands) > 1:
                # Disambiguate among cards with the same number using denom, HP, or level
                for c in matched_num_cands:
                    cid = c["id"]
                    detail = self._get_json(f"{query_base}/cards/{cid}")
                    if not detail:
                        continue
                    if denom and detail.get("set", {}).get("cardCount", {}).get("official") == denom:
                        selected_card_id = cid
                        break
                    if hp > 0 and detail.get("hp") == hp:
                        selected_card_id = cid
                        break
                    if query_level and self.extract_level(detail.get("name", "")) == query_level:
                        selected_card_id = cid
                        break
                if not selected_card_id:
                    selected_card_id = matched_num_cands[0]["id"]

        # 2. Denominator match (snap OCR errors like 12/114 -> 15/114)
        if not selected_card_id and denom:
            denom_cands = []
            for c in prioritized_candidates:
                cid = c["id"]
                detail = self._get_json(f"{query_base}/cards/{cid}")
                if detail and detail.get("set", {}).get("cardCount", {}).get("official") == denom:
                    denom_cands.append((c, detail))
            if denom_cands:
                # If HP or level matches, pick that one
                for c, det in denom_cands:
                    if hp > 0 and det.get("hp") == hp:
                        selected_card_id = c["id"]
                        break
                    if query_level and self.extract_level(det.get("name", "")) == query_level:
                        selected_card_id = c["id"]
                        break
                if not selected_card_id:
                    selected_card_id = denom_cands[0][0]["id"]

        # 3. Level match (for Diamond & Pearl / Platinum era cards like "Jirachi NIV.39")
        if not selected_card_id and query_level:
            for c in prioritized_candidates:
                cand_level = self.extract_level(c.get("name", ""))
                if cand_level == query_level:
                    selected_card_id = c["id"]
                    break

        # 4. HP match (disambiguate when card number is missing)
        if not selected_card_id and hp > 0:
            hp_cands = []
            for c in prioritized_candidates:
                cid = c["id"]
                detail = self._get_json(f"{query_base}/cards/{cid}")
                if detail and detail.get("hp") == hp:
                    hp_cands.append(c)
            if hp_cands:
                # If query has level, prefer DP/Pt era (set ID starting with 'dp' or 'pl')
                if query_level:
                    for c in hp_cands:
                        if c["id"].startswith("dp") or c["id"].startswith("pl"):
                            selected_card_id = c["id"]
                            break
                if not selected_card_id:
                    selected_card_id = hp_cands[0]["id"]

        # 5. Fallback: First candidate with an image or candidate 0
        if not selected_card_id:
            for c in prioritized_candidates:
                if c.get("image"):
                    selected_card_id = c["id"]
                    break
            if not selected_card_id:
                selected_card_id = prioritized_candidates[0]["id"]

        # Fetch detailed card information
        card_detail = self._get_json(f"{query_base}/cards/{selected_card_id}")
        if not card_detail:
            return None

        return self._build_price_info(card_detail, is_holo_detected=is_holo)

    def get_card_by_id(self, card_id: str, is_holo: bool = False) -> Optional[CardPriceInfo]:
        """Fetches card info directly by TCGdex ID (e.g. 'dp4-4')."""
        card_detail = self._get_json(f"{self.base_url}/cards/{card_id}")
        if not card_detail:
            return None
        return self._build_price_info(card_detail, is_holo_detected=is_holo)

    def _build_price_info(self, data: dict, is_holo_detected: bool) -> CardPriceInfo:
        pricing = data.get("pricing", {})
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
        elif trend is not None:
            recommended = trend
        elif avg is not None:
            recommended = avg
        else:
            recommended = low

        set_info = data.get("set", {}) or {}
        set_count = set_info.get("cardCount", {}) or {}
        official_num = f"{data.get('localId')}/{set_count.get('official', '?')}"

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
            image_url=data.get("image"),
            cardmarket_id=data.get("thirdParty", {}).get("cardmarket")
        )
