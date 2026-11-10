"""Âge de rotation des lots en ligne : réglage d'administration, journalisé.

Un lot en ligne composé par l'outil des lots et toujours invendu après ce
nombre de jours sort de la vitrine à la rotation suivante. Le réglage vit dans
la table ``settings``, comme la marge du plancher anti-bradage : sans ligne, la
valeur par défaut s'applique, donc aucune migration. Seul un compte
administrateur actif le change ; un accès agent ne le peut pas.
"""

import json
import sqlite3
from typing import Any

from ..inventory import now

DEFAULT_ROTATION_DAYS = 14
MIN_ROTATION_DAYS = 3
MAX_ROTATION_DAYS = 90
ROTATION_DAYS_KEY = "lot_rotation_days"
ROTATION_DAYS_EVENT = "lot-rotation-age"


def check_rotation_days(days: Any) -> int:
    """Un nombre entier de jours entre les bornes ; tout le reste est refusé."""
    if isinstance(days, bool) or not isinstance(days, int) or not MIN_ROTATION_DAYS <= days <= MAX_ROTATION_DAYS:
        raise ValueError(
            f"L’âge de rotation est un nombre entier de jours entre {MIN_ROTATION_DAYS} et {MAX_ROTATION_DAYS}."
        )
    return days


def lot_rotation_days(source: Any) -> int:
    """L'âge de rotation réglé, d'un magasin ou d'une connexion ouverte."""
    if hasattr(source, "connect"):
        with source.connect() as db:
            return lot_rotation_days(db)
    row = source.execute("SELECT value_json FROM settings WHERE key=?", (ROTATION_DAYS_KEY,)).fetchone()
    if row is None:
        return DEFAULT_ROTATION_DAYS
    return check_rotation_days(json.loads(row[0]))


def set_lot_rotation_days(store: Any, days: int, actor: str) -> dict[str, int]:
    """Enregistre l'âge de rotation et journalise qui l'a changé, quand, de quoi à quoi."""
    check_rotation_days(days)
    with store.connect(write=True) as db:
        if not db.execute(
            "SELECT 1 FROM users WHERE username=? AND role='admin' AND disabled=0 AND status='active'",
            (actor,),
        ).fetchone():
            from ..floor_requests import HumanOnly

            raise HumanOnly("Seul un compte administrateur règle l’âge de rotation des lots en ligne.")
        before = lot_rotation_days(db)
        write_rotation_days(db, days, actor, before)
    return {"days": days, "previous": before}


def write_rotation_days(db: sqlite3.Connection, days: int, actor: str, before: int) -> None:
    stamp = now()
    db.execute(
        "INSERT INTO settings(key,value_json,updated_by,updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,"
        "updated_by=excluded.updated_by,updated_at=excluded.updated_at",
        (ROTATION_DAYS_KEY, json.dumps(days), actor, stamp),
    )
    db.execute(
        "INSERT INTO events(copy_id,actor,kind,reason,before_json,after_json,created_at) VALUES(NULL,?,?,?,?,?,?)",
        (
            actor,
            ROTATION_DAYS_EVENT,
            "Réglage de l’âge de rotation des lots en ligne.",
            json.dumps({"days": before}),
            json.dumps({"days": days}),
            stamp,
        ),
    )


def lot_rotation_history(store: Any, limit: int = 20) -> list[dict[str, Any]]:
    with store.connect() as db:
        rows = db.execute(
            "SELECT actor,reason,before_json,after_json,created_at FROM events WHERE kind=? ORDER BY id DESC LIMIT ?",
            (ROTATION_DAYS_EVENT, limit),
        ).fetchall()
    return [
        {
            "actor": r["actor"],
            "reason": r["reason"],
            "previous": json.loads(r["before_json"]).get("days"),
            "days": json.loads(r["after_json"])["days"],
            "at": r["created_at"],
        }
        for r in rows
    ]
