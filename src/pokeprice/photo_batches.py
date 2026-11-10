"""Local photo previews, selected atomic application, and guarded undo."""

import io
import json
import uuid
import warnings

from PIL import Image

from .inventory import Conflict, now
from .photo_processing import prepare_photo
from .slicer import normalize_orientation, slice_grid

ROTATIONS = ("auto", "0", "90", "180", "270")


def slice_page_photo(
    data: bytes, rotation: str = "auto"
) -> tuple[bytes, list[tuple[int, bytes]]]:
    """Validate, orient, and slice a 3x3 binder page image into 9 pocket JPEGs."""
    if rotation not in ROTATIONS:
        raise ValueError("Rotation non prise en charge.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as opened:
                if (
                    opened.format not in ("JPEG", "PNG", "WEBP")
                    or opened.width * opened.height > 24_000_000
                    or min(opened.width, opened.height) < 18
                ):
                    raise ValueError("Format ou dimensions non pris en charge.")
                oriented = normalize_orientation(opened, rotation=rotation).convert(
                    "RGB"
                )
    except (
        OSError,
        ValueError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ):
        raise ValueError(
            "Photo JPEG, PNG ou WebP valide requise (24 mégapixels maximum)."
        ) from None

    page_image = oriented.copy()
    page_image.thumbnail((3200, 3200))
    page_buf = io.BytesIO()
    page_image.save(page_buf, format="JPEG", quality=90)

    pockets: list[tuple[int, bytes]] = []
    for position, crop in slice_grid(oriented, 3, 3, inset_pct=0.02):
        cell = crop.copy()
        cell.thumbnail((1600, 1600))
        cell_buf = io.BytesIO()
        cell.save(cell_buf, format="JPEG", quality=92)
        pockets.append((position, cell_buf.getvalue()))
    return page_buf.getvalue(), pockets


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

    def preview_page(self, owner, album_id, page, data, *, rotation="auto"):
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= 1000:
            raise ValueError("Numéro de page invalide (1 à 1000).")
        with self.store.connect() as db:
            album = db.execute(
                "SELECT id, name FROM albums WHERE id=?", (album_id,)
            ).fetchone()
            if not album:
                raise KeyError("Album inconnu.")
            rows = db.execute(
                "SELECT id FROM copies WHERE album_id=? AND page=? AND deleted_at='' "
                "ORDER BY position, created_at, id",
                (album_id, page),
            ).fetchall()
            existing = [self.store.get(db, r[0]) for r in rows]

        page_bytes, pockets = slice_page_photo(data, rotation=rotation)
        by_position: dict[int, list[dict]] = {pos: [] for pos in range(1, 10)}
        for card in existing:
            if 1 <= card["position"] <= 9:
                by_position[card["position"]].append(card)

        page_photo = self.store.save_photo(page_bytes)
        items = []
        for position, cell_bytes in pockets:
            result_photo = self.store.save_photo(cell_bytes)
            matches = by_position[position]
            location = f"{album['name']} · P.{page} #{position}"
            if len(matches) == 1:
                card = matches[0]
                items.append(
                    {
                        "key": f"pos-{position}",
                        "position": position,
                        "action": "update",
                        "id": card["id"],
                        "name": card["name"],
                        "set_name": card["set_name"],
                        "number": card["number"],
                        "identification_status": card["identification_status"],
                        "location": location,
                        "version": card["version"],
                        "before": card["photo"],
                        "original": card["photo_original"],
                        "result": result_photo,
                    }
                )
            elif len(matches) == 0:
                items.append(
                    {
                        "key": f"pos-{position}",
                        "position": position,
                        "action": "create",
                        "id": None,
                        "name": "À identifier",
                        "set_name": "",
                        "number": "",
                        "identification_status": "unresolved",
                        "location": location,
                        "version": None,
                        "before": None,
                        "original": None,
                        "result": result_photo,
                    }
                )
            else:
                items.append(
                    {
                        "key": f"pos-{position}",
                        "position": position,
                        "action": "conflict",
                        "id": None,
                        "name": " / ".join(c["name"] for c in matches),
                        "set_name": "",
                        "number": "",
                        "identification_status": "unresolved",
                        "location": location,
                        "version": None,
                        "before": matches[0]["photo"],
                        "original": matches[0]["photo_original"],
                        "result": result_photo,
                        "conflict_ids": [c["id"] for c in matches],
                    }
                )

        jid = str(uuid.uuid4())
        payload = {
            "kind": "page",
            "side": "front",
            "album_id": album["id"],
            "album": album["name"],
            "page": page,
            "rotation": rotation,
            "page_photo": page_photo,
            "items": items,
        }
        with self.store.connect(write=True) as db:
            db.execute(
                "INSERT INTO photo_batches VALUES(?,?,?,'preview',?,?)",
                (
                    jid,
                    owner,
                    json.dumps(payload, ensure_ascii=False),
                    now(),
                    now(),
                ),
            )
            return self.get(db, jid, owner)

    def _resolve_page_positions(self, data, selected, undo):
        if undo:
            return [
                item["position"]
                for item in data["items"]
                if item.get("applied_version")
            ]
        by_pos = {item["position"]: item for item in data["items"]}
        by_id = {
            item["id"]: item["position"]
            for item in data["items"]
            if item.get("id")
        }
        positions = []
        for raw in selected or []:
            if isinstance(raw, int) and not isinstance(raw, bool):
                pos = raw
            elif isinstance(raw, str):
                text = raw.strip()
                if text.isdigit():
                    pos = int(text)
                elif text.startswith("pos-") and text[4:].isdigit():
                    pos = int(text[4:])
                elif text in by_id:
                    pos = by_id[text]
                else:
                    raise ValueError("Photo absente ou étrangère à la simulation.")
            else:
                raise ValueError("Photo absente ou étrangère à la simulation.")
            if pos not in by_pos:
                raise ValueError("Photo absente ou étrangère à la simulation.")
            positions.append(pos)
        return positions

    def checked(self, db, jid, owner, selected, undo):
        job = self.get(db, jid, owner)
        if job["status"] != ("applied" if undo else "preview"):
            raise Conflict("Ce traitement a déjà été appliqué ou annulé.")
        data = job["data"]
        if data.get("kind") == "page":
            if not db.execute(
                "SELECT 1 FROM albums WHERE id=?", (data["album_id"],)
            ).fetchone():
                raise Conflict("L’album a changé depuis ce traitement.")
            positions = self._resolve_page_positions(data, selected, undo)
            if not positions or len(set(positions)) != len(positions):
                raise ValueError("Sélectionnez au moins une photo distincte.")
            items = {i["position"]: i for i in data["items"]}
            for pos in positions:
                item = items.get(pos)
                if not item or not item.get("result"):
                    raise ValueError("Photo absente ou étrangère à la simulation.")
                if item.get("action") == "conflict":
                    raise Conflict(
                        "Plusieurs exemplaires occupent déjà une pochette sélectionnée."
                    )
                if undo:
                    if not item.get("id"):
                        raise Conflict(
                            "Une fiche a changé depuis ce traitement. Aucune photo n’a été modifiée."
                        )
                    card = self.store.get(db, item["id"])
                    if card["deleted_at"] or card["version"] != item["applied_version"]:
                        raise Conflict(
                            "Une fiche a changé depuis ce traitement. Aucune photo n’a été modifiée."
                        )
                    if item["action"] == "create":
                        linked = db.execute(
                            "SELECT 1 FROM sale_items i JOIN sales s ON s.id=i.sale_id "
                            "WHERE i.copy_id=? AND s.status NOT IN ('cancelled','returned') LIMIT 1",
                            (item["id"],),
                        ).fetchone()
                        if card["stock_state"] != "available" or linked:
                            raise Conflict(
                                "Un exemplaire créé fait partie d’un lot en cours et ne peut pas être annulé."
                            )
                else:
                    current_ids = [
                        r[0]
                        for r in db.execute(
                            "SELECT id FROM copies WHERE album_id=? AND page=? AND position=? AND deleted_at=''",
                            (data["album_id"], data["page"], pos),
                        ).fetchall()
                    ]
                    if item["action"] == "update":
                        card = self.store.get(db, item["id"])
                        if (
                            card["deleted_at"]
                            or card["version"] != item["version"]
                            or current_ids != [item["id"]]
                        ):
                            raise Conflict(
                                "Une fiche a changé depuis ce traitement. Aucune photo n’a été modifiée."
                            )
                    elif item["action"] == "create":
                        if current_ids:
                            raise Conflict(
                                "Une pochette vide a été occupée depuis la découpe. Aucune photo n’a été modifiée."
                            )
            return data, positions, items

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
            # Prior state before any bulk write. Photos are named by their hash and
            # never deleted, so the database alone keeps every former photo.
            self.store.copy_database(db, "before-photo-batch")
        with self.store.connect(write=True) as db:
            # Checked again under the write lock: the state may have moved meanwhile.
            data, selected, items = self.checked(db, jid, owner, selected, undo)
            if data.get("kind") == "page":
                for pos in selected:
                    item = items[pos]
                    if item["action"] == "update":
                        changes = (
                            {
                                "photo": item["before"],
                                "photo_original": item["original"],
                            }
                            if undo
                            else {
                                "photo": item["result"],
                                "photo_original": item["result"],
                                "condition_confirmed": False,
                            }
                        )
                        version = item["applied_version"] if undo else item["version"]
                        card = self.store.patch(
                            item["id"],
                            changes,
                            version,
                            actor,
                            "Annulation du dépôt de page de classeur"
                            if undo
                            else f"Photo de la page {data['page']} découpée (pochette #{pos})",
                            evidence={
                                "type": "page-photo-batch",
                                "batch_id": jid,
                                "action": "update",
                                "album_id": data["album_id"],
                                "page": data["page"],
                                "position": pos,
                                "page_photo": data["page_photo"],
                                "undo": undo,
                            },
                            _db=db,
                        )
                        if not undo:
                            item["applied_version"] = card["version"]
                    elif item["action"] == "create":
                        if undo:
                            self.store.set_deleted(
                                item["id"],
                                True,
                                item["applied_version"],
                                actor,
                                "Annulation du dépôt de page de classeur",
                                _db=db,
                            )
                        else:
                            card = self.store.create_copy(
                                {
                                    "name": "À identifier",
                                    "set_name": "",
                                    "number": "",
                                    "language": "unknown",
                                    "identification_status": "unresolved",
                                    "album_id": data["album_id"],
                                    "page": data["page"],
                                    "position": pos,
                                    "photo": item["result"],
                                    "photo_original": item["result"],
                                },
                                actor,
                                f"Dépôt de la page {data['page']} (pochette #{pos})",
                                evidence={
                                    "type": "page-photo-batch",
                                    "batch_id": jid,
                                    "action": "create",
                                    "album_id": data["album_id"],
                                    "page": data["page"],
                                    "position": pos,
                                    "page_photo": data["page_photo"],
                                    "photo": item["result"],
                                },
                                _db=db,
                            )
                            item["id"] = card["id"]
                            item["applied_version"] = card["version"]
            else:
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
                (
                    json.dumps(data, ensure_ascii=False),
                    "undone" if undo else "applied",
                    now(),
                    jid,
                ),
            )
            return self.get(db, jid, owner)
