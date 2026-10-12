"""Card names in several languages, fetched once per edition and kept.

TCGdex is a free community service: names never change, so they are cached
forever, requests go one at a time with a pause, a whole set comes in a single
request, failures back off and a run stops after repeated server errors.
"""

import json
import time
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .inventory import now

API = "https://api.tcgdex.net/v2"
# Western languages share TCGdex card identifiers; Asian sets are catalogued apart.
LANGUAGES = ("fr", "en", "de", "it", "es", "pt")
NOT_FOUND_RETRY_DAYS = 90


class Transient(Exception):
    """Server busy or unreachable: retried later, never cached as a miss."""

    def __init__(self, retry_after=None):
        super().__init__(retry_after)
        self.retry_after = retry_after


def http_json(url):
    """(found, data): a 404 is a definite miss; 429, 5xx and network errors are transient."""
    request = Request(url, headers={"User-Agent": "pokeprice/0.1 (collection privée)"})
    try:
        with urlopen(request, timeout=20) as response:
            return True, json.loads(response.read())
    except HTTPError as error:
        if error.code == 404:
            return False, None
        if error.code == 429 or error.code >= 500:
            retry = error.headers.get("Retry-After") if error.headers else None
            seconds = None
            if retry:
                try:
                    seconds = float(retry)
                except ValueError:
                    try:
                        seconds = max(
                            0.0, parsedate_to_datetime(retry).timestamp() - time.time()
                        )
                    except (TypeError, ValueError):
                        seconds = None
            raise Transient(seconds) from None
        return False, None
    except (URLError, TimeoutError, OSError):
        raise Transient() from None


class NameCatalog:
    def __init__(
        self,
        store,
        get=http_json,
        *,
        pause=0.25,
        retries=3,
        max_failures=5,
        sleep=time.sleep,
    ):
        self.store, self.get = store, get
        self.pause, self.retries, self.max_failures, self.sleep = (
            pause,
            retries,
            max_failures,
            sleep,
        )

    # --- cache --------------------------------------------------------------

    @staticmethod
    def record(db, catalog_id, language, name, source):
        if isinstance(name, str) and name.strip():
            db.execute(
                "INSERT OR IGNORE INTO catalog_names VALUES(?,?,?,?,?)",
                (catalog_id, language, name.strip(), source, now()),
            )

    @staticmethod
    def search_text(db):
        """catalog_id -> every known name, for the collection search."""
        return {
            r[0]: r[1]
            for r in db.execute(
                "SELECT catalog_id, group_concat(name, ' ') FROM catalog_names GROUP BY catalog_id"
            )
        }

    def _cached(self, key):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT found, value, checked_at FROM catalog_lookups WHERE key=?",
                (key,),
            ).fetchone()
        if not row:
            return None
        found, value, checked = row
        if not found:
            age = time.time() - time.mktime(
                time.strptime(checked[:19], "%Y-%m-%dT%H:%M:%S")
            )
            if age > NOT_FOUND_RETRY_DAYS * 86400:
                return None
        return found, json.loads(value) if value else None

    def _remember(self, key, found, value=None):
        with self.store.connect(write=True) as db:
            db.execute(
                "INSERT OR REPLACE INTO catalog_lookups VALUES(?,?,?,?)",
                (
                    key,
                    int(found),
                    json.dumps(value, ensure_ascii=False)
                    if value is not None
                    else None,
                    now(),
                ),
            )

    # --- polite fetching ----------------------------------------------------

    def _fetch(self, key, url, keep, stats):
        """One cached request; `keep` reduces the answer to what must be stored."""
        cached = self._cached(key)
        if cached is not None:
            return cached
        if stats["stopped"]:
            return None
        for attempt in range(self.retries + 1):
            self.sleep(self.pause)
            stats["requests"] += 1
            try:
                found, data = self.get(url)
            except Transient as busy:
                stats["transient"] += 1
                self.sleep(
                    busy.retry_after if busy.retry_after is not None else 2**attempt
                )
                continue
            stats["consecutive_failures"] = 0
            value = keep(data) if found else None
            self._remember(key, found, value)
            return found, value
        stats["consecutive_failures"] += 1
        stats["failed"].append(key)
        if stats["consecutive_failures"] >= self.max_failures:
            stats["stopped"] = True  # Circuit breaker: the server is struggling.
        return None

    def refresh(self, languages=LANGUAGES):
        """Fill missing names of every catalogued edition of the collection."""
        stats = {
            "requests": 0,
            "transient": 0,
            "consecutive_failures": 0,
            "failed": [],
            "stopped": False,
            "stored": 0,
            "species": 0,
        }
        with self.store.connect() as db:
            wanted = {
                r[0]
                for r in db.execute(
                    "SELECT DISTINCT catalog_id FROM copies WHERE deleted_at='' AND catalog_id IS NOT NULL"
                )
            }
            have = {
                (r[0], r[1])
                for r in db.execute("SELECT catalog_id, language FROM catalog_names")
            }
            before = len(have)
        missing = {
            (c, lang) for c in wanted for lang in languages if (c, lang) not in have
        }
        # 1. One request per set and language gives every card name of that set.
        for set_id, lang in sorted(
            {(c.rsplit("-", 1)[0], lang) for c, lang in missing}
        ):
            result = self._fetch(
                f"set:{lang}:{set_id}",
                f"{API}/{lang}/sets/{set_id}",
                lambda data: {
                    c["id"]: c.get("name", "")
                    for c in (data or {}).get("cards", [])
                    if isinstance(c, dict) and c.get("id")
                },
                stats,
            )
            if result and result[0]:
                with self.store.connect(write=True) as db:
                    for card_id, name in result[1].items():
                        self.record(db, card_id, lang, name, "edition")
        # 2. Editions absent from a language (Base Set 2 in French): the species
        #    name, found once per Pokédex number and language.
        with self.store.connect() as db:
            have = {
                (r[0], r[1])
                for r in db.execute("SELECT catalog_id, language FROM catalog_names")
            }
        for catalog_id, lang in sorted(m for m in missing if m not in have):
            dex = None
            for source in ("en", "fr"):  # Some promos exist in French only.
                dex = self._fetch(
                    f"dex-of:{source}:{catalog_id}",
                    f"{API}/{source}/cards/{catalog_id}",
                    lambda data: (data or {}).get("dexId") or [],
                    stats,
                )
                if dex and dex[0] and dex[1]:
                    break
            if not dex or not dex[0] or not dex[1]:
                continue  # Trainers and energies have no Pokédex number.
            species = self._fetch(
                f"dex:{lang}:{dex[1][0]}",
                f"{API}/{lang}/cards?dexId=eq:{dex[1][0]}&pagination:itemsPerPage=10",
                lambda data: min(
                    (
                        c.get("name", "")
                        for c in data or []
                        if isinstance(c, dict) and c.get("name")
                    ),
                    key=len,
                    default="",
                ),
                stats,
            )
            if species and species[0] and species[1]:
                with self.store.connect(write=True) as db:
                    self.record(db, catalog_id, lang, species[1], "species")
                stats["species"] += 1
        with self.store.connect() as db:
            stats["stored"] = (
                db.execute("SELECT count(*) FROM catalog_names").fetchone()[0] - before
            )
        del stats["consecutive_failures"]
        return stats
