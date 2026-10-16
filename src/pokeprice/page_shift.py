"""Renumber pages of binders whose cover photo was counted as page 1."""

import json

from .inventory import Conflict

ACTOR = "system:page-shift"
# The scan numbered photos, cover included: the first card page became page 2.
# Platinium 3×3 was scanned without the cover and is already physical.
SHIFTED_ALBUMS = ("diamond-pearl", "platinium")


def candidates(store, *, _db=None):
    if _db is None:
        with store.connect() as db:
            return candidates(store, _db=db)
    result = []
    for row in _db.execute(
        "SELECT c.id,c.name,c.album_id,c.page,c.position,c.version,s.raw_json "
        "FROM copies c JOIN sources s ON s.copy_id=c.id "
        "WHERE c.deleted_at='' ORDER BY c.album_id,c.page,c.position"
    ):
        raw = json.loads(row["raw_json"])
        if raw.get("Album_ID") not in SHIFTED_ALBUMS:
            continue
        # Only copies still where the import put them: a page or album set by
        # hand since then is a physical decision, never shifted again.
        if (row["album_id"], row["page"]) != (raw["Album_ID"], int(raw["Page"])):
            continue
        if row["page"] < 2 or moved(_db, row["id"]):
            continue
        result.append(
            {
                "copy_id": row["id"],
                "name": row["name"],
                "album_id": row["album_id"],
                "position": row["position"],
                "expected_version": row["version"],
                "page": row["page"],
                "new_page": row["page"] - 1,
            }
        )
    return result


def moved(db, copy_id):
    for event in db.execute(
        "SELECT before_json,after_json FROM events WHERE copy_id=? AND kind='correction'",
        (copy_id,),
    ):
        before, after = json.loads(event[0]), json.loads(event[1])
        if any(before.get(k) != after.get(k) for k in ("album_id", "page")):
            return True
    return False


def apply(store, plan):
    """Version-checked, atomic renumbering with a fixed maintenance actor."""
    if len({p["copy_id"] for p in plan}) != len(plan):
        raise ValueError("Exemplaire répété dans le plan de renumérotation.")
    with store.connect(write=True) as db:
        current = {p["copy_id"]: p for p in candidates(store, _db=db)}
        if any(current.get(p["copy_id"]) != p for p in plan):
            raise Conflict("Le plan de renumérotation a changé. Relancez l’audit.")
        for p in plan:
            store.patch(
                p["copy_id"],
                {"page": p["new_page"]},
                p["expected_version"],
                ACTOR,
                "Page physique : la photo de couverture avait été comptée comme page 1.",
                _db=db,
            )
        return {"renumbered": len(plan), "items": plan}
