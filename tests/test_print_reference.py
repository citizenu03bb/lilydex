"""Contract behavior with synthetic claims, never evidence about real cards."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from pokeprice.print_reference import (
    InvalidReference,
    binding_key,
    copy_observations,
    load_ruleset,
    prudent_quote,
    quote_selection,
    resolve,
    validate_ruleset,
)

SOURCE_DOCUMENT = b"Synthetic source archive, no Pokemon facts"


def reference_data():
    scope = {"set_id": "synthetic", "languages": ["fr"], "numbers": [1, 1]}

    def claim(kind):
        return {
            "kind": kind,
            "status": "verified",
            "scope": scope,
            "claim": "Synthetic test fixture only",
            "source": "fixture:test",
            "accessed_at": "2026-01-01",
            "document_sha256": hashlib.sha256(SOURCE_DOCUMENT).hexdigest(),
        }

    binding = {
        "market": "fixture",
        "product_ref": "fixture:product-A",
        "native_variant": {"code": "parallel-holo"},
        "filters": {"none": True},
        "metric_family": {
            "id": "fixture-eur-holo",
            "version": 1,
            "metrics": {"trend": "trend-holo", "avg30": "avg30-holo"},
        },
        "currency": "EUR",
        "population": {"language": "aggregate", "condition": "aggregate"},
        "status": "verified",
        "scope": scope,
        "foil_projection": True,
        "evidence": ["market"],
    }
    return {
        "schema_version": 1,
        "content_version": "test.1",
        "evidence": {kind: claim(kind) for kind in ("print", "market", "closure")},
        "bindings": {
            "A": binding,
            "B": {**binding, "product_ref": "fixture:product-B"},
        },
        "rules": [
            {
                "id": "test",
                "scope": scope,
                "print_coverage": "complete",
                "market_coverage": "complete",
                "evidence": ["print"],
                "closure_evidence": ["closure"],
                "prints": [
                    {
                        "id": "plain",
                        "status": "verified",
                        "observations": {"stamp": ["absent"]},
                        "binding": "A",
                        "evidence": ["print"],
                    },
                    {
                        "id": "marked",
                        "status": "verified",
                        "observations": {"stamp": ["present:EX Test", "present:Test"]},
                        "binding": "B",
                        "evidence": ["print"],
                    },
                ],
            }
        ],
    }


@pytest.fixture
def reference():
    return reference_data()


def decision(reference, observations=None, **kwargs):
    identity = kwargs.pop(
        "identity",
        {
            "catalog_id": "synthetic-1",
            "language": "fr",
            "number": "1/1",
            "identification_status": "confirmed",
        },
    )
    return resolve(identity, observations or {}, validate_ruleset(reference), **kwargs)


def absent():
    return {"stamp": {"state": "absent", "human": True}}


def quote(reference, binding="A", metric="trend", amount=1200, acquisition="batch-A"):
    return {
        "id": "quote-1",
        "binding_key": binding_key(reference["bindings"][binding]),
        "metric": metric,
        "amount_cents": amount,
        "currency": "EUR",
        "source": "fixture:test",
        "observed_at": "2025-05-01",
        "population": reference["bindings"][binding]["population"],
        "acquisition_id": acquisition,
    }


def test_c01_finish_clarification_preserves_bound_quote(reference):
    before = quote(reference)
    result = decision(
        reference,
        {**absent(), "finish": {"state": "present", "value": "holo", "human": True}},
    )
    assert quote_selection(before, result) == {
        "state": "active",
        "reason": "binding_compatible",
        "quote": before,
    }
    assert before["observed_at"] == "2025-05-01"


def test_c02_stamp_alias_preserves_original_observation_and_quote(reference):
    observations = {"stamp": {"state": "present", "value": "EX TEST", "human": True}}
    before = copy.deepcopy(observations)
    first = decision(reference, observations)
    second = decision(
        reference, {"stamp": {"state": "present", "value": "Test", "human": True}}
    )
    assert first["selected_binding_key"] == second["selected_binding_key"]
    assert quote_selection(quote(reference, "B"), second)["state"] == "active"
    assert observations == before


def test_c03_same_foil_different_product_suspends(reference):
    old = quote(reference)
    result = decision(
        reference, {"stamp": {"state": "present", "value": "Test", "human": True}}
    )
    assert result["foil_projection"] is True
    assert quote_selection(old, result)["state"] == "suspended"
    assert old["amount_cents"] == 1200


def test_c04_ambiguous_prints_can_share_verified_market(reference):
    reference["rules"][0]["prints"][1]["binding"] = "A"
    result = decision(reference)
    assert result["print_status"] == "unobserved"
    assert len(result["candidate_print_ids"]) == 2
    assert result["market_status"] == "verified" and result["pricing_eligible"]


def test_c05_missing_discriminant_prevents_price_but_keeps_candidates(reference):
    result = decision(reference)
    assert result["market_status"] == "unobserved"
    assert result["missing_market_observations"] == ["stamp"]
    assert not result["pricing_eligible"] and result["selected_binding_key"] is None


def test_c06_partial_singleton_cannot_certify(reference):
    reference["rules"][0]["print_coverage"] = "partial"
    result = decision(reference, absent())
    assert len(result["candidate_print_ids"]) == 1 and result["unknown_remainder"]
    assert not result["pricing_eligible"]


def test_remainder_with_explicit_common_market_proof(reference):
    rule = reference["rules"][0]
    rule.update(
        print_coverage="partial", remainder_binding="A", remainder_evidence=["market"]
    )
    result = decision(reference, absent())
    assert result["unknown_remainder"] and result["market_status"] == "verified"


@pytest.mark.parametrize("language,number", [("en", 1), ("it", 1), ("fr", 2)])
def test_c07_outside_scope_not_extrapolated(reference, language, number):
    result = decision(
        reference,
        absent(),
        identity={
            "catalog_id": f"synthetic-{number}",
            "language": language,
            "identification_status": "confirmed",
        },
    )
    assert result["market_status"] == "uncovered" and not result["pricing_eligible"]


def test_ai_observation_cannot_eliminate(reference):
    result = decision(reference, {"stamp": {"state": "absent", "human": False}})
    assert len(result["candidate_print_ids"]) == 2 and not result["pricing_eligible"]


def test_common_binding_proof_can_cover_an_unclassified_print(reference):
    rule = reference["rules"][0]
    rule.update(
        print_coverage="partial", remainder_binding="A", remainder_evidence=["market"]
    )
    result = decision(
        reference,
        {"stamp": {"state": "present", "value": "Unlisted stamp", "human": True}},
    )
    assert not result["candidate_print_ids"] and result["unknown_remainder"]
    assert (
        result["print_status"] == "uncovered" and result["market_status"] == "verified"
    )
    assert result["foil_projection"] is True and result["pricing_eligible"]


def test_c09_catalogue_advisory_does_not_mask_verified_rule(reference):
    local = decision(reference, absent())
    remote = decision(
        reference,
        absent(),
        catalogue={
            "source": "fixture:catalogue",
            "variants": {"normal": True},
            "requested_language": "fr",
            "served_language": "en",
        },
    )
    assert (
        remote["selected_binding_key"] == local["selected_binding_key"]
        and remote["pricing_eligible"]
    )
    assert remote["warnings"][0]["served_language"] == "en"


def test_c10_equal_strong_proofs_conflict(reference):
    rule = reference["rules"][0]
    rule["conflict_group"] = "same-scope"
    other = copy.deepcopy(rule)
    other["id"] = "other"
    other["prints"][0]["binding"] = "B"
    reference["rules"].append(other)
    result = decision(reference, absent())
    assert (
        result["market_status"] == "conflict" and result["selected_binding_key"] is None
    )
    assert quote_selection(quote(reference), result)["state"] == "suspended"


def test_c10_local_dispute_suspends_without_rewriting_observations(reference):
    observations = absent()
    original = copy.deepcopy(observations)
    result = decision(
        reference,
        observations,
        disputes=[
            {
                "id": "dispute-1",
                "active": True,
                "affects": "market",
                "actor": "pat",
                "reason": "Different product",
                "created_at": "2026-01-01",
            }
        ],
    )
    assert (
        result["print_status"] == "identified" and result["market_status"] == "conflict"
    )
    assert observations == original


def test_print_only_dispute_keeps_proved_common_price(reference):
    result = decision(
        reference,
        absent(),
        disputes=[
            {
                "active": True,
                "affects": "print",
                "actor": "pat",
                "reason": "Print label",
                "created_at": "2026-01-01",
            }
        ],
    )
    assert result["print_status"] == "conflict" and result["pricing_eligible"]


def test_c11_identified_print_without_market_mapping(reference):
    reference["rules"][0]["prints"][0]["binding"] = None
    result = decision(reference, absent())
    assert (
        result["print_status"] == "identified" and result["market_status"] == "unmapped"
    )
    assert result["selected_binding_key"] is None


def test_c12_manual_reference_is_not_trend(reference):
    result = decision(reference, absent())
    assert (
        prudent_quote(
            [quote(reference, metric="manual_reference")],
            reference["bindings"]["A"],
            result,
        )
        is None
    )


def test_c13_rule_version_and_display_label_do_not_change_binding(reference):
    old = quote(reference)
    reference["content_version"] = "test.2"
    reference["bindings"]["A"]["label"] = "New label"
    assert quote_selection(old, decision(reference, absent()))["state"] == "active"
    reference["bindings"]["A"]["population"] = {
        "language": "fr",
        "condition": "aggregate",
    }
    assert quote_selection(old, decision(reference, absent()))["state"] == "suspended"


def test_c14_legacy_text_not_new_attestation(reference):
    card = {
        "stamp": "EX Test",
        "finish": "holo",
        "variant_confirmed": True,
        "variant_verified_by": "pat",
        "variant_verified_at": "2026-01-01",
    }
    observations = copy_observations(card)
    assert (
        observations["stamp"]["state"] == "unobserved"
        and not observations["stamp"]["human"]
    )
    old = {**quote(reference), "binding_key": None}
    assert (
        quote_selection(old, decision(reference, absent()))["state"] == "legacy_unbound"
    )


def test_c15_no_automatic_resurrection(reference):
    result = decision(reference, absent())
    assert quote_selection(quote(reference), result, "revoked")["state"] == "revoked"
    assert (
        quote_selection(quote(reference), result, "suspended")["state"] == "suspended"
    )


def test_c17_packaged_rules_valid_and_incomplete_by_design():
    rules = load_ruleset()
    assert len(rules.data["families"]) == 8 and len(rules.data["rules"]) == 5
    assert not rules.data["bindings"]
    result = resolve(
        {
            "catalog_id": "ex8-54",
            "language": "it",
            "identification_status": "confirmed",
        },
        {},
        rules,
    )
    assert not result["pricing_eligible"] and result["market_status"] == "uncovered"


def test_c18_canonical_order_and_no_clock(reference):
    original = decision(reference)
    reference["rules"][0]["prints"].reverse()
    reference["rules"][0]["prints"][0]["observations"]["stamp"].reverse()
    assert decision(reference) == original


@pytest.mark.parametrize(
    "mismatch",
    [
        "currency",
        "population",
        "acquisition_id",
        "binding_key",
        "observed_at",
        "source",
    ],
)
def test_c19_no_metric_mixing(reference, mismatch):
    result = decision(reference, absent())
    trend = quote(reference)
    average = quote(reference, metric="avg30", amount=900)
    assert prudent_quote([trend, average], reference["bindings"]["A"], result) == 900
    average[mismatch] = {"language": "en"} if mismatch == "population" else "other"
    assert prudent_quote([trend, average], reference["bindings"]["A"], result) is None


@pytest.mark.parametrize(
    "mutation",
    [
        "overlap",
        "null_dimension",
        "unknown_evidence",
        "outside_scope",
        "no_closure",
        "unknown_mark",
    ],
)
def test_invalid_reference_never_selects_by_file_order(reference, mutation):
    if mutation == "overlap":
        other = copy.deepcopy(reference["rules"][0])
        other["id"] = "other"
        reference["rules"].append(other)
    elif mutation == "null_dimension":
        reference["bindings"]["A"]["filters"] = {"reverse": None}
    elif mutation == "unknown_evidence":
        reference["bindings"]["A"]["evidence"] = ["missing"]
    elif mutation == "outside_scope":
        reference["bindings"]["A"]["scope"] = {
            **reference["bindings"]["A"]["scope"],
            "languages": ["en"],
        }
    elif mutation == "no_closure":
        reference["rules"][0]["closure_evidence"] = []
    else:
        reference["rules"][0]["prints"][0]["observations"] = {"stamp": ["unobserved"]}
    with pytest.raises(InvalidReference):
        validate_ruleset(reference)


def test_invalid_pack_gives_diagnostic(tmp_path):
    path = Path(tmp_path) / "invalid.json"
    path.write_text(json.dumps({"schema_version": 900}))
    with pytest.raises(InvalidReference, match="inutilisable"):
        load_ruleset(path)


def test_c18_language_scope_order_and_binding_filter_order(reference):
    for item in (
        list(reference["evidence"].values())
        + list(reference["bindings"].values())
        + reference["rules"]
    ):
        item["scope"]["languages"] = ["en", "fr"]
    original = decision(reference)
    reference = json.loads(json.dumps(reference))
    for item in (
        list(reference["evidence"].values())
        + list(reference["bindings"].values())
        + reference["rules"]
    ):
        item["scope"]["languages"].reverse()
    assert decision(reference) == original
    first = reference["bindings"]["A"]
    first["population"]["languages"] = ["fr", "it"]
    key = binding_key(first)
    first["population"]["languages"].reverse()
    assert binding_key(first) == key


def test_missing_source_archive_prevents_new_verified_price(reference):
    result = decision(reference, absent(), available_documents=[])
    assert result["market_status"] == "provisional" and not result["pricing_eligible"]
    assert "proof_unavailable" in result["reason_codes"]


def test_duplicate_json_keys_are_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version":1,"schema_version":2}')
    with pytest.raises(InvalidReference, match="dupliquée"):
        load_ruleset(path)


def test_partial_list_keeps_documented_candidates_instead_of_uncovered(reference):
    reference["rules"][0]["print_coverage"] = "partial"
    reference["rules"][0].pop("closure_evidence")
    result = decision(reference, absent())
    assert result["print_status"] == "candidates" and result["unknown_remainder"]
    assert "unknown_remainder" in result["reason_codes"]
    assert decision(reference)["print_status"] == "unobserved"


def test_legacy_global_attestation_covers_the_finish_only_and_says_so():
    card = {
        "finish": "holo",
        "stamp": "Old text",
        "stamp_state": "present",
        "variant_confirmed": True,
        "variant_verified_by": "pat",
        "variant_verified_at": "2026-10-12T10:00:00Z",
    }
    observations = copy_observations(card)
    assert observations["finish"]["human"]
    assert observations["finish"]["attestation"] == "legacy_global"
    assert not observations["stamp"]["human"]
    assert observations["stamp"]["attestation"] is None
    assert not copy_observations({**card, "finish": ""})["finish"]["human"]


def test_language_extension_needs_evidence_scoped_to_that_language(reference):
    # An EN rule never covers FR implicitly; an FR scope needs FR-scoped proof.
    for item in list(reference["evidence"].values()) + list(
        reference["bindings"].values()
    ):
        item["scope"] = {**item["scope"], "languages": ["en"]}
    reference["rules"][0]["scope"] = {
        **reference["rules"][0]["scope"],
        "languages": ["en", "fr"],
    }
    with pytest.raises(InvalidReference, match="hors périmètre"):
        validate_ruleset(reference)


def test_engine_matches_its_golden_vectors():
    from pokeprice.print_reference import ENGINE_VERSION

    vectors = json.loads(
        (Path(__file__).parent / "fixtures" / "engine_vectors.json").read_text()
    )
    # A semantic change needs a new ENGINE_VERSION and new vectors.
    assert vectors["engine_version"] == ENGINE_VERSION
    rulesets = {k: validate_ruleset(v) for k, v in vectors["rulesets"].items()}
    for case in vectors["cases"]:
        result = resolve(
            case["identity"],
            case["observations"],
            rulesets[case["ruleset"]],
            case["disputes"],
        )
        assert result == case["expected"], case["name"]


def test_engine_source_is_registered_for_its_version():
    from pokeprice.print_reference import ENGINE_VERSION
    from pokeprice.reference_service import ENGINE_SOURCES, engine_digest

    assert engine_digest() in ENGINE_SOURCES[ENGINE_VERSION], (
        "print_reference.py a changé. Si les vecteurs passent sans changement de "
        "sémantique, ajoutez cette empreinte à ENGINE_SOURCES ; sinon, créez une "
        "nouvelle ENGINE_VERSION et ses vecteurs : " + engine_digest()
    )
