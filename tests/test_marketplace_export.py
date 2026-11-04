import csv
import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from test_library import inputs

from pokeprice import marketplace_export as mx
from pokeprice.inventory import Store
from pokeprice.inventory_import import import_collection
from pokeprice.listings import Listings

SITE = "https://vitrine.example"
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture(autouse=True)
def default_margin(monkeypatch):
    monkeypatch.delenv(mx.LOT_MAX_MARGIN_ENV, raising=False)


@pytest.fixture
def base(tmp_path):
    """Temporary collection: Évoli alone in the storefront, a lot, two loose cards."""
    store = Store(tmp_path / "inventory")
    import_collection(store, inputs(tmp_path))
    with store.connect(write=True) as db:
        ids = {}
        for row in db.execute("SELECT id,name FROM copies ORDER BY id"):
            ids.setdefault(row["name"], []).append(row["id"])
        db.execute(
            "UPDATE copies SET condition_confirmed=1, variant_confirmed=1, finish='non_holo', "
            "reference_cents=NULL, price_source='Relevé Cardmarket', price_date='2026-10-20' "
            "WHERE identification_status='confirmed' AND name!='Fossile Dôme'"
        )
        db.execute(
            "INSERT INTO catalog_lookups VALUES(?,?,?,?)",
            ("cardmarket-product:dp4-91", 1, json.dumps({"id_product": 12345}), "2026-10-20"),
        )
    zarbi = ids["Zarbi L"]
    listings = Listings(store)
    # Published before the reference quote rises: the export must raise it to the floor.
    single = listings.publish(ids["Évoli"], "test", price_cents=60)
    lot = listings.publish(
        [ids["Unown L"][0], zarbi[2]], "test", price_cents=100, title="Lot Zarbi", lot=True
    )
    with store.connect(write=True) as db:
        db.execute("UPDATE copies SET reference_cents=100 WHERE name='Zarbi L'")
        db.execute("UPDATE copies SET reference_cents=200 WHERE name='Évoli'")
        db.execute("UPDATE copies SET reference_cents=123 WHERE name='Unown L'")
    return store, {"single": single["id"], "lot": lot["id"], "zarbi": zarbi[:2]}


def folders(target):
    return {
        p.name: p.joinpath("annonce.txt").read_text(encoding="utf-8")
        for p in sorted(target.iterdir())
        if p.is_dir()
    }


def section(text, name):
    return text.split(name + "\n", 1)[1].split("\n\n", 1)[0]


def test_prices_never_go_under_the_floor(base, tmp_path):
    store, ids = base
    export = mx.collect(mx.ReadOnlyStore(store.root))
    by_kind = {(a.kind, a.cards[0]["name"]): a for a in export.annonces}
    evoli = by_kind[("carte", "Évoli")]
    assert evoli.price_cents == 60 and evoli.floor_cents == 170
    assert mx.platform_price(evoli.price_cents, evoli.floor_cents, "vinted") == 170
    lot = next(a for a in export.annonces if a.kind == "lot")
    assert lot.floor_cents == 190  # (1.23 + 1.00) less 15 %, rounded up.
    assert mx.platform_price(lot.price_cents, lot.floor_cents, "leboncoin") == 200
    assert mx.platform_price(lot.price_cents, lot.floor_cents, "vinted") == 190
    assert mx.collect(mx.ReadOnlyStore(store.root), margin=50).annonces[0].floor_cents >= 50
    assert mx.floor_price(200, 0) == 200 and mx.floor_price(10, 10) == 50
    assert mx.floor_price(200) == 170
    for bad in (51, -1, 0.1, 15.0, "15", True):
        with pytest.raises(ValueError):
            mx.floor_price(200, bad)
    written, _ = mx.run(store.root, "leboncoin", tmp_path / "lbc", site=SITE)
    assert all(w["price_cents"] % 100 == 0 for w in written)
    texts = folders(tmp_path / "lbc")
    lot_text = next(t for t in texts.values() if "Lot de 2" in t)
    assert section(lot_text, "PRIX") == "2,00 €"
    assert f"{SITE}/carte/{ids['lot']}" in lot_text
    evoli_text = next(t for t in texts.values() if "Nom : Évoli" in t)
    assert section(evoli_text, "PRIX") == "2,00 €"
    assert f"{SITE}/carte/{ids['single']}" in evoli_text
    assert "Langue : Français" in evoli_text and "État : EX (excellent)" in evoli_text
    assert "Variante : Normale" in evoli_text and "Numéro : 59/111" in evoli_text
    assert section(evoli_text, "CATÉGORIE CONSEILLÉE") == mx.CATEGORY["leboncoin"]


def test_unchecked_cards_are_left_out_and_listed(base, tmp_path):
    store, _ = base
    mx.run(store.root, "vinted", tmp_path / "vinted", site=SITE)
    excluded = (tmp_path / "vinted" / "exclues.txt").read_text(encoding="utf-8")
    assert "Fossile Dôme" in excluded and "état à confirmer" in excluded
    assert "variante à confirmer" in excluded
    assert "À identifier" in excluded and "identité à confirmer" in excluded
    texts = folders(tmp_path / "vinted")
    assert len(texts) == 4  # Évoli, the lot and two loose Zarbi.
    assert not any("Fossile" in t or "À identifier" in t for t in texts.values())
    # Loose cards are not in the storefront: no link, but still priced.
    zarbi = [t for t in texts.values() if t.startswith("TITRE\nCarte Pokémon Zarbi")]
    assert len(zarbi) == 2 and all("/carte/" not in t for t in zarbi)
    assert all(section(t, "PRIX") == "1,00 €" for t in zarbi)
    folder = next(p for p in (tmp_path / "vinted").iterdir() if p.is_dir())
    assert (folder / "recto.jpg").is_file() or (folder / "carte01-recto.jpg").is_file()


def test_a_card_in_a_lot_or_reserved_is_not_offered_alone(base):
    store, ids = base
    with store.connect(write=True) as db:
        db.execute("UPDATE copies SET stock_state='reserved' WHERE id=?", (ids["zarbi"][0],))
    export = mx.collect(mx.ReadOnlyStore(store.root))
    singles = [a.cards[0]["id"] for a in export.annonces if a.kind == "carte"]
    assert ids["zarbi"][0] not in singles and ids["zarbi"][1] in singles
    assert not any(a.cards[0]["name"] == "Unown L" for a in export.annonces if a.kind == "carte")


def test_titles_fit_the_platform_limits(base, tmp_path):
    store, _ = base
    with store.connect(write=True) as db:
        db.execute("UPDATE copies SET name=? WHERE name='Évoli'", ("Évoli " + "très long " * 12,))
    for platform in ("vinted", "leboncoin"):
        mx.run(store.root, platform, tmp_path / platform)
        for text in folders(tmp_path / platform).values():
            assert 0 < len(section(text, "TITRE")) <= mx.TITLE_MAX[platform]
    card = {"name": "Zarbi L", "number": "91/106", "set_name": "Duels au Sommets",
            "language": "fr", "condition": "EX", "condition_confirmed": 1}
    title = mx.title(mx.Annonce("carte", [card], 100, 50), "vinted")
    assert title.startswith("Carte Pokémon Zarbi L - 91/106") and len(title) <= 50


def test_cardmarket_csv_follows_the_documented_columns(base, tmp_path):
    store, _ = base
    rows, _ = mx.run(store.root, "cardmarket", tmp_path / "cm")
    assert len(rows) == 1
    path = tmp_path / "cm" / mx.CARDMARKET_FILE
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, delimiter=mx.CARDMARKET_DELIMITER)
        header, *lines = list(reader)
    assert tuple(header) == mx.CARDMARKET_COLUMNS
    assert lines == [["12345", "2", "1.00", "2", "EX", "0", "0", "0", ""]]
    excluded = (tmp_path / "cm" / "exclues.txt").read_text(encoding="utf-8")
    assert "Évoli" in excluded and "produit Cardmarket inconnu" in excluded
    assert "Lot Zarbi" in excluded and "à l’unité" in excluded


def test_cardmarket_skips_a_product_judged_wrong(base):
    store, ids = base
    with store.connect(write=True) as db:
        store.event(db, ids["zarbi"][0], "test", "market-product", "Faux produit", {},
                    {"catalog_id": "dp4-91", "id_product": 12345, "verdict": "wrong"})
    assert mx.cardmarket_products(mx.ReadOnlyStore(store.root)) == {}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(root):
    # A WAL reader creates SQLite's empty -shm/-wal index files: not collection data.
    return sorted(p.name for p in root.rglob("*") if not p.name.endswith(("-shm", "-wal")))


def test_the_base_is_opened_read_only(base, tmp_path):
    store, _ = base
    with store.connect() as db:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = digest(store.database), files(store.root)
    readonly = mx.ReadOnlyStore(store.root)
    with pytest.raises(PermissionError), readonly.connect(write=True):
        pass
    with readonly.connect() as db, pytest.raises(sqlite3.OperationalError, match="readonly"):
        db.execute("UPDATE copies SET name='x'")
    for platform in mx.PLATFORMS:
        mx.run(store.root, platform, tmp_path / platform, site=SITE)
    after = digest(store.database), files(store.root)
    assert before == after
    wal = store.database.with_name(store.database.name + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0
    with pytest.raises(FileNotFoundError):
        mx.ReadOnlyStore(tmp_path / "absente")
    assert not (tmp_path / "absente").exists()


def test_the_output_folder_must_be_new(base, tmp_path):
    store, _ = base
    (tmp_path / "pris").mkdir()
    (tmp_path / "pris" / "autre.txt").write_text("x")
    with pytest.raises(FileExistsError):
        mx.run(store.root, "vinted", tmp_path / "pris")
    with pytest.raises(ValueError):
        mx.run(store.root, "ebay", tmp_path / "neuf")


def test_the_command_reports_what_it_wrote(base, tmp_path, capsys, monkeypatch):

    store, _ = base
    monkeypatch.delenv("POKEPRICE_HOST", raising=False)
    script = Path(__file__).resolve().parents[1] / "scripts" / "export_annonces.py"
    spec = importlib.util.spec_from_file_location("export_annonces", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / "sortie"
    args = ["--data", str(store.root), "--plateforme", "vinted", "--sortie", str(target)]
    assert module.main(args + ["--marge", "20"]) == 0
    out = capsys.readouterr().out
    assert "4 annonce(s)" in out and "exclues.txt" in out and "--site" in out
    assert module.main(args) == 1


def lots_script():
    sys.path.insert(0, str(SCRIPTS))
    try:
        import pokeprice_lots
    finally:
        sys.path.remove(str(SCRIPTS))
    return pokeprice_lots


def test_the_floor_follows_the_rule_of_the_lots(monkeypatch):
    lots = lots_script()
    assert (mx.DEFAULT_LOT_MAX_MARGIN, mx.LOT_MAX_MARGIN_ENV) == (
        lots.DEFAULT_LOT_MAX_MARGIN, lots.LOT_MAX_MARGIN_ENV)
    for raw in (None, "", " ", "0", "10", "15", "33", "50", "80", "-5"):
        if raw is None:
            monkeypatch.delenv(mx.LOT_MAX_MARGIN_ENV, raising=False)
        else:
            monkeypatch.setenv(mx.LOT_MAX_MARGIN_ENV, raw)
        assert mx.lot_max_margin() == lots.lot_max_margin()
        for cents in (0, 1, 99, 123, 223, 1999, 12345):
            assert mx.lot_floor_cents(cents) == lots.lot_floor_cents(cents)
            assert mx.floor_price(cents) == max(50, lots.lot_floor_cents(cents))
    monkeypatch.setenv(mx.LOT_MAX_MARGIN_ENV, "quinze")
    with pytest.raises(ValueError):
        mx.lot_max_margin()
    with pytest.raises(ValueError):
        lots.lot_max_margin()


def test_the_variable_sets_the_margin_and_the_option_overrides_it(base, monkeypatch):
    store, _ = base
    monkeypatch.setenv(mx.LOT_MAX_MARGIN_ENV, "30")
    lot = next(a for a in mx.collect(mx.ReadOnlyStore(store.root)).annonces if a.kind == "lot")
    assert lot.floor_cents == 157  # 2.23 less 30 %, rounded up.
    lot = next(a for a in mx.collect(mx.ReadOnlyStore(store.root), margin=10).annonces
               if a.kind == "lot")
    assert lot.floor_cents == 201
