"""Bench sampler and harvest counts, on a synthetic base: nothing real is read."""

import hashlib
import json
import sys

import pytest

from pokeprice import bench_sample
from pokeprice.bench_sample import BLIND_REASON
from pokeprice.inventory import Store
from pokeprice.manage import main


class Base:
    """A throwaway base filled by SQL, as the journal of a real one would read."""

    def __init__(self, folder):
        self.folder = folder
        self.store = Store(folder)
        self.count = 0
        with self.store.connect(write=True) as db:
            for album in ("a1", "a2"):
                db.execute("INSERT INTO albums VALUES(?,?)", (album, f"Classeur {album}"))

    def card(
        self,
        name,
        catalog_id,
        *,
        language="fr",
        finish="",
        confirmed=False,
        album="a1",
        page=1,
        position=1,
        cents=None,
        foil=False,
        variants=None,
        reason="fix variant",
        actor="alice",
        stock="available",
        photo="p.jpg",
        reading_before=False,
        verified_by=None,
        journal=True,
    ):
        self.count += 1
        copy_id = f"copy-{self.count:03d}"
        with self.store.connect(write=True) as db:
            db.execute(
                "INSERT OR IGNORE INTO editions VALUES(?,?,?,?,?,?,1)",
                (f"e-{catalog_id}-{language}", name, "Set", "1/100", language, catalog_id),
            )
            db.execute(
                "INSERT INTO copies(id,source_key,edition_id,name,set_name,number,language,"
                "catalog_id,identification_status,condition,foil,album_id,page,position,photo,"
                "reference_cents,stock_state,created_at,updated_at,finish,variant_confirmed,"
                "variant_verified_by) "
                "VALUES(?,?,?,?,'Set','1/100',?,?,'confirmed','NM',?,?,?,?,?,?,?,'t0','t0',?,?,?)",
                (
                    copy_id,
                    copy_id,
                    f"e-{catalog_id}-{language}",
                    name,
                    language,
                    catalog_id,
                    int(foil),
                    album,
                    page,
                    position,
                    photo,
                    cents,
                    stock,
                    finish,
                    int(confirmed),
                    (actor if verified_by is None else verified_by) if confirmed else "",
                ),
            )
            if variants is not None:
                self.store.event(
                    db,
                    copy_id,
                    "system:prices",
                    "price-snapshot",
                    "relevé",
                    {},
                    {"catalog_id": catalog_id, "variants": variants},
                )
            if reading_before:
                db.execute(
                    "INSERT INTO verifications VALUES(?,?,'variant','gemini','m','p','alice',"
                    "'2000-01-01','{}','{}','{}','{}','','{}')",
                    (f"v-{copy_id}", copy_id),
                )
            if confirmed and journal:
                self.store.event(
                    db,
                    copy_id,
                    actor,
                    "correction",
                    reason,
                    {"variant_confirmed": 0},
                    {"variant_confirmed": 1, "finish": finish},
                )
        return copy_id

    def run(self, **options):
        with bench_sample.open_readonly(self.folder) as db:
            copies = bench_sample.load_copies(db)
            return bench_sample.sample(
                copies, bench_sample.confirmations(db, copies), **options
            )

    def digest(self):
        """The base and its SQLite side files: a reader must leave all of them alone."""
        return {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(self.folder.iterdir())
            if path.name.startswith(self.store.database.name)
        }


@pytest.fixture
def base(tmp_path):
    return Base(tmp_path / "inventory")


def keys(result):
    return {s.key: s for s in result.strata}


def test_confirmations_tell_blind_harvested_and_automated_apart(base):
    base.card("Blind", "s-1", finish="reverse", confirmed=True, reason=BLIND_REASON + " : séance")
    base.card("Typed", "s-2", finish="holo", confirmed=True, reason="Vérification à l'aveugle (banc)")
    base.card("Physical", "s-3", finish="non_holo", confirmed=True, reason="Séance physique : en main")
    base.card("Unknown", "s-4", finish="non_holo", confirmed=True)
    # Blind is refused when a finish reading existed before the confirmation.
    base.card("Seen", "s-5", finish="holo", confirmed=True, reason=BLIND_REASON, reading_before=True)
    base.card("Agent", "s-6", finish="non_holo", confirmed=True, actor="agent:revue")
    base.card("Pending", "s-7")
    # The copy says who confirmed it; the journal alone is not enough.
    base.card("System", "s-8", finish="holo", confirmed=True, verified_by="system:import")
    base.card("Nobody", "s-9", finish="holo", confirmed=True, verified_by="")
    base.card("NoTrace", "s-10", finish="reverse", confirmed=True, verified_by="", journal=False)
    base.card("NoJournal", "s-11", finish="reverse", confirmed=True, journal=False)
    with bench_sample.open_readonly(base.folder) as db:
        copies = bench_sample.load_copies(db)
        found = {c.copy.name: c for c in bench_sample.confirmations(db, copies)}
        counts = bench_sample.harvest(db, base.folder / "photos")
    assert {n: c.provenance for n, c in found.items()} == {
        "Blind": "aveugle",
        "Typed": "aveugle",
        "Physical": "recoltee",
        "Unknown": "recoltee",
        "Seen": "recoltee",
        "Agent": "automate",
        "System": "automate",
        "Nobody": "indeterminee",
        "NoTrace": "indeterminee",
        "NoJournal": "recoltee",
    }
    assert found["Physical"].method == "physique" and found["Unknown"].method == "indeterminee"
    assert found["Seen"].reading_seen and not found["Blind"].reading_seen
    # A model never supplies the truth: the agent's confirmation is counted apart.
    assert counts["confirmees_par_une_personne"] == 6
    assert counts["confirmees_par_un_automate_exclues"] == 2
    # Nobody can be credited: neither a truth nor an automaton, counted apart.
    assert counts["confirmees_sans_auteur_etabli_exclues"] == 2
    assert counts["par_provenance"] == {"aveugle": 2, "recoltee": 4}
    assert counts["par_finition"] == {"autre": 2, "holo": 2, "reverse": 2}
    assert counts["lecture_de_finition_vue_avant"] == 1
    assert counts["photo_presente_sur_disque"] == 0  # No photo file in this base.
    assert "Blind" not in json.dumps(counts)  # Counts only, no card is named.


def test_under_represented_strata_come_first(base):
    # Plenty of verified French mattes; no Japanese, no reverse yet.
    for index in range(12):
        base.card(f"Mat{index}", f"m-{index}", finish="non_holo", confirmed=True)
    plain = [base.card(f"Plain{i}", f"p-{i}", page=1, position=i + 1) for i in range(6)]
    japanese = base.card("Ja", "j-1", language="ja", page=3, position=2)
    reverse = base.card("Rev", "r-1", page=2, position=5, variants={"reverse": True, "normal": True})
    result = base.run(count=3, target_total=15, target_stratum=4)
    chosen = [copy.id for copy, _ in result.cards]
    assert japanese in chosen and reverse in chosen
    assert sum(copy_id in plain for copy_id in chosen) == 1
    reasons = {copy.id: why for copy, why in result.cards}
    assert reasons[japanese] == ("japonais",) and reasons[reverse] == ("reverse",)
    strata = keys(result)
    assert strata["ensemble"].verified == 12 and strata["japonais"].chosen == 1
    assert strata["japonais"].candidates == 1 and strata["japonais"].missing == 3


def test_output_follows_the_binder_and_one_copy_per_print(base):
    base.card("Zed", "z-1", album="a2", page=1, position=1)
    base.card("Twin", "t-1", album="a1", page=9, position=4)
    base.card("Twin", "t-1", album="a1", page=9, position=5)  # Same print: one is enough.
    base.card("First", "f-1", album="a1", page=2, position=7)
    base.card("Early", "e-1", album="a1", page=2, position=3)
    result = base.run(count=10)
    places = [(copy.album_id, copy.page, copy.position) for copy, _ in result.cards]
    assert places == [("a1", 2, 3), ("a1", 2, 7), ("a1", 9, 4), ("a2", 1, 1)]


def test_only_cards_that_can_be_verified_are_proposed(base):
    base.card("Done", "d-1", finish="holo", confirmed=True)
    base.card("Sold", "s-1", stock="sold")
    base.card("NoPhoto", "n-1", photo=None)
    wanted = base.card("Free", "f-1", album="a2")
    base.card("Other", "o-1", album="a1")
    assert [c.id for c, _ in base.run(count=5, albums=["Classeur a2"]).cards] == [wanted]
    assert len(base.run(count=5).cards) == 2
    with pytest.raises(ValueError):
        base.run(count=0)


def test_value_and_neighbour_strata(base):
    costly = base.card("Costly", "c-1", cents=2500, page=4)
    base.card("Pika", "pk-1", page=5, position=1)
    base.card("Pika", "pk-2", page=5, position=2)  # Same name, another print.
    base.card("Lone", "l-1", page=6)
    result = base.run(count=2, target_total=0, target_stratum=5, value_cents=1000)
    reasons = {copy.name: why for copy, why in result.cards}
    assert reasons == {"Costly": ("valeur",), "Pika": ("voisines",)}
    assert result.cards[0][0].id == costly
    assert keys(result)["voisines"].candidates == 2


def test_a_possible_reverse_counts_for_its_observed_share(base):
    # Ten verified cards whose catalogue lists a reverse; two were reverses.
    for index in range(10):
        base.card(
            f"V{index}",
            f"v-{index}",
            finish="reverse" if index < 2 else "non_holo",
            confirmed=True,
            variants={"reverse": True},
        )
    for index in range(8):
        base.card(f"C{index}", f"c-{index}", page=2, position=index + 1, variants={"reverse": True})
    result = base.run(count=8, target_total=0, target_stratum=3)
    reverse = keys(result)["reverse"]
    # One reverse is missing; at one in five, five cards are proposed, not one.
    assert reverse.verified == 2 and reverse.chosen == 5 and reverse.expected == 1.0


def test_blind_only_ignores_harvested_confirmations(base):
    for index in range(3):
        base.card(f"H{index}", f"h-{index}", finish="non_holo", confirmed=True)
    base.card("B", "b-1", finish="non_holo", confirmed=True, reason=BLIND_REASON)
    for index in range(4):
        base.card(f"C{index}", f"c-{index}", page=2, position=index + 1)
    assert len(base.run(count=9, target_total=4, target_stratum=0).cards) == 0
    result = base.run(count=9, target_total=4, target_stratum=0, blind_only=True)
    assert len(result.cards) == 3 and keys(result)["ensemble"].blind == 1


def test_the_sheet_hides_readings_and_the_json_serves_tools(base):
    copy_id = base.card("Secret", "s-1", page=3, position=4, foil=True)
    result = base.run(count=1)
    sheet = bench_sample.as_sheet(result)
    assert "page 3, pochette 4" in sheet and "Secret" not in sheet and "Foil" not in sheet
    assert "Secret" in bench_sample.as_sheet(result, names=True)
    data = bench_sample.as_json(result)
    assert data["cartes"] == [
        {
            "id": copy_id,
            "version": 1,
            "album": "Classeur a1",
            "album_id": "a1",
            "page": 3,
            "pochette": 4,
            "nom": "Secret",
            "numero": "1/100",
            "langue": "fr",
            "motifs": ["reverse"],
        }
    ]
    assert BLIND_REASON in data["consigne"]


def test_the_commands_read_only_and_need_an_explicit_base(base, tmp_path, monkeypatch, capsys):
    base.card("One", "o-1")
    base.card("Two", "t-1", finish="holo", confirmed=True)
    before = base.digest()
    target = tmp_path / "seance.json"
    for arguments in (
        ["bench-harvest"],
        ["bench-sample", "--count", "5", "--output", str(target)],
        ["bench-sample", "--format", "sheet"],
    ):
        monkeypatch.setattr(sys, "argv", ["pokeprice-manage", "--data", str(base.folder), *arguments])
        main()
    output = capsys.readouterr().out
    assert '"confirmees_par_une_personne": 1' in output and "page 1, pochette 1" in output
    assert [c["nom"] for c in json.loads(target.read_text())["cartes"]] == ["One"]
    # Neither the base nor a -wal / -shm side file was touched or created.
    assert base.digest() == before and set(before) >= {"collection.sqlite3"}

    def refused(*arguments):
        monkeypatch.setattr(sys, "argv", ["pokeprice-manage", *arguments])
        with pytest.raises(SystemExit) as stopped:
            main()
        assert stopped.value.code == 2
        return capsys.readouterr().err

    # An existing file is never overwritten, and the default base is never guessed.
    session = target.read_text()
    error = refused("--data", str(base.folder), "bench-sample", "--output", str(target))
    assert "File exists" in error and str(target) in error
    assert target.read_text() == session
    assert "bench-sample exige --data explicite" in refused("bench-sample")
    assert "bench-harvest exige --data explicite" in refused("bench-harvest")
    assert "invalid choice" in refused("--data", str(base.folder), "bench-sample", "--format", "csv")
    assert "au moins une carte" in refused("--data", str(base.folder), "bench-sample", "--count", "0")
    missing = tmp_path / "absent"
    assert "Base introuvable" in refused("--data", str(missing), "bench-harvest")
    assert not missing.exists()  # A read-only command never creates a base.
    assert base.digest() == before


def test_a_base_in_use_keeps_its_data_and_journal(base, monkeypatch, capsys):
    # The application holds the base open: its -wal and -shm files exist.
    import sqlite3

    base.card("One", "o-1")
    holder = sqlite3.connect(base.store.database)
    try:
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("UPDATE albums SET name=name")  # Puts frames in the journal.
        holder.commit()
        before = base.digest()
        assert set(before) == {
            "collection.sqlite3",
            "collection.sqlite3-shm",
            "collection.sqlite3-wal",
        }
        for action in ("bench-harvest", "bench-sample"):
            monkeypatch.setattr(sys, "argv", ["pokeprice-manage", "--data", str(base.folder), action])
            main()
        assert '"nom": "One"' in capsys.readouterr().out
        after = base.digest()
        # SQLite registers a reader in -shm; the data and its journal do not move.
        assert set(after) == set(before)
        for name in ("collection.sqlite3", "collection.sqlite3-wal"):
            assert after[name] == before[name]
    finally:
        holder.close()
