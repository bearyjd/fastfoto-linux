"""Small-sample statistics in pure Python: Wilson intervals and the zero-event bound."""

from collections.abc import Sequence

Z_95 = 1.959963984540054
ONE_SIDED_ALPHA = 0.05
NO_SAMPLES = "no samples"


def wilson_interval(k: int, n: int) -> tuple[float, float] | None:
    """The 95% Wilson score interval for ``k`` of ``n``; None when ``n`` is 0."""
    raise NotImplementedError


def zero_upper_bound(n: int) -> float | None:
    """The exact one-sided 95% upper bound for 0 events in ``n`` trials; None when ``n`` is 0."""
    raise NotImplementedError


def nearest_rank(values: Sequence[float], percent: int) -> float | None:
    """The nearest-rank percentile of ``values``; None when empty."""
    raise NotImplementedError


def proportion(k: int, n: int) -> dict[str, object]:
    """``k`` of ``n`` with its Wilson interval and, for k = 0, the zero-event upper bound."""
    raise NotImplementedError
