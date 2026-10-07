import pytest
from pokeprice.tcgdex import TCGdexClient
from conftest import card


def test_clean_name():
    assert TCGdexClient.clean_name("Kapoera NIV.25") == "Kapoera"
    assert TCGdexClient.clean_name("Ortide Niv. 24") == "Ortide"
    assert TCGdexClient.clean_name("Charizard LV.76") == "Charizard"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("15/114", ("15", 114)),
        ("04/106", ("4", 106)),
        ("53", ("53", None)),
        ("", (None, None)),
    ],
)
def test_parse_number(raw, expected):
    assert TCGdexClient.parse_card_number(raw) == expected


@pytest.mark.parametrize(
    "english,fr,number,count,hp",
    [("Gulpin", "Goupelin", 98, 146, 60), ("Charizard", "Charibari", 4, 130, 120)],
)
def test_exact_english_before_french_fuzzy(
    client_factory, english, fr, number, count, hp
):
    client = client_factory(
        [
            card("en-1", english, number, count, hp, language="en"),
            card("fr-1", fr, 26, 146, 140),
        ],
        {fr.lower(): fr},
    )
    info = client.search_card(english, f"{number}/{count}", hp=hp)
    assert info.name == english
    assert info.language == "en"
    assert info.match_method == "exact"
    assert not any(fr in url for url in client.queries)


@pytest.mark.parametrize("reverse", [False, True])
def test_full_fraction_beats_earlier_hp_match(client_factory, reverse):
    details = [card("wrong-4", "Darkrai", 4, 130), card("right-4", "Darkrai", 4, 106)]
    client = client_factory(details[::-1] if reverse else details)
    assert client.search_card("Darkrai", "4/106", hp=80).card_id == "right-4"


def test_unique_numerator_with_wrong_denominator_is_unresolved(client_factory):
    client = client_factory([card("wrong-38", "Sulfura", 38, 214, 120)])
    assert client.search_card("Sulfura NIV.42", "38/147", hp=100) is None


def test_denominator_does_not_override_hp(client_factory):
    client = client_factory([card("ecard2-26", "Octillery", 26, 147, 80)])
    assert client.search_card("Octillery NIV.40", "73/147", hp=90) is None


def test_unique_number_correction_requires_review(client_factory):
    client = client_factory([card("bw1-15", "Gruikui", 15, 114, 70)])
    info = client.search_card("Gruikui", "12/114", hp=70)
    assert info.card_number == "15/114"
    assert info.match_method == "number-corrected"
    assert client.last_match_reason


def test_ambiguous_correction_returns_none(client_factory):
    client = client_factory(
        [card("bw1-15", "Gruikui", 15, 114, 70), card("bw1-16", "Gruikui", 16, 114, 60)]
    )
    assert client.search_card("Gruikui", "12/114") is None


def test_missing_reference_does_not_pick_first_image(client_factory):
    client = client_factory(
        [card("set-1", "Pikachu", 1, 100, 50), card("set-2", "Pikachu", 2, 100, 50)]
    )
    assert client.search_card("Pikachu", hp=50) is None


@pytest.mark.parametrize("pricing", [None, {}, {"cardmarket": None, "tcgplayer": None}])
def test_null_pricing_preserves_card(client_factory, pricing):
    client = client_factory(
        [card("set-4", "Darkrai", 4, 106, pricing=pricing, thirdParty=None)]
    )
    info = client.search_card("Darkrai", "4/106")
    assert info is not None and info.cm_recommended_eur is None


def test_explicit_english_id_keeps_english_identity(client_factory):
    from conftest import card

    client = client_factory([card("ex8-54", "Barboach", 54, 107, 50, language="en")])
    info = client.get_card_by_id("ex8-54", True, language="en")
    assert info.name == "Barboach" and info.language == "en"
    assert info.card_number == "54/107"
