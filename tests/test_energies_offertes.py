"""Les énergies offertes d'un lot se lisent comme un cadeau, à part (décision 0041)."""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from test_pokeprice_lots import add_copy

from pokeprice.inventory import Store
from pokeprice.listing_package import package
from pokeprice.listings import Listings, Storefront
from pokeprice.webapp import create_app


@pytest.fixture
def lot(tmp_path):
    store = Store(tmp_path / "inventory")
    with store.connect(write=True) as db:
        db.executemany("INSERT INTO albums VALUES(?,?)", [("a", "Album A"), ("b", "Album B")])
    paid = [add_copy(store, "a", n)["id"] for n in (1, 2)]
    energy = {"name": "Énergie Feu", "catalog_id": "", "number": "", "set_name": ""}
    gifts = [add_copy(store, "b", n, price=None, **energy)["id"] for n in (1, 2)]
    gifts.append(add_copy(store, "b", 3, price=None, **{**energy, "name": "Énergie Eau"})["id"])
    # Les énergies en premier : l'affichage les remet après les cartes payées.
    listing = Listings(store).publish(gifts + paid, "tester", price_cents=300, lot=True,
                                      title="Doublons")
    with store.connect(write=True) as db:
        sale = store.create_sale({"title": "Doublons", "amount_cents": 300, "asking_cents": 300},
                                 paid + gifts, "tester", _db=db)
    return store, listing["id"], sale, paid, gifts


def public(store, listing_id):
    storefront = Storefront(store)
    with store.connect() as db:
        return storefront.public(storefront.rows(db, listing_id)[0], storefront.cards(db, listing_id))


def test_the_storefront_marks_offered_energies_and_shows_them_last(lot):
    store, listing_id, _, paid, gifts = lot
    items = public(store, listing_id)["items"]
    assert [bool(i.get("offered")) for i in items] == [False, False, True, True, True]
    assert [i["name"] for i in items if i.get("offered")] == ["Énergie Feu", "Énergie Feu", "Énergie Eau"]
    # L'index désigne toujours la photo de la bonne carte.
    assert sorted(i["index"] for i in items) == list(range(5))


def test_a_lone_energy_is_not_a_gift(tmp_path):
    store = Store(tmp_path / "inventory")
    with store.connect(write=True) as db:
        db.execute("INSERT INTO albums VALUES('a','Album A')")
    energy = add_copy(store, "a", 1, price=None, name="Énergie Feu", catalog_id="", number="", set_name="")
    listing = Listings(store).publish([energy["id"]], "tester", price_cents=50)
    assert "offered" not in public(store, listing["id"])["items"][0]


def test_the_listing_package_puts_the_gift_apart(lot, tmp_path):
    store, _, sale, paid, gifts = lot
    target = tmp_path / "lot.zip"
    package(store, sale, target)
    with zipfile.ZipFile(target) as archive:
        text = archive.read("description.txt").decode()
        checks = archive.read("a-completer.txt").decode()
    assert "Lot de 2 carte(s) Pokémon. En cadeau : 3 énergies de base offertes" in text
    gift = text[text.rindex("En cadeau"):].splitlines()[1:]
    assert sorted(gift) == ["- Énergie Eau", "- Énergie Feu × 2"]
    assert "Énergie" not in checks  # rien à vérifier sur un cadeau


def test_the_page_for_robots_counts_only_the_paid_cards(lot):
    store, listing_id, *_ = lot
    with TestClient(create_app(store.root)) as client:
        page = client.get(f"/carte/{listing_id}").text
    assert "Lot de 2 cartes" in page and "Énergies de base offertes : 3." in page
    summary = page[page.index('id="card-summary"'):]
    assert "Énergie" not in summary[summary.index("<ul>"):summary.index("</ul>")]
