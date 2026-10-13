import copy

import pytest
from fastapi.testclient import TestClient
from test_pricing import CARD, confirmed
from test_valuation import card

from pokeprice.inventory import Store
from pokeprice.market_product import neighbours, set_code_from
from pokeprice.pricing import summarize
from pokeprice.valuation import assess
from pokeprice.webapp import create_app

# Shape of TCGdex on 13 October 2026: dp4-3 Darkrai Lv.38 and dp4-4 Darkrai
# Lv.40 both carried idProduct 277905 (the Lv.38 on Cardmarket).
NEIGHBOURS = {
    "cards/swsh7-076": {
        "name": "Pumpkaboo",
        "hp": 60,
        "pricing": {"cardmarket": {"idProduct": 277048}},
    },
    "cards/swsh7-078": {"name": "Other", "pricing": {"cardmarket": {"idProduct": 1}}},
    "sets/swsh7": {"abbreviation": {"official": "EVS"}},
}


@pytest.mark.parametrize(
    "catalog_id, expected",
    [
        ("dp4-4", ["dp4-3", "dp4-5"]),
        ("swsh7-077", ["swsh7-076", "swsh7-078"]),
        ("dpp-DP19", ["dpp-DP18", "dpp-DP20"]),
        ("np-1", ["np-2"]),
        ("invalid", []),
        (None, []),
    ],
)
def test_neighbours_keep_prefix_and_padding(catalog_id, expected):
    assert neighbours(catalog_id) == expected


def test_set_code_prefers_the_printed_abbreviation():
    assert (
        set_code_from({"abbreviation": {"official": "GE"}, "tcgOnline": "GE"}) == "GE"
    )
    assert set_code_from({"tcgOnline": "PR-NP"}) == "NP"
    assert set_code_from({"tcgOnline": "HS"}) is None
    assert set_code_from(None) is None


def test_a_verdict_on_another_product_no_longer_applies():
    snapshot = summarize(CARD, False)
    verdict = {"catalog_id": CARD["id"], "id_product": 1, "verdict": "wrong"}
    result = assess(card(), snapshot, market_verdict=verdict)
    assert result["prudent_cents"] == 625
    assert result["market_product"] == {
        "id_product": 277048,
        "verdict": "",
        "shared_with": [],
    }


@pytest.fixture
def client(tmp_path):
    calls = []

    def fetch(catalog_id, language):
        data = copy.deepcopy(CARD)
        data["id"] = catalog_id
        return data

    def market(path):
        calls.append(path)
        return NEIGHBOURS[path]

    store = Store(tmp_path / "inventory")
    app = create_app(store.root, price_fetch=fetch, market_fetch=market)
    with TestClient(app) as client:
        client.post(
            "/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}
        )
        client.post("/api/albums", json={"name": "Test"})
        client.calls = calls
        yield client


def refresh(client, copy):
    response = client.post(
        f"/api/copies/{copy['id']}/price-refresh",
        json={"expected_version": copy["version"]},
    )
    return response


def judge(client, copy, verdict, reason="Page Cardmarket : Lv.38, carte Lv.40"):
    return client.post(
        f"/api/copies/{copy['id']}/market-product",
        json={
            "expected_version": copy["version"],
            "verdict": verdict,
            "reason": reason,
        },
    )


def detail(client, copy):
    return client.get(f"/api/copies/{copy['id']}").json()


def test_shared_product_is_flagged_then_rejected_for_a_manual_price(client):
    copy_ = confirmed(client, name="Gourgeist")
    response = refresh(client, copy_)
    assert response.status_code == 200, response.text
    shared = [{"catalog_id": "swsh7-076", "name": "Pumpkaboo", "hp": 60}]
    assert response.json()["price_snapshot"]["shared_product_with"] == shared
    copy_ = detail(client, copy_)
    assert copy_["valuation"]["market_product"]["shared_with"] == shared
    labels = {r["code"]: r["label"] for r in copy_["valuation"]["reasons"]}
    # English names mislead (Airmure is Skarmory): number and HP come first.
    assert "n° 076 (Pumpkaboo en anglais, 60 PV)" in labels["market_product"]
    assert "votre n° 077" in labels["market_product"]
    assert copy_["cardmarket_url"]
    assert copy_["cardmarket_search_url"].endswith("searchString=Gourgeist+EVS+077")
    # Neighbours and set code are cached: a second refresh asks nothing more.
    assert refresh(client, copy_).status_code == 200
    assert sorted(client.calls) == sorted(NEIGHBOURS)

    assert judge(client, copy_, "wrong", reason="").status_code == 422
    response = judge(client, detail(client, copy_), "wrong")
    assert response.status_code == 200, response.text
    assert response.json()["reference_cents"] is None
    copy_ = detail(client, copy_)
    value = copy_["valuation"]
    assert value["market_product"]["verdict"] == "wrong"
    assert value["prudent_cents"] is None
    assert {r["code"] for r in value["reasons"]} == {"missing_price"}
    assert copy_["cardmarket_url"] is None and copy_["cardmarket_search_url"]
    blocked = refresh(client, copy_)
    assert (
        blocked.status_code == 422 and "signalé incorrect" in blocked.json()["detail"]
    )

    response = client.patch(
        f"/api/copies/{copy_['id']}",
        json={
            "expected_version": copy_["version"],
            "reason": "Tendance relevée sur la bonne page",
            "reference_price_eur": 31.59,
            "price_source": "Cardmarket · Darkrai Lv.40 (GE 4) · tendance",
        },
    )
    assert response.status_code == 200, response.text
    value = detail(client, copy_)["valuation"]
    assert value["prudent_cents"] == 3159 and value["manual_price"]
    assert value["market_product"]["verdict"] == "wrong"


def test_verified_product_closes_the_doubt(client):
    copy_ = confirmed(client, name="Gourgeist")
    refresh(client, copy_)
    response = judge(client, detail(client, copy_), "verified", reason="Page conforme")
    assert response.status_code == 200, response.text
    value = detail(client, copy_)["valuation"]
    assert value["market_product"] == {
        "id_product": 277048,
        "verdict": "verified",
        "shared_with": [],
    }
    assert "market_product" not in {r["code"] for r in value["reasons"]}
    assert value["prudent_cents"] == 625


def test_a_product_can_only_be_judged_after_a_refresh(client):
    copy_ = confirmed(client, name="Gourgeist")
    response = judge(client, copy_, "wrong")
    assert (
        response.status_code == 422 and "Relevez d’abord" in response.json()["detail"]
    )
