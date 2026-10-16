import copy

import pytest
from fastapi.testclient import TestClient
from test_intake import values
from test_pricing import CARD

from pokeprice.pricing import summarize
from pokeprice.valuation import amount, assess, totals
from pokeprice.webapp import create_app


def card(**overrides):
    return {
        "catalog_id": "swsh7-077",
        "name": "Gourgeist",
        "set_name": "Evolving Skies",
        "number": "077/203",
        "language": "en",
        "identification_status": "confirmed",
        "foil": False,
        "stamp": "",
        "condition": "PL",
        "condition_confirmed": False,
        "price_date": "2026-10-07",
        **overrides,
    }


def test_prudent_value_uses_30_days_and_risk_uses_the_other_variant():
    result = assess(card(), summarize(CARD, False))
    assert result["trend_cents"] == 625
    assert result["prudent_cents"] == 625
    assert result["risk_cents"] == 14015  # min(429.97, 140.15), not avg1=1450.
    assert {r["code"] for r in result["reasons"]} >= {
        "value",
        "variant_premium",
        "condition",
    }
    assert result["market_unstable"]
    assert (
        assess(card(), summarize(CARD, False), threshold_cents=14016)["needs_review"]
        is False
    )
    assert (
        assess(card(), summarize(CARD, False), threshold_cents=14015)["needs_review"]
        is True
    )


@pytest.mark.parametrize(
    "value", [None, True, False, "4.20", -1, float("nan"), float("inf")]
)
def test_invalid_or_absent_quote_stays_unknown(value):
    assert amount(value) is None


def test_zero_is_a_real_quote_but_a_single_metric_is_not_prudent():
    snapshot = {
        "catalog_id": "swsh7-077",
        "raw": {"cardmarket": {"trend": 0, "avg30": 0}},
    }
    result = assess(card(), snapshot)
    assert result["prudent_cents"] == result["risk_cents"] == 0
    assert result["needs_review"] is False
    snapshot["raw"]["cardmarket"] = {"trend": 42, "avg30": None}
    result = assess(card(), snapshot)
    assert result["prudent_cents"] is None and result["risk_cents"] is None
    assert result["needs_review"] and result["risk_incomplete"]
    summary = totals([{"valuation": result}])
    assert summary["prudent_cents"] is None and summary["prudent_missing"] == 1
    assert summary["trend_cents"] == 4200 and summary["trend_known"] == 1


def test_uncertain_candidate_prices_never_become_collection_value():
    candidates = [{"id": CARD["id"], "price_snapshot": summarize(CARD, False)}]
    result = assess(
        card(catalog_id=None, identification_status="review", price_date=""),
        candidates=candidates,
    )
    assert result["risk_cents"] == 14015
    assert result["trend_cents"] is None and result["prudent_cents"] is None
    assert {r["code"] for r in result["reasons"]} >= {"identity", "value"}
    candidates.append({"id": "unknown-price"})
    assert assess(card(identification_status="review"), candidates=candidates)[
        "risk_incomplete"
    ]


@pytest.mark.parametrize(
    "overrides",
    [
        {"price_date": ""},
        {"catalog_id": "different"},
        {"identification_status": "review"},
    ],
)
def test_an_invalidated_price_snapshot_is_not_revived(overrides):
    result = assess(card(**overrides), summarize(CARD, False))
    assert result["trend_cents"] is None and result["prudent_cents"] is None
    assert result["needs_review"]


def test_non_eur_quotes_are_not_summed_as_euros():
    snapshot = summarize(copy.deepcopy(CARD), False)
    snapshot["raw"]["cardmarket"]["unit"] = "USD"
    assert assess(card(), snapshot)["prudent_cents"] is None


def test_known_reverse_with_no_quotes_cannot_silently_go_to_bulk():
    snapshot = {
        "catalog_id": "swsh7-077",
        "variants": {"normal": True, "reverse": True},
        "raw": {"cardmarket": {"trend": 1, "avg30": 0.5}},
    }
    result = assess(card(), snapshot)
    assert result["risk_cents"] == 50
    assert result["needs_review"] and result["risk_incomplete"]


def test_a_candidate_snapshot_must_match_its_catalogue_id():
    result = assess(
        card(identification_status="review"),
        candidates=[{"id": "different", "price_snapshot": summarize(CARD, False)}],
    )
    assert result["risk_cents"] is None and result["risk_incomplete"]


@pytest.mark.parametrize("raw", ["invalid", {"cardmarket": [1, 2]}])
def test_malformed_catalogue_prices_remain_unknown(raw):
    result = assess(card(), {"catalog_id": CARD["id"], "raw": raw})
    assert result["prudent_cents"] is None and result["needs_review"]


def test_malformed_variant_metadata_does_not_hide_known_price_risk():
    snapshot = summarize(CARD, False)
    snapshot["variants"] = ["invalid"]
    assert assess(card(), snapshot)["risk_cents"] == 14015


def test_physical_verification_closes_review_without_hiding_valuable_or_unstable_market():
    c = card(
        foil=True, finish="reverse", variant_confirmed=True, condition_confirmed=True
    )
    result = assess(c, summarize(CARD, True))
    assert result["risk_cents"] == result["prudent_cents"] == 14015
    assert result["is_valuable"] and result["market_unstable"]
    assert not result["needs_review"]
    c["condition_confirmed"] = False
    assert {r["code"] for r in assess(c, summarize(CARD, True))["reasons"]} == {
        "value",
        "condition",
    }


def test_checked_standard_excludes_the_rejected_expensive_reverse():
    result = assess(
        card(variant_confirmed=True, condition_confirmed=True), summarize(CARD, False)
    )
    assert result["risk_cents"] == 625
    assert not result["needs_review"] and not result["is_valuable"]
    assert len(result["hypotheses"]) == 1


def test_human_verification_does_not_invent_a_price_or_revive_invalidated_quote():
    c = card(variant_confirmed=True, condition_confirmed=True, price_date="")
    result = assess(c, summarize(CARD, False))
    assert {r["code"] for r in result["reasons"]} == {"missing_price"}
    assert result["prudent_cents"] is None


def test_checked_standard_does_not_wait_for_a_nonexistent_reverse_quote():
    snapshot = {
        "catalog_id": "swsh7-077",
        "variants": {"normal": True, "reverse": True},
        "raw": {"cardmarket": {"trend": 1, "avg30": 0.5}},
    }
    result = assess(card(variant_confirmed=True), snapshot)
    assert result["risk_cents"] == 50 and not result["risk_incomplete"]
    assert not result["needs_review"]


def test_catalogue_disagreement_does_not_override_physical_confirmation():
    snapshot = summarize(CARD, True)
    snapshot["variant_check"] = True
    c = card(foil=True, variant_confirmed=True, condition_confirmed=True)
    result = assess(c, snapshot)
    assert result["variant_catalog_warning"] and not result["needs_review"]


def test_stamped_holon_holo_cannot_be_valued_as_a_confirmed_nonfoil():
    snapshot = summarize(CARD, False)
    snapshot["catalog_id"] = "ex13-78"
    c = card(
        catalog_id="ex13-78",
        stamp="EX Fantômes Holon",
        finish="holo",
        variant_confirmed=True,
        condition_confirmed=True,
    )
    result = assess(c, snapshot)
    assert result["price_variant_issue"] and result["needs_review"]
    assert result["prudent_cents"] is None and result["trend_cents"] is None
    assert result["risk_cents"] == 14015
    assert {r["code"] for r in result["reasons"]} == {"price_variant", "missing_price"}
    c["foil"] = True
    result = assess(c, snapshot)
    assert not result["price_variant_issue"] and not result["needs_review"]
    assert result["prudent_cents"] == result["risk_cents"] == 14015


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(tmp_path / "inventory", price_fetch=lambda *_: copy.deepcopy(CARD))
    ) as client:
        assert (
            client.post(
                "/api/setup",
                json={"username": "pat", "password": "Collection-test-2026!"},
            ).status_code
            == 200
        )
        client.post("/api/albums", json={"name": "Test"})
        yield client


def create(client, **overrides):
    response = client.post(
        "/api/copies",
        json=values(
            client,
            catalog_id=CARD["id"],
            identification_status="confirmed",
            condition="PL",
            **overrides,
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()


def refresh(client, c):
    response = client.post(
        f"/api/copies/{c['id']}/price-refresh", json={"expected_version": c["version"]}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_api_review_filter_threshold_pagination_and_group_totals(client):
    refresh(client, create(client))
    refresh(client, create(client, position=2))
    for endpoint in ("/api/copies", "/api/editions"):
        response = client.get(
            endpoint,
            params={"review": "needed", "threshold": 10, "sort": "binder", "limit": 1},
        ).json()
        assert len(response["items"]) == 1
        amounts = response["valuation_totals"]
        assert (
            amounts["copies"] == 2
            and amounts["trend_cents"] == amounts["prudent_cents"] == 1250
        )
        assert amounts["review_count"] == 2
        assert (
            amounts["sale_estimate_cents"] is None
            and amounts["sale_estimate_missing"] == 2
        )
        assert (
            client.get(endpoint, params={"review": "needed", "threshold": 150}).json()[
                "total"
            ]
            == 0
        )
        assert client.get(endpoint, params={"review": "invalid"}).status_code == 422
        assert client.get(endpoint, params={"threshold": 0}).status_code == 422
    assert (
        client.get("/api/summary").json()["valuation_totals"]["prudent_cents"] == 1250
    )


def test_sale_estimate_is_excluded_after_grade_or_identity_changes_even_if_reverted(
    client,
):
    c = refresh(client, create(client))
    response = client.post(
        f"/api/copies/{c['id']}/sale-estimate",
        json={"text": "Gourgeist\nPL\n14,00 €\nPL\n16,00 €"},
    )
    assert response.status_code == 201, response.text
    detail = client.get(f"/api/copies/{c['id']}").json()
    assert detail["valuation"]["sale_estimate_cents"] == 1500
    assert (
        client.get("/api/summary").json()["valuation_totals"]["sale_estimate_cents"]
        == 1500
    )
    for grade in ("NM", "PL"):
        detail = client.patch(
            f"/api/copies/{c['id']}",
            json={
                "expected_version": detail["version"],
                "reason": "Vérification",
                "condition": grade,
            },
        ).json()
    detail = client.get(f"/api/copies/{c['id']}").json()
    assert detail["sale_estimate"] is not None and detail["sale_estimate_stale"] is True
    assert detail["valuation"]["sale_estimate_cents"] is None
    assert (
        client.get("/api/summary").json()["valuation_totals"]["sale_estimate_cents"]
        is None
    )
    detail = client.patch(
        f"/api/copies/{c['id']}",
        json={
            "expected_version": detail["version"],
            "reason": "Identité corrigée",
            "catalog_id": "new-identity",
        },
    ).json()
    assert (
        client.get(f"/api/copies/{c['id']}").json()["valuation"]["prudent_cents"]
        is None
    )


def test_candidate_evidence_is_valued_without_confirming_or_fetching_prices(client):
    c = create(client)
    store = client.app.state.store
    c = store.patch(
        c["id"],
        {"identification_status": "review", "catalog_id": None},
        c["version"],
        "pat",
        "À identifier",
    )
    evidence = {
        "searches": [
            {
                "query": {k: c[k] for k in ("name", "number", "language")},
                "candidates": [{"id": CARD["id"], "pricing": CARD["pricing"]}],
            }
        ]
    }
    with store.connect(write=True) as db:
        store.event(
            db, c["id"], "pat", "identification", "Éditions candidates", {}, evidence
        )
    detail = client.get(f"/api/copies/{c['id']}").json()
    assert detail["reference_cents"] is None and detail["catalog_id"] is None
    assert detail["valuation"]["risk_cents"] == 14015
    assert detail["valuation"]["prudent_cents"] is None
    c = client.patch(
        f"/api/copies/{c['id']}",
        json={
            "expected_version": c["version"],
            "name": "Other card",
            "reason": "Lecture corrigée",
        },
    ).json()
    assert (
        client.get(f"/api/copies/{c['id']}").json()["valuation"]["risk_cents"] is None
    )


def manual(**overrides):
    return card(
        **{
            "catalog_id": "np-29",
            "variant_confirmed": True,
            "condition_confirmed": True,
            "reference_cents": 5210,
            "price_source": "Cardmarket · page produit Celebi-NP29 · tendance",
            **overrides,
        }
    )


def test_manual_reference_stands_in_when_tcgdex_has_no_cardmarket_quote():
    result = assess(manual())
    assert result["risk_cents"] == result["prudent_cents"] == 5210
    assert result["trend_cents"] == 5210
    assert result["risk_incomplete"] and result["is_valuable"]
    assert result["manual_price"]["source"].startswith("Cardmarket")
    assert not result["needs_review"]
    assert result["hypotheses"][0]["observed_at"] == "2026-10-07"
    # Unconfirmed physical checks still apply above the threshold.
    reasons = {r["code"] for r in assess(manual(condition_confirmed=False))["reasons"]}
    assert reasons == {"value", "condition"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"price_source": "TCGdex · Cardmarket trend"},
        {"price_source": ""},
        {"price_date": ""},
        {"reference_cents": None},
    ],
)
def test_only_a_dated_human_reference_counts_as_manual_value(overrides):
    result = assess(manual(**overrides))
    assert result["manual_price"] is None and result["risk_cents"] is None
    assert {r["code"] for r in result["reasons"]} == {"missing_price"}


def test_a_tcgdex_prudent_price_wins_over_the_manual_reference():
    c = manual(catalog_id="swsh7-077")
    result = assess(c, summarize(CARD, False))
    assert result["manual_price"] is None and result["prudent_cents"] == 625


def test_price_sort_follows_the_prudent_value_with_unknown_prices_last(
    tmp_path, monkeypatch
):
    from pokeprice.inventory import Store

    store = Store(tmp_path / "inventory")
    with store.connect(write=True) as db:
        db.execute("INSERT INTO albums VALUES('a','A')")
    prudent = {"Abra": 300, "Bulbizarre": None, "Carapuce": 1200, "Dracaufeu": 300}
    for position, name in enumerate(prudent, 1):
        store.create_copy(
            dict(
                name=name, set_name="Test", number=f"{position}/100", language="fr",
                album_id="a", page=1, position=position,
                identification_status="review", foil=False, condition="EX",
            ),
            "pat",
            "Test",
        )

    def valuation(card, context, source=None, *, threshold_cents=1000):
        value = prudent[card["name"]]
        return {
            "prudent_cents": value, "trend_cents": value, "sale_estimate_cents": None,
            "needs_review": False, "price_variant_issue": False,
        }

    monkeypatch.setattr(Store, "valuation", staticmethod(valuation))
    names = lambda sort: [c["name"] for c in store.listing(sort=sort)["items"]]
    assert names("price") == ["Carapuce", "Abra", "Dracaufeu", "Bulbizarre"]
    assert names("price_asc") == ["Abra", "Dracaufeu", "Carapuce", "Bulbizarre"]
    assert [g["name"] for g in store.grouped(sort="price")["items"]][0] == "Carapuce"


def test_api_accepts_the_price_sorts(client):
    refresh(client, create(client))
    for endpoint in ("/api/copies", "/api/editions"):
        for sort in ("price", "price_asc"):
            response = client.get(endpoint, params={"sort": sort})
            assert response.status_code == 200 and response.json()["total"] == 1
        assert client.get(endpoint, params={"sort": "cost"}).status_code == 422
