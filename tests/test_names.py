import pytest
from test_pricing import client, confirmed  # noqa: F401 - pytest fixture and helper

from pokeprice.names import NameCatalog, Transient


class FakeTCGdex:
    """Answers by URL and counts every request made."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, url):
        self.calls.append(url)
        answer = self.answers.get(url.removeprefix("https://api.tcgdex.net/v2/"))
        if isinstance(answer, Exception):
            raise answer
        return (answer is not None), answer


SETS = {
    "fr/sets/swsh7": {
        "cards": [
            {"id": "swsh7-077", "name": "Banshitrouye"},
            {"id": "swsh7-001", "name": "Chenipan"},
        ]
    },
    "en/sets/swsh7": {"cards": [{"id": "swsh7-077", "name": "Gourgeist"}]},
    "de/sets/swsh7": {"cards": [{"id": "swsh7-077", "name": "Pumpdjinn"}]},
    # Base Set 2 was never released in French: species fallback by Pokédex number.
    "en/sets/base4": {"cards": [{"id": "base4-4", "name": "Charizard"}]},
    "en/cards/base4-4": {"name": "Charizard", "dexId": [6]},
    # A French-only promo: its Pokédex number comes from the French card.
    "fr/sets/2013bw": {"cards": [{"id": "2013bw-5", "name": "Pikachu"}]},
    "fr/cards/2013bw-5": {"name": "Pikachu", "dexId": [25]},
    "en/cards?dexId=eq:25&pagination:itemsPerPage=10": [
        {"name": "Pikachu V"},
        {"name": "Pikachu"},
    ],
    "fr/cards?dexId=eq:6&pagination:itemsPerPage=10": [
        {"name": "Dracaufeu-EX"},
        {"name": "Dracaufeu"},
    ],
}


def catalog(store, fake):
    return NameCatalog(store, fake, pause=0, sleep=lambda _: None)


def test_one_request_per_set_and_language_then_none(client):  # noqa: F811
    store = client.app.state.store
    card = confirmed(client, catalog_id="swsh7-077", position=1)
    fake = FakeTCGdex(SETS)
    stats = catalog(store, fake).refresh(("fr", "en", "de"))
    assert sorted(fake.calls) == sorted(
        f"https://api.tcgdex.net/v2/{lang}/sets/swsh7" for lang in ("fr", "en", "de")
    )
    assert stats["requests"] == 3 and stats["failed"] == [] and not stats["stopped"]
    # Every card of the set is kept: a future binder costs nothing for it.
    assert stats["stored"] == 4
    found = client.get("/api/copies", params={"q": "pumpdjinn"}).json()
    assert [c["id"] for c in found["items"]] == [card["id"]]
    fake.calls.clear()
    assert catalog(store, fake).refresh(("fr", "en", "de"))["requests"] == 0
    assert fake.calls == []


def test_missing_translation_uses_the_species_once_and_is_remembered(client):  # noqa: F811
    store = client.app.state.store
    card = confirmed(client, catalog_id="base4-4", position=2, name="Charizard")
    fake = FakeTCGdex(SETS)
    stats = catalog(store, fake).refresh(("fr", "en"))
    assert stats["species"] == 1
    assert [
        c["id"]
        for c in client.get("/api/copies", params={"q": "dracaufeu"}).json()["items"]
    ] == [card["id"]]
    fake.calls.clear()
    catalog(store, fake).refresh(("fr", "en"))
    assert fake.calls == []  # The French 404 and the species are both cached.


def test_server_errors_back_off_and_stop_without_caching_a_miss(client):  # noqa: F811
    store = client.app.state.store
    for position, set_id in enumerate(("swsh7", "base4", "dp6"), start=3):
        confirmed(client, catalog_id=f"{set_id}-1", position=position)
    busy = FakeTCGdex({f"fr/sets/{s}": Transient(0) for s in ("swsh7", "base4", "dp6")})
    stats = NameCatalog(
        store, busy, pause=0, retries=1, max_failures=2, sleep=lambda _: None
    ).refresh(("fr",))
    assert stats["stopped"] and len(stats["failed"]) == 2
    assert len(busy.calls) == 4  # Two sets tried twice each, then the breaker opens.
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM catalog_lookups").fetchone()[0] == 0


def test_price_refresh_records_the_name_it_already_received(client):  # noqa: F811
    card = confirmed(client, position=6)
    client.post(f"/api/copies/{card['id']}/price-refresh", json={"expected_version": 1})
    with client.app.state.store.connect() as db:
        rows = db.execute(
            "SELECT language, source FROM catalog_names WHERE catalog_id='swsh7-077'"
        ).fetchall()
    assert [tuple(r) for r in rows] == [("en", "edition")]


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_names_are_not_stored(client, value):  # noqa: F811
    with client.app.state.store.connect(write=True) as db:
        NameCatalog.record(db, "x-1", "fr", value, "edition")
        assert db.execute("SELECT count(*) FROM catalog_names").fetchone()[0] == 0


def test_french_only_promo_gets_its_pokedex_number_from_the_french_card(client):  # noqa: F811
    store = client.app.state.store
    confirmed(client, catalog_id="2013bw-5", position=7, name="Pikachu", language="fr")
    fake = FakeTCGdex(SETS)
    catalog(store, fake).refresh(("fr", "en"))
    with store.connect() as db:
        rows = db.execute(
            "SELECT language, name, source FROM catalog_names WHERE catalog_id='2013bw-5' ORDER BY language"
        ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("en", "Pikachu", "species"),
        ("fr", "Pikachu", "edition"),
    ]
