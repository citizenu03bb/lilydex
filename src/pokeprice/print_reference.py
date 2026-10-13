"""Offline print resolution. This module never reads a copy database or the clock.

Rules are claims with explicit scopes, not guesses made from catalogue flags.
An incomplete list retains an unknown remainder even when only one entry matches.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from importlib.resources import files

ENGINE_VERSION = "1"
STATES = {"unobserved", "absent", "present"}
FINISHES = {"non_holo", "holo", "holo_border", "reverse", "special"}
OBSERVATIONS = {"finish", "stamp", "distribution"}
BINDING_FIELDS = {
    "market",
    "product_ref",
    "native_variant",
    "filters",
    "metric_family",
    "currency",
    "population",
}


class InvalidReference(ValueError):
    pass


def normalized(value):
    # Keep matching semantics inside the versioned engine archived for replay.
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", str(value)).casefold()
        if not unicodedata.combining(c)
    ).strip()


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def binding_key(binding):
    """Only market semantics identify a binding; labels and rule versions don't."""
    if not BINDING_FIELDS <= binding.keys():
        raise InvalidReference("Correspondance marchande incomplète.")
    semantics = {key: binding[key] for key in BINDING_FIELDS}
    if any(semantics[key] is None for key in BINDING_FIELDS):
        raise InvalidReference("Dimension marchande inconnue.")
    if any(
        not isinstance(semantics[key], str) or not semantics[key].strip()
        for key in ("market", "product_ref", "currency")
    ):
        raise InvalidReference("Identité marchande vide.")
    if not semantics["product_ref"].startswith(semantics["market"] + ":"):
        raise InvalidReference("Produit marchand non qualifié.")
    for key in ("native_variant", "filters", "metric_family", "population"):
        if not isinstance(semantics[key], dict) or not semantics[key]:
            raise InvalidReference("Dimension marchande non explicite : " + key)
    family = semantics["metric_family"]
    if (
        not family.get("id")
        or not family.get("version")
        or not isinstance(family.get("metrics"), dict)
        or not family["metrics"]
    ):
        raise InvalidReference("Sémantique des métriques non versionnée.")
    if not re.fullmatch(r"[A-Z]{3}", semantics["currency"]):
        raise InvalidReference("Devise inconnue.")

    # An explicit `none`/`all`/`aggregate` object is known; null at any depth is not.
    def known(value):
        if value is None:
            return False
        if isinstance(value, dict):
            return all(known(v) for v in value.values())
        if isinstance(value, list):
            return all(known(v) for v in value)
        return True

    if not known(semantics):
        raise InvalidReference("Dimension marchande inconnue.")
    semantics = json.loads(canonical(semantics))
    for dimension in ("filters", "population"):
        for name, value in semantics[dimension].items():
            if isinstance(value, list):
                semantics[dimension][name] = sorted(value, key=canonical)
    return "binding:" + digest(semantics)


def _check_scope(scope):
    if not isinstance(scope, dict) or not scope.get("set_id"):
        raise InvalidReference("Édition absente du périmètre.")
    if scope.keys() - {"set_id", "languages", "numbers", "exclusions"}:
        raise InvalidReference(
            "Dimension de périmètre non prise en charge ; aucune extrapolation autorisée."
        )
    languages = scope.get("languages")
    if (
        not isinstance(languages, list)
        or not languages
        or any(not re.fullmatch(r"[a-z]{2,3}", lang) for lang in languages)
    ):
        raise InvalidReference("Langues explicites requises.")
    numbers = scope.get("numbers")
    if (
        not isinstance(numbers, list)
        or len(numbers) != 2
        or any(type(n) is not int for n in numbers)
        or not 0 <= numbers[0] <= numbers[1] <= 9999
    ):
        raise InvalidReference("Plage de numéros invalide.")
    if any(
        type(n) is not int or not numbers[0] <= n <= numbers[1]
        for n in scope.get("exclusions", [])
    ):
        raise InvalidReference("Exclusion hors périmètre.")


def _contains(outer, inner):
    return (
        outer["set_id"] == inner["set_id"]
        and set(inner["languages"]) <= set(outer["languages"])
        and outer["numbers"][0]
        <= inner["numbers"][0]
        <= inner["numbers"][1]
        <= outer["numbers"][1]
        and not (set(outer.get("exclusions", [])) - set(inner.get("exclusions", [])))
        & set(range(inner["numbers"][0], inner["numbers"][1] + 1))
    )


@dataclass(frozen=True)
class Ruleset:
    """Immutable, validated canonical content, including the extracted facts."""

    content: str
    hash: str

    @property
    def data(self):
        return json.loads(self.content)


def validate_ruleset(data):
    try:
        if (
            data.get("schema_version") != 1
            or not isinstance(data.get("content_version"), str)
            or not data["content_version"]
        ):
            raise InvalidReference("Version du référentiel inconnue.")
        evidence = data["evidence"]
        bindings = data["bindings"]
        rules = data["rules"]
        if (
            not isinstance(evidence, dict)
            or not isinstance(bindings, dict)
            or not isinstance(rules, list)
        ):
            raise InvalidReference("Structure du référentiel invalide.")
        for claim in evidence.values():
            _check_scope(claim["scope"])
            if claim["kind"] not in ("print", "market", "closure") or claim[
                "status"
            ] not in ("verified", "provisional"):
                raise InvalidReference("Type de preuve inconnu.")
            if (
                not claim.get("claim")
                or not claim.get("source")
                or not claim.get("accessed_at")
            ):
                raise InvalidReference("Preuve sans fait extrait, source ou date.")
            if not re.fullmatch(r"[a-f0-9]{64}", claim.get("document_sha256", "")):
                raise InvalidReference("Preuve sans empreinte de document.")

        def proof(ids, kind, scope, verified=False):
            if not ids or any(i not in evidence for i in ids):
                raise InvalidReference("Preuve absente ou inconnue.")
            if not any(
                evidence[i]["kind"] == kind
                and _contains(evidence[i]["scope"], scope)
                and (not verified or evidence[i]["status"] == "verified")
                for i in ids
            ):
                raise InvalidReference(
                    "Preuve hors périmètre ou insuffisante : " + kind
                )

        for identifier, binding in bindings.items():
            if not identifier:
                raise InvalidReference("Correspondance sans identifiant.")
            binding_key(binding)
            if binding.get("status") not in ("verified", "provisional") or binding.get(
                "foil_projection"
            ) not in (None, False, True):
                raise InvalidReference("Statut de correspondance inconnu.")
            _check_scope(binding["scope"])
            proof(
                binding.get("evidence", []),
                "market",
                binding["scope"],
                binding["status"] == "verified",
            )
        seen = set()
        for rule in rules:
            if not rule.get("id") or rule["id"] in seen:
                raise InvalidReference("Identifiant de règle absent ou dupliqué.")
            seen.add(rule["id"])
            scope = rule["scope"]
            _check_scope(scope)
            for kind in ("print", "market"):
                if rule[kind + "_coverage"] not in (
                    "complete",
                    "partial",
                    "provisional",
                ):
                    raise InvalidReference("Couverture inconnue.")
            proof(rule.get("evidence", []), "print", scope)
            if rule["print_coverage"] == "complete":
                proof(rule.get("closure_evidence", []), "closure", scope, True)
            if not isinstance(rule["prints"], list) or not rule["prints"]:
                raise InvalidReference("Règle sans impressions.")
            print_ids = set()
            for printing in rule["prints"]:
                if not printing.get("id") or printing["id"] in print_ids:
                    raise InvalidReference("Impression absente ou dupliquée.")
                print_ids.add(printing["id"])
                if printing.get("status") not in ("verified", "provisional"):
                    raise InvalidReference("Statut d’impression inconnu.")
                proof(
                    printing.get("evidence", []),
                    "print",
                    scope,
                    printing["status"] == "verified",
                )
                for field, accepted in printing.get("observations", {}).items():
                    if (
                        field not in OBSERVATIONS
                        or not isinstance(accepted, list)
                        or not accepted
                    ):
                        raise InvalidReference("Discriminant inconnu ou vide.")
                    if field == "finish" and not set(accepted) <= FINISHES:
                        raise InvalidReference("Finition inconnue.")
                    if field != "finish" and any(
                        v != "absent" and not v.startswith("present:") for v in accepted
                    ):
                        raise InvalidReference("Marque sans état explicite.")
                binding_id = printing.get("binding")
                if binding_id is not None and (
                    binding_id not in bindings
                    or not _contains(bindings[binding_id]["scope"], scope)
                ):
                    raise InvalidReference("Correspondance absente ou hors périmètre.")
            remainder = rule.get("remainder_binding")
            if remainder is not None:
                if (
                    remainder not in bindings
                    or bindings[remainder]["status"] != "verified"
                    or not _contains(bindings[remainder]["scope"], scope)
                ):
                    raise InvalidReference("Correspondance du reste inconnue.")
                proof(rule.get("remainder_evidence", []), "market", scope, True)
            for other in rules:
                if other is rule or other.get("id") in seen:
                    continue
                _check_scope(other["scope"])
                a, b = scope, other["scope"]
                common = (
                    set(
                        range(
                            max(a["numbers"][0], b["numbers"][0]),
                            min(a["numbers"][1], b["numbers"][1]) + 1,
                        )
                    )
                    - set(a.get("exclusions", []))
                    - set(b.get("exclusions", []))
                )
                if (
                    a["set_id"] == b["set_id"]
                    and set(a["languages"]) & set(b["languages"])
                    and common
                ):
                    if not rule.get("conflict_group") or rule.get(
                        "conflict_group"
                    ) != other.get("conflict_group"):
                        raise InvalidReference("Chevauchement de règles non déclaré.")
        # Sort unordered collections so file/list order never affects replay/hash.
        clean = json.loads(canonical(data))
        for item in list(clean["evidence"].values()) + list(clean["bindings"].values()):
            item["scope"]["languages"] = sorted(set(item["scope"]["languages"]))
            item["scope"]["exclusions"] = sorted(
                set(item["scope"].get("exclusions", []))
            )
            if "evidence" in item:
                item["evidence"] = sorted(set(item["evidence"]))
        clean["rules"].sort(key=lambda r: r["id"])
        for rule in clean["rules"]:
            rule["prints"].sort(key=lambda p: p["id"])
            for field in ("evidence", "closure_evidence", "remainder_evidence"):
                if field in rule:
                    rule[field] = sorted(set(rule[field]))
            rule["scope"]["languages"] = sorted(set(rule["scope"]["languages"]))
            rule["scope"]["exclusions"] = sorted(
                set(rule["scope"].get("exclusions", []))
            )
            for printing in rule["prints"]:
                printing["evidence"] = sorted(set(printing["evidence"]))
                printing["observations"] = {
                    k: sorted(set(v))
                    for k, v in printing.get("observations", {}).items()
                }
        content = canonical(clean)
        return Ruleset(content, hashlib.sha256(content.encode()).hexdigest())
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        if isinstance(exc, InvalidReference):
            raise
        raise InvalidReference(
            "Structure du référentiel invalide : " + str(exc)
        ) from exc


def load_ruleset(path=None):
    resource = (
        files("pokeprice").joinpath("reference/prints-v1.json")
        if path is None
        else path
    )
    try:

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise InvalidReference("Clé JSON dupliquée : " + key)
                result[key] = value
            return result

        return validate_ruleset(
            json.loads(resource.read_text(encoding="utf-8"), object_pairs_hook=unique)
        )
    except (OSError, ValueError) as exc:
        raise InvalidReference("Référentiel inutilisable : " + str(exc)) from exc


def copy_observations(card):
    """Legacy text is not an attestation that a mark is present or absent."""
    attested = bool(
        card.get("variant_confirmed")
        and card.get("variant_verified_by")
        and card.get("variant_verified_at")
    )
    result = {
        "finish": {
            "state": "present" if card.get("finish") else "unobserved",
            "value": card.get("finish", ""),
            "human": attested,
        }
    }
    provenance = json.loads(card.get("observation_provenance") or "{}")
    finish_record = provenance.get("finish", {})
    if finish_record:
        result["finish"]["human"] = bool(
            finish_record.get("actor")
            and finish_record.get("observed_at")
            and finish_record.get("origin") == "human"
            and finish_record.get("text") == card.get("finish", "")
        )
        result["finish"]["provenance"] = finish_record
    for field in ("stamp", "distribution"):
        record = provenance.get(field, {})
        result[field] = {
            "state": card.get(field + "_state", "unobserved"),
            "value": card.get(field, ""),
            "human": bool(
                record.get("actor")
                and record.get("observed_at")
                and record.get("origin", "human") == "human"
                and record.get("state") == card.get(field + "_state", "unobserved")
                and record.get("text") == card.get(field, "")
            ),
            "provenance": record,
        }
    return result


def _value(observation):
    if not observation.get("human") or observation.get("state") == "unobserved":
        return None
    if observation.get("state") == "absent":
        return "absent"
    if observation.get("state") == "present" and observation.get("value"):
        return "present:" + normalized(str(observation["value"]))
    return None


def resolve(
    identity,
    observations,
    ruleset,
    disputes=(),
    catalogue=None,
    available_documents=None,
):
    """Pure, deterministic candidate-set resolution; no inferred observations."""
    data = ruleset.data
    result = {
        "engine_version": ENGINE_VERSION,
        "rules_version": data["content_version"],
        "rules_hash": ruleset.hash,
        "print_status": "uncovered",
        "market_status": "uncovered",
        "candidate_print_ids": [],
        "unknown_remainder": True,
        "candidate_binding_keys": [],
        "candidates": [],
        "missing_print_observations": [],
        "missing_market_observations": [],
        "selected_binding_key": None,
        "provisional_binding_keys": [],
        "foil_projection": None,
        "pricing_eligible": False,
        "warnings": [],
        "conflicts": [],
        "reason_codes": [],
        "evidence_ids": [],
    }
    catalog_id = identity.get("catalog_id") or ""
    match = re.fullmatch(r"(.+)-(\d+)", catalog_id)
    active = []
    if match:
        set_id, number = match[1], int(match[2])
        printed = re.fullmatch(r"(\d+)(?:/\d+)?", identity.get("number") or "")
        if printed and int(printed[1]) != number:
            result.update(
                print_status="conflict",
                market_status="conflict",
                conflicts=[{"affects": "both", "reason": "identity_number_conflict"}],
                reason_codes=["identity_number_conflict"],
            )
            return result
        active = [
            r
            for r in data["rules"]
            if r["scope"]["set_id"] == set_id
            and identity.get("language") in r["scope"]["languages"]
            and r["scope"]["numbers"][0] <= number <= r["scope"]["numbers"][1]
            and number not in r["scope"].get("exclusions", [])
        ]
    strong_groups = {
        r.get("conflict_group")
        for r in active
        if r["print_coverage"] == "complete"
        and all(p["status"] == "verified" for p in r["prints"])
    } - {None}
    weaker = [
        r
        for r in active
        if r.get("conflict_group") in strong_groups
        and r["print_coverage"] == "provisional"
    ]
    if weaker:
        active = [r for r in active if r not in weaker]
        result["warnings"].append(
            {
                "code": "weaker_rule_disagreement",
                "rule_ids": sorted(r["id"] for r in weaker),
            }
        )
    values = {field: _value(observations.get(field, {})) for field in OBSERVATIONS}
    if values["finish"]:
        values["finish"] = values["finish"].removeprefix("present:")
    candidates = []
    requirements = {}
    for rule in active:
        for printing in rule["prints"]:
            requirements[rule["id"] + ":" + printing["id"]] = printing.get(
                "observations", {}
            )
            if any(
                values[field] is not None
                and values[field]
                not in [
                    v
                    if field == "finish" or v == "absent"
                    else "present:" + normalized(v.removeprefix("present:"))
                    for v in accepted
                ]
                for field, accepted in printing.get("observations", {}).items()
            ):
                continue
            binding = data["bindings"].get(printing.get("binding"))
            key = binding_key(binding) if binding else None
            candidates.append(
                {
                    "print_id": rule["id"] + ":" + printing["id"] + ":" + catalog_id,
                    "rule_id": rule["id"],
                    "local_print_id": printing["id"],
                    "print_status": printing["status"],
                    "binding_key": key,
                    "binding_status": binding["status"] if binding else "unmapped",
                    "foil_projection": binding.get("foil_projection")
                    if binding
                    else None,
                    "evidence_ids": sorted(
                        set(
                            printing["evidence"]
                            + (binding.get("evidence", []) if binding else [])
                        )
                    ),
                }
            )
    candidates.sort(key=lambda p: p["print_id"])
    unknown = not active or any(r["print_coverage"] != "complete" for r in active)
    result.update(
        candidates=candidates,
        candidate_print_ids=[p["print_id"] for p in candidates],
        unknown_remainder=unknown,
    )
    binding_keys = {p["binding_key"] for p in candidates if p["binding_key"]}
    remainder_keys = {
        binding_key(data["bindings"][r["remainder_binding"]])
        for r in active
        if r.get("remainder_binding")
    }
    if unknown:
        binding_keys.update(remainder_keys)
    result["candidate_binding_keys"] = sorted(binding_keys)
    result["provisional_binding_keys"] = sorted(
        {p["binding_key"] for p in candidates if p["binding_status"] == "provisional"}
    )
    result["evidence_ids"] = sorted(
        {i for p in candidates for i in p["evidence_ids"]}
        | {
            i
            for r in active
            for field in ("evidence", "closure_evidence", "remainder_evidence")
            for i in r.get(field, [])
        }
    )
    missing_print, missing_market = set(), set()
    for field in sorted(OBSERVATIONS):
        relevant = [
            (p, requirements[p["rule_id"] + ":" + p["local_print_id"]].get(field))
            for p in candidates
        ]
        if values[field] is not None or not any(v for _, v in relevant):
            continue
        if unknown or len({canonical(v) for _, v in relevant}) > 1:
            missing_print.add(field)
        if len({p["binding_key"] for p, _ in relevant}) > 1:
            missing_market.add(field)
    result["missing_print_observations"] = sorted(missing_print)
    result["missing_market_observations"] = sorted(missing_market)
    if not active or not candidates:
        result["reason_codes"].append(
            "scope_uncovered" if not active else "observation_uncovered"
        )
    elif unknown:
        result["print_status"] = "uncovered"
        result["reason_codes"].append("unknown_remainder")
    elif len(candidates) == 1 and candidates[0]["print_status"] == "verified":
        result["print_status"] = "identified"
    else:
        result["print_status"] = "unobserved" if missing_print else "candidates"
    closed_market = not unknown or (
        active
        and all(
            r["print_coverage"] == "complete" or r.get("remainder_binding")
            for r in active
        )
    )
    verified_market = bool(
        (candidates or (unknown and closed_market and remainder_keys))
        and closed_market
        and len(binding_keys) == 1
        and all(p["binding_status"] == "verified" for p in candidates)
        and all(r["market_coverage"] == "complete" for r in active)
    )
    if verified_market:
        result["market_status"] = "verified"
        result["selected_binding_key"] = next(iter(binding_keys))
        projections = {p["foil_projection"] for p in candidates}
        if unknown:
            projections.update(
                data["bindings"][r["remainder_binding"]].get("foil_projection")
                for r in active
                if r.get("remainder_binding")
            )
        result["foil_projection"] = projections.pop() if len(projections) == 1 else None
    elif not active or not candidates or not closed_market:
        result["market_status"] = "uncovered"
    elif any(p["binding_status"] == "unmapped" for p in candidates):
        result["market_status"] = "unmapped"
        result["reason_codes"].append("market_unmapped")
    elif missing_market:
        result["market_status"] = "unobserved"
    elif result["provisional_binding_keys"] or any(
        r["market_coverage"] != "complete" for r in active
    ):
        result["market_status"] = "provisional"
    else:
        result["market_status"] = "ambiguous"
    if missing_market:
        result["reason_codes"].append("market_observation_missing")
    strong = [
        r
        for r in active
        if r.get("conflict_group") and r["print_coverage"] == "complete"
    ]
    if len(strong) > 1:
        signatures = {
            canonical(
                sorted(
                    (p["local_print_id"], p["binding_key"])
                    for p in candidates
                    if p["rule_id"] == r["id"]
                )
            )
            for r in strong
        }
        if len(signatures) > 1:
            market_signatures = {
                canonical(
                    sorted(
                        {
                            p["binding_key"]
                            for p in candidates
                            if p["rule_id"] == r["id"]
                        },
                        key=lambda k: k or "",
                    )
                )
                for r in strong
            }
            result["conflicts"].append(
                {
                    "affects": "print"
                    if len(market_signatures) == 1 and verified_market
                    else "both",
                    "reason": "contradictory_rules",
                    "rule_ids": sorted(r["id"] for r in strong),
                }
            )
    for dispute in disputes:
        if (
            dispute.get("active")
            and dispute.get("actor")
            and dispute.get("reason")
            and dispute.get("created_at")
        ):
            result["conflicts"].append(
                {
                    "affects": dispute.get("affects", "both"),
                    "reason": "local_dispute",
                    "id": dispute.get("id"),
                }
            )
    result["conflicts"].sort(key=canonical)
    if any(c["affects"] in ("print", "both") for c in result["conflicts"]):
        result["print_status"] = "conflict"
    if any(c["affects"] in ("market", "both") for c in result["conflicts"]):
        result.update(
            market_status="conflict", selected_binding_key=None, foil_projection=None
        )
    if result["conflicts"]:
        result["reason_codes"].insert(0, "conflict")
    if catalogue:
        result["warnings"].append(
            {
                "code": "catalogue_advisory",
                "requested_language": catalogue.get("requested_language"),
                "served_language": catalogue.get("served_language"),
                "source": catalogue.get("source"),
            }
        )
    result["pricing_eligible"] = (
        result["market_status"] == "verified"
        and identity.get("identification_status") == "confirmed"
    )
    if available_documents is not None:
        missing = sorted(
            {data["evidence"][i]["document_sha256"] for i in result["evidence_ids"]}
            - set(available_documents)
        )
        if missing:
            result["warnings"].append(
                {"code": "proof_unavailable", "document_hashes": missing}
            )
            result["reason_codes"].append("proof_unavailable")
            if result["market_status"] == "verified":
                result.update(
                    market_status="provisional",
                    selected_binding_key=None,
                    foil_projection=None,
                    pricing_eligible=False,
                )
    if identity.get("identification_status") != "confirmed":
        result["reason_codes"].append("identity_unconfirmed")
    return result


def quote_selection(quote, resolution, previous_state="active"):
    """Compare full bindings. Suspensions and revocations never auto-resurrect."""
    if previous_state in ("revoked", "suspended"):
        return {
            "state": previous_state,
            "reason": "explicit_restoration_required",
            "quote": quote,
        }
    if not quote:
        return {"state": "missing", "reason": "no_quote", "quote": None}
    if not quote.get("binding_key"):
        return {
            "state": "legacy_manual"
            if quote.get("metric") == "manual_reference"
            else "legacy_unbound",
            "reason": "binding_unproved",
            "quote": quote,
        }
    if (
        not resolution["pricing_eligible"]
        or quote["binding_key"] != resolution["selected_binding_key"]
    ):
        return {"state": "suspended", "reason": "binding_incompatible", "quote": quote}
    return {"state": "active", "reason": "binding_compatible", "quote": quote}


def prudent_quote(quotes, binding, resolution):
    """Only EUR trend and avg30 from one compatible acquisition can be combined."""
    key = binding_key(binding)
    if (
        binding["currency"] != "EUR"
        or not resolution["pricing_eligible"]
        or resolution["selected_binding_key"] != key
    ):
        return None
    groups = {}
    for quote in quotes:
        acquisition = quote.get("acquisition_id")
        if (
            quote.get("binding_key") != key
            or quote.get("currency") != "EUR"
            or not acquisition
            or quote.get("population") != binding["population"]
            or quote.get("metric") not in ("trend", "avg30")
            or type(quote.get("amount_cents")) is not int
            or quote["amount_cents"] < 0
        ):
            continue
        acquisition_key = (
            acquisition,
            quote.get("source"),
            quote.get("observed_at"),
            quote.get("source_date"),
            canonical(quote.get("acquisition", {})),
        )
        groups.setdefault(acquisition_key, {}).setdefault(quote["metric"], []).append(
            quote
        )
    complete = [
        metrics
        for metrics in groups.values()
        if set(metrics) == {"trend", "avg30"}
        and all(len(v) == 1 for v in metrics.values())
    ]
    # Selecting between different dated acquisitions is a separate, audited action.
    if len(complete) != 1:
        return None
    return min(complete[0][metric][0]["amount_cents"] for metric in ("trend", "avg30"))
