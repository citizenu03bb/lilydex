"""Cardmarket's official price guide completes prints TCGdex leaves unquoted."""

import json
import os

import pytest
from fastapi.testclient import TestClient
from test_intake import values

from pokeprice import pricing
from pokeprice.cardmarket_guide import CardmarketGuide, has_quote, product_parts
from pokeprice.inventory import Store
from pokeprice.pricing import NoCardmarketQuote, fetch_card_with_guide
from pokeprice.valuation import manual_reference
from pokeprice.webapp import create_app

GUIDE = {
    "createdAt": "2026-10-22T02:45:11+0200",
    "priceGuides": [
        {"idProduct": 277993, "trend": 0.45, "avg30": 0.48, "low": 0.1, "trend-holo": None},
        {"idProduct": 278191, "trend": 8.02, "avg30": 7.91, "low": 5.0},
        {"idProduct": 277959, "trend": 0.45, "avg30": 0.89, "trend-holo": 3.18, "avg30-holo": 3.52},
    ],
}
PRODUCTS = {
    "products": [
        {"idProduct": 277993, "name": "Unown [L] Lv.18 [LINK | Hidden Power]", "idExpansion": 1563},
        {"idProduct": 277994, "name": "Unown [L] [Laugh | Hidden Power]", "idExpansion": 1563},
        {"idProduct": 277959, "name": "Unown [G] Lv.17 [GUARD | Hidden Power]", "idExpansion": 1563},
        {"idProduct": 278191, "name": "Unown [!] Lv.16 [! | Hidden Power]", "idExpansion": 1566},
    ]
}
TCGDEX = {
    "sets/dp4": {"cards": [{"id": "dp4-57"}, {"id": "dp4-91"}]},
    "cards/dp4-57": {"id": "dp4-57", "name": "Unown G", "pricing": {"cardmarket": {"idProduct": 277959}}},
    "cards/dp4-91": {
        "id": "dp4-91", "name": "Unown L", "pricing": {},
        "abilities": [{"name": "LINK"}], "attacks": [{"name": "Hidden Power"}],
    },
}


def files(url):
    return json.dumps(GUIDE if "priceGuide" in url else PRODUCTS).encode()


@pytest.fixture
def guide(tmp_path):
    store = Store(tmp_path / "inventory")
    return CardmarketGuide(tmp_path / "cm", store, fetch=files, get_json=TCGDEX.get)


def test_product_names_split_into_name_and_moves():
    assert product_parts("Unown [L] Lv.18 [LINK | Hidden Power]") == ("unown l", {"link", "hidden power"})
    assert product_parts("Meganium [Sleep Powder | Giant Bloom]") == ("meganium", {"sleep powder", "giant bloom"})
    assert product_parts("Nidoran [F] [Fury Swipes | Call for Family]")[0] == "nidoran f"


def test_tcgdex_product_without_quote_takes_the_guide_prices(guide):
    data = {"id": "dp4-57", "pricing": {"cardmarket": {"idProduct": 277959, "trend": None}}}
    completed = guide.complete(data)
    block = completed["pricing"]["cardmarket"]
    assert block["trend"] == 0.45 and block["trend-holo"] == 3.18 and block["updated"] == GUIDE["createdAt"]
    assert completed["_acquisition"]["cardmarket_guide"]["method"] == "produit indiqué par TCGdex"


def test_unmapped_print_is_matched_by_expansion_name_and_moves(guide):
    completed = guide.complete({"id": "dp4-91", "pricing": {}})
    provenance = completed["_acquisition"]["cardmarket_guide"]
    assert provenance["id_product"] == 277993 and "attaques" in provenance["method"]
    assert completed["pricing"]["cardmarket"]["trend"] == 0.45


def test_ambiguous_or_unknown_prints_stay_unquoted(guide):
    PRODUCTS["products"].append(
        {"idProduct": 999, "name": "Unown [L] Lv.18 [LINK | Hidden Power]", "idExpansion": 1563}
    )
    try:
        assert guide.complete({"id": "dp4-91", "pricing": {}}) == {"id": "dp4-91", "pricing": {}}
    finally:
        PRODUCTS["products"].pop()
    assert guide.complete({"id": "xx1-1", "pricing": {}}) == {"id": "xx1-1", "pricing": {}}


def test_a_tcgdex_quote_is_never_replaced(guide):
    data = {"id": "dp4-57", "pricing": {"cardmarket": {"idProduct": 277959, "trend": 1.0}}}
    assert guide.complete(data) is data


def test_unreachable_cardmarket_keeps_the_previous_files_or_changes_nothing(tmp_path, monkeypatch):
    # A freshly booted machine has a small monotonic clock (CI runners).
    monkeypatch.setattr("pokeprice.cardmarket_guide.time.monotonic", lambda: 5.0)
    def offline(url):
        raise OSError("hors ligne")

    data = {"id": "dp4-57", "pricing": {"cardmarket": {"idProduct": 277959}}}
    assert CardmarketGuide(tmp_path / "empty", fetch=offline, get_json=TCGDEX.get).complete(data) == data
    warm = CardmarketGuide(tmp_path / "cm", fetch=files, get_json=TCGDEX.get)
    warm._data()
    for path in (tmp_path / "cm").iterdir():  # yesterday's files
        os.utime(path, (0, 0))
    stale = CardmarketGuide(tmp_path / "cm", fetch=offline, get_json=TCGDEX.get)
    assert stale.complete(data)["pricing"]["cardmarket"]["trend"] == 0.45


def test_refresh_records_the_guide_as_source_not_as_a_manual_reference(tmp_path, monkeypatch):
    def tcgdex_without_quote(catalog_id, language, *, require_price=False):
        if require_price:
            raise NoCardmarketQuote("TCGdex connaît cette carte mais ne fournit aucun prix.")
        return {"id": catalog_id, "name": "Unown L", "pricing": {},
                "_acquisition": {"provider": "TCGdex", "served_language": "fr"}}

    monkeypatch.setattr(pricing, "fetch_catalogue_card", tcgdex_without_quote)
    store = Store(tmp_path / "inventory")
    guide = CardmarketGuide(tmp_path / "cm", store, fetch=files, get_json=TCGDEX.get)
    with TestClient(create_app(store.root, price_fetch=fetch_card_with_guide(guide))) as client:
        client.post("/api/setup", json={"username": "pat", "password": "Collection-test-2026!"})
        client.post("/api/albums", json={"name": "Test"})
        card = client.post("/api/copies", json=values(
            client, name="Zarbi L", number="91/106", set_name="Duels au Sommets", language="fr",
            hp=60, catalog_id="dp4-91", identification_status="confirmed")).json()
        response = client.post(f"/api/copies/{card['id']}/price-refresh", json={"expected_version": card["version"]})
        assert response.status_code == 200, response.text
        after = response.json()
        detail = client.get(f"/api/copies/{card['id']}").json()
    assert after["reference_cents"] == 45
    assert after["price_source"] == "Cardmarket · guide des prix trend"
    assert after["price_snapshot"]["cardmarket_guide"]["id_product"] == 277993
    assert manual_reference(after) is None
    assert detail["valuation"]["prudent_cents"] == 45


def test_a_print_absent_from_the_guide_keeps_the_clear_tcgdex_message(tmp_path, monkeypatch):
    def tcgdex_without_quote(catalog_id, language, *, require_price=False):
        if require_price:
            raise NoCardmarketQuote("TCGdex connaît cette carte mais ne fournit aucun prix.")
        return {"id": catalog_id, "pricing": {}}

    monkeypatch.setattr(pricing, "fetch_catalogue_card", tcgdex_without_quote)
    guide = CardmarketGuide(tmp_path / "cm", fetch=files, get_json=TCGDEX.get)
    with pytest.raises(NoCardmarketQuote):
        fetch_card_with_guide(guide)("xx1-1", "fr")
    assert not has_quote({"trend": None, "avg30-holo": None})
