"""Despeckle on generated pages: what goes, what must stay, and each abstain status."""

import cv2
import numpy as np
import pytest
from fastfoto_linux.documents.despeckle import DespeckleStatus, despeckle_white
from fastfoto_linux.documents.despeckle_tables import guard_px, speck_px

from fastfoto_linux.documents import cleanup, despeckle
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode
from tests.documents import despeckle_fixtures as fx

APPLIED, NONE = DespeckleStatus.APPLIED, DespeckleStatus.NONE


def test_dust_is_all_removed() -> None:
    page = fx.dust()
    result = despeckle_white(page, fx.DPI)
    assert (result.status, result.removed) == (APPLIED, 40)
    assert result.pixels is not None
    assert result.pixels.all()
    assert not page.all()  # the input is not modified


@pytest.mark.parametrize("make", [fx.text_line, fx.colon, fx.ellipsis, fx.halftone])
def test_punctuation_and_halftone_are_kept(make) -> None:
    result = despeckle_white(make(), fx.DPI)
    assert (result.status, result.pixels, result.removed) == (NONE, None, 0)


def test_the_hairlines_are_kept() -> None:
    assert despeckle_white(fx.hairline(), fx.DPI).status is NONE


def test_a_diagonal_speck_is_one_component_with_eight_connectivity() -> None:
    result = despeckle_white(fx.diagonal_speck(), fx.DPI)
    assert (result.status, result.removed) == (APPLIED, 1)


def test_the_labelling_asks_for_eight_connectivity(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []
    original = cv2.connectedComponentsWithStats

    def spy(image, *args, **kwargs):
        seen.append(kwargs.get("connectivity", args[0] if args else 8))
        return original(image, *args, **kwargs)

    monkeypatch.setattr(cv2, "connectedComponentsWithStats", spy)
    despeckle_white(fx.dust(), fx.DPI)
    assert seen
    assert set(seen) == {8}


def test_a_dotted_leader_at_1_5_mm_is_kept_and_at_3_mm_is_removed() -> None:
    assert despeckle_white(fx.dotted_leader(1.5), fx.DPI).status is NONE
    result = despeckle_white(fx.dotted_leader(3.0), fx.DPI)
    assert (result.status, result.removed) == (APPLIED, 20)


def test_the_size_cap_is_inclusive() -> None:
    assert despeckle_white(fx.speck(4), fx.DPI).status is NONE  # 4 > s = 3
    result = despeckle_white(fx.speck(3), fx.DPI)  # 3 <= s
    assert (result.status, result.removed) == (APPLIED, 1)


def test_a_wide_flat_speck_over_the_cap_on_one_axis_is_kept() -> None:
    page = fx.blank()
    fx.ink(page, 500, 500, 1, 4)
    assert despeckle_white(page, fx.DPI).status is NONE


def test_a_red_dot_is_kept_with_a_colour_source_and_removed_without() -> None:
    white, source = fx.red_dot()
    kept = despeckle_white(white, fx.DPI, source=source)
    assert (kept.status, kept.removed) == (APPLIED, 1)  # only the grey speck goes
    assert kept.pixels is not None
    assert not kept.pixels[500:503, 500:503].any()
    assert kept.pixels[900:903, 900:903].all()
    both = despeckle_white(white, fx.DPI)
    assert both.removed == 2


def test_a_sparse_field_is_busy_and_untouched() -> None:
    result = despeckle_white(fx.sparse_field(), fx.DPI)
    assert (result.status, result.pixels, result.removed) == (DespeckleStatus.BUSY, None, 0)


def test_the_two_round_case_is_removed_whole(monkeypatch: pytest.MonkeyPatch) -> None:
    page = fx.asymmetric()
    result = despeckle_white(page, fx.DPI)
    assert (result.status, result.removed) == (APPLIED, 2)
    assert result.pixels is not None
    assert result.pixels.all()
    monkeypatch.setattr(despeckle, "MAX_ROUNDS", 1)
    again = despeckle_white(page, fx.DPI)
    assert (again.status, again.pixels) == (DespeckleStatus.UNSTABLE, None)


def test_below_150_dpi_is_low_dpi() -> None:
    result = despeckle_white(fx.dust(), 149)
    assert (result.status, result.pixels) == (DespeckleStatus.LOW_DPI, None)


def test_the_status_names() -> None:
    assert {s.value for s in DespeckleStatus} == {
        "off",
        "not_bw",
        "low_dpi",
        "too_large",
        "busy",
        "unstable",
        "none",
        "applied",
    }


@pytest.mark.parametrize("dpi", [300, 600])
@pytest.mark.parametrize("delta", [-1, 0, 1, 2])
def test_work_too_large_agrees_with_cleanup(
    monkeypatch: pytest.MonkeyPatch, dpi: int, delta: int
) -> None:
    monkeypatch.setattr(cleanup, "MAX_WORK_PIXELS", 10_000)
    f = dpi // cleanup.WORK_DPI
    height = 100 * f + (1 if delta == 2 else 0)
    width = (10_000 // 100) * f + delta * f
    grey = np.full((height, width), 200, dtype=np.uint8)
    too_large = cleanup.work_too_large(height, width, dpi)
    status = cleanup.clean_pixels(grey, dpi, ColourMode.GREY, CleanupPolicy.LIGHT).status
    assert too_large is (status is cleanup.CleanupStatus.TOO_LARGE)
    assert cleanup.work_too_large(100 * f, 100 * f, dpi) is False
    assert cleanup.work_too_large(100 * f, 100 * f + f, dpi) is True


def test_work_too_large_uses_the_real_limit() -> None:
    assert cleanup.work_too_large(4000, 6000, 300) is False  # 2000 x 3000 = 6M
    assert cleanup.work_too_large(6000, 8200, 300) is True  # 3000 x 4100 = 12.3M


def test_a_page_too_large_for_the_work_grid_abstains(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cleanup, "MAX_WORK_PIXELS", 100)
    result = despeckle_white(fx.dust(), fx.DPI)
    assert (result.status, result.pixels) == (DespeckleStatus.TOO_LARGE, None)


@pytest.mark.parametrize("dpi", range(150, 1201))
def test_the_thresholds_never_pass_their_millimetres(dpi: int) -> None:
    assert speck_px(dpi) * 25400 <= 300 * dpi
    assert (speck_px(dpi) + 1) * 25400 > 300 * dpi  # the largest whole pixel count
    assert guard_px(dpi) * 25400 >= 2500 * dpi
    assert (guard_px(dpi) - 1) * 25400 < 2500 * dpi  # the smallest


def test_the_thresholds_at_the_common_resolutions() -> None:
    assert (speck_px(300), guard_px(300)) == (3, 30)
    assert (speck_px(600), guard_px(600)) == (7, 60)
