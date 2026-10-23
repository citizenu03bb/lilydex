"""Anonymous storefront audience: daily totals, without cookie or kept address.

A visitor is told apart for one day only, by a hash of their address and
browser salted with a random value. The salt and the day's hashes are deleted
when the day ends: afterwards no count leads back to anyone. Totals are kept
25 months, the period the CNIL allows an audience measure exempt from consent.
The period is the one announced on /a-propos.
"""

import hashlib
import re
import secrets
import sqlite3
import threading
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

RETENTION = timedelta(days=761)  # 25 months
BOTS = re.compile(
    r"bot|crawl|spider|slurp|preview|monitor|uptime|headless|lighthouse|"
    r"curl|wget|python|httpx|go-http|java/|okhttp|node-fetch|axios",
    re.I,
)
MOBILE = re.compile(r"mobi|android|iphone|ipad", re.I)
SCHEMA = """
CREATE TABLE IF NOT EXISTS totals(day TEXT NOT NULL, kind TEXT NOT NULL,
    key TEXT NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(day, kind, key));
CREATE TABLE IF NOT EXISTS salts(day TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS seen(day TEXT NOT NULL, visitor TEXT NOT NULL,
    PRIMARY KEY(day, visitor));
"""


def counted(agent, headers):
    """Robots, prefetches and visitors who ask not to be followed are left out."""
    if not agent or BOTS.search(agent):
        return False
    if "prefetch" in (headers.get("sec-purpose", "") + headers.get("purpose", "")):
        return False
    return headers.get("sec-gpc") != "1" and headers.get("dnt") != "1"


def referrer_domain(referrer, own_hosts):
    host = (urlsplit(referrer).hostname or "") if referrer else ""
    host = host.removeprefix("www.")
    return "" if not host or host in own_hosts else host[:120]


class Audience:
    def __init__(self, directory, own_hosts=()):
        # Beside the collection base, never in it: counting a visit does not
        # change the collection's version nor weigh on its backups.
        self.path = Path(directory) / "audience.sqlite3"
        self.own = {h.removeprefix("www.") for h in own_hosts}
        self.lock = threading.Lock()
        self.day = None
        with self.connect() as db:
            db.executescript(SCHEMA)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return closing(db)

    def forget(self, db, today):
        """End past days: their salts and hashes go, old totals expire."""
        db.execute("DELETE FROM salts WHERE day<?", (today,))
        db.execute("DELETE FROM seen WHERE day<?", (today,))
        cutoff = (date.fromisoformat(today) - RETENTION).isoformat()
        db.execute("DELETE FROM totals WHERE day<?", (cutoff,))

    def record(self, kind, key, address, agent, referrer="", today=None):
        today = today or date.today().isoformat()
        with self.lock, self.connect() as db, db:
            if self.day != today:
                self.forget(db, today)
                self.day = today
            salt = db.execute("SELECT value FROM salts WHERE day=?", (today,)).fetchone()
            if salt is None:
                salt = secrets.token_hex(16)
                db.execute("INSERT INTO salts VALUES(?,?)", (today, salt))
            else:
                salt = salt["value"]
            visitor = hashlib.sha256(f"{salt}|{address}|{agent}".encode()).hexdigest()[:20]
            if db.execute("INSERT OR IGNORE INTO seen VALUES(?,?)", (today, visitor)).rowcount:
                self.bump(db, today, "visitors", "")
                self.bump(db, today, "device", "mobile" if MOBILE.search(agent) else "desktop")
            self.bump(db, today, kind, key)
            domain = referrer_domain(referrer, self.own) if kind == "page" else ""
            if domain:
                self.bump(db, today, "referrer", domain)

    def bump(self, db, day, kind, key):
        db.execute(
            "INSERT INTO totals VALUES(?,?,?,1) "
            "ON CONFLICT(day,kind,key) DO UPDATE SET count=count+1",
            (day, kind, key),
        )

    def report(self, days=30, today=None):
        last = date.fromisoformat(today) if today else date.today()
        first = last - timedelta(days=days - 1)
        with self.lock, self.connect() as db, db:
            self.forget(db, last.isoformat())
            rows = db.execute(
                "SELECT day,kind,key,count FROM totals WHERE day BETWEEN ? AND ?",
                (first.isoformat(), last.isoformat()),
            ).fetchall()
        daily = {
            (first + timedelta(days=n)).isoformat(): {"visitors": 0, "pages": 0}
            for n in range(days)
        }
        sums = {"page": {}, "listing": {}, "referrer": {}, "device": {}}
        for row in rows:
            if row["kind"] == "visitors":
                daily[row["day"]]["visitors"] += row["count"]
                continue
            if row["kind"] == "page":
                daily[row["day"]]["pages"] += row["count"]
            group = sums.setdefault(row["kind"], {})
            group[row["key"]] = group.get(row["key"], 0) + row["count"]

        def top(kind, label, limit=10):
            ranked = sorted(sums[kind].items(), key=lambda kv: (-kv[1], kv[0]))
            return [{label: key, "count": count} for key, count in ranked[:limit]]

        return {
            "from": first.isoformat(),
            "to": last.isoformat(),
            "days": [{"day": day, **values} for day, values in daily.items()],
            "visitors": sum(d["visitors"] for d in daily.values()),
            "page_views": sum(sums["page"].values()),
            "listing_views": sum(sums["listing"].values()),
            "pages": sums["page"],
            "listings": top("listing", "id"),
            "referrers": top("referrer", "domain"),
            "devices": {k: sums["device"].get(k, 0) for k in ("mobile", "desktop")},
        }
