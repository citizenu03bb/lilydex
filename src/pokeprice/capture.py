"""Owned, resumable capture sessions with atomic and idempotent advancement."""

import json
import uuid

from .inventory import Conflict, now


class CaptureService:
    def __init__(self, store, intake):
        self.store, self.intake = store, intake

    def get(self, db, session_id, owner):
        row = db.execute(
            "SELECT * FROM capture_sessions WHERE id=? AND owner_id=?",
            (session_id, owner),
        ).fetchone()
        if not row:
            raise KeyError("Série inconnue.")
        result = dict(row)
        result["data"] = json.loads(result.pop("data_json"))
        return result

    def listing(self, owner):
        with self.store.connect() as db:
            return [
                self.get(db, r[0], owner)
                for r in db.execute(
                    "SELECT id FROM capture_sessions WHERE owner_id=? AND status!='closed' ORDER BY updated_at DESC",
                    (owner,),
                )
            ]

    def create(self, owner, values):
        with self.store.connect(write=True) as db:
            if db.execute(
                "SELECT 1 FROM capture_sessions WHERE owner_id=? AND status='active'",
                (owner,),
            ).fetchone():
                raise Conflict(
                    "Une série est déjà ouverte. Reprenez-la ou mettez-la en pause."
                )
            if not db.execute(
                "SELECT 1 FROM albums WHERE id=?", (values["album_id"],)
            ).fetchone():
                raise ValueError("Album inconnu.")
            if values["position"] > values["slots"]:
                raise ValueError("Pochette supérieure au nombre de pochettes par page.")
            sid = str(uuid.uuid4())
            data = {
                "page": values["page"],
                "position": values["position"],
                "fields": {},
                "front_token": None,
                "back_token": None,
                "completed": 0,
            }
            db.execute(
                "INSERT INTO capture_sessions VALUES(?,?,?,'active',?,?,1,?,?)",
                (
                    sid,
                    owner,
                    values["album_id"],
                    values["slots"],
                    json.dumps(data),
                    now(),
                    now(),
                ),
            )
            return self.get(db, sid, owner)

    def patch(self, sid, owner, version, changes):
        with self.intake.lock:
            discarded = []
            for key in ("front_token", "back_token"):
                if changes.get(key):
                    draft = self.intake.draft(changes[key], owner)
                    if draft["existing"] or draft["saved"]:
                        raise ValueError(
                            "Photo déjà utilisée ou réservée à une identification."
                        )
                    self.intake.persist(changes[key], owner, durable=True)
            with self.store.connect(write=True) as db:
                session = self.get(db, sid, owner)
                if session["version"] != version or session["status"] == "closed":
                    raise Conflict("La série a changé. Rechargez-la.")
                status = changes.get("status", session["status"])
                if (
                    status == "active"
                    and db.execute(
                        "SELECT 1 FROM capture_sessions WHERE owner_id=? AND status='active' AND id!=?",
                        (owner, sid),
                    ).fetchone()
                ):
                    raise Conflict(
                        "Mettez l’autre série en pause avant de reprendre celle-ci."
                    )
                data = {
                    **session["data"],
                    **{k: v for k, v in changes.items() if k != "status"},
                }
                other_tokens = set()
                for other in db.execute(
                    "SELECT data_json FROM capture_sessions WHERE owner_id=? AND status!='closed' AND id!=?",
                    (owner, sid),
                ):
                    other_data = json.loads(other[0])
                    other_tokens.update(
                        (other_data.get("front_token"), other_data.get("back_token"))
                    )
                if any(
                    data.get(key) and data[key] in other_tokens
                    for key in ("front_token", "back_token")
                ):
                    raise Conflict(
                        "Cette photo appartient déjà à une autre série en cours."
                    )
                if data["position"] > session["slots"]:
                    raise ValueError("Pochette supérieure au format de la page.")
                if data.get("front_token") and data["front_token"] == data.get(
                    "back_token"
                ):
                    raise ValueError(
                        "Utilisez deux prises de vue distinctes pour recto et verso."
                    )
                if status == "closed":
                    discarded = [
                        data.get(key)
                        for key in ("front_token", "back_token")
                        if data.get(key)
                    ]
                    for token in discarded:
                        db.execute(
                            "DELETE FROM intake_drafts WHERE token=? AND owner_id=?",
                            (token, owner),
                        )
                    data.update(front_token=None, back_token=None, fields={})
                db.execute(
                    "UPDATE capture_sessions SET status=?,data_json=?,version=version+1,updated_at=? WHERE id=?",
                    (status, json.dumps(data, ensure_ascii=False), now(), sid),
                )
                result = self.get(db, sid, owner)
            for token in discarded:
                self.intake.drafts.pop(token, None)
            return result

    def save(
        self,
        sid,
        owner,
        actor,
        version,
        token,
        values,
        chosen,
        confirmed,
        acknowledgments,
    ):
        with self.intake.lock:
            with self.store.connect(write=True) as db:
                session = self.get(db, sid, owner)
                data = session["data"]
                if data.get("last_token") == token:
                    return {
                        "card": self.store.get(db, data["last_copy"]),
                        "session": session,
                    }
                if session["status"] != "active" or session["version"] != version:
                    raise Conflict(
                        "La série a changé. Rechargez-la avant d’enregistrer."
                    )
                if token != data.get("front_token"):
                    raise Conflict("Le recto courant a changé.")
                draft = self.intake.draft(token, owner)
                if draft["saved"] or draft["existing"]:
                    raise ValueError("Préparation déjà utilisée.")
                back = (
                    self.intake.draft(data["back_token"], owner)
                    if data.get("back_token")
                    else None
                )
                if back and (back["saved"] or back["existing"]):
                    raise ValueError("Verso déjà utilisé.")
                values = {**values, "album_id": session["album_id"]}
                if values["position"] > session["slots"]:
                    raise ValueError("Pochette supérieure au format de la page.")
                evidence = self.intake.photo_evidence(back) if back else None
                if evidence:
                    values.update(
                        back_photo=evidence["prepared_photo"],
                        back_photo_original=evidence["original_photo"],
                    )
                card = self.intake.save(
                    token,
                    owner,
                    actor,
                    values,
                    chosen,
                    confirmed,
                    duplicate_acknowledgments=acknowledgments,
                    _db=db,
                )
                if evidence:
                    self.store.event(
                        db,
                        card["id"],
                        actor,
                        "photo-preparation",
                        "Verso enregistré avec la série",
                        {},
                        {"side": "back", **evidence},
                    )
                for consumed, additions in (
                    (token, {"saved": card["id"]}),
                    (
                        data.get("back_token"),
                        {
                            "saved": card["id"],
                            "attached_copy": card["id"],
                            "attached_side": "back",
                        },
                    ),
                ):
                    if consumed:
                        stored = json.loads(
                            db.execute(
                                "SELECT data_json FROM intake_drafts WHERE token=?",
                                (consumed,),
                            ).fetchone()[0]
                        )
                        stored.update(additions)
                        db.execute(
                            "UPDATE intake_drafts SET data_json=? WHERE token=?",
                            (json.dumps(stored), consumed),
                        )
                page, position = values["page"], values["position"] + 1
                if position > session["slots"]:
                    page, position = page + 1, 1
                data = {
                    "page": min(page, 1000),
                    "position": position,
                    "fields": {},
                    "front_token": None,
                    "back_token": None,
                    "completed": data["completed"] + 1,
                    "last_token": token,
                    "last_copy": card["id"],
                }
                db.execute(
                    "UPDATE capture_sessions SET data_json=?,status=?,version=version+1,updated_at=? WHERE id=?",
                    (
                        json.dumps(data),
                        "closed" if page > 1000 else "active",
                        now(),
                        sid,
                    ),
                )
                result = {"card": card, "session": self.get(db, sid, owner)}
            # Consumed tokens are marked only after the database transaction commits.
            draft["saved"] = card["id"]
            if back:
                back.update(
                    saved=card["id"], attached_copy=card["id"], attached_side="back"
                )
            return result
