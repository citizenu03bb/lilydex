"""Morning batch: one catalogue request per edition, journal only on change, guide first."""

import copy
import json
import sys

import pytest
from fastapi.testclient import TestClient
from test_intake import values

from pokeprice import cardmarket_guide, market_product, names, pricing
from pokeprice.cardmarket_guide import CardmarketGuide
from pokeprice.inventory import Store
from pokeprice.manage import main
from pokeprice.pricing import PriceService, notable
from pokeprice.webapp import create_app

CARD = {
    "id": "swsh7-077",
    "name": "Gourgeist",
    "hp": 120,
    "variants": {"normal": True, "holo": False, "reverse": False},
    "pricing": {
        "cardmarket": {
            "updated": "2026-10-07T09:52:36.685Z",
            "unit": "EUR",
            "idProduct": 277048,
            "avg": 6.4,
            "low": 4.9,
            "trend": 6.25,
            "avg1": 6.1,
            "avg7": 6.2,
            "avg30": 6.3,
        }
    },
    "_acquisition": {"provider": "TCGdex", "served_language": "en"},
}
GUIDE = {
    "createdAt": "2026-10-23T02:45:11+0200",
    "priceGuides": [
        {"idProduct": 277048, "trend": 9.5, "avg30": 9.1, "low": 8.0, "avg1": 9.4, "avg7": 9.2},
    ],
}
PRODUCTS = {"products": [{"idProduct": 277048, "name": "Gourgeist", "idExpansion": 2848}]}


def files(url):
    return json.dumps(GUIDE if "priceGuide" in url else PRODUCTS).encode()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Any real request fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError("Aucun appel réseau dans les tests.")

    for module in (pricing, cardmarket_guide, market_product, names):
        monkeypatch.setattr(module, "urlopen", refuse)


@pytest.fixture
def client(tmp_path):
    calls = []
    answers = {}

    def fetch(catalog_id, language):
        calls.append((catalog_id, language))
        if catalog_id == "offline-1":
            raise RuntimeError("TCGdex indisponible")
        card = copy.deepcopy(answers.get(catalog_id, CARD))
        card["id"] = catalog_id
        return card

    store = Store(tmp_path / "inventory")
    with TestClient(create_app(store.root, price_fetch=fetch)) as client:
        client.post(
            "/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}
        )
        client.post("/api/albums", json={"name": "Test"})
        client.calls, client.answers, client.fetch = calls, answers, fetch
        yield client


def confirmed(client, position, **overrides):
    response = client.post(
        "/api/copies",
        json=values(
            client,
            **{
                "catalog_id": "swsh7-077",
                "identification_status": "confirmed",
                "condition": "PL",
                "position": position,
                **overrides,
            },
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()


def snapshots(store, copy_id):
    with store.connect() as db:
        return db.execute(
            "SELECT COUNT(*) FROM events WHERE kind='price-snapshot' AND copy_id=?",
            (copy_id,),
        ).fetchone()[0]


def test_copies_of_one_edition_share_a_single_request(client):
    store = client.app.state.store
    english = [confirmed(client, position) for position in (1, 2, 3)]
    french = confirmed(client, 4, language="fr")
    broken = [confirmed(client, p, catalog_id="offline-1") for p in (5, 6)]
    service = PriceService(store, client.fetch)
    summary = service.refresh_many("manage")
    assert sorted(client.calls) == [
        ("offline-1", "en"),
        ("swsh7-077", "en"),
        ("swsh7-077", "fr"),
    ]
    assert summary["selected"] == 6 and summary["editions"] == 3
    assert summary["refreshed"] == 4 and summary["recorded"] == 4
    assert {f["id"] for f in summary["failed"]} == {c["id"] for c in broken}
    for card in english + [french]:
        assert client.get(f"/api/copies/{card['id']}").json()["reference_cents"] == 625


def test_unchanged_price_writes_no_snapshot_and_keeps_the_version(client):
    store = client.app.state.store
    card = confirmed(client, 1)
    service = PriceService(store, client.fetch)
    service.refresh_many("manage")
    first = client.get(f"/api/copies/{card['id']}").json()
    assert snapshots(store, card["id"]) == 1
    # Next morning: TCGdex dates its quote anew, the price is the same.
    newer = copy.deepcopy(CARD)
    newer["pricing"]["cardmarket"]["updated"] = "2026-10-08T09:50:00.000Z"
    client.answers["swsh7-077"] = newer
    summary = service.refresh_many("manage")
    assert summary["refreshed"] == 1 and summary["recorded"] == 0
    assert summary["notable"] == []
    again = client.get(f"/api/copies/{card['id']}").json()
    assert again["version"] == first["version"]
    assert snapshots(store, card["id"]) == 1
    # A new price is a new snapshot, and a notable change above the threshold.
    newer["pricing"]["cardmarket"]["trend"] = 8.0
    summary = service.refresh_many("manage", threshold=0.25)
    assert summary["recorded"] == 1 and snapshots(store, card["id"]) == 2
    assert summary["notable"][0]["before_cents"] == 625
    assert summary["notable"][0]["after_cents"] == 800
    assert service.refresh_many("manage", threshold=0.5)["notable"] == []


def test_a_new_product_alone_is_a_new_snapshot(client):
    store = client.app.state.store
    card = confirmed(client, 1)
    service = PriceService(store, client.fetch)
    service.refresh_many("manage")
    moved = copy.deepcopy(CARD)
    moved["pricing"]["cardmarket"]["idProduct"] = 277049
    client.answers["swsh7-077"] = moved
    assert service.refresh_many("manage")["recorded"] == 1
    assert snapshots(store, card["id"]) == 2


def test_notable_changes_ignore_bulk_cards():
    assert notable(None, 30, 0.2) and notable(30, None, 0.2)
    assert not notable(20, 60, 0.2)  # Under 2 €: lot material.
    assert notable(500, 600, 0.2) and not notable(500, 590, 0.2)


def test_tcgdex_product_becomes_the_cards_catalogue_lookup(client):
    store = client.app.state.store
    confirmed(client, 1)
    PriceService(store, client.fetch).refresh_many("manage")
    with store.connect() as db:
        row = db.execute(
            "SELECT value FROM catalog_lookups WHERE key='cardmarket-product:swsh7-077'"
        ).fetchone()
    assert json.loads(row[0]) == {"id_product": 277048, "name": "Gourgeist", "hp": 120}


def test_from_guide_prices_known_products_without_any_tcgdex_request(client, tmp_path):
    store = client.app.state.store
    known = [confirmed(client, position) for position in (1, 2)]
    unknown = confirmed(client, 3, catalog_id="np-9")
    # TCGdex quotes np-9 without naming its product: no lookup is kept.
    client.answers["np-9"] = copy.deepcopy(CARD)
    del client.answers["np-9"]["pricing"]["cardmarket"]["idProduct"]
    service = PriceService(store, client.fetch)
    service.refresh_many("manage")
    client.calls.clear()
    guide = CardmarketGuide(tmp_path / "cm", store, fetch=files, get_json={}.get)
    summary = service.refresh_from_guide("manage", guide)
    # Only the card without a known product went to TCGdex.
    assert client.calls == [("np-9", "en")]
    assert summary["guide"] == {"created": GUIDE["createdAt"], "priced": 2}
    assert summary["refreshed"] == 3 and summary["editions"] == 1
    assert {n["id"] for n in summary["notable"]} == {c["id"] for c in known}
    for card in known:
        detail = client.get(f"/api/copies/{card['id']}").json()
        assert detail["reference_cents"] == 950
        assert detail["price_source"] == "Cardmarket · guide des prix trend"
        snapshot = detail["price_snapshot"]
        assert snapshot["cardmarket_guide"]["id_product"] == 277048
        assert "cache" in snapshot["cardmarket_guide"]["method"]
        # Variants come from the previous TCGdex snapshot.
        assert snapshot["variants"] == CARD["variants"]
    assert client.get(f"/api/copies/{unknown['id']}").json()["reference_cents"] == 625
    # The same guide the next morning: nothing to journal.
    client.calls.clear()
    again = service.refresh_from_guide("manage", guide)
    assert again["recorded"] == 0 and client.calls == [("np-9", "en")]
    assert snapshots(store, known[0]["id"]) == 2


def test_from_guide_leaves_a_product_judged_wrong_to_the_usual_path(client, tmp_path):
    store = client.app.state.store
    card = confirmed(client, 1)
    service = PriceService(store, client.fetch)
    service.refresh_many("manage")
    with store.connect(write=True) as db:
        store.event(
            db, card["id"], "pat", "market-product", "Produit faux", {},
            {"catalog_id": "swsh7-077", "id_product": 277048, "verdict": "wrong"},
        )
    client.calls.clear()
    guide = CardmarketGuide(tmp_path / "cm", store, fetch=files, get_json={}.get)
    summary = service.refresh_from_guide("manage", guide)
    assert summary["guide"]["priced"] == 0
    assert client.calls == [("swsh7-077", "en")]


def test_from_guide_needs_the_guide(client, tmp_path):
    store = client.app.state.store

    def unavailable(url):
        raise OSError("hors ligne")

    guide = CardmarketGuide(tmp_path / "cm", store, fetch=unavailable, get_json={}.get)
    with pytest.raises(RuntimeError, match="--from-guide"):
        PriceService(store, client.fetch).refresh_from_guide("manage", guide)


def test_manage_prices_from_guide_reports_changes_and_stale_storefront_prices(
    client, monkeypatch, capsys
):
    store = client.app.state.store
    card = confirmed(client, 1)
    PriceService(store, client.fetch).refresh_many("manage")
    from pokeprice.listings import Listings

    listing = Listings(store).publish(
        [card["id"]], "pat", price_cents=630, price_mode="trend",
        price_source="TCGdex · Cardmarket (tendance)",
    )
    # The day's guide is already on disk: the command downloads nothing.
    directory = store.root / "cardmarket"
    directory.mkdir()
    for name, url in cardmarket_guide.FILES.items():
        (directory / name).write_bytes(files(url))
    monkeypatch.setattr(pricing, "fetch_card", client.fetch)
    monkeypatch.setattr(names.NameCatalog, "refresh", lambda self, *a: {})
    monkeypatch.setattr(
        sys,
        "argv",
        ["pokeprice-manage", "--data", str(store.root), "prices", "--from-guide",
         "--threshold", "30"],
    )
    client.calls.clear()
    main()
    report = json.loads(capsys.readouterr().out)
    assert client.calls == []
    assert report["guide"]["priced"] == 1 and report["recorded"] == 1
    assert report["notable"][0]["after_cents"] == 950
    stale = report["stale_storefront"]
    assert stale[0]["listing_id"] == listing["id"]
    assert stale[0]["price_cents"] == 630 and stale[0]["current_cents"] == 950


def quote(**metrics):
    """CARD with other Cardmarket metrics for the same product."""
    card = copy.deepcopy(CARD)
    card["pricing"]["cardmarket"].update(metrics, updated="2026-10-08T09:50:00.000Z")
    return card


def reasons(client, copy_id):
    detail = client.get(f"/api/copies/{copy_id}").json()
    return detail, [r["code"] for r in detail["valuation"]["reasons"]]


# One sale at 20 € on a card that trades around 6 €: the averages diverge.
SPIKE = {"trend": 20.0, "avg1": 20.0, "avg7": 14.0, "avg30": 6.4}


def test_batch_keeps_the_reference_an_unstable_market_would_move(client):
    store = client.app.state.store
    card = confirmed(client, 1)
    service = PriceService(store, client.fetch)
    service.refresh_many("manage")
    before = client.get(f"/api/copies/{card['id']}").json()
    client.answers["swsh7-077"] = quote(**SPIKE)
    summary = service.refresh_many("manage")
    detail, codes = reasons(client, card["id"])
    assert detail["reference_cents"] == 625 and detail["version"] == before["version"]
    assert detail["valuation"]["trend_cents"] == before["valuation"]["trend_cents"]
    assert summary["held"] == [
        {
            "id": card["id"],
            "name": card["name"],
            "catalog_id": "swsh7-077",
            "before_cents": 625,
            "proposed_cents": 2000,
            "source": "TCGdex · Cardmarket trend",
        }
    ]
    assert summary["notable"] == [] and summary["changed"] == 0
    assert "price_held" in codes and detail["valuation"]["needs_review"]
    assert snapshots(store, card["id"]) == 1
    with store.connect() as db:
        held = db.execute(
            "SELECT COUNT(*) FROM events WHERE kind='price-held' AND copy_id=?",
            (card["id"],),
        ).fetchone()[0]
    assert held == 1
    # The same spike the next morning: nothing new to journal.
    again = service.refresh_many("manage")
    assert again["recorded"] == 0 and len(again["held"]) == 1


def test_batch_applies_a_large_move_on_a_steady_market(client):
    store = client.app.state.store
    card = confirmed(client, 1)
    service = PriceService(store, client.fetch)
    service.refresh_many("manage")
    client.answers["swsh7-077"] = quote(trend=9.5, avg1=9.4, avg7=9.2, avg30=9.1)
    summary = service.refresh_many("manage")
    assert summary["held"] == [] and len(summary["notable"]) == 1
    assert client.get(f"/api/copies/{card['id']}").json()["reference_cents"] == 950


def test_a_relevé_by_hand_applies_the_quote_and_ends_the_review(client):
    store = client.app.state.store
    card = confirmed(client, 1)
    service = PriceService(store, client.fetch)
    service.refresh_many("manage")
    client.answers["swsh7-077"] = quote(**SPIKE)
    service.refresh_many("manage")
    detail, _ = reasons(client, card["id"])
    response = client.post(
        f"/api/copies/{card['id']}/price-refresh",
        json={"expected_version": detail["version"]},
    )
    assert response.status_code == 200, response.text
    detail, codes = reasons(client, card["id"])
    assert detail["reference_cents"] == 2000 and "price_held" not in codes


def test_a_steadier_morning_ends_the_review_even_at_the_same_price(client):
    store = client.app.state.store
    card = confirmed(client, 1)
    service = PriceService(store, client.fetch)
    service.refresh_many("manage")
    client.answers["swsh7-077"] = quote(**SPIKE)
    service.refresh_many("manage")
    # The market settles back on the kept reference.
    client.answers["swsh7-077"] = copy.deepcopy(CARD)
    summary = service.refresh_many("manage")
    detail, codes = reasons(client, card["id"])
    assert summary["held"] == [] and summary["recorded"] == 1
    assert detail["reference_cents"] == 625 and "price_held" not in codes


def test_from_guide_keeps_the_reference_an_unstable_guide_would_move(
    client, tmp_path, monkeypatch
):
    store = client.app.state.store
    card = confirmed(client, 1)
    service = PriceService(store, client.fetch)
    service.refresh_many("manage")
    spiked = copy.deepcopy(GUIDE)
    spiked["priceGuides"][0].update(trend=21.0, avg1=21.0, avg7=12.0, avg30=6.5, low=4.0)
    monkeypatch.setitem(globals(), "GUIDE", spiked)
    guide = CardmarketGuide(tmp_path / "cm", store, fetch=files, get_json={}.get)
    summary = service.refresh_from_guide("manage", guide)
    assert summary["guide"]["priced"] == 1
    assert [h["proposed_cents"] for h in summary["held"]] == [2100]
    detail, codes = reasons(client, card["id"])
    assert detail["reference_cents"] == 625 and "price_held" in codes
