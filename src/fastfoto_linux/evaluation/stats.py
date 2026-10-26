"""Small-sample statistics in pure Python: Wilson intervals and the zero-event bound."""

import math
from collections.abc import Sequence

Z_95 = 1.959963984540054
ONE_SIDED_ALPHA = 0.05
NO_SAMPLES = "no samples"


def wilson_interval(k: int, n: int) -> tuple[float, float] | None:
    """The 95% Wilson score interval for ``k`` of ``n``; None when ``n`` is 0."""
    if n <= 0:
        return None
    p = k / n
    z2 = Z_95 * Z_95
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = Z_95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (0.0 if k == 0 else max(0.0, centre - half)), (
        1.0 if k == n else min(1.0, centre + half)
    )


def zero_upper_bound(n: int) -> float | None:
    """The exact one-sided 95% upper bound for 0 events in ``n`` trials; None when ``n`` is 0."""
    if n <= 0:
        return None
    return 1 - ONE_SIDED_ALPHA ** (1 / n)


def nearest_rank(values: Sequence[float], percent: int) -> float | None:
    """The nearest-rank percentile of ``values``; None when empty."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percent / 100 * len(ordered)))
    return ordered[rank - 1]


def proportion(k: int, n: int) -> dict[str, object]:
    """``k`` of ``n`` with its Wilson interval and, for k = 0, the zero-event upper bound."""
    interval = wilson_interval(k, n)
    return {
        "k": k,
        "n": n,
        "p": k / n if n else None,
        "lo": interval[0] if interval else None,
        "hi": interval[1] if interval else None,
        "zero_upper_bound": zero_upper_bound(n) if k == 0 else None,
        "note": None if n else NO_SAMPLES,
    }
