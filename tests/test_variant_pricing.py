import pytest

from pokeprice.variant_pricing import category, pricing_issue


def observed(**fields):
    return {
        "identification_status": "confirmed",
        "catalog_id": "test-1",
        "finish": "holo",
        "stamp": "",
        "foil": False,
        **fields,
    }


@pytest.mark.parametrize(
    "flags,expected",
    [
        ({"normal": True, "holo": False, "reverse": True}, True),
        ({"normal": False, "holo": True, "reverse": True}, False),
        ({"normal": False, "holo": True, "reverse": False}, False),
        ({"normal": True, "holo": True, "reverse": False}, None),
        ({"normal": True, "holo": False, "reverse": False}, None),
        ({"normal": True}, None),
        ({}, None),
    ],
)
def test_holo_category_uses_explicit_edition_flags(flags, expected):
    result = category(observed(), {"catalog_id": "test-1", "variants": flags})
    assert result["foil"] is expected
    assert (result["mode"] == "automatic") is (expected is not None)


@pytest.mark.parametrize(
    "catalog_id,stamp,expected",
    [
        ("ex8-54", "EX Deoxys", True),
        ("ex8-16", "Deoxys", True),
        ("ex8-95", "EX Deoxys", True),
        ("ex8-15", "EX Deoxys", None),
        ("ex8-96", "EX Deoxys", None),
        ("ex8-54", "Promo", None),
        ("ex13-78", "EX Fantômes Holon", True),
        ("ex13-18", "Holon Phantoms", True),
        ("ex13-98", "EX Holon Phantoms", True),
        ("ex13-17", "EX Fantômes Holon", None),
        ("ex13-99", "EX Fantômes Holon", None),
        ("ex14-47", "EX Gardiens de Cristal", True),
        ("ex14-56", "EX Crystal Guardians", True),
        ("ex14-14", "Gardiens de Cristal", True),
        ("ex14-88", "Crystal Guardians", True),
        ("ex14-13", "EX Gardiens de Cristal", None),
        ("ex14-89", "EX Gardiens de Cristal", None),
        ("ex14-47", "Promo", None),
    ],
)
def test_documented_stamped_parallel_bounds(catalog_id, stamp, expected):
    assert category(observed(catalog_id=catalog_id, stamp=stamp))["foil"] is expected


def test_foreign_snapshot_or_stamp_does_not_choose_a_category():
    flags = {"normal": False, "holo": True}
    assert (
        category(observed(), {"catalog_id": "other-1", "variants": flags})["mode"]
        == "review"
    )
    assert (
        category(observed(stamp="Promo"), {"catalog_id": "test-1", "variants": flags})[
            "mode"
        ]
        == "review"
    )
    assert category(observed(finish=""))["mode"] == "legacy"
    assert pricing_issue(observed(finish="")) is None
    assert pricing_issue(observed(variant_confirmed=True))
    assert (
        pricing_issue(
            observed(
                variant_confirmed=True,
                variant_observation="Produit particulier identifié",
            )
        )
        is None
    )


def test_matte_and_parallel_holo_prices_disambiguate_pop_manaphy():
    snapshot = {
        "catalog_id": "pop9-2",
        "variants": {"normal": True, "holo": True, "reverse": False},
        "raw": {
            "tcgplayer": {
                "normal": {"productId": 87147},
                "holofoil": {"productId": 87147},
            }
        },
    }
    card = observed(catalog_id="pop9-2")
    decision = category(card, snapshot)
    assert decision["mode"] == "automatic" and decision["foil"] is True
    assert "pas reverse" in decision["reason"]
    assert pricing_issue(card, snapshot)
    assert pricing_issue({**card, "foil": True}, snapshot) is None
    assert category({**card, "finish": "non_holo"}, snapshot)["foil"] is False
    # Flags alone, another edition, or a special stamp remain insufficient.
    assert category(card, {**snapshot, "raw": {}})["mode"] == "review"
    assert category(card, {**snapshot, "catalog_id": "other-2"})["mode"] == "review"
    assert category({**card, "stamp": "Promo spéciale"}, snapshot)["mode"] == "review"


def test_holo_and_reverse_prices_resolve_incorrect_scrafty_flags():
    snapshot = {
        "catalog_id": "bw4-74",
        "variants": {"normal": True, "holo": False, "reverse": False},
        "raw": {
            "tcgplayer": {
                "holofoil": {"productId": 88978},
                "reverse-holofoil": {"productId": 88978},
            }
        },
    }
    card = observed(catalog_id="bw4-74", foil=True)
    decision = category(card, snapshot)
    assert decision["mode"] == "automatic" and decision["foil"] is False
    assert pricing_issue(card, snapshot)
    assert pricing_issue({**card, "foil": False}, snapshot) is None
    assert category({**card, "finish": "reverse"}, snapshot)["foil"] is True
    assert category(card, {**snapshot, "catalog_id": "other-74"})["mode"] == "review"
    assert category({**card, "stamp": "Promo"}, snapshot)["mode"] == "review"
    assert (
        category({**card, "identification_status": "review"}, snapshot)["mode"]
        == "review"
    )
    prints = snapshot["raw"]["tcgplayer"]
    for incomplete in (
        {"holofoil": prints["holofoil"]},
        {"reverse-holofoil": prints["reverse-holofoil"]},
        {**prints, "normal": {}},
        {**prints, "normal": None},
        None,
    ):
        assert (
            category(card, {**snapshot, "raw": {"tcgplayer": incomplete}})["mode"]
            == "review"
        )
