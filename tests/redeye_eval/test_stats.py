"""Wilson intervals, the zero-event bound and nearest-rank percentiles."""

import numpy as np
import pytest

from fastfoto_linux.evaluation.stats import (
    nearest_rank,
    proportion,
    wilson_interval,
    zero_upper_bound,
)

TOL = 1e-9


@pytest.mark.parametrize(
    ("k", "n", "lo", "hi"),
    [
        (0, 10, 0.0, 0.2775327998628899),
        (5, 10, 0.23659309101190405, 0.763406908988096),
        (10, 10, 0.7224672001371101, 1.0),
    ],
)
def test_wilson_literal_values(k, n, lo, hi) -> None:
    got = wilson_interval(k, n)
    assert got is not None
    assert got[0] == pytest.approx(lo, abs=TOL)
    assert got[1] == pytest.approx(hi, abs=TOL)


def test_zero_event_upper_bound_is_exact() -> None:
    assert zero_upper_bound(10) == pytest.approx(0.2589, abs=1e-4)
    assert zero_upper_bound(30) == pytest.approx(0.0950, abs=1e-4)
    assert zero_upper_bound(1) == pytest.approx(0.95)


def test_no_samples_is_none_never_zero_or_one() -> None:
    assert wilson_interval(0, 0) is None
    assert zero_upper_bound(0) is None
    row = proportion(0, 0)
    assert row["p"] is None and row["lo"] is None and row["hi"] is None
    assert row["zero_upper_bound"] is None
    assert row["note"] == "no samples"


def test_proportion_row_for_zero_of_n_carries_the_bound() -> None:
    row = proportion(0, 30)
    assert row["k"] == 0 and row["n"] == 30 and row["p"] == 0.0
    assert row["zero_upper_bound"] == pytest.approx(0.0950, abs=1e-4)
    assert proportion(3, 30)["zero_upper_bound"] is None


def test_seeded_interval_properties() -> None:
    rng = np.random.default_rng(20261026)
    for _ in range(500):
        n = int(rng.integers(1, 400))
        k = int(rng.integers(0, n + 1))
        lo, hi = wilson_interval(k, n)  # type: ignore[misc]
        assert 0.0 <= lo <= k / n <= hi <= 1.0
        mirror_lo, mirror_hi = wilson_interval(n - k, n)  # type: ignore[misc]
        assert lo == pytest.approx(1 - mirror_hi, abs=TOL)
        assert hi == pytest.approx(1 - mirror_lo, abs=TOL)


def test_nearest_rank() -> None:
    values = [5.0, 1.0, 3.0, 2.0, 4.0]
    assert nearest_rank(values, 50) == 3.0
    assert nearest_rank(values, 10) == 1.0
    assert nearest_rank(values, 90) == 5.0
    assert nearest_rank([], 50) is None
