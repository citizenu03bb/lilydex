"""Bulk card moves across albums or pages with preview, atomic apply, and full undo."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .inventory import Conflict, now
from .inventory_backup import backup

# Schema 23: persistent move previews and applied batches for atomic undo.
SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS move_batches(id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES users(id), data_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('preview','applied','undone')),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
PRAGMA user_version=23;
COMMIT;
"""


class MoveBatches:
    def __init__(self, store, backup_root=None):
        self.store = store
        self.backup_root = (
            Path(backup_root) if backup_root else store.root.parent / "backups"
        )

    def preview(
        self,
        owner_id,
        copies,
        album_id,
        *,
        mode="auto",
        start_page=1,
        start_position=1,
        slots=9,
        reason="Déplacement groupé",
    ):
        if not copies:
            raise ValueError("Sélectionnez au moins un exemplaire à déplacer.")
        if len(copies) > 200:
            raise ValueError("Maximum 200 exemplaires par déplacement.")
        if len({c["id"] for c in copies}) != len(copies):
            raise ValueError("Exemplaires répétés.")
        album_id = (album_id or "").strip()
        if not album_id:
            raise ValueError("Choisissez un album d’arrivée.")
        if mode not in ("auto", "from_slot"):
            raise ValueError("Mode de placement invalide.")
        slots = int(slots or 9)
        start_page = int(start_page or 1)
        start_position = int(start_position or 1)
        if not 1 <= slots <= 100:
            raise ValueError("Nombre de cases par page invalide.")
        if not 1 <= start_page <= 1000 or not 1 <= start_position <= slots:
            raise ValueError("Page ou case de départ invalide.")
        reason = (reason or "").strip()
        if not reason:
            raise ValueError("Précisez le motif du déplacement.")

        moving_ids = {c["id"] for c in copies}
        with self.store.connect(write=True) as db:
            album = db.execute(
                "SELECT id, name FROM albums WHERE id=?", (album_id,)
            ).fetchone()
            if not album:
                raise ValueError("Album d’arrivée inconnu.")
            to_album_name = album["name"]

            cards = [
                (
                    self._target(db, target["id"], target["expected_version"]),
                    int(target["expected_version"]),
                )
                for target in copies
            ]
            occupied = self._occupied_slots(db, album_id, moving_ids)

            page, pos = start_page, start_position
            items = []
            for card, expected_version in cards:
                if mode == "auto":
                    while (page, pos) in occupied:
                        pos += 1
                        if pos > slots:
                            page += 1
                            pos = 1
                if page > 1000:
                    raise ValueError(
                        "Numéro de page trop élevé dans l’album d’arrivée."
                    )
                occupants = occupied.get((page, pos), [])
                published = bool(
                    db.execute(
                        "SELECT 1 FROM listing_items i JOIN listings l ON l.id=i.listing_id "
                        "WHERE i.copy_id=? AND i.active=1 AND l.state='online' LIMIT 1",
                        (card["id"],),
                    ).fetchone()
                )
                items.append(
                    {
                        "id": card["id"],
                        "name": card["name"],
                        "set_name": card["set_name"],
                        "number": card["number"],
                        "language": card["language"],
                        "condition": card["condition"],
                        "expected_version": expected_version,
                        "applied_version": None,
                        "from_album_id": card["album_id"],
                        "from_album": card["album"],
                        "from_page": card["page"],
                        "from_position": card["position"],
                        "to_album_id": album_id,
                        "to_album": to_album_name,
                        "to_page": page,
                        "to_position": pos,
                        "unchanged": (
                            card["album_id"] == album_id
                            and card["page"] == page
                            and card["position"] == pos
                        ),
                        "collision": bool(occupants),
                        "occupied_by": occupants,
                        "published": published,
                    }
                )
                pos += 1
                if pos > slots:
                    page += 1
                    pos = 1

            collisions = [
                {
                    "copy_id": item["id"],
                    "name": item["name"],
                    "number": item["number"],
                    "page": item["to_page"],
                    "position": item["to_position"],
                    "occupied_by": item["occupied_by"],
                }
                for item in items
                if item["collision"]
            ]
            jid = str(uuid.uuid4())
            timestamp = now()
            data = {
                "album_id": album_id,
                "album_name": to_album_name,
                "mode": mode,
                "start_page": start_page,
                "start_position": start_position,
                "slots": slots,
                "reason": reason,
                "items": items,
                "collisions": collisions,
                "collisions_count": len(collisions),
                "has_collisions": bool(collisions),
            }
            db.execute(
                "INSERT INTO move_batches VALUES(?,?,?,'preview',?,?)",
                (
                    jid,
                    owner_id,
                    json.dumps(data, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
            return self.get(db, jid, owner_id)

    def apply(
        self,
        jid,
        owner_id,
        actor,
        *,
        reason=None,
        allow_collisions=False,
    ):
        def checked(db):
            job = self.get(db, jid, owner_id)
            if job["status"] != "preview":
                raise Conflict("Ce déplacement a déjà été traité.")
            data = job["data"]
            if not db.execute(
                "SELECT 1 FROM albums WHERE id=?", (data["album_id"],)
            ).fetchone():
                raise ValueError("Album d’arrivée inconnu.")
            for item in data["items"]:
                self._target(db, item["id"], item["expected_version"])
            moving_ids = {item["id"] for item in data["items"]}
            occupied = self._occupied_slots(db, data["album_id"], moving_ids)
            if not allow_collisions:
                for item in data["items"]:
                    occupants = occupied.get((item["to_page"], item["to_position"]))
                    if occupants:
                        other = occupants[0]
                        raise Conflict(
                            f"La case page {item['to_page']} #{item['to_position']} "
                            f"de « {data['album_name']} » est déjà occupée par "
                            f"{other['name']} ({other['number']}). "
                            "Choisissez d’autres cases ou le placement automatique."
                        )
            return job

        with self.store.connect() as db:
            checked(db)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup(
            self.store,
            self.backup_root / f"before-move-batch-{stamp}.zip",
        )
        with self.store.connect(write=True) as db:
            job = checked(db)
            data = job["data"]
            effective_reason = (
                (reason if reason is not None else data.get("reason") or "")
                .strip()
                or "Déplacement groupé"
            )
            data["reason"] = effective_reason
            for item in data["items"]:
                self._target(db, item["id"], item["expected_version"])
                updated = self.store.patch(
                    item["id"],
                    {
                        "album_id": item["to_album_id"],
                        "page": item["to_page"],
                        "position": item["to_position"],
                    },
                    item["expected_version"],
                    actor,
                    effective_reason,
                    _db=db,
                )
                item["applied_version"] = updated["version"]
            db.execute(
                "UPDATE move_batches SET data_json=?, status='applied', updated_at=? WHERE id=?",
                (json.dumps(data, ensure_ascii=False), now(), jid),
            )
            return self.get(db, jid, owner_id)

    def undo(self, jid, owner_id, actor, *, reason=None):
        def checked(db):
            job = self.get(db, jid, owner_id)
            if job["status"] != "applied":
                raise Conflict("Seul un déplacement appliqué peut être annulé.")
            data = job["data"]
            moving_ids = {item["id"] for item in data["items"]}
            occupied_by_album = {}
            for item in data["items"]:
                if not item.get("applied_version"):
                    raise Conflict("Version appliquée absente.")
                self._target(
                    db,
                    item["id"],
                    item["applied_version"],
                    version_message=(
                        "Un exemplaire a été modifié depuis l’application du déplacement."
                    ),
                )
                from_album_id = item["from_album_id"]
                if not db.execute(
                    "SELECT 1 FROM albums WHERE id=?", (from_album_id,)
                ).fetchone():
                    raise ValueError("Album d’origine inconnu.")
                if from_album_id not in occupied_by_album:
                    occupied_by_album[from_album_id] = self._occupied_slots(
                        db, from_album_id, moving_ids
                    )
                occupants = occupied_by_album[from_album_id].get(
                    (item["from_page"], item["from_position"])
                )
                if occupants:
                    other = occupants[0]
                    raise Conflict(
                        f"La case d’origine page {item['from_page']} #{item['from_position']} "
                        f"de « {item['from_album']} » est désormais occupée par "
                        f"{other['name']} ({other['number']})."
                    )
            return job

        with self.store.connect(write=True) as db:
            job = checked(db)
            data = job["data"]
            undo_reason = (reason or "").strip() or (
                f"Annulation du déplacement : {data.get('reason', 'Déplacement groupé')}"
            )
            for item in data["items"]:
                self._target(
                    db,
                    item["id"],
                    item["applied_version"],
                    version_message=(
                        "Un exemplaire a été modifié depuis l’application du déplacement."
                    ),
                )
                updated = self.store.patch(
                    item["id"],
                    {
                        "album_id": item["from_album_id"],
                        "page": item["from_page"],
                        "position": item["from_position"],
                    },
                    item["applied_version"],
                    actor,
                    undo_reason,
                    _db=db,
                )
                item["undone_version"] = updated["version"]
            db.execute(
                "UPDATE move_batches SET data_json=?, status='undone', updated_at=? WHERE id=?",
                (json.dumps(data, ensure_ascii=False), now(), jid),
            )
            return self.get(db, jid, owner_id)

    def _occupied_slots(self, db, album_id, excluded_ids):
        occupied = {}
        for row in db.execute(
            "SELECT id, name, set_name, number, page, position FROM copies "
            "WHERE album_id=? AND deleted_at='' ORDER BY page, position, id",
            (album_id,),
        ):
            if row["id"] in excluded_ids:
                continue
            occupied.setdefault((row["page"], row["position"]), []).append(dict(row))
        return occupied

    def _target(self, db, copy_id, expected_version=None, *, version_message=None):
        card = self.store.get(db, copy_id)
        label = f"{card['name']} ({card['number']})" if card.get("number") else card["name"]
        if card["deleted_at"]:
            raise Conflict(
                f"{label} est dans la corbeille : restaurez-le avant de le déplacer."
            )
        if expected_version is not None and card["version"] != expected_version:
            raise Conflict(
                version_message
                or "Un exemplaire a changé entre-temps. Rechargez la sélection."
            )
        sale = db.execute(
            "SELECT s.id, s.title, s.status FROM sale_items i JOIN sales s ON s.id=i.sale_id "
            "WHERE i.copy_id=? AND s.status NOT IN ('cancelled','returned') LIMIT 1",
            (copy_id,),
        ).fetchone()
        lot_listing = db.execute(
            "SELECT l.id, l.title FROM listing_items i JOIN listings l ON l.id=i.listing_id "
            "WHERE i.copy_id=? AND i.active=1 AND l.state='online' "
            "AND (SELECT COUNT(*) FROM listing_items WHERE listing_id=l.id AND active=1) > 1 LIMIT 1",
            (copy_id,),
        ).fetchone()
        if card["stock_state"] == "sold" or (
            sale and sale["status"] in ("sold", "shipped", "completed")
        ):
            raise Conflict(f"{label} est vendu et ne peut pas être déplacé.")
        if card["stock_state"] == "reserved" or (sale and sale["status"] == "reserved"):
            raise Conflict(f"{label} est réservé et ne peut pas être déplacé.")
        if sale:
            raise Conflict(
                f"{label} appartient au lot actif « {sale['title']} ». "
                "Annulez d’abord le lot avant de déplacer la carte."
            )
        if lot_listing:
            title = lot_listing["title"] or lot_listing["id"][:8]
            raise Conflict(
                f"{label} appartient au lot publié en vitrine « {title} ». "
                "Dépubliez d’abord le lot avant de déplacer la carte."
            )
        return card

    def get(self, db, jid, owner_id):
        row = db.execute(
            "SELECT * FROM move_batches WHERE id=? AND owner_id=?", (jid, owner_id)
        ).fetchone()
        if not row:
            raise KeyError("Lot de déplacement introuvable.")
        data = json.loads(row["data_json"])
        return {
            "id": row["id"],
            "status": row["status"],
            "data": data,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
