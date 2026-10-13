"""Physical decisions survive catalogue refreshes and retain attributable history."""

import copy
import csv
import io

import pytest
from fastapi.testclient import TestClient
from test_intake import values
from test_pricing import CARD

from pokeprice.inventory import Store
from pokeprice.inventory_backup import backup, export_csv, restore_backup
from pokeprice.pricing import summarize
from pokeprice.webapp import create_app


@pytest.fixture
def client(tmp_path):
    catalogue = copy.deepcopy(CARD)
    catalogue["variants"] = {"holo": True, "normal": False, "reverse": False}
    with TestClient(
        create_app(
            tmp_path / "inventory",
            price_fetch=lambda catalog_id, *_: {**catalogue, "id": catalog_id},
        )
    ) as client:
        client.post(
            "/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}
        )
        client.post("/api/albums", json={"name": "Test"})
        yield client


def create(client, **fields):
    fields.setdefault("variant_observation", "Produit spécial examiné physiquement")
    response = client.post(
        "/api/copies",
        json=values(
            client,
            catalog_id=CARD["id"],
            identification_status="confirmed",
            foil=True,
            condition="NM",
            condition_confirmed=True,
            **fields,
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()


def patch(client, card, **fields):
    return client.patch(
        f"/api/copies/{card['id']}",
        json={
            "expected_version": card["version"],
            "reason": "Examen de la carte physique",
            **fields,
        },
    )


def refresh(client, card):
    response = client.post(
        f"/api/copies/{card['id']}/price-refresh",
        json={"expected_version": card["version"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_confirmed_variant_leaves_old_filter_but_keeps_catalogue_disagreement(client):
    card = refresh(client, create(client))
    assert client.get("/api/copies?variant=check").json()["total"] == 1
    card = patch(
        client,
        card,
        finish="special",
        variant_confirmed=True,
        variant_observation="Holo spéciale observée, catalogue incomplet",
    ).json()
    assert card["variant_verified_by"] == "pat" and card["variant_verified_at"]
    checked_at = card["variant_verified_at"]
    assert card["reference_cents"] is None
    card = refresh(client, card)
    assert client.get("/api/copies?variant=check").json()["total"] == 0
    row = client.get("/api/copies").json()["items"][0]
    assert row["variant_catalog_warning"] and not row["variant_check"]
    snapshot = client.get(f"/api/copies/{card['id']}").json()["price_snapshot"]
    assert row["price_alerts"] < len(snapshot["warnings"])
    assert not row["valuation"]["needs_review"] and row["valuation"]["is_valuable"]
    card = refresh(client, card)
    assert card["variant_confirmed"] and card["variant_verified_at"] == checked_at
    assert client.get("/api/copies?review=needed").json()["total"] == 0
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert any(
        '"variant_observation": "Holo spéciale' in event["after_json"]
        for event in detail["history"]
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"name": "Other"},
        {"number": "9/100"},
        {"catalog_id": "other-9"},
        {"set_name": "Other"},
        {"language": "fr"},
        {"foil": False},
        {"stamp": "Promo"},
        {"finish": "holo_border"},
        {"identification_status": "review"},
    ],
)
def test_relevant_correction_invalidates_confirmation(client, fields):
    card = create(client, finish="special", variant_confirmed=True)
    response = patch(client, card, **fields)
    assert response.status_code == 200, response.text
    after = response.json()
    assert not after["variant_confirmed"]
    assert after["variant_verified_at"] == after["variant_verified_by"] == ""


def test_front_photo_replacement_invalidates_physical_confirmation(client):
    card = create(client, finish="special", variant_confirmed=True)
    store = client.app.state.store
    photo = store.save_photo(b"front-photo-test")
    card = store.patch(
        card["id"], {"photo": photo}, card["version"], "pat", "Nouveau recto"
    )
    assert not card["variant_confirmed"] and not card["variant_verified_at"]


def test_location_grade_and_price_changes_do_not_invalidate_variant(client):
    card = create(client, finish="special", variant_confirmed=True)
    checked_at = card["variant_verified_at"]
    card = patch(client, card, page=3, condition="LP", notes="Déplacée").json()
    assert card["variant_confirmed"] and card["variant_verified_at"] == checked_at
    assert not card["condition_confirmed"]
    card = refresh(client, card)
    assert card["variant_confirmed"] and card["variant_verified_at"] == checked_at


def test_prime_holo_border_uses_standard_and_needs_a_new_price_only(client):
    card = refresh(client, create(client))
    response = patch(
        client,
        card,
        foil=False,
        finish="holo_border",
        variant_confirmed=True,
        variant_observation="Cadre holo d’origine",
    )
    assert response.status_code == 200, response.text
    card = response.json()
    assert card["reference_cents"] is None and card["price_date"] == ""
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert {r["code"] for r in detail["valuation"]["reasons"]} == {"missing_price"}
    card = refresh(client, card)
    assert card["variant_confirmed"]
    assert not client.get(f"/api/copies/{card['id']}").json()["valuation"][
        "needs_review"
    ]


@pytest.mark.parametrize(
    "fields",
    [
        {"variant_confirmed": True},
        {
            "variant_confirmed": True,
            "finish": "special",
            "identification_status": "review",
        },
        {"finish": "invented"},
        {"variant_verified_by": "someone-else"},
    ],
)
def test_invalid_or_forged_confirmation_is_rejected_without_writing(client, fields):
    card = create(client)
    assert patch(client, card, **fields).status_code in (400, 422)
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["version"] == card["version"] and not detail["variant_confirmed"]


def test_physical_confirmation_is_preserved_by_exports_and_restoration(
    client, tmp_path
):
    card = create(
        client,
        finish="special",
        variant_confirmed=True,
        variant_observation="Cadre observé",
    )
    store = client.app.state.store
    row = next(csv.DictReader(io.StringIO(export_csv(store))))
    assert row["finish"] == "special" and row["variant_verified_by"] == "pat"
    archive = tmp_path / "backup.zip"
    backup(store, archive)
    destination = tmp_path / "restored"
    restore_backup(archive, destination)
    with Store(destination).connect() as db:
        restored = Store.get(db, card["id"])
    for key in (
        "finish",
        "variant_confirmed",
        "variant_verified_at",
        "variant_verified_by",
        "variant_observation",
    ):
        assert restored[key] == card[key]


def test_legacy_stamped_holo_is_excluded_until_automatic_category_repair(
    client,
):
    response = client.post(
        "/api/copies",
        json=values(
            client,
            catalog_id="ex13-78",
            name="Pikachu",
            number="78/110",
            set_name="EX Fantômes Holon",
            identification_status="confirmed",
            condition="PO",
            condition_confirmed=True,
            foil=False,
            finish="holo",
            stamp="EX Fantômes Holon",
        ),
    )
    assert response.status_code == 201, response.text
    card = response.json()
    store = client.app.state.store
    snapshot = summarize({**CARD, "id": "ex13-78"}, False)
    # Reproduce a confirmation recorded by the previous version of the form.
    with store.connect(write=True) as db:
        db.execute(
            "UPDATE copies SET foil=0,variant_confirmed=1,variant_verified_by='pat',variant_verified_at='2026-10-12',reference_cents=438,price_date='2026-10-12' WHERE id=?",
            (card["id"],),
        )
        store.event(
            db,
            card["id"],
            "pat",
            "price-snapshot",
            "Ancien relevé Standard",
            {},
            snapshot,
        )
    row = client.get("/api/copies?review=needed").json()["items"][0]
    assert row["variant_confirmed"] and row["valuation"]["price_variant_issue"]
    assert row["valuation"]["prudent_cents"] is None
    assert row["valuation"]["risk_cents"] == 14015
    summary = client.get("/api/summary").json()
    assert summary["confirmed_without_price"] == 1
    assert summary["valuation_totals"]["trend_cents"] is None
    assert (
        patch(
            client, card, reference_price_eur=4.38, price_source="Relevé manuel"
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/copies/{card['id']}/sale-estimate",
            json={"text": "Pikachu\nPO\n4,00 €"},
        ).status_code
        == 422
    )
    # Unrelated work remains possible, then the category can be corrected.
    # Price refresh repairs the derived category, preserving physical provenance.
    card = refresh(client, card)
    assert card["foil"] and card["variant_verified_at"] == "2026-10-12"
    assert card["variant_verified_by"] == "pat"
    row = client.get(f"/api/copies/{card['id']}").json()
    assert not row["valuation"]["price_variant_issue"]
    assert row["valuation"]["prudent_cents"] == 14015
    assert not row["valuation"]["needs_review"]


@pytest.mark.parametrize("finish,expected", [("non_holo", False), ("reverse", True)])
def test_category_is_calculated_despite_wrong_client_selection(
    client, finish, expected
):
    card = create(client)
    response = patch(
        client, card, finish=finish, foil=not expected, variant_confirmed=True
    )
    assert response.status_code == 200, response.text
    assert bool(response.json()["foil"]) is expected
    assert response.json()["variant_confirmed"]


def test_seedot_refresh_repairs_category_without_forging_physical_confirmation(client):
    catalogue = {
        **copy.deepcopy(CARD),
        "id": "ex5-71",
        "variants": {"normal": True, "holo": False, "reverse": True},
    }
    client.app.state.pricing.fetch = lambda *_: catalogue
    response = client.post(
        "/api/copies",
        json=values(
            client,
            catalog_id="ex5-71",
            identification_status="confirmed",
            foil=False,
            condition="GD",
            condition_confirmed=True,
        ),
    )
    card = refresh(client, response.json())
    store = client.app.state.store
    # Legacy UI confirmed an illustration holo while retaining Standard.
    with store.connect(write=True) as db:
        db.execute(
            "UPDATE copies SET finish='holo',variant_confirmed=1,variant_verified_at='2026-10-12',variant_verified_by='pat' WHERE id=?",
            (card["id"],),
        )
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["price_category"]["foil"] is True
    assert detail["valuation"]["prudent_cents"] is None
    preview = client.post(
        f"/api/copies/{card['id']}/variant-preview", json={"finish": "holo"}
    )
    assert preview.json()["foil"] is True
    assert client.get(f"/api/copies/{card['id']}").json()["version"] == card["version"]
    after = refresh(client, card)
    assert after["foil"] and after["variant_confirmed"]
    assert (
        after["variant_verified_at"] == "2026-10-12"
        and after["variant_verified_by"] == "pat"
    )
    assert after["reference_cents"] == 42997
    assert not client.get(f"/api/copies/{card['id']}").json()["valuation"][
        "needs_review"
    ]
    assert refresh(client, after)["version"] == after["version"]
    # Automatic categories cannot be overridden by an API client.
    fixed = patch(client, after, foil=False).json()
    assert fixed["foil"] and fixed["variant_verified_at"] == "2026-10-12"
    # A changed edition must not reuse the previous edition's catalogue flags.
    preview = client.post(
        f"/api/copies/{card['id']}/variant-preview", json={"catalog_id": "other-71"}
    )
    assert preview.json()["mode"] == "review"


def test_ambiguous_holo_is_not_priced_until_product_is_documented(client):
    client.app.state.pricing.fetch = lambda catalog_id, *_: {
        **CARD,
        "id": catalog_id,
        "variants": {"normal": True, "holo": True, "reverse": False},
    }
    card = create(client)
    response = patch(
        client, card, finish="holo", variant_confirmed=True, variant_observation=""
    )
    assert response.status_code == 200, response.text
    card = response.json()
    assert card["variant_confirmed"] and card["variant_verified_by"] == "pat"
    assert not card["variant_observation"]
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["valuation"]["price_variant_issue"]
    assert detail["valuation"]["prudent_cents"] is None
    assert (
        patch(
            client, card, reference_price_eur=6.25, price_source="Relevé manuel"
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/copies/{card['id']}/price-refresh",
            json={"expected_version": card["version"]},
        ).status_code
        == 422
    )
    card = patch(
        client,
        card,
        variant_confirmed=True,
        variant_observation="Impression holo du produit spécial vérifiée",
    ).json()
    assert refresh(client, card)["variant_confirmed"]


def test_fresh_catalogue_automatically_prices_holo_original_as_standard(client):
    card = create(client)
    card = patch(client, card, finish="holo_border").json()
    assert not card["variant_confirmed"]
    # Fresh catalogue metadata is used even without an earlier snapshot.
    card = refresh(client, card)
    assert not card["foil"] and card["reference_cents"] == 625
    assert not card[
        "variant_confirmed"
    ]  # A network quote is not a physical examination.
    card = patch(client, card, variant_confirmed=True).json()
    assert card["variant_confirmed"]


def test_old_category_correction_without_finish_returns_to_review(client):
    card = create(client)
    card = patch(client, card, foil=False).json()
    card = refresh(client, card)
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert any(
        "Ancienne correction" in r["label"] for r in detail["valuation"]["reasons"]
    )
    card = patch(client, card, finish="non_holo", variant_confirmed=True).json()
    card = refresh(client, card)
    assert not client.get(f"/api/copies/{card['id']}").json()["valuation"][
        "needs_review"
    ]


def test_manaphy_holo_saves_without_invented_observation_and_uses_parallel_price(
    client,
):
    catalogue = {
        "id": "pop9-2",
        "name": "Manaphy",
        "variants": {"normal": True, "holo": True, "reverse": False},
        "pricing": {
            "cardmarket": {
                "unit": "EUR",
                "updated": "2026-10-12",
                "trend": 3.51,
                "avg30": 2.78,
                "trend-holo": 1.69,
                "avg30-holo": 1.42,
            },
            "tcgplayer": {
                "normal": {"productId": 87147},
                "holofoil": {"productId": 87147},
            },
        },
    }
    client.app.state.pricing.fetch = lambda *_: catalogue
    response = client.post(
        "/api/copies",
        json=values(
            client,
            name="Manaphy",
            catalog_id="pop9-2",
            identification_status="confirmed",
            foil=False,
            condition="NM",
            condition_confirmed=True,
        ),
    )
    card = refresh(client, response.json())
    preview = client.post(
        f"/api/copies/{card['id']}/variant-preview", json={"finish": "holo"}
    )
    assert preview.json()["foil"] is True and preview.json()["mode"] == "automatic"
    response = patch(
        client,
        card,
        finish="holo",
        foil=False,
        variant_confirmed=True,
        variant_observation="",
    )
    assert response.status_code == 200, response.text
    card = response.json()
    assert (
        card["foil"] and card["variant_confirmed"] and not card["variant_observation"]
    )
    card = refresh(client, card)
    assert card["reference_cents"] == 169
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["valuation"]["prudent_cents"] == 142
    assert not detail["price_snapshot"]["variant_check"]
    assert not detail["valuation"]["needs_review"]


def test_baggaid_holo_saves_as_standard_despite_incorrect_catalogue_flags(client):
    catalogue = {
        "id": "bw4-74",
        "name": "Baggaïd",
        "variants": {"normal": True, "holo": False, "reverse": False},
        "pricing": {
            "cardmarket": {
                "unit": "EUR",
                "updated": "2026-10-12",
                "trend": 0.92,
                "avg30": 0.90,
                "trend-holo": 1.54,
                "avg30-holo": 1.22,
            },
            "tcgplayer": {
                "holofoil": {"productId": 88978, "marketPrice": 1.28},
                "reverse-holofoil": {"productId": 88978, "marketPrice": 1.14},
            },
        },
    }
    client.app.state.pricing.fetch = lambda *_: catalogue
    response = client.post(
        "/api/copies",
        json=values(
            client,
            name="Baggaïd",
            catalog_id="bw4-74",
            identification_status="confirmed",
            foil=True,
            condition="NM",
            condition_confirmed=True,
        ),
    )
    assert response.status_code == 201, response.text
    card = refresh(client, response.json())
    preview = client.post(
        f"/api/copies/{card['id']}/variant-preview", json={"finish": "holo"}
    )
    assert preview.json()["foil"] is False and preview.json()["mode"] == "automatic"
    response = patch(
        client,
        card,
        finish="holo",
        foil=True,
        variant_confirmed=True,
        variant_observation="",
    )
    assert response.status_code == 200, response.text
    card = response.json()
    assert not card["foil"] and card["variant_confirmed"]
    assert not card["variant_observation"] and card["variant_verified_by"] == "pat"
    assert card["reference_cents"] is None
    card = refresh(client, card)
    assert card["reference_cents"] == 92
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["valuation"]["prudent_cents"] == 90
    assert not detail["valuation"]["needs_review"]
    assert client.get("/api/copies?review=needed").json()["total"] == 0
    # The reverse remains Foil, including when its price crosses the alert threshold.
    response = patch(client, card, finish="reverse", variant_confirmed=True)
    assert response.status_code == 200, response.text
    card = refresh(client, response.json())
    assert card["foil"] and card["reference_cents"] == 154
    catalogue["pricing"]["cardmarket"]["trend-holo"] = 3.54
    assert not summarize(catalogue, True)["variant_check"]


def test_celebi_finish_metadata_without_euro_prices_is_cached_independently(client):
    catalogue = {
        "id": "np-29",
        "variants": {"normal": False, "holo": True, "reverse": False},
        "pricing": {
            "cardmarket": None,
            "tcgplayer": {
                "unit": "USD",
                "holofoil": {"productId": 84145, "marketPrice": 74.41},
            },
        },
    }
    calls = []

    def metadata(*args):
        calls.append(args)
        return catalogue

    client.app.state.variant_catalogue.fetch = metadata
    response = client.post(
        "/api/copies",
        json=values(
            client,
            name="Celebi",
            catalog_id="np-29",
            identification_status="confirmed",
            foil=False,
            condition="EX",
            condition_confirmed=True,
        ),
    )
    assert response.status_code == 201, response.text
    card = patch(
        client,
        response.json(),
        reference_price_eur=52.10,
        price_source="Ancien relevé manuel",
    ).json()
    before = client.get(f"/api/copies/{card['id']}").json()
    preview = client.post(
        f"/api/copies/{card['id']}/variant-preview", json={"finish": "holo"}
    )
    assert preview.json()["mode"] == "automatic" and preview.json()["foil"] is False
    after = client.get(f"/api/copies/{card['id']}").json()
    assert after["version"] == card["version"] and after["reference_cents"] == 5210
    assert after["history"] == before["history"] and after["price_snapshot"] is None
    card = patch(
        client,
        card,
        finish="holo",
        foil=True,
        variant_confirmed=True,
        variant_observation="",
    ).json()
    assert card["variant_confirmed"] and card["variant_verified_by"] == "pat"
    assert not card["foil"] and not card["variant_observation"]
    assert card["reference_cents"] == 5210
    assert card["price_source"] == before["price_source"]
    assert card["price_date"] == before["price_date"]
    assert len(calls) == 1
    detail = client.get(f"/api/copies/{card['id']}").json()
    row = client.get("/api/copies").json()["items"][0]
    assert detail["price_category"] == row["price_category"]
    assert detail["price_category"]["mode"] == "automatic"
    assert not detail["valuation"]["price_variant_issue"]
    # No euro quote from TCGdex: the dated manual reference stands in for it.
    assert detail["valuation"]["prudent_cents"] == 5210
    assert detail["valuation"]["manual_price"]["source"] == "Ancien relevé manuel"
    assert detail["valuation"]["risk_incomplete"]
    assert not detail["valuation"]["needs_review"]
    with client.app.state.store.connect() as db:
        stored = db.execute(
            "SELECT value FROM catalog_lookups WHERE key LIKE 'variant:%'"
        ).fetchone()[0]
    assert "marketPrice" not in stored and "74.41" not in stored
    # Metadata survives a new resolver and permits a separate manual euro quote.
    from pokeprice.variant_catalogue import VariantCatalogue

    fresh = VariantCatalogue(client.app.state.store, metadata)
    fresh.ensure(card)
    card = patch(
        client, card, reference_price_eur=51, price_source="Nouveau relevé Cardmarket"
    ).json()
    assert card["reference_cents"] == 5100 and card["variant_confirmed"]
    assert len(calls) == 1


def test_physical_holo_confirmation_survives_metadata_outage(client):
    def offline(*_):
        raise RuntimeError("Catalogue hors ligne")

    client.app.state.variant_catalogue.fetch = offline
    card = create(client)
    response = patch(
        client, card, finish="holo", variant_confirmed=True, variant_observation=""
    )
    assert response.status_code == 200, response.text
    card = response.json()
    assert card["variant_confirmed"] and card["variant_verified_by"] == "pat"
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["price_category"]["mode"] == "review"
    assert detail["valuation"]["price_variant_issue"]
    assert (
        patch(
            client, card, reference_price_eur=12, price_source="Relevé manuel"
        ).status_code
        == 422
    )


def test_deoxys_barboach_refresh_repairs_category_and_preserves_physical_holo(client):
    catalogue = {
        "id": "ex8-54",
        "variants": {"normal": True, "holo": False, "reverse": True},
        "pricing": {
            "cardmarket": {
                "unit": "EUR",
                "updated": "2026-10-12",
                "idProduct": 276457,
                "trend": 0.72,
                "avg30": 0.50,
                "trend-holo": 13.52,
                "avg30-holo": 9.32,
            },
        },
    }
    client.app.state.pricing.fetch = lambda *_: catalogue
    response = client.post(
        "/api/copies",
        json=values(
            client,
            name="Barboach",
            catalog_id="ex8-54",
            language="it",
            number="54/107",
            set_name="Deoxys",
            identification_status="confirmed",
            foil=False,
            finish="holo",
            stamp="EX Deoxys",
            variant_confirmed=True,
            variant_observation="",
            condition="EX",
            condition_confirmed=True,
        ),
    )
    assert response.status_code == 201, response.text
    card = response.json()
    # Reproduce the previously saved Standard category without altering the
    # user's observation or its provenance, as on the actual Barboach copy.
    with client.app.state.store.connect(write=True) as db:
        db.execute("UPDATE copies SET foil=0 WHERE id=?", (card["id"],))
    card = client.get(f"/api/copies/{card['id']}").json()
    checked_at = card["variant_verified_at"]
    assert card["price_category"]["foil"] is True
    card = refresh(client, card)
    assert card["foil"] and card["reference_cents"] == 1352
    assert card["finish"] == "holo" and card["stamp"] == "EX Deoxys"
    assert card["variant_confirmed"] and card["variant_verified_by"] == "pat"
    assert card["variant_verified_at"] == checked_at and not card["variant_observation"]
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["valuation"]["prudent_cents"] == 932
    assert not detail["valuation"]["needs_review"]
    assert "isReverseHolo=Y" in detail["cardmarket_url"]
