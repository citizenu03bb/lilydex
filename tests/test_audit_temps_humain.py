import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
from test_library import inputs

from pokeprice.inventory import Store
from pokeprice.inventory_import import import_collection

ROOT = Path(__file__).resolve().parent.parent / "scripts"
spec = importlib.util.spec_from_file_location(
    "audit_temps_humain", ROOT / "audit_temps_humain.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

HUMAN = "operatrice-test"
AGENT = "agent:grant-test-1234"


def at(minute, second=0):
    return f"2026-01-10T10:{minute:02d}:{second:02d}+00:00"


@pytest.fixture
def inventory(tmp_path):
    store = Store(tmp_path / "inventory")
    import_collection(store, inputs(tmp_path))
    with store.connect(write=True) as db:
        db.execute(
            "INSERT INTO users(id,username,password_hash,role,created_at) VALUES(?,?,?,?,?)",
            ("u1", HUMAN, "x", "admin", at(0)),
        )
        ids = [r[0] for r in db.execute("SELECT id FROM copies ORDER BY id")]
        db.execute("UPDATE copies SET identification_status='confirmed'")
        db.execute(
            "UPDATE copies SET identification_status='unresolved',reference_cents=NULL WHERE id=?",
            (ids[0],),
        )
        db.execute(
            "UPDATE copies SET identification_status='review',reference_cents=NULL WHERE id IN (?,?)",
            (ids[1], ids[2]),
        )
        # Les imports d'origine ne doivent pas brouiller la mesure.
        db.execute("DELETE FROM events")

        def event(copy_id, actor, kind, created_at, before=None, after=None):
            db.execute(
                "INSERT INTO events(copy_id,actor,kind,reason,before_json,after_json,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    copy_id,
                    actor,
                    kind,
                    "Motif privé de " + HUMAN,
                    json.dumps(before or {}),
                    json.dumps(after or {}),
                    created_at,
                ),
            )

        base = {"name": "Zarbi L", "condition": "EX", "page": 1, "foil": 0}
        # Séance humaine 1 : identité, état (2 min), identité (+ identification
        # dans la même transaction, 4 min), déplacement (1 min).
        event(ids[0], HUMAN, "correction", at(0), base, {**base, "name": "Évoli"})
        event(ids[1], HUMAN, "correction", at(2), base, {**base, "condition": "NM"})
        event(ids[2], HUMAN, "correction", at(6), base, {**base, "number": "1/2"})
        event(ids[2], HUMAN, "identification", at(6, 1))
        event(ids[3], HUMAN, "correction", at(7, 1), base, {**base, "page": 2})
        # Séance humaine 2 après 20 min de pause : variante, prix, puis lot.
        event(ids[0], HUMAN, "correction", at(30), base, {**base, "foil": 1})
        event(ids[1], HUMAN, "variant-validation", at(31))
        event(ids[2], HUMAN, "price-snapshot", at(32, 30))
        # Agent : deux corrections de prix rapides.
        event(ids[4], AGENT, "agent-correction", at(40), {}, {"reference_cents": 120})
        event(ids[5], AGENT, "agent-correction", at(40, 5), {}, {"reference_cents": 80})
        # Automate : import, exclu des médianes humaines.
        event(ids[6], "import", "import", at(50))
        sale = "sale-1"
        db.execute(
            "INSERT INTO sales(id,title,amount_cents,created_at,updated_at) VALUES(?,?,?,?,?)",
            (sale, "Lot test", 500, at(33), at(33)),
        )
        db.execute(
            "INSERT INTO sale_events(sale_id,actor,before_json,after_json,reason,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (sale, HUMAN, "{}", "{}", "Création", at(34)),
        )
    return store


def digest(directory):
    return hashlib.sha256((Path(directory) / "collection.sqlite3").read_bytes()).hexdigest()


def test_sessions_decisions_and_estimates(inventory):
    report = audit.build_report(inventory.root, examine=4)
    assert report["authors"] == {"agent": 1, "automate": 1, "humain": 1}
    assert report["sessions"] == 4
    human = report["decisions"]["humain"]
    assert human["identité"]["decisions"] == 2
    # La première décision d'une séance n'a pas de durée ; l'identification
    # écrite avec la correction ne compte pas pour une décision de plus.
    assert human["identité"]["measured"] == 1
    assert human["identité"]["median_seconds"] == 241.0
    assert human["état"]["median_seconds"] == 120.0
    assert human["déplacement"]["median_seconds"] == 60.0
    assert human["variante"]["decisions"] == 2
    assert human["variante"]["median_seconds"] == 60.0
    assert human["prix"]["median_seconds"] == 90.0
    assert human["lot"]["decisions"] == 1
    assert human["lot"]["median_seconds"] == 90.0
    assert report["decisions"]["agent"]["prix"] == {
        "decisions": 2,
        "measured": 1,
        "median_seconds": 5.0,
        "total_seconds": 5.0,
    }
    queues = report["queues"]
    assert queues["À identifier"]["cards"] == 1
    assert queues["À vérifier"]["cards"] == 2
    assert queues["À vérifier"]["remaining_seconds"] == 482.0
    # Médiane de variante + état humains : 60 et 120.
    assert queues["À examiner"]["median_seconds"] == 90.0
    assert queues["À examiner"]["remaining_seconds"] == 360.0
    first = report["session_details"][0]
    assert first["author"] == "humain-1" and first["active_seconds"] == 421.0
    assert first["by_category"]["identité"] == {"decisions": 2, "seconds": 241.0}


def test_gap_is_configurable(inventory):
    report = audit.build_report(inventory.root, gap_minutes=30, examine=0)
    assert [s["origin"] for s in report["session_details"]] == [
        "humain",
        "agent",
        "automate",
    ]


def test_cli_outputs_have_no_personal_data(inventory, capsys):
    for flags in ([], ["--json"]):
        assert audit.main(["--data", str(inventory.root), *flags]) == 0
        output = capsys.readouterr().out
        assert HUMAN not in output and "grant-test" not in output
        assert "Zarbi" not in output and "Évoli" not in output and "Motif" not in output
        assert "sale-1" not in output
    report = json.loads(output)
    assert report["queues"]["À examiner"]["cards"] is not None
    assert {s["author"] for s in report["session_details"]} == {
        "humain-1",
        "agent-1",
        "automate-1",
    }


def test_data_is_required(capsys):
    with pytest.raises(SystemExit):
        audit.main([])
    assert "--data" in capsys.readouterr().err


def test_missing_database_is_not_created(tmp_path, capsys):
    assert audit.main(["--data", str(tmp_path / "absent")]) == 2
    assert not (tmp_path / "absent").exists()


def test_database_cannot_be_written(inventory):
    before = digest(inventory.root)
    with audit.connect_readonly(inventory.root) as db:
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM events")
        with pytest.raises(sqlite3.OperationalError):
            db.execute(
                "INSERT INTO events(copy_id,actor,kind,reason,before_json,after_json,created_at) "
                "VALUES(NULL,'x','x','x','{}','{}','x')"
            )
    audit.main(["--data", str(inventory.root), "--json"])
    assert digest(inventory.root) == before
    # En mode WAL, SQLite peut créer l'index partagé d'un lecteur ; le journal
    # d'écriture, lui, reste vide.
    wal = inventory.root / "collection.sqlite3-wal"
    assert not wal.exists() or wal.stat().st_size == 0
    with sqlite3.connect(inventory.database) as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 11
