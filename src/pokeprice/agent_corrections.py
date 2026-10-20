"""Operator-approved catalogue links; the agent may execute, never author, a plan."""

import hashlib
import json
import re

from .agent import AgentError, AgentService, canonical
from .intake import catalogue_name_matches, number_key
from .inventory import Conflict, now
from .pricing import SOURCE, fetch_catalogue_card, summarize
from .valuation import amount, applicable
from .variant_pricing import category, pricing_issue

SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS agent_corrections(
 grant_id TEXT NOT NULL REFERENCES agent_grants(id),
 copy_id TEXT NOT NULL REFERENCES copies(id), expected_version INTEGER NOT NULL,
 approval_sha256 TEXT NOT NULL, plan_json TEXT NOT NULL, source_json TEXT NOT NULL,
 approved_by TEXT NOT NULL REFERENCES users(id), approved_at TEXT NOT NULL,
 receipt_json TEXT, applied_at TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(grant_id,copy_id));
PRAGMA user_version=19;
COMMIT;
"""


class CorrectionService:
    def __init__(self, store, fetch=fetch_catalogue_card):
        self.store, self.agents, self.fetch = store, AgentService(store), fetch

    def approve(self, grant_id, requests, reason):
        """Local operator only: register the user's approval, not a physical attestation.

        Quotes and identity metadata come from the provider, never from a client price.
        Network reads happen outside the transaction; all versions are checked again.
        """
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            raise ValueError("Motif d'autorisation requis (1 à 1000 caractères).")
        if not isinstance(requests, list) or not 1 <= len(requests) <= 20:
            raise ValueError("Autorisez de 1 à 20 corrections par délégation.")
        if any(
            not isinstance(r, dict)
            or set(r)
            - {"id", "expected_version", "catalog_id", "number", "refresh_price"}
            for r in requests
        ):
            raise ValueError(
                "Le plan ne peut demander que référence, catalogue et relevé."
            )
        if len({r.get("id") for r in requests}) != len(requests):
            raise ValueError("Exemplaires distincts requis.")
        with self.store.connect() as db:
            row = db.execute(
                "SELECT token_hash FROM agent_grants WHERE id=?", (grant_id,)
            ).fetchone()
            if not row or not row["token_hash"]:
                raise ValueError("Délégation active requise.")
            token_hash = row["token_hash"]
            grant = self.agents.authorize(db, token_hash, "corrections:apply")
            originals = {}
            for request in requests:
                ident, version = request.get("id"), request.get("expected_version")
                if (
                    not isinstance(ident, str)
                    or type(version) is not int
                    or version < 1
                ):
                    raise ValueError("UUID et version attendue requis.")
                card = self.agents.scoped_card(db, grant, ident)
                if card["version"] != version:
                    raise Conflict("La fiche a changé avant l'autorisation.")
                if card["reference_cents"] is not None:
                    raise Conflict(
                        "Un prix existe déjà : aucune référence ne sera écrasée."
                    )
                originals[ident] = card
            verdicts = self.store.market_verdicts(db)
        prepared = []
        for request in requests:
            card = originals[request["id"]]
            catalog_id = request.get("catalog_id")
            if not isinstance(catalog_id, str) or not re.fullmatch(
                r"[A-Za-z0-9._-]{1,120}", catalog_id
            ):
                raise ValueError("Identifiant catalogue requis.")
            if card["catalog_id"] not in (None, "", catalog_id):
                raise Conflict("Une autre édition est déjà liée à cette fiche.")
            number = request.get("number", card["number"])
            refresh = request.get("refresh_price", True)
            if (
                not isinstance(number, str)
                or len(number) > 80
                or "/" not in number
                or type(refresh) is not bool
            ):
                raise ValueError(
                    "Référence complète et choix de relevé explicite requis."
                )
            data = self.fetch(catalog_id, card["language"])
            count = (data.get("set") or {}).get("cardCount", {}).get("official")
            full_number = str(data.get("localId", "")) + (f"/{count}" if count else "")
            if (
                data.get("id") != catalog_id
                or not catalogue_name_matches(card["name"], data.get("name", ""))
                or number_key(number) != number_key(full_number)
                or (
                    card["hp"] is not None
                    and data.get("hp") is not None
                    and str(card["hp"]) != str(data["hp"])
                )
            ):
                raise ValueError(
                    "Le catalogue ne correspond pas au nom, numéro complet ou PV autorisés."
                )
            changes = {
                "catalog_id": catalog_id,
                "set_name": (data.get("set") or {}).get("name", ""),
                "number": number,
                "identification_status": "confirmed",
            }
            # Existing physical observations stay intact. A new identity invalidates
            # the global variant approval, exactly as a normal Store correction does.
            proposed = {**card, **changes, "variant_confirmed": False}
            snapshot = summarize(data, bool(card["foil"]))
            decision = category(proposed, snapshot)
            if decision["mode"] == "automatic":
                proposed["foil"] = decision["foil"]
                snapshot = summarize(data, proposed["foil"])
            snapshot["observed_at"] = now()
            cm = (data.get("pricing") or {}).get("cardmarket") or {}
            issue = pricing_issue(proposed, snapshot)
            blocked = (
                applicable(verdicts.get(catalog_id), snapshot["id_product"]) == "wrong"
            )
            cents = (
                amount(snapshot["reference_eur"])
                if refresh
                and not issue
                and not blocked
                and cm.get("unit", "EUR") == "EUR"
                else None
            )
            if cents is not None:
                changes.update(
                    reference_cents=cents,
                    price_source=f"{SOURCE} {snapshot['reference_field']}",
                    price_date=snapshot["updated"] or snapshot["observed_at"],
                )
            source = (
                data.get("_acquisition", {}).get("source")
                or f"https://api.tcgdex.net/v2/{card['language']}/cards/{catalog_id}"
            )
            source_sha256 = hashlib.sha256(canonical(data).encode()).hexdigest()
            plan = {
                "id": card["id"],
                "expected_version": card["version"],
                "changes": changes,
                "reason": reason.strip(),
                "source": source,
                "source_sha256": source_sha256,
                "price_status": "refreshed"
                if cents is not None
                else "unavailable_or_not_authorized",
                "price_issue": issue
                or ("Produit marchand signalé incorrect." if blocked else ""),
                "price_snapshot": snapshot if cents is not None else None,
                "approval_origin": "operator_recorded_user_request",
            }
            digest = hashlib.sha256(canonical(plan).encode()).hexdigest()
            prepared.append((plan, digest, data))
        with self.store.connect(write=True) as db:
            current_grant = self.agents.authorize(db, token_hash, "corrections:apply")
            if current_grant["id"] != grant_id:
                raise Conflict("La délégation a changé.")
            for plan, _digest, _data in prepared:
                card = self.agents.scoped_card(db, current_grant, plan["id"])
                if card["version"] != plan["expected_version"]:
                    raise Conflict("La fiche a changé pendant la préparation.")
                if db.execute(
                    "SELECT 1 FROM agent_corrections WHERE grant_id=? AND copy_id=?",
                    (grant_id, card["id"]),
                ).fetchone():
                    raise Conflict(
                        "Une autorisation existe déjà pour cette fiche et cette délégation."
                    )
            for plan, digest, data in prepared:
                db.execute(
                    "INSERT INTO agent_corrections VALUES(?,?,?,?,?,?,?,?,NULL,'')",
                    (
                        grant_id,
                        plan["id"],
                        plan["expected_version"],
                        digest,
                        canonical(plan),
                        canonical(data),
                        current_grant["owner_id"],
                        now(),
                    ),
                )
        return [
            {
                "id": plan["id"],
                "expected_version": plan["expected_version"],
                "approval_sha256": digest,
                "changes": plan["changes"],
                "price_status": plan["price_status"],
                "source": plan["source"],
            }
            for plan, digest, _data in prepared
        ]

    def pending(self, db, token_hash):
        grant = self.agents.authorize(db, token_hash, "corrections:apply")
        output = []
        for row in db.execute(
            "SELECT * FROM agent_corrections WHERE grant_id=? ORDER BY copy_id",
            (grant["id"],),
        ):
            self.agents.scoped_card(db, grant, row["copy_id"])
            plan = json.loads(row["plan_json"])
            output.append(
                {
                    key: plan[key]
                    for key in (
                        "id",
                        "expected_version",
                        "changes",
                        "source",
                        "source_sha256",
                        "price_status",
                        "price_issue",
                    )
                }
                | {
                    "approval_sha256": row["approval_sha256"],
                    "applied": bool(row["receipt_json"]),
                    "receipt": json.loads(row["receipt_json"])
                    if row["receipt_json"]
                    else None,
                }
            )
        return {"items": output, "album_id": grant["album_id"]}

    def apply(self, token_hash, copy_id, version, approval_sha256, request_id):
        with self.store.connect(write=True) as db:
            grant = self.agents.authorize(db, token_hash, "corrections:apply")
            card = self.agents.scoped_card(db, grant, copy_id)
            row = db.execute(
                "SELECT * FROM agent_corrections WHERE grant_id=? AND copy_id=?",
                (grant["id"], copy_id),
            ).fetchone()
            if not row:
                raise AgentError(
                    403,
                    "not_approved",
                    "Aucune correction autorisée pour cet exemplaire.",
                )
            if (
                version != row["expected_version"]
                or approval_sha256 != row["approval_sha256"]
            ):
                raise Conflict("Version ou empreinte du plan autorisé différente.")
            if row["receipt_json"]:
                return json.loads(row["receipt_json"])
            if card["version"] != version:
                raise Conflict(
                    "La fiche a changé : nouvelle revue et autorisation nécessaires."
                )
            plan = json.loads(row["plan_json"])
            if hashlib.sha256(canonical(plan).encode()).hexdigest() != approval_sha256:
                raise Conflict("Plan autorisé altéré.")
            if (
                hashlib.sha256(
                    canonical(json.loads(row["source_json"])).encode()
                ).hexdigest()
                != plan["source_sha256"]
            ):
                raise Conflict("Source de l'autorisation altérée.")
            if (
                plan["price_snapshot"]
                and applicable(
                    self.store.market_verdicts(db).get(plan["changes"]["catalog_id"]),
                    plan["price_snapshot"]["id_product"],
                )
                == "wrong"
            ):
                raise Conflict(
                    "Le produit marchand a été signalé incorrect depuis l'autorisation."
                )
            actor = "agent:" + grant["id"]
            after = self.store.patch(
                copy_id,
                plan["changes"],
                version,
                actor,
                plan["reason"],
                _db=db,
                _category_snapshot=plan["price_snapshot"],
            )
            if plan["price_snapshot"]:
                self.store.event(
                    db,
                    copy_id,
                    actor,
                    "price-snapshot",
                    "Relevé TCGdex du plan autorisé",
                    {},
                    plan["price_snapshot"],
                )
            receipt = {
                "id": copy_id,
                "version": after["version"],
                "previous_version": version,
                "approval_sha256": approval_sha256,
                "agent_id": grant["id"],
                "request_id": request_id,
                "catalog_id": after["catalog_id"],
                "reference_cents": after["reference_cents"],
                "price_status": plan["price_status"],
                "physical_confirmation_created": False,
                "applied_at": now(),
            }
            self.store.event(
                db,
                copy_id,
                actor,
                "agent-correction",
                "Application d'un plan autorisé par le propriétaire",
                {},
                {
                    **receipt,
                    "approval_origin": plan["approval_origin"],
                    "source": plan["source"],
                    "source_sha256": plan["source_sha256"],
                },
            )
            db.execute(
                "UPDATE agent_corrections SET receipt_json=?,applied_at=? WHERE grant_id=? AND copy_id=?",
                (canonical(receipt), receipt["applied_at"], grant["id"], copy_id),
            )
            return receipt
