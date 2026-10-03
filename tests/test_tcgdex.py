"""
Unit tests for pokeprice TCGdex client.
"""

from pokeprice.tcgdex import TCGdexClient


def test_clean_name():
    assert TCGdexClient.clean_name("Kapoera NIV.25") == "Kapoera"
    assert TCGdexClient.clean_name("Ortide Niv. 24") == "Ortide"
    assert TCGdexClient.clean_name("Hippopotas NIV.31") == "Hippopotas"
    assert TCGdexClient.clean_name("Gruikui") == "Gruikui"


def test_parse_card_number():
    assert TCGdexClient.parse_card_number("15/114") == ("15", 114)
    assert TCGdexClient.parse_card_number("04/106") == ("4", 106)
    assert TCGdexClient.parse_card_number("53") == ("53", None)
    assert TCGdexClient.parse_card_number("") == (None, None)


def test_tcgdex_lookup_darkrai():
    client = TCGdexClient(language="fr")
    info = client.search_card(name="Darkrai", raw_number="4/106", is_holo=True)
    assert info is not None
    assert info.name == "Darkrai"
    assert "4" in info.card_number
    assert "Duels" in info.set_name
    assert info.cm_trend_eur is not None and info.cm_trend_eur > 0
    assert info.tcg_market_usd is not None and info.tcg_market_usd > 10


def test_tcgdex_fuzzy_autosnap_gruikui():
    client = TCGdexClient(language="fr")
    # Simulate OCR typo where '15' was read as '12', but denominator '114' was correct
    info = client.search_card(name="Gruikui", raw_number="12/114")
    assert info is not None
    assert "Noir & Blanc" in info.set_name
    assert info.cm_trend_eur is not None


def test_tcgdex_stadium_salle_de_maitre():
    client = TCGdexClient(language="fr")
    info = client.search_card(name="Salle de Maître")
    assert info is not None
    assert "Salle de Maître" in info.name
    assert info.cm_trend_eur is not None
