"""The band rule on whole frames as the real scanner sends them (round 2).

A raw frame is full length: the paper, its band, then about 98 mm of white tail (393 mm at 300
dpi). The scanner straightens the paper by rotating the frame, so the pad is everything outside
the rotated rectangle (a slanted lower edge and a wedge up one side, 14 mm wide at 3 degrees),
the paper stays axis-aligned and is often pure 255 like the pad, and the page is a JPEG (quality
90, 4:4:4), which rings around the pad's edge. Numbers only: nothing here is a real pixel.
"""

from dataclasses import replace

import numpy as np
import pytest

from fastfoto_linux.documents.band import BOTTOM_EDGE, band_cut
from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import (
    BACKING_RGB,
    Scene,
    px,
    scanner_page,
    with_jpeg,
    with_text,
)
from tests.documents.helpers import bw_page, colour_page, grey_page

KEEP_MM = 1.0
LEFTOVER_MM = 2.5  # of backing that may stay: the 1 mm kept, the shadow, the blur of the codec
BAND_MM = 10.8  # the shadow and the band of ``scanner_page``
PALE_BACKING = (190, 200, 210)  # 18 from the backing colour, and 40 levels under the paper
FOOTER_RGB = (185, 195, 205)  # a blue-grey 26 from the backing: past 20, inside the band's 36
TILTS = (0.0, 0.5, -0.5, 1.5, 3.0, -3.0)
CASES = (
    [(300, tilt, 255) for tilt in TILTS]
    + [(300, tilt, 250) for tilt in (0.0, 1.5, 3.0, -3.0)]
    + [(200, 1.5, 255), (200, -3.0, 250), (600, 0.0, 255), (600, 3.0, 250)]
)


def frame(dpi: int, **kwargs) -> Scene:
    """A frame before the codec; 600 dpi pages are small in millimetres so that tests stay fast."""
    small = {"width_mm": 60.0, "paper_mm": 40.0} if dpi >= 600 else {}
    return scanner_page(dpi=dpi, **{**small, **kwargs})


def real_page(dpi: int, **kwargs) -> Scene:
    return with_jpeg(frame(dpi, **kwargs))


def painted(scene: Scene, rows: slice, columns: slice, value) -> Scene:
    image = scene.image.copy()
    image[rows, columns] = value
    return replace(scene, image=image)


def assert_band_cut(scene: Scene, result) -> None:
    """The band rule cut: the paper and its edge line whole, at most a few mm of backing left."""
    kept = scene.height - result.bottom
    assert result.band_bottom
    assert scene.paper_end <= kept <= scene.paper_end + px(LEFTOVER_MM, scene.dpi)
    assert (result.left, result.right, result.top) == (0, 0, 0)


# ---- the band is found on the frame the scanner sends ------------------------------------------


@pytest.mark.parametrize(("dpi", "tilt", "tone"), CASES)
def test_the_band_pad_and_white_tail_are_cut_at_every_tilt(
    dpi: int, tilt: float, tone: int
) -> None:
    scene = real_page(dpi, tilt_deg=tilt, paper_tone=tone)
    assert_band_cut(scene, trim_page(colour_page(scene)))


@pytest.mark.parametrize("dpi", [200, 300])
@pytest.mark.parametrize("edge_line", [True, False], ids=["edge-line", "no-edge-line"])
@pytest.mark.parametrize("band_mm", [6.0, 10.0, 15.0])
def test_a_band_of_6_to_15_mm_is_cut_with_or_without_an_edge_line(
    dpi: int, band_mm: float, edge_line: bool
) -> None:
    scene = real_page(dpi, band_mm=band_mm, edge_line=edge_line, tilt_deg=1.5)
    assert_band_cut(scene, trim_page(colour_page(scene)))


@pytest.mark.parametrize("shadow_mm", [0.0, 1.0])
def test_a_shadow_of_up_to_a_millimetre_does_not_stop_the_cut(shadow_mm: float) -> None:
    scene = real_page(300, shadow_mm=shadow_mm, tilt_deg=-1.5)
    assert_band_cut(scene, trim_page(colour_page(scene)))


@pytest.mark.parametrize("tail_mm", [0.0, 30.0, 98.0])
def test_the_band_is_found_above_a_white_tail_of_any_length(tail_mm: float) -> None:
    scene = real_page(300, tail_mm=tail_mm, tilt_deg=1.5)
    assert_band_cut(scene, trim_page(colour_page(scene)))


@pytest.mark.parametrize("tilt", [3.0, -3.0])
def test_pad_at_both_ends_of_the_band_rows_does_not_hide_the_band(tilt: float) -> None:
    """The slanted lower edge and the side wedge lie at opposite ends of the lowest rows, so the
    backing joins neither side of the strip."""
    scene = frame(300, tilt_deg=tilt)
    rows = slice(scene.paper_end, scene.paper_end + px(BAND_MM, 300))
    scene = with_jpeg(
        painted(painted(scene, rows, slice(0, 100), 255), rows, slice(-100, None), 255)
    )
    assert_band_cut(scene, trim_page(colour_page(scene)))


def test_white_that_is_not_pad_stays_with_the_cut_and_must_be_blank() -> None:
    """A speck of ink size anywhere in the 98 mm of tail keeps the band: the removed strip is
    the whole of it, and the tail rule (which keeps the mark) decides instead."""
    scene = frame(300, tilt_deg=1.5)
    row = scene.paper_end + px(BAND_MM + 40.0, 300)
    scene = with_jpeg(painted(scene, slice(row, row + px(3.0, 300)), slice(900, 900 + 36), 30))
    result = trim_page(colour_page(scene))
    assert not result.band_bottom
    assert scene.height - result.bottom >= row + px(3.0, 300)


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_speck_of_one_pixel_in_the_pad_is_noise_and_one_of_ink_size_is_not(dpi: int) -> None:
    scene = frame(dpi, tilt_deg=1.5)
    row = scene.height - px(5.0, dpi)
    noise = with_jpeg(painted(scene, slice(row, row + 1), slice(900, 901), 120))
    assert_band_cut(noise, trim_page(colour_page(noise)))
    dust = with_jpeg(painted(scene, slice(row, row + 3), slice(900, 903), 120))
    assert not trim_page(colour_page(dust)).band_bottom


# ---- what is next to the band is not touched ---------------------------------------------------


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_footer_bar_in_a_shadow_like_blue_grey_two_millimetres_above_the_paper_is_kept(
    dpi: int,
) -> None:
    scene = frame(dpi, edge_line=False, tilt_deg=1.5)
    bar = slice(scene.paper_end - px(6.0, dpi), scene.paper_end - px(2.0, dpi))
    scene = with_jpeg(painted(scene, bar, slice(None), FOOTER_RGB))
    result = trim_page(colour_page(scene))
    assert_band_cut(scene, result)  # the white between the bar and the band ends the band


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_blank_white_slip_wider_than_10_mm_in_the_band_is_not_cut_through(dpi: int) -> None:
    scene = frame(dpi, tilt_deg=1.5)
    rows = slice(scene.paper_end + px(1.0, dpi), scene.paper_end + px(4.0, dpi))
    scene = with_jpeg(painted(scene, rows, slice(px(80.0, dpi), px(100.0, dpi)), 255))
    result = trim_page(colour_page(scene))
    kept = scene.height - result.bottom
    assert result.band_bottom
    assert scene.paper_end + px(4.0, dpi) <= kept <= scene.paper_end + px(4.0 + LEFTOVER_MM, dpi)


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_white_slip_hanging_below_the_paper_end_is_not_cut_through(dpi: int) -> None:
    scene = frame(dpi, tilt_deg=-1.5)
    rows = slice(scene.paper_end - px(3.0, dpi), scene.paper_end + px(3.0, dpi))
    scene = with_jpeg(painted(scene, rows, slice(px(80.0, dpi), px(100.0, dpi)), 255))
    kept = scene.height - trim_page(colour_page(scene)).bottom
    assert kept >= scene.paper_end + px(3.0, dpi)


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_blank_white_slip_narrower_than_10_mm_goes_with_the_band(dpi: int) -> None:
    scene = frame(dpi, tilt_deg=1.5)
    rows = slice(scene.paper_end + px(1.0, dpi), scene.paper_end + px(4.0, dpi))
    scene = with_jpeg(painted(scene, rows, slice(px(80.0, dpi), px(88.0, dpi)), 255))
    assert_band_cut(scene, trim_page(colour_page(scene)))


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_mark_in_the_band_keeps_the_page_whole_of_the_band_rule(dpi: int) -> None:
    scene = frame(dpi, tilt_deg=1.5)
    row = scene.paper_end + px(5.0, dpi)
    scene = with_jpeg(painted(scene, slice(row, row + px(3.0, dpi)), slice(900, 900 + 36), 30))
    assert not trim_page(colour_page(scene)).band_bottom


@pytest.mark.parametrize("dpi", [200, 300])
def test_text_on_the_last_line_of_the_paper_is_kept(dpi: int) -> None:
    scene = frame(dpi, tilt_deg=3.0)
    top = (scene.paper_end - px(1.0, dpi)) * 25.4 / dpi - 2.0 - 2.5
    scene = with_jpeg(with_text(scene, 25, top, 30))
    result = trim_page(colour_page(scene))
    assert result.band_bottom
    assert scene.content is not None
    assert scene.height - result.bottom >= scene.content[3] + px(2.0, dpi)


# ---- limits that stay, and pages without a band ------------------------------------------------


@pytest.mark.parametrize("band_mm", [1.0, 25.0], ids=["too-thin", "too-tall"])
def test_a_band_under_3_mm_or_over_20_mm_is_not_cut_as_a_band(band_mm: float) -> None:
    scene = real_page(300, band_mm=band_mm, shadow_mm=0.0, edge_line=False, tilt_deg=1.5)
    result = trim_page(colour_page(scene))
    assert not result.band_bottom
    assert scene.height - result.bottom >= scene.paper_end


def test_a_pale_margin_printed_to_the_paper_end_is_cut_with_the_band_the_known_limit() -> None:
    scene = frame(300, band_mm=3.0, shadow_mm=0.0, edge_line=False, tilt_deg=1.5)
    pale = slice(scene.paper_end - px(6.0, 300), scene.paper_end)
    scene = with_jpeg(painted(scene, pale, slice(None), PALE_BACKING))
    result = trim_page(colour_page(scene))
    assert result.band_bottom
    assert scene.height - result.bottom < scene.paper_end - px(4.0, 300)


def test_a_pale_margin_taller_than_the_band_cap_is_kept_and_so_is_the_paper() -> None:
    scene = frame(300, shadow_mm=0.0, tilt_deg=1.5)
    pale = slice(scene.paper_end - px(25.0, 300), scene.paper_end)
    scene = with_jpeg(painted(scene, pale, slice(None), PALE_BACKING))
    result = trim_page(colour_page(scene))
    assert not result.band_bottom
    assert scene.height - result.bottom >= scene.paper_end


def test_a_page_with_no_band_is_trimmed_by_the_tail_rule_as_before() -> None:
    scene = real_page(300, band_mm=0.0, shadow_mm=0.0, edge_line=False, paper_tone=240)
    result = trim_page(colour_page(scene))
    assert not result.band_bottom
    assert abs(scene.height - result.bottom - (scene.paper_end + px(3.0, 300))) <= 1


@pytest.mark.parametrize("make", [grey_page, bw_page], ids=["grey", "bw"])
def test_grey_and_bilevel_frames_are_not_cut_by_the_band_rule(make) -> None:
    result = trim_page(make(real_page(200, tilt_deg=1.5)))
    assert (result.left, result.right, result.top) == (0, 0, 0)
    assert not result.band_bottom


def test_a_65_mm_slip_on_the_backing_has_the_band_below_it_cut() -> None:
    scene = frame(300, paper_mm=60.0, tilt_deg=1.5)
    image = scene.image.copy()
    image[: scene.paper_end, : px(25.0, 300)] = BACKING_RGB
    image[: scene.paper_end, px(90.0, 300) :] = BACKING_RGB
    scene = with_jpeg(replace(scene, image=image))
    assert_band_cut(scene, trim_page(colour_page(scene)))


# ---- the rule itself ---------------------------------------------------------------------------


def test_the_band_must_start_within_20_mm_of_the_bottom_of_the_page_it_is_given() -> None:
    body = frame(200, tilt_deg=0.0, tail_mm=0.0).image
    white = np.full((px(15.0, 200), body.shape[1], 3), 255, np.uint8)
    assert band_cut(np.concatenate([body, white]), 200, BOTTOM_EDGE) is not None
    farther = np.full((px(25.0, 200), body.shape[1], 3), 255, np.uint8)
    assert band_cut(np.concatenate([body, farther]), 200, BOTTOM_EDGE) is None


def test_the_input_is_not_modified() -> None:
    scene = real_page(200, tilt_deg=1.5)
    before = scene.image.copy()
    trim_page(colour_page(scene))
    assert np.array_equal(scene.image, before)
