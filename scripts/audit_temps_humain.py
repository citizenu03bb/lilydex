"""Mesurer le temps humain passé sur la collection à partir de l'historique.

Lecture seule : la base est ouverte en SQLite ``mode=ro`` et aucune ligne n'est
écrite. Le script reconstitue les séances actives de chaque auteur dans la
table ``events`` (et ``sale_events`` pour les lots), regroupe les événements
en décisions, mesure la durée de chaque décision et estime le temps restant
pour les files « À identifier », « À vérifier » et « À examiner ».

Une décision est une suite d'événements consécutifs d'un même auteur sur une
même carte (ou un même lot) : une correction qui écrit ``correction`` puis
``identification`` dans la même transaction compte pour une seule décision.
Sa durée est l'écart avec la fin de la décision précédente dans la même
séance ; la première décision d'une séance n'a pas de durée mesurable.

La sortie ne contient ni nom d'auteur, ni nom de carte, ni motif saisi : les
auteurs sont pseudonymisés (``humain-1``, ``agent-1``…) par ordre d'apparition.

Usage sur le serveur, toujours avec ``--data`` explicite :

    uv run python scripts/audit_temps_humain.py --data /srv/pokeprice/inventory
    uv run python scripts/audit_temps_humain.py --data … --json
"""

import argparse
import json
import math
import sqlite3
import statistics
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

CATEGORIES = ("identité", "variante", "état", "prix", "lot", "déplacement", "autre")

# Champs d'une fiche dont le changement révèle la nature d'une correction,
# par ordre de priorité quand une même correction en touche plusieurs.
FIELDS = (
    (
        "identité",
        (
            "name",
            "set_name",
            "number",
            "language",
            "catalog_id",
            "identification_status",
            "hp",
            "edition_id",
        ),
    ),
    (
        "variante",
        (
            "foil",
            "finish",
            "stamp_state",
            "distribution",
            "distribution_state",
            "variant_confirmed",
        ),
    ),
    ("état", ("condition", "condition_confirmed")),
    ("prix", ("reference_cents", "price_source", "price_date")),
    ("déplacement", ("album_id", "page", "position")),
    ("lot", ("stock_state",)),
)

KINDS = {
    "identification": "identité",
    "edition": "identité",
    "edition-validation": "identité",
    "language-validation": "identité",
    "reference-dispute": "identité",
    "variant": "variante",
    "variant-validation": "variante",
    "condition-validation": "état",
    "condition-assessment": "état",
    "price-snapshot": "prix",
    "sale-estimate": "prix",
    "market-product": "prix",
    "bound-price-selection": "prix",
    "bound-price-suspension": "prix",
    "bound-price-restoration": "prix",
    "listing": "lot",
    "unlisting": "lot",
    "stock": "lot",
    "sale": "lot",
}

# Événements dont le contenu doit être lu pour connaître la nature.
DIFFED = {"correction", "agent-correction"}
PRIORITY = {c: i for i, c in enumerate(CATEGORIES)}

# Chaque file : statut ou critère dans la base, et catégories de décisions
# dont la médiane sert à estimer le temps par carte.
QUEUES = (
    ("À identifier", ("identité",)),
    ("À vérifier", ("identité",)),
    ("À examiner", ("variante", "état")),
)


@contextmanager
def connect_readonly(directory):
    """Ouvrir la base en lecture seule ; une écriture lève OperationalError."""
    database = Path(directory).resolve() / "collection.sqlite3"
    if not database.is_file():
        raise FileNotFoundError(f"Base introuvable : {database}")
    db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    try:
        yield db
    finally:
        db.close()


def parse_time(value):
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def loads(text):
    try:
        value = json.loads(text or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def classify(kind, before, after):
    if kind in DIFFED:
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        if before and after:
            for category, fields in FIELDS:
                if changed & set(fields):
                    return category
        if kind == "agent-correction":
            return "prix" if "reference_cents" in after else "identité"
        return "autre"
    return KINDS.get(kind, "autre")


def table_exists(db, name):
    return bool(
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
    )


def staff(db):
    if not table_exists(db, "users"):
        return set()
    columns = {r[1] for r in db.execute("PRAGMA table_info(users)")}
    where = " WHERE role IN ('admin','editor')" if "role" in columns else ""
    return {r[0].casefold() for r in db.execute("SELECT username FROM users" + where)}


def origin(actor, humans):
    if actor.startswith("agent:"):
        return "agent"
    if actor.casefold() in humans:
        return "humain"
    return "automate"


def read_events(db):
    """Événements triés par auteur puis date, sans motif ni contenu de fiche."""
    rows = []
    for r in db.execute(
        "SELECT id,copy_id,actor,kind,before_json,after_json,created_at FROM events"
    ):
        before, after = loads(r["before_json"]), loads(r["after_json"])
        rows.append(
            {
                "actor": r["actor"],
                "target": ("copy", r["copy_id"]),
                "category": classify(r["kind"], before, after),
                "at": parse_time(r["created_at"]),
                "order": (0, r["id"]),
            }
        )
    if table_exists(db, "sale_events"):
        for r in db.execute("SELECT id,sale_id,actor,created_at FROM sale_events"):
            rows.append(
                {
                    "actor": r["actor"],
                    "target": ("sale", r["sale_id"]),
                    "category": "lot",
                    "at": parse_time(r["created_at"]),
                    "order": (1, r["id"]),
                }
            )
    rows.sort(key=lambda e: (e["actor"], e["at"], e["order"]))
    return rows


def sessions_of(events, gap_seconds):
    """Découper les événements de chaque auteur en séances, puis en décisions."""
    sessions = []
    current = None
    for event in events:
        if (
            current is None
            or current["actor"] != event["actor"]
            or (event["at"] - current["end"]).total_seconds() >= gap_seconds
        ):
            current = {
                "actor": event["actor"],
                "start": event["at"],
                "end": event["at"],
                "decisions": [],
            }
            sessions.append(current)
        decisions = current["decisions"]
        if decisions and decisions[-1]["target"] == event["target"]:
            decision = decisions[-1]
            decision["end"] = event["at"]
            if PRIORITY[event["category"]] < PRIORITY[decision["category"]]:
                decision["category"] = event["category"]
        else:
            decisions.append(
                {
                    "target": event["target"],
                    "category": event["category"],
                    "start": event["at"],
                    "end": event["at"],
                    "previous_end": decisions[-1]["end"] if decisions else None,
                }
            )
        current["end"] = event["at"]
    for session in sessions:
        for decision in session["decisions"]:
            previous = decision.pop("previous_end")
            decision["seconds"] = (
                (decision["end"] - previous).total_seconds()
                if previous is not None
                else None
            )
    return sessions


def summary(durations, count):
    return {
        "decisions": count,
        "measured": len(durations),
        "median_seconds": round(statistics.median(durations), 1) if durations else None,
        "total_seconds": round(sum(durations), 1),
    }


def queue_counts(db):
    """Compter les files sans charger les fiches (pas de nom de carte en mémoire)."""
    columns = {r[1] for r in db.execute("PRAGMA table_info(copies)")}
    alive = " AND deleted_at=''" if "deleted_at" in columns else ""
    counts = {}
    for label, statuses in (
        ("À identifier", ("unresolved", "failed")),
        ("À vérifier", ("review",)),
    ):
        counts[label] = db.execute(
            "SELECT COUNT(*) FROM copies WHERE identification_status IN ("
            + ",".join("?" * len(statuses))
            + ")"
            + alive,
            statuses,
        ).fetchone()[0]
    return counts


def review_count(directory, threshold_cents):
    """Taille de la file « À examiner » telle que l'application la calcule."""
    try:
        from pokeprice.inventory import Store
        from pokeprice.library import normalized
        from pokeprice.reference_service import ReferenceService
    except ImportError:
        return None

    class ReadOnlyStore(Store):
        # Store.__init__ crée des dossiers et migre la base : on le contourne.
        def __init__(self, directory):
            self.root = Path(directory).resolve()
            self.photos = self.root / "photos"
            self.database = self.root / "collection.sqlite3"
            self.reference = ReferenceService(self)

        @contextmanager
        def connect(self, **kwargs):
            with connect_readonly(self.database.parent) as db:
                db.create_function("normalized", 1, normalized)
                yield db

    try:
        data = ReadOnlyStore(directory).listing(
            limit=1000000, sort="binder", threshold_cents=threshold_cents
        )
    except sqlite3.Error:
        return None
    return sum(1 for c in data["items"] if c["valuation"]["needs_review"])


def build_report(directory, *, gap_minutes=5.0, threshold_cents=1000, examine=None):
    gap_seconds = gap_minutes * 60
    with connect_readonly(directory) as db:
        humans = staff(db)
        events = read_events(db)
        counts = queue_counts(db)
    if examine is None:
        examine = review_count(directory, threshold_cents)
    counts["À examiner"] = examine

    sessions = sessions_of(events, gap_seconds)
    pseudonyms = {}
    numbering = {}
    for session in sorted(sessions, key=lambda s: s["start"]):
        actor = session["actor"]
        if actor not in pseudonyms:
            kind = origin(actor, humans)
            numbering[kind] = numbering.get(kind, 0) + 1
            pseudonyms[actor] = (kind, f"{kind}-{numbering[kind]}")

    by_origin = {}
    session_rows = []
    for session in sorted(sessions, key=lambda s: s["start"]):
        kind, alias = pseudonyms[session["actor"]]
        stats = by_origin.setdefault(
            kind, {c: {"count": 0, "durations": []} for c in CATEGORIES}
        )
        per_category = {}
        for decision in session["decisions"]:
            entry = stats[decision["category"]]
            entry["count"] += 1
            row = per_category.setdefault(
                decision["category"], {"decisions": 0, "seconds": 0.0}
            )
            row["decisions"] += 1
            if decision["seconds"] is not None:
                entry["durations"].append(decision["seconds"])
                row["seconds"] += decision["seconds"]
        session_rows.append(
            {
                "author": alias,
                "origin": kind,
                "start": session["start"].isoformat(),
                "active_seconds": round(
                    (session["end"] - session["start"]).total_seconds(), 1
                ),
                "decisions": len(session["decisions"]),
                "by_category": {
                    c: {"decisions": v["decisions"], "seconds": round(v["seconds"], 1)}
                    for c, v in sorted(per_category.items(), key=lambda i: PRIORITY[i[0]])
                },
            }
        )

    decisions = {
        kind: {c: summary(v["durations"], v["count"]) for c, v in stats.items()}
        for kind, stats in sorted(by_origin.items())
    }
    human = by_origin.get("humain", {c: {"count": 0, "durations": []} for c in CATEGORIES})
    estimates = {}
    for label, basis in QUEUES:
        pooled = [d for c in basis for d in human[c]["durations"]]
        median = statistics.median(pooled) if pooled else None
        count = counts.get(label)
        estimates[label] = {
            "cards": count,
            "basis": list(basis),
            "median_seconds": round(median, 1) if median is not None else None,
            "remaining_seconds": round(median * count, 1)
            if median is not None and count is not None
            else None,
        }
    authors = {}
    for kind, _ in pseudonyms.values():
        authors[kind] = authors.get(kind, 0) + 1
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "gap_minutes": gap_minutes,
        "threshold_cents": threshold_cents,
        "events": len(events),
        "authors": dict(sorted(authors.items())),
        "sessions": len(sessions),
        "active_seconds": {
            kind: round(sum(s["active_seconds"] for s in session_rows if s["origin"] == kind), 1)
            for kind in sorted(authors)
        },
        "decisions": decisions,
        "queues": estimates,
        "session_details": session_rows,
    }


def duration(seconds):
    if seconds is None:
        return "—"
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min {secs:02d} s"
    return f"{secs} s"


def table(headers, rows):
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    def line(r):
        return "  ".join(str(x).ljust(w) for x, w in zip(r, widths)).rstrip()

    return "\n".join([line(headers), line(["-" * w for w in widths])] + [line(r) for r in rows])


def text_report(report):
    parts = [
        "Temps humain mesuré dans l'historique",
        f"Séances : écart < {report['gap_minutes']:g} min entre événements d'un même auteur",
        f"Événements : {report['events']} ; séances : {report['sessions']} ; auteurs : "
        + (", ".join(f"{n} {k}" for k, n in report["authors"].items()) or "aucun"),
        "",
    ]
    for kind, stats in report["decisions"].items():
        parts.append(
            f"Décisions — {kind} (temps actif {duration(report['active_seconds'][kind])})"
        )
        parts.append(
            table(
                ["Type", "Décisions", "Mesurées", "Médiane", "Total"],
                [
                    [
                        c,
                        s["decisions"],
                        s["measured"],
                        duration(s["median_seconds"]),
                        duration(s["total_seconds"]),
                    ]
                    for c, s in stats.items()
                    if s["decisions"]
                ],
            )
        )
        parts.append("")
    parts.append("Temps restant estimé (médianes humaines)")
    parts.append(
        table(
            ["File", "Cartes", "Base", "Médiane", "Restant"],
            [
                [
                    label,
                    "?" if q["cards"] is None else q["cards"],
                    "+".join(q["basis"]),
                    duration(q["median_seconds"]),
                    duration(q["remaining_seconds"]),
                ]
                for label, q in report["queues"].items()
            ],
        )
    )
    parts.append("")
    parts.append("Séances")
    parts.append(
        table(
            ["Auteur", "Début", "Actif", "Décisions", "Par type"],
            [
                [
                    s["author"],
                    s["start"][:16].replace("T", " "),
                    duration(s["active_seconds"]),
                    s["decisions"],
                    ", ".join(
                        f"{c} {v['decisions']} ({duration(v['seconds'])})"
                        for c, v in s["by_category"].items()
                    ),
                ]
                for s in report["session_details"]
            ],
        )
    )
    return "\n".join(parts) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Mesurer le temps humain depuis l'historique, en lecture seule."
    )
    parser.add_argument(
        "--data", required=True, type=Path, help="Dossier de la base d'inventaire"
    )
    parser.add_argument(
        "--gap-minutes",
        type=float,
        default=5,
        help="Écart maximal entre deux événements d'une même séance (5 min)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=10,
        help="Seuil en euros de la file « À examiner » (10 €)",
    )
    parser.add_argument("--json", action="store_true", help="Sortie JSON")
    args = parser.parse_args(argv)
    if not math.isfinite(args.gap_minutes) or not 0 < args.gap_minutes <= 1440:
        parser.error("L'écart doit être compris entre 0 et 1 440 minutes.")
    if not math.isfinite(args.threshold) or not 0.01 <= args.threshold <= 10000:
        parser.error("Le seuil doit être compris entre 0,01 et 10 000 €.")
    try:
        report = build_report(
            args.data,
            gap_minutes=args.gap_minutes,
            threshold_cents=round(args.threshold * 100),
        )
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(text_report(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
