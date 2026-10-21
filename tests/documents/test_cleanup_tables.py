"""The cleanup tables: pinned values, and the properties proven for every paper level."""

import hashlib

import numpy as np
import pytest

from fastfoto_linux.documents import cleanup_tables as t
from fastfoto_linux.documents.modes import CleanupPolicy
from tests.documents import cleanup_reference as ref

PINS = {CleanupPolicy.LIGHT: "1d072a20e83300fa", CleanupPolicy.STRONG: "9092c7e2543b6c94"}
PRESET_POLICIES = (CleanupPolicy.LIGHT, CleanupPolicy.STRONG)


def digest(table: np.ndarray) -> str:
    return hashlib.sha256(table.astype("<i4").tobytes()).hexdigest()[:16]


@pytest.mark.parametrize("policy", PRESET_POLICIES)
def test_the_table_at_paper_232_is_pinned(policy: CleanupPolicy) -> None:
    assert digest(t.tone_table(policy, 232)) == PINS[policy]


def test_the_constants_are_the_contract_s() -> None:
    assert t.PRESETS[CleanupPolicy.LIGHT] == t.CleanupPreset(245, 4506, 88, 80)
    assert t.PRESETS[CleanupPolicy.STRONG] == t.CleanupPreset(255, 5120, 85, 75)
    assert set(t.PRESETS) == set(PRESET_POLICIES)
    assert (t.INK_LO_PCT, t.INK_HI_PCT, t.TONAL_PCT, t.TONAL_SHARE_PCT) == (78, 90, 92, 20)
    assert (t.BG_WINDOW_MM, t.BG_SMOOTH_MM, t.CELL_MM) == (10.0, 5.0, 4.0)
    assert (t.PAPER_PCT, t.PAPER_MIN_LEVEL, t.STOCK_CHROMA) == (90, 160, 16)
    assert (t.Q_BITS, t.Q, t.BAND_ROWS) == (12, 4096, 512)


@pytest.mark.parametrize("policy", PRESET_POLICIES)
@pytest.mark.parametrize("paper", [0, 1, 37, 100, 159, 160, 200, 232, 250, 255])
def test_production_tables_equal_the_scalar_transcription(
    policy: CleanupPolicy, paper: int
) -> None:
    assert np.array_equal(t.tone_table(policy, paper), ref.tone_table(policy, paper))


@pytest.mark.parametrize("policy", PRESET_POLICIES)
def test_the_proven_properties_hold_for_every_paper_level(policy: CleanupPolicy) -> None:
    levels = np.arange(256, dtype=np.int64)
    for paper in range(256):
        table = t.tone_table(policy, paper).astype(np.int64)
        assert (table >= t.Q).all()
        out = np.minimum(255, (levels[None, :] * table + t.Q // 2) >> t.Q_BITS)
        assert (out >= levels[None, :]).all(), paper  # never darker
        assert (np.diff(out, axis=1) >= 0).all(), paper  # monotone in the input level
        for b in range(1, 256):
            below = levels[: b + 1]
            # contrast to the local paper never drops
            assert (out[b, b] - out[b, below] >= b - below).all(), (paper, b)
            # at or below INK_LO of the local paper: byte-identical
            ink = levels[levels * 100 <= b * t.INK_LO_PCT]
            assert (out[b, ink] == ink).all(), (paper, b)
