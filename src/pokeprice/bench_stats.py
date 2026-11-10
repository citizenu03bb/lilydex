"""Confidence intervals for the recognition bench: a rate never goes without its count.

A bench rate is ``k`` good answers out of ``n`` cards. With a few dozen cards the
rate alone says little: 22/27 is compatible with a true rate anywhere between
63 % and 92 %. Published bounds are rounded away from the rate, never towards it. Every published figure therefore carries a 95 % interval:

- Wilson's score interval when both good and bad answers were observed;
- Clopper–Pearson (exact) when all answers agree, as a one-sided 95 % bound:
  0 error out of 21 says "under 13.3 %", not "0 %".

Standard library only, so that the offline bench replay needs no extra.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Two-sided 95 % normal quantile (Wilson) and one-sided 5 % risk (exact bound).
Z95 = 1.959963984540054
ALPHA = 0.05


@dataclass(frozen=True)
class Interval:
    """``good`` out of ``total``, with the bounds of its 95 % interval (shares)."""

    good: int
    total: int
    low: float
    high: float
    method: str  # "wilson", "clopper-pearson" or "" when nothing was measured

    @property
    def rate(self) -> float | None:
        return self.good / self.total if self.total else None

    def text(self) -> str:
        """``22/27 (IC 95 % : 63,3–91,9 %)``, the form used in reports and docs."""
        if not self.total:
            return "non mesuré"
        return (
            f"{self.good}/{self.total} "
            f"(IC 95 % : {percent(self.low, upper=False)}–{percent(self.high, upper=True)} %)"
        )


def percent(share: float, *, upper: bool) -> str:
    """A bound as a percentage, rounded away from the rate: never tighter than computed.

    A lower bound is rounded down and an upper bound up, to one decimal (two
    under 1 % and over 99 %, where they matter).
    """
    value = round(share * 100, 9)  # Absorbs the noise of the float product.
    if value in (0.0, 100.0):
        return f"{value:.0f}"
    digits = 2 if value < 1 or value > 99 else 1
    scale = 10**digits
    rounded = (math.ceil if upper else math.floor)(round(value * scale, 6)) / scale
    return f"{rounded:.{digits}f}".replace(".", ",")


def check(good: int, total: int) -> None:
    if total < 0 or not 0 <= good <= max(total, 0):
        raise ValueError("Il faut 0 ≤ réussites ≤ total.")


def wilson(good: int, total: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval (two-sided)."""
    check(good, total)
    if not total:
        return 0.0, 1.0
    return wilson_share(good / total, total, z)


def wilson_share(share: float, total: int, z: float = Z95) -> tuple[float, float]:
    """Wilson bounds for an observed share, which planning leaves fractional."""
    denominator = 1 + z * z / total
    centre = (share + z * z / (2 * total)) / denominator
    half = (
        z
        * math.sqrt(share * (1 - share) / total + z * z / (4 * total * total))
        / denominator
    )
    # At the edges the bound is exact: no rounding noise around 0 or 1.
    low = 0.0 if share <= 0 else max(0.0, centre - half)
    high = 1.0 if share >= 1 else min(1.0, centre + half)
    return low, high


def clopper_pearson_bound(total: int, alpha: float = ALPHA) -> float:
    """Exact one-sided bound when all ``total`` answers agree.

    With no failure out of ``total``, the failure rate is below this value at
    the ``1 - alpha`` level: the largest rate ``p`` with ``(1 - p)**total >= alpha``.
    """
    if total < 0:
        raise ValueError("Il faut un total positif.")
    return 1.0 if not total else 1 - alpha ** (1 / total)


def interval(good: int, total: int) -> Interval:
    """The 95 % interval published with a bench rate."""
    check(good, total)
    if not total:
        return Interval(good, total, 0.0, 1.0, "")
    if good == 0:
        return Interval(good, total, 0.0, clopper_pearson_bound(total), "clopper-pearson")
    if good == total:
        return Interval(
            good, total, 1 - clopper_pearson_bound(total), 1.0, "clopper-pearson"
        )
    low, high = wilson(good, total)
    return Interval(good, total, low, high, "wilson")


def cards_for_bound(bound: float, alpha: float = ALPHA) -> int:
    """Cards to verify without a single failure to state "failure rate under ``bound``"."""
    if not 0 < bound < 1:
        raise ValueError("La borne est une part entre 0 et 1.")
    # The rounding absorbs the floating-point noise of an exact quotient.
    return math.ceil(round(math.log(alpha) / math.log(1 - bound), 9))


def cards_for_half_width(half_width: float, share: float = 0.5, z: float = Z95) -> int:
    """Smallest count whose Wilson interval is at most ``± half_width`` at this rate."""
    if not 0 < half_width < 0.5 or not 0 <= share <= 1:
        raise ValueError("Demi-largeur entre 0 et 0,5, taux entre 0 et 1.")
    total = 1
    while True:
        low, high = wilson_share(share, total, z)
        if (high - low) / 2 <= half_width:
            return total
        total += 1
