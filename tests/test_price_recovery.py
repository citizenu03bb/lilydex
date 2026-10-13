import json

import pytest

from pokeprice.inventory import Conflict, Store
from pokeprice.price_recovery import ACTOR, PRICE_FIELDS, apply, candidates


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "inventory")
    with store.connect(write=True) as db:
        db.execute("INSERT INTO albums VALUES('test','Test')")
    return store


def quoted(store, *, foil=False, **fields):
    return store.create_copy(
        dict(
            name="Test",
            set_name="Test",
            number="54/107",
            language="it",
            catalog_id="ex8-54",
            album_id="test",
            page=1,
            position=1,
            identification_status="confirmed",
            foil=foil,
            condition="EX",
            condition_confirmed=True,
            reference_cents=1352,
            price_source="Cardmarket trend",
            price_date="2026-10-07",
            **fields,
        ),
        "pat",
        "Relevé historique",
    )


def legacy_loss(store, *, foil=False, finish="non_holo", **fields):
    before = quoted(store, foil=foil, **fields)
    card = store.patch(
        before["id"],
        {"finish": finish, "variant_confirmed": True},
        before["version"],
        "pat",
        "Examen physique",
    )
    # Reproduce the previous release's finish-only invalidation in a test DB.
    with store.connect(write=True) as db:
        db.execute(
            "UPDATE copies SET reference_cents=NULL,price_source='',price_date='' WHERE id=?",
            (card["id"],),
        )
        card = store.get(db, card["id"])
        db.execute(
            "UPDATE events SET after_json=? WHERE copy_id=? AND kind='correction'",
            (json.dumps(card), card["id"]),
        )
    return card


@pytest.mark.parametrize(
    "foil,finish,stamp",
    [(False, "non_holo", ""), (True, "reverse", ""), (True, "holo", "EX Deoxys")],
)
def test_compatible_finish_preserves_sourced_quote(store, foil, finish, stamp):
    card = quoted(store, foil=foil, stamp=stamp)
    after = store.patch(
        card["id"],
        {"finish": finish, "variant_confirmed": True},
        card["version"],
        "pat",
        "Examen physique",
    )
    assert all(after[k] == card[k] for k in PRICE_FIELDS)
    assert after["variant_verified_by"] == "pat" and after["variant_verified_at"]


@pytest.mark.parametrize(
    "changes",
    [
        {"finish": "reverse"},
        {"finish": "special"},
        {"finish": "holo", "stamp": "Promo inconnue"},
        {"finish": "non_holo", "catalog_id": "other-1"},
    ],
)
def test_incompatible_or_ambiguous_product_still_clears_quote(store, changes):
    card = quoted(store)
    after = store.patch(card["id"], changes, card["version"], "pat", "Correction")
    assert after["reference_cents"] is None and not after["price_date"]


def test_recovery_preserves_physical_evidence_and_original_quote_date(store):
    card = legacy_loss(store)
    plan = candidates(store)
    assert len(plan) == 1
    assert apply(store, plan)["restored"] == 1
    with store.connect() as db:
        after = store.get(db, card["id"])
        event = dict(
            db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 1").fetchone()
        )
    assert after["reference_cents"] == 1352 and after["price_date"] == "2026-10-07"
    changed = {k for k in card if card[k] != after[k]}
    assert changed == {*PRICE_FIELDS, "version", "updated_at"}
    assert after["variant_verified_by"] == "pat"
    assert event["actor"] == ACTOR and str(plan[0]["loss_event_id"]) in event["reason"]
    assert (
        candidates(store) == []
    )  # Idempotent: restored cards disappear from the plan.


@pytest.mark.parametrize(
    "changes",
    [
        {
            "reference_cents": 200,
            "price_source": "Nouveau relevé",
            "price_date": "2026-10-13",
        },
        {"catalog_id": "other-1"},
        {"finish": "reverse"},
        {"variant_confirmed": False},
    ],
)
def test_recovery_rejects_new_quotes_or_different_product(store, changes):
    card = legacy_loss(store)
    store.patch(card["id"], changes, card["version"], "pat", "Nouvelle décision")
    assert candidates(store) == []


def test_manual_price_deletion_is_not_recovered(store):
    card = quoted(store, finish="non_holo", variant_confirmed=True)
    store.patch(
        card["id"],
        {"reference_cents": None, "price_source": "", "price_date": ""},
        card["version"],
        "pat",
        "Supprimer le relevé",
    )
    assert candidates(store) == []


def test_recovery_revalidates_the_entire_plan_before_writing(store):
    first, second = legacy_loss(store), legacy_loss(store)
    plan = candidates(store)
    store.patch(
        second["id"], {"notes": "Nouvelle note"}, second["version"], "pat", "Note"
    )
    with pytest.raises(Conflict):
        apply(store, plan)
    with store.connect() as db:
        assert store.get(db, first["id"])["reference_cents"] is None


def test_recovery_accepts_intermediate_category_correction_back_to_original(store):
    card = legacy_loss(store, foil=True, finish="holo", stamp="EX Deoxys")
    with store.connect(write=True) as db:
        wrong = {**card, "foil": 0, "version": card["version"] + 1}
        store.event(
            db, card["id"], "pat", "correction", "Ancienne catégorie", card, wrong
        )
        store.event(
            db, card["id"], "pat", "correction", "Catégorie rétablie", wrong, card
        )
    assert len(candidates(store)) == 1
