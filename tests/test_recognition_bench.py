"""The recognition bench as a non-regression gate (M2): minimum score per measure.

The bench photos and truth stay local (outputs/, never committed): the recorded
run is replayed when present, the live run only on request (POKEPRICE_BENCH=1).
"""

import importlib.util
import json
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/bench_recognition.py"
spec = importlib.util.spec_from_file_location("bench_recognition", SCRIPT)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def entry(copy_id, name="Aquali", number="12/64", **truth):
    return {
        "copy_id": copy_id,
        "label": copy_id,
        "name": name,
        "number": number,
        "truth": {
            "catalog_id": "base2-12",
            "language": "fr",
            "art_holo": True,
            "stamp": False,
            **truth,
        },
    }


def record(**fields):
    return {
        "observation": {"number": "12/64", "language": "fr"},
        "candidates": ["base2-12"],
        "reading": {"artwork": "holo", "stamp_text": ""},
        "proposal": {"status": "examine", "foil": None},
        "confirmed_variant": {"finish": "holo", "foil": False},
        **fields,
    }


def test_a_perfect_run_passes():
    failures, lines = bench.app_regressions([entry("a")], [{"cards": {"a": record()}}])
    assert failures == [] and "examine 1" in lines[-1]


def test_a_measure_below_its_share_is_a_regression():
    # 23/30 (77 %) for the number: 3 good readings out of 4 (75 %) is just below.
    entries = [entry(str(i)) for i in range(4)]
    cards = {str(i): record() for i in range(3)}
    cards["3"] = record(observation={"number": "13/64", "language": "fr"})
    failures, _ = bench.app_regressions(entries, [{"cards": cards}])
    assert len(failures) == 1 and "Numéro" in failures[0]


def test_the_worst_run_decides():
    good = {"cards": {"a": record()}}
    unlucky = {"cards": {"a": record(candidates=["base1-12"])}}
    failures, lines = bench.app_regressions([entry("a")], [good, unlucky])
    assert len(failures) == 1 and "Édition" in failures[0] and "[1/1, 0/1]" in failures[0]


def test_a_proposal_against_the_confirmed_variant_fails_the_bench():
    # A reverse proposed as Standard is the error the review exists to prevent.
    run = {
        "cards": {
            "a": record(
                proposal={"status": "proposed", "foil": False},
                confirmed_variant={"finish": "reverse", "foil": True},
            )
        }
    }
    failures, _ = bench.app_regressions([entry("a")], [run])
    assert failures and "a" in failures[0]


def test_a_cheap_reverse_proposed_as_standard_is_reported_not_failed():
    run = {
        "cards": {
            "a": record(
                proposal={"status": "proposed", "foil": False},
                confirmed_variant={"finish": "reverse", "foil": True},
                valuation={
                    "threshold_cents": 1000,
                    "hypotheses": [{"foil": True, "prudent_cents": 77}],
                },
            )
        }
    }
    failures, lines = bench.app_regressions([entry("a")], [run])
    assert failures == [] and any("tolérées" in line and "(a)" in line for line in lines)


def test_an_unclear_artwork_is_an_abstention_not_a_wrong_reading():
    run = {"cards": {"a": record(reading={"artwork": "unclear", "stamp_text": ""})}}
    scores = bench.app_scores([entry("a")], run)["a"]
    assert scores["art_holo_ok"] is None and scores["art_holo_read"] is False


def test_a_truncated_photo_must_be_refused_not_read():
    gliscor = entry("g", name="Gliscor E4", number="62/111")
    refused = {"observation_error": "Le recto d’une seule carte doit être lisible."}
    scores = bench.app_scores([gliscor], {"cards": {"g": refused}})["g"]
    assert scores["refused_ok"] is True
    assert scores["number_ok"] is scores["language_ok"] is scores["edition_ok"] is None
    guessed = record(observation={"number": "62/111", "language": "en"})
    assert bench.app_scores([gliscor], {"cards": {"g": guessed}})["g"]["refused_ok"] is False


def test_failed_readings_count_as_wrong_and_unknown_truth_is_ignored():
    entries = [entry("a", art_holo=None, stamp=None, catalog_id=None)]
    run = {"cards": {"a": {"observation_error": "Lecture Gemini indisponible"}}}
    scores = bench.app_scores(entries, run)["a"]
    assert scores["number_ok"] is False and scores["language_ok"] is False
    assert scores["edition_ok"] is scores["art_holo_ok"] is scores["stamp_ok"] is None


def test_every_rate_is_printed_with_its_count_and_interval():
    entries = [entry(str(i)) for i in range(4)]
    cards = {str(i): record() for i in range(3)}
    cards["3"] = record(observation={"number": "13/64", "language": "fr"})
    _, lines = bench.app_regressions(entries, [{"cards": cards}])
    number = next(line for line in lines if line.startswith("Numéro"))
    assert "3/4 (IC 95 % : 30–95,4 %)" in number
    language = next(line for line in lines if line.startswith("Langue (lecture de saisie)"))
    assert "4/4 (IC 95 % : 47–100 %)" in language  # No failure: exact one-sided bound.


def test_no_wrong_proposal_is_a_bound_not_a_zero_rate():
    # Variant verified by a person: confirmed in the collection, or bench truth.
    entries = [entry("a"), entry("b", verified_variant=True, foil=False), entry("c")]
    cards = {
        "a": record(),
        "b": record(confirmed_variant=None, proposal={"status": "proposed", "foil": False}),
        "c": record(confirmed_variant=None),  # Nobody verified it: not counted.
    }
    failures, lines = bench.app_regressions(entries, [{"cards": cards}])
    assert failures == []
    assert any("variantes vérifiées" in line and "0/2 (IC 95 % : 0–78 %)" in line for line in lines)
    cards["b"]["proposal"]["foil"] = True  # Against the verified truth, price unknown.
    failures, _ = bench.app_regressions(entries, [{"cards": cards}])
    assert failures and "b" in failures[0]


def test_strata_keep_blind_and_harvested_truths_apart():
    entries = [
        entry("blind", provenance="aveugle"),
        entry("harvested", provenance="recoltee", language="en"),
        entry("old", art_holo=False, reverse=True),
    ]
    cards = {
        "blind": record(),
        "harvested": record(observation={"number": "9/64", "language": "en"}),
        "old": record(reading={"artwork": "matte", "stamp_text": ""}),
    }
    strata = bench.app_strata(entries, [{"cards": cards}])
    provenance = strata["Provenance de la vérité"]
    assert set(provenance) == {
        "vérifiées à l’aveugle",
        "récoltées (confirmation antérieure)",
        "banc initial",
    }
    number = bench.APP_LABELS["number_ok"]
    assert provenance["vérifiées à l’aveugle"][number].text().startswith("1/1 ")
    assert provenance["récoltées (confirmation antérieure)"][number].text().startswith("0/1 ")
    assert set(strata["Langue"]) == {"en", "fr"} and strata["Langue"]["fr"]["cartes"] == 2
    assert set(strata["Finition"]) == {"holo", "reverse"}
    lines = bench.strata_lines(strata)
    assert "Finition : reverse (1 carte)" in lines
    assert any(bench.WRONG in line and "0/1" in line for line in lines)


@pytest.mark.skipif(
    not bench.app_runs(),
    reason="Aucune lecture de l’application enregistrée.",
)
def test_recorded_readings_never_yield_a_proposal_against_a_confirmed_variant():
    """Current rules on recorded readings: a rule regression shows without Gemini.

    The reading scores themselves only move with a live run (``app``).
    """
    entries = json.loads((bench.replay_dir() / "truth.json").read_text())
    wrong = [
        e["label"]
        for run in bench.app_runs()
        for scores in [bench.app_scores(entries, bench.replay(run))]
        for e in entries
        if scores[e["copy_id"]]["wrong_proposal"]
    ]
    assert len(wrong) <= bench.MAX_WRONG_PROPOSALS, wrong


@pytest.mark.skipif(
    not os.environ.get("POKEPRICE_BENCH"),
    reason="Banc réel (Gemini, TCGdex) : POKEPRICE_BENCH=1 pour le lancer.",
)
def test_live_application_meets_the_minimum_scores():
    entries = json.loads((bench.OUT / "truth.json").read_text())
    runs = [bench.run_app(index) for index in range(1, bench.APP_RUNS + 1)]
    failures, lines = bench.app_regressions(entries, runs)
    assert not failures, "\n".join(lines)
