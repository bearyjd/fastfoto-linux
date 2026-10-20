"""Fixed-point straighten maths: trig table, inscribed size, direction and bit-exact warping."""

import hashlib
import math

import numpy as np
import pytest

from fastfoto_linux.photo_edits import PhotoGeometry, apply_geometry
from fastfoto_linux.photo_edits import straighten as st
from tests.photo_edits.straighten_reference import (
    interpolate,
    reference_geometry,
    straightened_frame,
)

ANGLES = range(-150, 151)
SIZES = [(1, 1), (1, 50), (2, 2), (5, 400), (37, 53), (2400, 3600)]
SHAPES = [(37, 53), (53, 37), (64, 64), (5, 400), (200, 300)]


def rgb(height: int, width: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, (height, width, 3), dtype=np.uint8)


def test_constants_are_the_contract_values() -> None:
    assert (st.STRAIGHTEN_LIMIT_TENTHS, st.TRIG_BITS, st.SUBPIXEL, st.TILE) == (150, 24, 32, 512)


def test_trig_table_is_pinned_against_libm_drift() -> None:
    table = [st.trig(t) for t in ANGLES]
    assert hashlib.sha256(repr(table).encode()).hexdigest()[:16] == "093e14ce15c2efbc"
    assert st.trig(0) == (1 << 24, 0)
    assert st.trig(-37)[1] == -st.trig(37)[1] and st.trig(-37)[0] == st.trig(37)[0]


@pytest.mark.parametrize("tenths", [0, 7, -150, 150])
def test_sample_coords_match_a_scalar_python_integer_definition(tenths: int) -> None:
    width, height, frame_w, frame_h = 41, 29, 30, 20
    cos, sin = st.trig(tenths)
    cols, rows = np.array([[0, 7, 29]]), np.array([[0], [5], [19]])
    x, y = st.sample_coords(width, height, frame_w, frame_h, tenths, cols, rows)
    for i, r in enumerate((0, 5, 19)):
        for j, c in enumerate((0, 7, 29)):
            u2, v2 = 2 * c - (frame_w - 1), 2 * r - (frame_h - 1)
            want_x = ((((width - 1) << 24) + u2 * cos + v2 * sin) * 16 + (1 << 23)) >> 24
            want_y = ((((height - 1) << 24) - u2 * sin + v2 * cos) * 16 + (1 << 23)) >> 24
            assert (int(x[i, j]), int(y[i, j])) == (want_x, want_y)


def test_size_at_zero_is_the_source() -> None:
    for width, height in SIZES:
        assert st.straightened_size(width, height, 0) == (width, height)


def test_known_size_tracks_the_float_estimate() -> None:
    width, height = 300, 200
    angle = math.radians(0.7)
    s, c = math.sin(angle), math.cos(angle)
    est_w = ((width - 1) * c - (height - 1) * s) / (c * c - s * s)
    est_h = ((height - 1) * c - (width - 1) * s) / (c * c - s * s)
    fw, fh = st.straightened_size(width, height, 7)
    assert est_w - 1 <= fw <= est_w + 1 and est_h - 1 <= fh <= est_h + 1
    assert fw < width and fh < height


def _inside(width: int, height: int, tenths: int, fw: int, fh: int) -> tuple[bool, bool]:
    cols = np.array([0, fw - 1, 0, fw - 1], dtype=np.int64)
    rows = np.array([0, 0, fh - 1, fh - 1], dtype=np.int64)
    x, y = st.sample_coords(width, height, fw, fh, tenths, cols, rows)
    return (
        bool((x >= 0).all() and (x <= 32 * (width - 1)).all()),
        bool((y >= 0).all() and (y <= 32 * (height - 1)).all()),
    )


@pytest.mark.parametrize(("width", "height"), SIZES)
def test_inscribed_frame_is_inside_and_maximal_for_every_angle(width: int, height: int) -> None:
    for tenths in ANGLES:
        fw, fh = st.straightened_size(width, height, tenths)
        assert 1 <= fw <= width and 1 <= fh <= height
        assert _inside(width, height, tenths, fw, fh) == (True, True), (tenths, fw, fh)
        if fw < width:
            assert not all(_inside(width, height, tenths, fw + 1, fh)), (tenths, "fw")
        if fh < height:
            assert not all(_inside(width, height, tenths, fw, fh + 1)), (tenths, "fh")
        assert st.straightened_size(width, height, -tenths) == (fw, fh)


def test_positive_tenths_rotate_the_content_clockwise() -> None:
    image = np.zeros((101, 101, 3), np.uint8)
    image[50, 70] = 255  # right of the centre
    out = apply_geometry(image, PhotoGeometry(0, None, 150))
    row, col = np.unravel_index(out.sum(axis=-1).argmax(), out.shape[:2])
    assert row > (out.shape[0] - 1) / 2 and col > (out.shape[1] - 1) / 2
    mirrored = apply_geometry(image, PhotoGeometry(0, None, -150))
    row, _ = np.unravel_index(mirrored.sum(axis=-1).argmax(), mirrored.shape[:2])
    assert row < (mirrored.shape[0] - 1) / 2


def test_a_rising_horizon_becomes_level_at_plus_thirty() -> None:
    image = np.full((300, 400, 3), 255, np.uint8)
    slope = math.tan(math.radians(3.0))
    for x in range(400):
        image[round(150 - (x - 200) * slope), x] = 0
    out = apply_geometry(image, PhotoGeometry(0, None, 30))
    rows = out.sum(axis=-1).argmin(axis=0)[20:-20]
    assert rows.max() - rows.min() <= 2


@pytest.mark.parametrize(("height", "width"), SHAPES)
@pytest.mark.parametrize("tenths", [3, -150, 37, 150, -1])
def test_warp_tile_is_bit_identical_to_the_numpy_reference(
    height: int, width: int, tenths: int
) -> None:
    pixels = rgb(height, width, height * 1000 + width)
    fw, fh = st.straightened_size(width, height, tenths)
    rows, cols = np.mgrid[0:fh, 0:fw].astype(np.int64)
    x, y = st.sample_coords(width, height, fw, fh, tenths, cols, rows)
    assert np.array_equal(st.warp_tile(pixels, x, y), interpolate(pixels, x, y))
    for r0, c0 in ((0, 0), (fh // 2, fw // 3)):  # an arbitrary tile equals the whole
        tile = (slice(r0, r0 + 7), slice(c0, c0 + 11))
        assert np.array_equal(
            st.warp_tile(pixels, x[tile], y[tile]), interpolate(pixels, x[tile], y[tile])
        )


@pytest.mark.parametrize("tenths", [0, 1, 37, -150])
def test_interpolation_is_exact_at_lattice_points(tenths: int) -> None:
    pixels = rgb(9, 13, 5)
    ys, xs = np.mgrid[0:9, 0:13].astype(np.int64)
    assert np.array_equal(st.warp_tile(pixels, xs * 32, ys * 32), pixels)
    assert np.array_equal(interpolate(pixels, xs * 32, ys * 32), pixels)


@pytest.mark.parametrize(("height", "width"), SHAPES)
@pytest.mark.parametrize("tenths", [1, -37, 150])
@pytest.mark.parametrize("quarter_turns", [0, 1, 2, 3])
@pytest.mark.parametrize("cropped", [False, True])
def test_apply_geometry_equals_the_reference_exactly(
    height: int, width: int, tenths: int, quarter_turns: int, cropped: bool
) -> None:
    pixels = rgb(height, width, width + height)
    fw, fh = st.straightened_size(width, height, tenths)
    crop = (1, 1, fw - 1, fh - 1) if cropped and fw > 2 and fh > 2 else None
    before = pixels.copy()
    result = apply_geometry(pixels, PhotoGeometry(quarter_turns, crop, tenths))
    assert np.array_equal(result, reference_geometry(pixels, tenths, quarter_turns, crop))
    assert result.dtype == np.uint8 and result.flags.c_contiguous
    assert not np.shares_memory(result, pixels) and np.array_equal(pixels, before)


@pytest.mark.parametrize("quarter_turns", [0, 1, 3])
def test_tiling_across_seams_equals_one_untiled_reference(quarter_turns: int) -> None:
    pixels = rgb(900, 1300, 7)
    tenths = 23
    fw, fh = st.straightened_size(1300, 900, tenths)
    crop = (3, 5, fw - 2, fh - 4)
    assert crop[2] - crop[0] > st.TILE and crop[3] - crop[1] > st.TILE
    result = apply_geometry(pixels, PhotoGeometry(quarter_turns, crop, tenths))
    assert np.array_equal(result, reference_geometry(pixels, tenths, quarter_turns, crop))


def test_the_whole_frame_reference_matches_the_fused_uncropped_pass() -> None:
    pixels = rgb(60, 90, 3)
    assert np.array_equal(
        apply_geometry(pixels, PhotoGeometry(0, None, 11)), straightened_frame(pixels, 11)
    )
