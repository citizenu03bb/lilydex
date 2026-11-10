"""Contrats du paquet pokeprice.lots : la connexion vient de l'appelant, Gemini reste au poste."""

import subprocess
import sys

import pytest

from pokeprice.lots import LotCompositionRecipe, LotsEngine
from test_pokeprice_lots import add_copy, test_db  # noqa: F401 - fixture


def forbid_connections(monkeypatch, store):
    """Après l'ouverture de ``db`` : toute autre connexion du magasin échoue."""

    def connect(*, write=False):
        raise AssertionError("le moteur a ouvert sa propre connexion")

    monkeypatch.setattr(store, "connect", connect)


def test_the_engine_reads_through_the_connection_it_is_given(test_db, monkeypatch):
    _, store = test_db
    cards = [add_copy(store, "b", 40 + i, price=150)["id"] for i in range(2)]
    with store.connect(write=True) as db:
        sale_id = store.create_sale(
            {"title": "Lot", "amount_cents": 300, "asking_cents": 300}, cards, "tester", _db=db
        )
    engine = LotsEngine(store)
    recipe = LotCompositionRecipe(title="Lot", summary="Essai")
    with store.connect() as db:
        forbid_connections(monkeypatch, store)
        assert engine.analyze(db)["total_excess_duplicates"] >= 2
        assert engine.status(db)["active_drafts_count"] == 1
        assert engine.plan_rotation(db, dry_run=True).report["initial_active_drafts"] == 1
        assert engine.compose_from_recipe(db, recipe)["lot"] is not None
        assert engine.publish_lot(db, sale_id, dry_run=True)["copies_count"] == 2


def test_the_engine_reads_the_margin_from_its_connection(test_db, monkeypatch):
    _, store = test_db
    engine = LotsEngine(store)
    recipe = LotCompositionRecipe(title="Lot", summary="Essai", bundle_rules={"target_discount_percent": 90})
    with store.connect() as db:
        forbid_connections(monkeypatch, store)
        assert engine.compose_from_recipe(db, recipe)["lot"]["discount_percent"] == 15


@pytest.mark.parametrize("module", ["pokeprice.lots", "pokeprice.lots.engine"])
def test_the_engine_does_not_load_gemini(module):
    code = (
        f"import sys, {module}; "
        "assert 'pokeprice.lots_prompt' not in sys.modules; "
        "assert 'google.genai' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
