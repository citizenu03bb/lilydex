"""Synthetic session scenarios across operator approval and delegated HTTP writes.

These cases exercise the software contract, not model compliance with the skill.
"""

import copy
import json
from pathlib import Path

import pytest
import test_agent_corrections

from pokeprice.agent_corrections import CorrectionService
from pokeprice.inventory import Conflict

PREFIX = "/api/agent/v1"
CASES = json.loads(
    (Path(__file__).parent / "fixtures/agent_pricing_cases.json").read_text()
)["cases"]


@pytest.fixture
def shop(tmp_path):
    yield from test_agent_corrections.shop.__wrapped__(tmp_path)


def configure(shop, case):
    _client, agents, _grant, cards, _other, _user = shop
    card = agents.store.patch(
        cards[0]["id"],
        {**case["copy"], "variant_confirmed": True},
        cards[0]["version"],
        "owner",
        "Synthetic scenario setup",
    )
    if "existing_reference_cents" in case:
        card = agents.store.patch(
            card["id"],
            {
                "reference_cents": case["existing_reference_cents"],
                "price_source": "Référence humaine synthétique",
                "price_date": "2026-01-01",
            },
            card["version"],
            "owner",
            "Synthetic existing reference",
        )
    return card


def source(case):
    fixture = case["catalogue"]
    number, total = fixture["number"].split("/")
    data = test_agent_corrections.native(fixture["id"], "fr")
    data.update(name=fixture["name"], hp=fixture["hp"], localId=number)
    data["set"] = {"name": "Édition de test", "cardCount": {"official": int(total)}}
    quote = fixture["quote_eur"]
    data["pricing"] = (
        {"cardmarket": {"unit": "EUR", "trend": quote, "updated": "2026-01-01"}}
        if quote is not None
        else {}
    )
    return data


def snapshot(store):
    with store.connect() as db:
        return {
            table: [
                dict(r) for r in db.execute(f"SELECT * FROM {table} ORDER BY rowid")
            ]
            for table in (
                "copies",
                "events",
                "prices",
                "agent_corrections",
                "listings",
                "sales",
            )
        }


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_session_case_through_operator_approval_and_agent_api(shop, case):
    client, agents, grant, _cards, other, _user = shop
    card = configure(shop, case)
    original = snapshot(agents.store)
    fetched = []

    def fetch(ident, language):
        assert ident == case["catalogue"]["id"] and language == "fr"
        fetched.append((ident, language))
        return copy.deepcopy(source(case))

    request = {
        "id": card["id"],
        "expected_version": card["version"],
        "catalog_id": case["catalogue"]["id"],
        "refresh_price": case.get("refresh_price", True),
    }
    outcome = case["expected"]["outcome"]
    if outcome in {"invalid_plan", "invalid_identity", "existing_reference"}:
        error = Conflict if outcome == "existing_reference" else ValueError
        with pytest.raises(error):
            CorrectionService(agents.store, fetch=fetch).approve(
                grant["id"], [request], "Synthetic explicit approval"
            )
        assert snapshot(agents.store) == original
        assert len(fetched) == (1 if outcome == "invalid_identity" else 0)
        return

    plan = CorrectionService(agents.store, fetch=fetch).approve(
        grant["id"], [request], "Synthetic explicit approval"
    )[0]
    approved = snapshot(agents.store)
    assert {k: v for k, v in approved.items() if k != "agent_corrections"} == {
        k: v for k, v in original.items() if k != "agent_corrections"
    }
    assert len(fetched) == 1
    exposed = client.get(PREFIX + "/corrections").json()["items"]
    assert len(exposed) == 1 and exposed[0]["id"] == card["id"]
    assert exposed[0]["changes"] == plan["changes"]
    body = {k: plan[k] for k in ("expected_version", "approval_sha256")}
    endpoint = PREFIX + "/copies/" + card["id"] + "/apply-correction"
    if outcome == "stale":
        human = agents.store.patch(
            card["id"],
            case["concurrent_changes"],
            card["version"],
            "owner",
            "Synthetic newer human observation",
        )
        changed = snapshot(agents.store)
        assert client.post(endpoint, json=body).status_code == 409
        assert snapshot(agents.store) == changed
        reread = client.get(PREFIX + "/copies/" + card["id"]).json()
        assert reread["version"] == human["version"]
        assert reread["stamp_state"] == "unobserved"
        assert not reread["variant_confirmed"]
        return

    response = client.post(endpoint, json=body)
    assert response.status_code == 200, response.text
    receipt = response.json()
    reread = client.get(PREFIX + "/copies/" + card["id"]).json()
    assert reread["reference_cents"] == case["expected"]["reference_cents"]
    assert reread["catalog_id"] == case["catalogue"]["id"]
    assert reread["name"] == card["name"] and reread["number"] == card["number"]
    assert reread["version"] == card["version"] + 1
    assert receipt["agent_id"] == grant["id"]
    assert not receipt["physical_confirmation_created"]
    with agents.store.connect() as db:
        after = agents.store.get(db, card["id"])
        assert agents.store.get(db, other["id"]) == other
        events = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM events WHERE actor=?", ("agent:" + grant["id"],)
            )
        ]
    for key in (
        "condition",
        "condition_confirmed",
        "finish",
        "stamp_state",
        "distribution_state",
        "observation_provenance",
        "stock_state",
        "notes",
    ):
        assert after[key] == card[key], key
    if card["catalog_id"] is None:
        assert not after["variant_confirmed"] and not after["variant_verified_by"]
    else:
        assert after["variant_confirmed"] == card["variant_confirmed"]
        assert after["variant_verified_by"] == card["variant_verified_by"]
    priced = case["expected"]["reference_cents"] is not None
    assert sum(e["kind"] == "price-snapshot" for e in events) == int(priced)
    if priced:
        assert after["price_source"] == "TCGdex · Cardmarket trend"
        assert after["price_date"] == "2026-01-01"
    else:
        assert after["price_source"] == after["price_date"] == ""
        assert plan["price_status"] == "unavailable_or_not_authorized"
    applied = snapshot(agents.store)
    assert client.post(endpoint, json=body).json() == receipt
    assert snapshot(agents.store) == applied
