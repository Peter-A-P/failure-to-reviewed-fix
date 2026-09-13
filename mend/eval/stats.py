"""Confidence intervals. Every reported number carries one (CLAUDE.md, and Rule E).

Two estimators, because the numbers in this project come in two shapes.

Wilson score intervals for proportions: hit rate, test-first rate, confidently-wrong rate,
stay-quiet precision. Wilson rather than the normal approximation because these
proportions sit near 0 or near 1 on samples of about 120, exactly where the normal
approximation produces intervals that run past 0% or 100% and quietly mislead. Wilson
cannot, and it stays sensible at zero successes, which is the case that matters most here:
a confidently-wrong rate of 0 out of 40 is not evidence of a zero rate, and Wilson says so.

Bootstrap percentile intervals for everything else: ARI, purity, completeness,
symptoms-per-root-cause, cost per resolved issue. These are not proportions and have no
closed form, and the bootstrap is the honest way to say how much the number would move on
a different sample of the same size.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

# 95 percent, two-sided. The plan reports 95 percent intervals throughout.
_Z_95 = 1.959963984540054
DEFAULT_RESAMPLES = 2000


@dataclass(frozen=True, slots=True)
class Interval:
    """A point estimate with a two-sided interval and the sample size behind it.

    n is part of the value, not metadata. "20% (4% to 48%)" is a different claim from
    "20% (17% to 23%)", and a table that prints the interval without the n invites the
    reader to guess which one they are looking at.
    """

    estimate: float
    low: float
    high: float
    n: int
    method: str

    def as_percent(self, places: int = 1) -> str:
        return (
            f"{self.estimate * 100:.{places}f}% "
            f"({self.low * 100:.{places}f}% to {self.high * 100:.{places}f}%, n = {self.n})"
        )

    def as_value(self, places: int = 2) -> str:
        return (
            f"{self.estimate:.{places}f} "
            f"({self.low:.{places}f} to {self.high:.{places}f}, n = {self.n})"
        )


def wilson(successes: int, n: int, *, z: float = _Z_95) -> Interval:
    """Wilson score interval for a binomial proportion.

    Defined at n = 0 as the whole unit interval: no observations is not the same as a
    rate of zero, and returning nothing would push the caller into inventing a value.
    """
    if successes < 0 or n < 0 or successes > n:
        raise ValueError("successes must be between 0 and n")
    if n == 0:
        return Interval(0.0, 0.0, 1.0, 0, "wilson")

    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half_width = (z / denominator) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return Interval(p, max(0.0, centre - half_width), min(1.0, centre + half_width), n, "wilson")


def bootstrap[T](
    sample: Sequence[T],
    statistic: Callable[[Sequence[T]], float],
    *,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = 20270705,
    alpha: float = 0.05,
) -> Interval:
    """Percentile bootstrap interval for any statistic of a sample.

    The seed is fixed and stated so that a published interval is reproducible to the digit.
    It is the build's first day, which is as arbitrary as any seed and at least says so.

    Resamples that produce a statistic of NaN (an empty draw, a ratio with a zero
    denominator) are discarded rather than propagated. If too few survive, the interval is
    the whole range of the statistic rather than a confident-looking lie.
    """
    n = len(sample)
    if n == 0:
        return Interval(float("nan"), float("nan"), float("nan"), 0, "bootstrap")

    point = statistic(sample)
    if n == 1:
        return Interval(point, point, point, 1, "bootstrap")

    rng = np.random.default_rng(seed)
    values: list[float] = []
    for _ in range(resamples):
        indices = rng.integers(0, n, size=n)
        draw = [sample[int(i)] for i in indices]
        value = statistic(draw)
        if math.isfinite(value):
            values.append(value)

    if len(values) < resamples // 10:
        return Interval(point, float("-inf"), float("inf"), n, "bootstrap-degenerate")

    low, high = np.percentile(values, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return Interval(point, float(low), float(high), n, "bootstrap")


def paired_difference(
    before: Sequence[float],
    after: Sequence[float],
    *,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = 20270705,
) -> Interval:
    """Bootstrap interval for the mean paired difference (after minus before).

    Paired, because the ablations in PLAN.md section 1 run the same tasks with one part of
    the design removed. Comparing two independent samples would throw away the pairing and
    widen the interval for no reason, and the whole question is whether the difference on
    the same task is real.
    """
    if len(before) != len(after):
        raise ValueError("paired samples must be the same length")
    differences = [b - a for a, b in zip(before, after, strict=True)]
    return bootstrap(
        differences,
        lambda s: float(np.mean(s)) if s else float("nan"),
        resamples=resamples,
        seed=seed,
    )
