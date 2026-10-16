import json

import pytest

from pokeprice.inventory import Conflict, Store
from pokeprice.page_shift import ACTOR, apply, candidates


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "inventory")
    with store.connect(write=True) as db:
        for album in ("platinium", "platinium-3x3"):
            db.execute("INSERT INTO albums VALUES(?,?)", (album, album))
    return store


def imported(store, album, page, position=1):
    copy = store.create_copy(
        dict(
            name="Test",
            set_name="Test",
            number="1/100",
            language="fr",
            album_id=album,
            page=page,
            position=position,
            identification_status="review",
            foil=False,
            condition="EX",
        ),
        "import",
        "Import",
    )
    raw = {"Album_ID": album, "Page": page, "Position": position}
    with store.connect(write=True) as db:
        db.execute(
            "INSERT INTO sources VALUES(?,?,?,?)",
            (copy["id"], json.dumps(raw), "0" * 64, "2026-10-04"),
        )
    return copy


def page_of(store, copy):
    with store.connect() as db:
        return store.get(db, copy["id"])["page"]


def test_shifts_only_cover_counted_albums_and_untouched_copies(store):
    shifted = imported(store, "platinium", 3)
    physical = imported(store, "platinium-3x3", 3)
    by_hand = imported(store, "platinium", 5)
    by_hand = store.patch(by_hand["id"], {"page": 4}, by_hand["version"], "pat", "fix")
    moved_back = imported(store, "platinium", 7)
    moved_back = store.patch(moved_back["id"], {"page": 9}, moved_back["version"], "pat", "fix")
    store.patch(moved_back["id"], {"page": 7}, moved_back["version"], "pat", "fix")
    manual = store.create_copy(
        dict(
            name="Test", set_name="Test", number="1/100", language="fr",
            album_id="platinium", page=6, position=1,
            identification_status="review", foil=False, condition="EX",
        ),
        "pat",
        "Ajout manuel",
    )
    plan = candidates(store)
    assert [p["copy_id"] for p in plan] == [shifted["id"]]
    assert apply(store, plan)["renumbered"] == 1
    assert [page_of(store, c) for c in (shifted, physical, by_hand, moved_back, manual)] == [
        2, 3, 4, 7, 6
    ]
    with store.connect() as db:
        event = db.execute(
            "SELECT actor FROM events WHERE copy_id=? ORDER BY id DESC", (shifted["id"],)
        ).fetchone()
    assert event["actor"] == ACTOR
    assert candidates(store) == []


def test_apply_refuses_a_stale_plan(store):
    copy = imported(store, "platinium", 3)
    plan = candidates(store)
    store.patch(copy["id"], {"notes": "vu"}, copy["version"], "pat", "note")
    with pytest.raises(Conflict):
        apply(store, plan)
    assert page_of(store, copy) == 3
