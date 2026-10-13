import copy
import io
import json

import pytest
from fastapi.testclient import TestClient
from test_intake import values

from pokeprice import pricing
from pokeprice.inventory import Store
from pokeprice.pricing import (
    NoCardmarketQuote,
    binding_market_url,
    cardmarket_search_url,
    cardmarket_url,
    fetch_catalogue_card,
    summarize,
)
from pokeprice.webapp import create_app

# Shape of a real TCGdex answer (ex13-78, 7 October 2026): a thin, volatile
# holo market next to a normal-only card.
CARD = {
    "id": "swsh7-077",
    "name": "Gourgeist",
    "variants": {"normal": True, "holo": False, "reverse": False},
    "pricing": {
        "cardmarket": {
            "updated": "2026-10-07T09:52:36.685Z",
            "unit": "EUR",
            "idProduct": 277048,
            "avg": 7.9,
            "low": 0.9,
            "trend": 6.25,
            "avg1": 7.12,
            "avg7": 5.35,
            "avg30": 7.1,
            "avg-holo": 800,
            "low-holo": 30,
            "trend-holo": 429.97,
            "avg1-holo": 1450,
            "avg7-holo": 375.61,
            "avg30-holo": 140.15,
        }
    },
}


def test_normal_variant_is_stable_and_holo_variant_is_flagged():
    normal = summarize(CARD, foil=False)
    assert normal["reference_field"] == "trend" and normal["reference_eur"] == 6.25
    assert normal["metrics"]["avg30"] == 7.1 and normal["id_product"] == 277048
    # Only the other variant's value differs enough to deserve a warning.
    assert len(normal["warnings"]) == 2
    assert "429,97 €" in normal["warnings"][0]
    holo = summarize(CARD, foil=True)
    assert holo["reference_field"] == "trend-holo" and holo["reference_eur"] == 429.97
    text = " ".join(holo["warnings"])
    assert "ne connaît pas de version Foil" in text and "tamponnée" in text
    assert "6,25 €" in text and "instable" in text and "prix bas" in text
    missing = copy.deepcopy(CARD)
    del missing["pricing"]["cardmarket"]["trend"]
    assert summarize(missing, foil=False)["reference_field"] == "avg30"


def test_cardmarket_link_filters_language_and_condition():
    url = cardmarket_url(277048, "fr", "PL")
    assert url.startswith("https://www.cardmarket.com/fr/Pokemon/Products?")
    assert "idProduct=277048" in url and "language=2" in url
    assert "minCondition=6" in url
    assert cardmarket_url(277048, "zh", "") == (
        "https://www.cardmarket.com/fr/Pokemon/Products?idProduct=277048"
    )
    assert cardmarket_url(None, "fr", "NM") is None
    assert cardmarket_url(277048, "fr", "LP", foil=True).endswith("&isReverseHolo=Y")


def test_bulk_cards_carry_no_warnings():
    bulk = copy.deepcopy(CARD)
    bulk["pricing"]["cardmarket"].update(
        {"trend": 0.31, "low": 0.02, "avg1": 0.1, "avg7": 0.3, "avg30": 0.26}
    )
    bulk["pricing"]["cardmarket"]["trend-holo"] = 0.99
    assert summarize(bulk, foil=False)["warnings"] == []


@pytest.fixture
def client(tmp_path):
    calls = []

    def fetch(catalog_id, language):
        calls.append((catalog_id, language))
        if catalog_id == "offline-1":
            raise RuntimeError("TCGdex indisponible")
        if catalog_id == "np-29":
            raise NoCardmarketQuote(
                "TCGdex connaît cette carte mais ne fournit aucun prix Cardmarket."
            )
        card = copy.deepcopy(CARD)
        card["id"] = catalog_id
        if catalog_id == "holo-1":  # Printed holo only, no reverse.
            card["variants"] = {"holo": True}
        return card

    store = Store(tmp_path / "inventory")
    with TestClient(create_app(store.root, price_fetch=fetch)) as client:
        client.post(
            "/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}
        )
        client.post("/api/albums", json={"name": "Test"})
        client.calls = calls
        yield client


def confirmed(client, **overrides):
    response = client.post(
        "/api/copies",
        json=values(
            client,
            **{
                "catalog_id": "swsh7-077",
                "identification_status": "confirmed",
                "condition": "PL",
                **overrides,
            },
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_refresh_records_dated_reference_snapshot_and_link(client):
    card = confirmed(client, foil=True)
    response = client.post(
        f"/api/copies/{card['id']}/price-refresh", json={"expected_version": 1}
    )
    assert response.status_code == 200, response.text
    assert client.calls == [("swsh7-077", "en")]
    updated = response.json()
    assert updated["reference_cents"] == 42997
    assert updated["price_snapshot"]["warnings"]
    assert updated["price_source"] == "TCGdex · Cardmarket trend-holo"
    assert updated["price_date"] == "2026-10-07T09:52:36.685Z"
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["price_snapshot"]["metrics"]["avg30"] == 140.15
    assert detail["price_snapshot"]["warnings"]
    assert detail["prices"][0]["amount_cents"] == 42997
    assert "language=1" in detail["cardmarket_url"]
    assert "minCondition=6" in detail["cardmarket_url"]
    assert "isReverseHolo=Y" in detail["cardmarket_url"]
    # Same values again: a new dated snapshot, no new correction or price row.
    version = detail["version"]
    again = client.post(
        f"/api/copies/{card['id']}/price-refresh", json={"expected_version": version}
    ).json()
    assert again["version"] == version
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert len(detail["prices"]) == 1
    assert sum(e["kind"] == "price-snapshot" for e in detail["history"]) == 2


def test_refresh_requires_confirmed_identity_current_version_and_tcgdex(client):
    review = client.post("/api/copies", json=values(client)).json()
    response = client.post(
        f"/api/copies/{review['id']}/price-refresh", json={"expected_version": 1}
    )
    assert response.status_code == 422 and "confirmez" in response.json()["detail"]
    card = confirmed(client, position=2)
    stale = client.post(
        f"/api/copies/{card['id']}/price-refresh", json={"expected_version": 9}
    )
    assert stale.status_code == 409
    offline = confirmed(client, position=3, catalog_id="offline-1")
    failed = client.post(
        f"/api/copies/{offline['id']}/price-refresh", json={"expected_version": 1}
    )
    assert failed.status_code == 503
    assert client.get(f"/api/copies/{offline['id']}").json()["price_snapshot"] is None
    assert client.calls == [("offline-1", "en")]


def test_holo_only_card_marked_reverse_is_told_to_use_the_normal_price():
    holo_only = copy.deepcopy(CARD)
    holo_only["variants"] = {"holo": True}
    holo_only["pricing"]["cardmarket"].update({"trend": 310.4, "trend-holo": 190.22})
    warnings = summarize(holo_only, foil=True)["warnings"]
    assert "imprimée holo d’origine" in warnings[0]
    reverse = copy.deepcopy(CARD)
    reverse["variants"] = {"normal": True, "reverse": True}
    assert not any("reverse" in w for w in summarize(reverse, foil=True)["warnings"])


def test_variant_filter_lists_foil_cards_to_check_until_corrected(client):
    holo = confirmed(client, catalog_id="holo-1", foil=True, position=4)
    plain = confirmed(client, position=5)
    client.post(f"/api/copies/{holo['id']}/price-refresh", json={"expected_version": 1})
    client.post(
        f"/api/copies/{plain['id']}/price-refresh", json={"expected_version": 1}
    )

    def ids(variant):
        listing = client.get("/api/copies", params={"variant": variant}).json()
        return {c["id"]: c for c in listing["items"]}

    assert set(ids("foil")) == {holo["id"]} and set(ids("standard")) == {plain["id"]}
    checked = ids("check")
    assert set(checked) == {holo["id"]} and checked[holo["id"]]["price_alerts"] >= 1
    assert ids("")[plain["id"]]["variant_check"] is False
    grouped = client.get("/api/editions", params={"variant": "check"}).json()
    assert grouped["copies_total"] == 1
    assert client.get("/api/copies", params={"variant": "holo"}).status_code == 422
    version = client.get(f"/api/copies/{holo['id']}").json()["version"]
    client.patch(
        f"/api/copies/{holo['id']}",
        json={"expected_version": version, "reason": "Vérifiée", "foil": False},
    )
    assert ids("check") == {}
    # Not physically confirmed: still in the M0 audit list, alert or not.
    assert set(ids("unverified")) == set(ids("foil")) - {holo["id"]}
    foil = confirmed(client, foil=True, position=6)
    assert foil["id"] in ids("unverified")
    version = client.get(f"/api/copies/{foil['id']}").json()["version"]
    confirm = client.patch(
        f"/api/copies/{foil['id']}",
        json={
            "expected_version": version,
            "reason": "Reverse vue",
            "finish": "reverse",
            "variant_confirmed": True,
        },
    )
    assert confirm.status_code == 200, confirm.text
    assert foil["id"] not in ids("unverified")


def test_stamp_is_a_searchable_variant_that_resets_the_reference(client):
    import sqlite3

    from pokeprice.intake import Observation

    store = client.app.state.store
    with sqlite3.connect(store.database) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 14
    card = confirmed(client, foil=True, position=6, stamp="EX Fantômes Holon")
    assert card["stamp"] == "EX Fantômes Holon"
    priced = client.post(
        f"/api/copies/{card['id']}/price-refresh", json={"expected_version": 1}
    ).json()
    assert priced["reference_cents"] == 42997
    stamped = client.get("/api/copies", params={"variant": "stamped"}).json()
    assert [c["id"] for c in stamped["items"]] == [card["id"]]
    found = client.get("/api/copies", params={"q": "fantomes holon"}).json()
    assert card["id"] in [c["id"] for c in found["items"]]
    # A different stamp is a different variant: the old reference no longer holds.
    changed = client.patch(
        f"/api/copies/{card['id']}",
        json={
            "expected_version": priced["version"],
            "reason": "Tampon relu",
            "stamp": "",
        },
    ).json()
    assert changed["stamp"] == "" and changed["reference_cents"] is None
    assert (
        client.get("/api/copies", params={"variant": "stamped"}).json()["items"] == []
    )
    # Older readings without the field stay valid.
    observation = Observation.model_validate(
        {
            "name": "Pikachu",
            "number": "78/110",
            "language": "fr",
            "hp": 50,
            "readable_front": True,
            "flaws": "",
            "notes": "",
        }
    )
    assert observation.stamp_text == ""


# Text copied from a real Cardmarket page (Pikachu EX Holon Phantoms, Foil, FR).
PASTED = """Pikachu (HP 78)
Articles disponibles
56
De
30,00 €
Tendance des prix
429,97 €
Prix moyen 1 jour
1.450,00 €
Vendeur
Offre
786
Fabercollecter
LP
59,00 €
1
22
K
DateACard
LP
VI
60,00 €
1
Nsurr
GD
STAMP
85,50 €
1
MarcoSan77
EX
Stamp, ask photos
1.150,00 €
1
"""


def test_pasted_offers_skip_header_prices_and_keep_comments():
    from pokeprice.pricing import parse_offers

    offers = parse_offers(PASTED)
    assert [(o["condition"], o["price_eur"]) for o in offers] == [
        ("LP", 59.0),
        ("LP", 60.0),
        ("GD", 85.5),
        ("EX", 1150.0),
    ]
    assert offers[1]["comment"] == "VI" and offers[2]["comment"] == "STAMP"


def test_estimate_uses_same_condition_else_a_documented_discount():
    from pokeprice.pricing import estimate_sale, parse_offers

    offers = parse_offers(PASTED)
    lp = estimate_sale(offers, "LP")
    assert lp["estimate_eur"] == 59.5 and (lp["low_eur"], lp["high_eur"]) == (59, 60)
    assert lp["confidence"] == "moyenne"
    # Real Scraggy PO offers: the median, not the cheapest few (damaged, clearance).
    po = [
        {"condition": "PO", "price_eur": v, "comment": ""}
        for v in (0.15, 0.4, 0.8, 1, 1, 1)
    ]
    market = estimate_sale(po, "PO")
    assert market["estimate_eur"] == 0.9 and market["confidence"] == "bonne"
    assert market["low_eur"] == 0.5 and market["high_eur"] == 1.0
    # Stamped variant: only stamped offers count; PO is three steps below GD.
    stamped = estimate_sale(offers, "PO", stamp="EX Fantômes Holon")
    assert stamped["offers_used"] == 2 and stamped["confidence"] == "faible"
    assert stamped["estimate_eur"] == round(85.5 * 0.75**3, 2)
    assert "85,50 €" in stamped["method"]
    with pytest.raises(ValueError):
        estimate_sale(offers, "")


def test_sale_estimate_is_recorded_without_touching_the_card(client):
    card = confirmed(
        client, foil=True, position=7, stamp="EX Fantômes Holon", condition="PO"
    )
    response = client.post(
        f"/api/copies/{card['id']}/sale-estimate", json={"text": PASTED}
    )
    assert response.status_code == 201, response.text
    assert response.json()["estimate_eur"] == round(85.5 * 0.75**3, 2)
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["sale_estimate"]["offers_used"] == 2
    assert detail["version"] == card["version"] and detail["reference_cents"] is None
    # The pasted page does not name this card: the estimate says so.
    other = confirmed(client, position=8, condition="LP", name="Gourgeist")
    warned = client.post(
        f"/api/copies/{other['id']}/sale-estimate", json={"text": PASTED}
    ).json()
    assert any("Gourgeist" in w for w in warned["warnings"])
    empty = client.post(
        f"/api/copies/{card['id']}/sale-estimate", json={"text": "rien à lire"}
    )
    assert empty.status_code == 422


def test_bound_market_url_uses_native_filters_and_not_foil():
    binding = {
        "market": "cardmarket",
        "product_ref": "cardmarket:277048",
        "native_variant": {"code": "parallel-holo"},
        "foil_projection": True,
        "filters": {"none": True},
    }
    assert binding_market_url(binding).endswith("idProduct=277048")
    assert "isReverseHolo" not in binding_market_url(binding)
    binding["filters"] = {"isReverseHolo": "Y"}
    binding["foil_projection"] = False
    assert "isReverseHolo=Y" in binding_market_url(binding)


def test_refresh_many_snapshots_confirmed_cards_and_reports_failures(client):
    from pokeprice.pricing import PriceService

    store = client.app.state.store
    good = confirmed(client, position=9)
    bad = confirmed(client, position=10, catalog_id="offline-1")
    client.post("/api/copies", json=values(client, position=11))  # Not confirmed.
    service = PriceService(store, client.app.state.pricing.fetch)
    summary = service.refresh_many("manage")
    assert summary["selected"] == 2 and summary["refreshed"] == 1
    assert summary["failed"][0]["id"] == bad["id"]
    assert summary["reference_after_cents"] == 625
    again = service.refresh_many("manage", only_missing=True)
    assert again["selected"] == 1  # Only the failed one was never snapshotted.
    assert client.get(f"/api/copies/{good['id']}").json()["price_snapshot"]


def test_a_card_without_cardmarket_quote_is_not_reported_as_an_outage(monkeypatch):
    # Shape of TCGdex np-29 on 13 October 2026: TCGplayer only.
    data = {"id": "np-29", "pricing": {"cardmarket": None, "tcgplayer": {}}}
    monkeypatch.setattr(
        pricing, "urlopen", lambda *a, **k: io.BytesIO(json.dumps(data).encode())
    )
    with pytest.raises(NoCardmarketQuote, match="aucun prix Cardmarket"):
        fetch_catalogue_card("np-29", "fr", require_price=True)
    assert fetch_catalogue_card("np-29", "fr")["id"] == "np-29"

    def offline(*args, **kwargs):
        raise OSError("réseau")

    monkeypatch.setattr(pricing, "urlopen", offline)
    with pytest.raises(RuntimeError, match="indisponible") as error:
        fetch_catalogue_card("np-29", "fr", require_price=True)
    assert not isinstance(error.value, NoCardmarketQuote)


def test_unpriced_refresh_is_a_clear_422_and_detail_offers_an_inferred_search(client):
    card = confirmed(client, catalog_id="np-29", name="Celebi")
    response = client.post(
        f"/api/copies/{card['id']}/price-refresh", json={"expected_version": 1}
    )
    assert response.status_code == 422
    assert "aucun prix Cardmarket" in response.json()["detail"]
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["cardmarket_url"] is None
    assert detail["cardmarket_search_url"] == (
        "https://www.cardmarket.com/fr/Pokemon/Products/Search?searchString=Celebi+29"
    )


def test_inferred_cardmarket_search_uses_name_and_local_number():
    # Checked on Cardmarket, 13 October 2026: a unique match opens the product.
    assert cardmarket_search_url("Nidoran ♀", "base2-57").endswith(
        "searchString=Nidoran+57"
    )
    assert cardmarket_search_url("Unown L", "dp4-91").endswith(
        "searchString=Unown+L+91"
    )
    assert cardmarket_search_url("Celebi", None) is None
    assert cardmarket_search_url("", "np-29") is None
