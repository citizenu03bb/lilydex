"""Local photo previews, selected atomic application, and guarded undo."""

import json
import uuid
from datetime import datetime, timezone

from .inventory import Conflict, now
from .inventory_backup import backup
from .photo_processing import prepare_photo


class PhotoBatches:
    def __init__(self, store):
        self.store = store

    def get(self, db, job_id, owner):
        row = db.execute(
            "SELECT * FROM photo_batches WHERE id=? AND owner_id=?", (job_id, owner)
        ).fetchone()
        if not row:
            raise KeyError("Simulation inconnue.")
        job = dict(row)
        job["data"] = json.loads(job.pop("data_json"))
        return job

    def preview(self, owner, copies, side, options):
        field = "photo" if side == "front" else "back_photo"
        with self.store.connect() as db:
            originals = [self.store.get(db, c["id"]) for c in copies]
        items = []
        for requested, card in zip(copies, originals, strict=True):
            if card["deleted_at"] or card["version"] != requested["expected_version"]:
                raise Conflict("Un exemplaire a changé. Rechargez la sélection.")
            item = {
                "id": card["id"],
                "name": card["name"],
                "location": f"{card['album']} · P.{card['page']} #{card['position']}",
                "version": card["version"],
                "before": card[field],
                "original": card[field + "_original"],
                "result": None,
            }
            source = item["original"] or item["before"]
            if source:
                image, processing = prepare_photo(
                    (self.store.photos / source).read_bytes(), **options
                )
                item.update(
                    result=self.store.save_photo(image),
                    processing=processing,
                    fallback=not bool(item["original"]),
                )
            items.append(item)
        jid = str(uuid.uuid4())
        with self.store.connect(write=True) as db:
            db.execute(
                "INSERT INTO photo_batches VALUES(?,?,?,'preview',?,?)",
                (
                    jid,
                    owner,
                    json.dumps({"side": side, "items": items}, ensure_ascii=False),
                    now(),
                    now(),
                ),
            )
            return self.get(db, jid, owner)

    def checked(self, db, jid, owner, selected, undo):
        job = self.get(db, jid, owner)
        if job["status"] != ("applied" if undo else "preview"):
            raise Conflict("Ce traitement a déjà été appliqué ou annulé.")
        data = job["data"]
        if undo:
            selected = [
                item["id"] for item in data["items"] if item.get("applied_version")
            ]
        if not selected or len(set(selected)) != len(selected):
            raise ValueError("Sélectionnez au moins une photo distincte.")
        items = {i["id"]: i for i in data["items"]}
        for copy_id in selected:
            item = items.get(copy_id)
            if not item or not item["result"]:
                raise ValueError("Photo absente ou étrangère à la simulation.")
            card = self.store.get(db, copy_id)
            expected = item["applied_version"] if undo else item["version"]
            if card["deleted_at"] or card["version"] != expected:
                raise Conflict(
                    "Une fiche a changé depuis ce traitement. Aucune photo n’a été modifiée."
                )
        return data, selected, items

    def apply(self, jid, owner, actor, selected, *, undo=False):
        # Refused requests must not cost a full archive: check before backing up.
        with self.store.connect() as db:
            self.checked(db, jid, owner, selected, undo)
        # Archive prior state before any bulk write. No cloud or model calls here.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup(
            self.store,
            self.store.root.parent / "backups" / f"before-photo-batch-{stamp}.zip",
        )
        with self.store.connect(write=True) as db:
            # Checked again under the write lock: the state may have moved meanwhile.
            data, selected, items = self.checked(db, jid, owner, selected, undo)
            field = "photo" if data["side"] == "front" else "back_photo"
            for copy_id in selected:
                item = items[copy_id]
                changes = {
                    field: item["before"] if undo else item["result"],
                    field + "_original": item["original"],
                }
                version = item["applied_version"] if undo else item["version"]
                card = self.store.patch(
                    copy_id,
                    changes,
                    version,
                    actor,
                    "Annulation du traitement photo par lot"
                    if undo
                    else "Préparation locale des photos par lot",
                    evidence={
                        "type": "photo-batch",
                        "batch_id": jid,
                        "side": data["side"],
                        "undo": undo,
                        "processing": item["processing"],
                    },
                    _db=db,
                )
                if not undo:
                    item["applied_version"] = card["version"]
            db.execute(
                "UPDATE photo_batches SET data_json=?,status=?,updated_at=? WHERE id=?",
                (json.dumps(data), "undone" if undo else "applied", now(), jid),
            )
            return self.get(db, jid, owner)
