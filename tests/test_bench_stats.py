"""Interval maths of the recognition bench: every rate goes with its count."""

import math

import pytest

from pokeprice.bench_stats import (
    cards_for_bound,
    cards_for_half_width,
    clopper_pearson_bound,
    interval,
    percent,
    wilson,
)


def test_wilson_matches_the_reference_values():
    # 22 editions confirmed out of 27: the interval an outside review computed.
    low, high = wilson(22, 27)
    assert round(low, 3) == 0.633 and round(high, 3) == 0.918
    # Textbook case: 5 out of 10.
    low, high = wilson(5, 10)
    assert round(low, 4) == 0.2366 and round(high, 4) == 0.7634


def test_wilson_stays_within_bounds_and_contains_the_rate():
    for total in (1, 2, 7, 30, 200):
        for good in range(total + 1):
            low, high = wilson(good, total)
            assert 0 <= low <= good / total <= high <= 1


def test_no_failure_gives_an_exact_one_sided_bound():
    # 0 error out of 21: the error rate is under 13.3 %, not zero.
    assert round(clopper_pearson_bound(21), 3) == 0.133
    zero = interval(0, 21)
    assert zero.method == "clopper-pearson" and zero.low == 0
    assert math.isclose((1 - zero.high) ** 21, 0.05)
    full = interval(21, 21)
    assert full.high == 1 and math.isclose(full.low, 1 - zero.high)


def test_mixed_results_use_wilson_and_nothing_measured_says_so():
    assert interval(22, 27).method == "wilson"
    assert interval(22, 27).text() == "22/27 (IC 95 % : 63–91,8 %)"
    assert interval(0, 21).text() == "0/21 (IC 95 % : 0–13 %)"
    assert interval(0, 0).text() == "non mesuré" and interval(0, 0).rate is None


def test_percent_keeps_a_decimal_only_near_the_edges():
    assert percent(0.633) == "63" and percent(0.0495) == "5,0"
    assert percent(0.9926) == "99,26" and percent(1.0) == "100" and percent(0.0) == "0"
    assert percent(0.00011) == "0,01" and percent(0.918) == "91,8"


def test_impossible_counts_are_refused():
    for good, total in ((3, 2), (-1, 4), (0, -1)):
        with pytest.raises(ValueError):
            interval(good, total)


def test_cards_needed_for_a_zero_failure_bound():
    # "Rule of three": about 3 / bound cards without a failure.
    assert cards_for_bound(0.05) == 59
    assert cards_for_bound(0.02) == 149
    assert cards_for_bound(0.01) == 299
    for bound in (0.05, 0.02):
        needed = cards_for_bound(bound)
        assert clopper_pearson_bound(needed) <= bound < clopper_pearson_bound(needed - 1)


def test_cards_needed_for_an_interval_width():
    needed = cards_for_half_width(0.05, share=0.8)
    low, high = wilson(round(0.8 * needed), needed)
    assert 230 <= needed <= 250 and (high - low) / 2 <= 0.051
    # The worst case is a rate of one half; a wider interval needs fewer cards.
    assert cards_for_half_width(0.05) > needed > cards_for_half_width(0.10, share=0.8)
    with pytest.raises(ValueError):
        cards_for_half_width(0.6)
