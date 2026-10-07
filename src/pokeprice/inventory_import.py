"""One-way, idempotent import with original rows retained as provenance."""

import base64
import hashlib
import json
from pathlib import Path
import uuid

from .inventory import Store, cents, now
from .library import consolidate, load_manifest


def import_collection(store: Store, manifest):
    albums = load_manifest(manifest)
    frame, data = consolidate(albums, store.root)
    records = json.loads(frame.to_json(orient="records", force_ascii=False))
    crops = {c["id"]: c["image"] for g in data["groups"] for c in g["copies"]}
    images = {}
    for source_key, image in crops.items():
        if not image.startswith("data:image/jpeg;base64,"):
            raise ValueError(f"Photo de carte absente : {source_key}")
        images[source_key] = store.save_photo(
            base64.b64decode(image.split(",", 1)[1], validate=True)
        )
    result = {
        "source_copies": len(records),
        "created": 0,
        "unchanged": 0,
        "source_changed": [],
        "albums": {},
    }
    with store.connect(write=True) as db:
        for album in albums:
            db.execute(
                "INSERT OR IGNORE INTO albums VALUES(?,?)", (album["id"], album["name"])
            )
        for raw in records:
            source_key = raw["Exemplaire_ID"]
            copy_id = str(
                uuid.uuid5(uuid.NAMESPACE_URL, "pokeprice:copy:" + source_key)
            )
            raw_json = json.dumps(
                raw, sort_keys=True, ensure_ascii=False, allow_nan=False
            )
            checksum = hashlib.sha256(raw_json.encode()).hexdigest()
            existing = db.execute(
                "SELECT c.id,s.sha256 FROM copies c LEFT JOIN sources s ON s.copy_id=c.id WHERE c.source_key=?",
                (source_key,),
            ).fetchone()
            if existing:
                if existing["sha256"] != checksum:
                    result["source_changed"].append(source_key)
                else:
                    result["unchanged"] += 1
                continue
            confirmed = raw["Statut_Identification"] == "confirmed"
            stamp = now()
            card = {
                "id": copy_id,
                "source_key": source_key,
                "name": raw.get("Nom_Verifie")
                or raw.get("Identified_Name")
                or raw.get("OCR_Name")
                or "À identifier",
                "set_name": raw.get("Extension") or "",
                "number": raw.get("Numero_Officiel") or "",
                "language": raw.get("Langue_Carte") or "unknown",
                "catalog_id": raw.get("TCGdex_ID") if confirmed else None,
                "hp": raw.get("PV_Verifie")
                if raw.get("PV_Verifie") is not None
                else raw.get("PV"),
                "identification_status": raw["Statut_Identification"],
                "condition": raw.get("Etat") or "",
                "condition_confirmed": False,
                "foil": raw.get("Is_Foil") == "Oui",
                "album_id": raw["Album_ID"],
                "page": int(raw["Page"]),
                "position": int(raw["Position"]),
                "notes": raw.get("Note_Verification") or "",
                "photo": images[source_key],
                "reference_cents": cents(raw.get("Prix_Reference_EUR"))
                if confirmed
                else None,
                "price_source": raw.get("Source_Prix_EUR") or "" if confirmed else "",
                "price_date": raw.get("Date_Prix") or "" if confirmed else "",
                "created_at": stamp,
                "updated_at": stamp,
            }
            card["edition_id"] = store.edition(db, card)
            db.execute(
                "INSERT INTO copies("
                + ",".join(card)
                + ") VALUES("
                + ",".join("?" for _ in card)
                + ")",
                list(card.values()),
            )
            db.execute(
                "INSERT INTO sources VALUES(?,?,?,?)",
                (copy_id, raw_json, checksum, stamp),
            )
            store.event(
                db,
                copy_id,
                "import",
                "import",
                "Import des sources conservées",
                {},
                card,
            )
            store.observe_price(db, card, "import")
            result["created"] += 1
        result["albums"] = {
            r["album_id"]: r["n"]
            for r in db.execute(
                "SELECT album_id,COUNT(*) n FROM copies GROUP BY album_id"
            )
        }
        db.execute(
            "INSERT INTO imports(manifest,result_json,created_at) VALUES(?,?,?)",
            (
                str(Path(manifest).resolve()),
                json.dumps(result, ensure_ascii=False),
                now(),
            ),
        )
    result["inventory"] = store.summary()
    return result
