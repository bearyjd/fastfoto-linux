"""Paper cleanup on generated pages: equal to the reference, banded or not, and what survives."""

import threading
import tracemalloc

import numpy as np
import pytest

from fastfoto_linux.documents import cleanup
from fastfoto_linux.documents.encode import effective_cleanup, encode_page, render_page
from fastfoto_linux.documents.errors import DocumentCancelledError
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode
from tests.documents import cleanup_fixtures as fx
from tests.documents import cleanup_reference as ref

POLICIES = (CleanupPolicy.LIGHT, CleanupPolicy.STRONG)
OUTPUTS = (ColourMode.GREY, ColourMode.COLOUR)
NAMES = tuple(fx.FIXTURES)


def page_of(fixture: fx.Fixture) -> LoadedPage:
    return LoadedPage(fixture.pixels, ColourMode.COLOUR, fixture.dpi)


def render(fixture: fx.Fixture, mode: ColourMode, policy: CleanupPolicy) -> np.ndarray:
    return render_page(page_of(fixture), mode, policy)


def assert_matches_reference(
    src: np.ndarray, dpi: int, output: ColourMode, policy: CleanupPolicy
) -> str:
    status, expected = ref.reference(src, dpi, output, policy)
    result = cleanup.clean_pixels(src, dpi, output, policy)
    assert result.status.value == status
    if expected is None:
        assert result.pixels is None
    else:
        assert result.pixels is not None
        assert result.pixels.dtype == np.uint8
        assert np.array_equal(result.pixels, expected)
    return status


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("output", OUTPUTS)
def test_every_fixture_equals_the_reference(
    name: str, policy: CleanupPolicy, output: ColourMode
) -> None:
    assert_matches_reference(fx.FIXTURES[name]().pixels, fx.DPI, output, policy)


@pytest.mark.parametrize("policy", POLICIES)
def test_a_grey_source_equals_the_reference(policy: CleanupPolicy) -> None:
    grey = np.ascontiguousarray(fx.shaded_paper().pixels[..., 0])
    assert assert_matches_reference(grey, fx.DPI, ColourMode.GREY, policy) == "applied"


@pytest.mark.parametrize("seed", [1, 2])
@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("output", OUTPUTS)
def test_random_noise_equals_the_reference(seed: int, policy: CleanupPolicy, output: ColourMode):
    assert_matches_reference(fx.noise_page(seed).pixels, fx.DPI, output, policy)


@pytest.mark.parametrize(
    "shape", [(877, 1003, 600), (901, 667, 600), (613, 701, 300), (97, 61, 600)]
)
@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("output", OUTPUTS)
def test_odd_sizes_at_600_and_300_dpi_equal_the_reference(
    shape: tuple[int, int, int], policy: CleanupPolicy, output: ColourMode
) -> None:
    height, width, dpi = shape
    page = fx.odd_size_page(dpi, height, width)
    status = assert_matches_reference(page.pixels, dpi, output, policy)
    assert status == "applied" or (height, width) == (97, 61)


@pytest.mark.parametrize("rows", [7, 64, 513])
@pytest.mark.parametrize("output", OUTPUTS)
def test_banding_does_not_change_a_pixel(
    rows: int, output: ColourMode, monkeypatch: pytest.MonkeyPatch
) -> None:
    pages = (fx.shaded_paper().pixels, fx.photo_region().pixels, fx.odd_size_page().pixels)
    dpis = (fx.DPI, fx.DPI, 600)
    whole = [
        cleanup.clean_pixels(p, d, output, CleanupPolicy.STRONG).pixels
        for p, d in zip(pages, dpis, strict=True)
    ]
    monkeypatch.setattr(cleanup, "BAND_ROWS", rows)
    for pixels, dpi, expected in zip(pages, dpis, whole, strict=True):
        banded = cleanup.clean_pixels(pixels, dpi, output, CleanupPolicy.STRONG).pixels
        assert expected is not None
        assert np.array_equal(banded, expected)


def test_two_runs_give_identical_bytes() -> None:
    pixels = fx.shaded_paper().pixels
    first = cleanup.clean_pixels(pixels, fx.DPI, ColourMode.COLOUR, CleanupPolicy.STRONG).pixels
    second = cleanup.clean_pixels(pixels, fx.DPI, ColourMode.COLOUR, CleanupPolicy.STRONG).pixels
    assert first is not None and second is not None
    assert first.tobytes() == second.tobytes()


def test_the_input_is_not_modified() -> None:
    pixels = fx.shaded_paper().pixels
    before = pixels.copy()
    cleanup.clean_pixels(pixels, fx.DPI, ColourMode.COLOUR, CleanupPolicy.STRONG)
    assert np.array_equal(pixels, before)


# --- survival --------------------------------------------------------------------------------


def baseline(fixture: fx.Fixture, mode: ColourMode) -> np.ndarray:
    return render(fixture, mode, CleanupPolicy.OFF)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("output", OUTPUTS)
def test_never_darker_and_dark_ink_is_byte_identical(
    name: str, policy: CleanupPolicy, output: ColourMode
) -> None:
    fixture = fx.FIXTURES[name]()
    before, after = baseline(fixture, output), render(fixture, output, policy)
    assert (after >= before).all()
    ink = before <= 60 if output is ColourMode.GREY else (before <= 60).all(axis=2)
    assert np.array_equal(after[ink], before[ink])


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("output", OUTPUTS)
@pytest.mark.parametrize(
    ("name", "mask"),
    [
        ("red_annotation", "red"),
        ("stamp", "pink"),
        ("punctuation_dot", "dot"),
        ("ruled_table", "rules120"),
        ("photo_region", "photo_mid"),
        ("photo_region", "photo_high"),
    ],
)
def test_coloured_marks_dots_rules_and_photo_cores_are_untouched(
    name: str, mask: str, policy: CleanupPolicy, output: ColourMode
) -> None:
    fixture = fx.FIXTURES[name]()
    where = fixture.masks[mask]
    assert where.any()
    before, after = baseline(fixture, output), render(fixture, output, policy)
    assert np.array_equal(after[where], before[where])


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("name", ["faint_pencil", "stamp", "ruled_table"])
def test_faint_marks_keep_their_contrast_to_the_paper(name: str, policy: CleanupPolicy) -> None:
    fixture = fx.FIXTURES[name]()
    assert fixture.samples
    before, after = baseline(fixture, ColourMode.GREY), render(fixture, ColourMode.GREY, policy)
    for mark, paper in fixture.samples:
        assert int(after[paper]) - int(after[mark]) >= int(before[paper]) - int(before[mark])
        assert after[mark] >= before[mark]


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("name", ["coloured_stock", "cream_paper"])
def test_stock_is_left_alone_in_colour_and_whitened_in_grey(
    name: str, policy: CleanupPolicy
) -> None:
    fixture = fx.FIXTURES[name]()
    colour = cleanup.clean_pixels(fixture.pixels, fx.DPI, ColourMode.COLOUR, policy)
    assert colour.status is cleanup.CleanupStatus.STOCK
    assert colour.pixels is None
    assert np.array_equal(render(fixture, ColourMode.COLOUR, policy), fixture.pixels)
    grey = cleanup.clean_pixels(fixture.pixels, fx.DPI, ColourMode.GREY, policy)
    assert grey.status is cleanup.CleanupStatus.APPLIED
    assert not np.array_equal(
        render(fixture, ColourMode.GREY, policy), baseline(fixture, ColourMode.GREY)
    )


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("output", OUTPUTS)
def test_a_dark_page_is_skipped_whole(policy: CleanupPolicy, output: ColourMode) -> None:
    fixture = fx.dark_page()
    result = cleanup.clean_pixels(fixture.pixels, fx.DPI, output, policy)
    assert result.status is cleanup.CleanupStatus.DARK
    assert np.array_equal(render(fixture, output, policy), baseline(fixture, output))


@pytest.mark.parametrize("output", OUTPUTS)
def test_an_already_white_page_barely_changes(output: ColourMode) -> None:
    fixture = fx.already_white()
    before = baseline(fixture, output)
    assert np.array_equal(render(fixture, output, CleanupPolicy.LIGHT), before)
    strong = render(fixture, output, CleanupPolicy.STRONG)
    assert int(np.abs(strong.astype(int) - before.astype(int)).max()) <= 6
    assert not np.array_equal(strong, before)


@pytest.mark.parametrize("output", OUTPUTS)
def test_shaded_paper_is_lifted_to_the_capped_targets(output: ColourMode) -> None:
    fixture = fx.shaded_paper()
    strip = fx.px(5)

    def edges(policy: CleanupPolicy) -> tuple[float, float]:
        out = render(fixture, output, policy)
        out = out if out.ndim == 2 else out[..., 0]
        return float(out[:, :strip].mean()), float(out[:, -strip:].mean())

    before_right = float(baseline(fixture, output)[:, -strip:].mean())
    left, right = edges(CleanupPolicy.STRONG)
    assert left >= 248 and right >= 248
    left, right = edges(CleanupPolicy.LIGHT)
    assert left >= 240 and right >= 222
    assert right - before_right >= 15


def test_the_effects_are_stronger_under_strong_than_light() -> None:
    fixture = fx.shaded_paper()
    light = render(fixture, ColourMode.GREY, CleanupPolicy.LIGHT).astype(int)
    strong = render(fixture, ColourMode.GREY, CleanupPolicy.STRONG).astype(int)
    assert (strong >= light).all() and (strong > light).any()


# --- the limits of the skips -------------------------------------------------------------------


def flat_page(paper: tuple[int, int, int]) -> np.ndarray:
    page = np.empty((200, 160, 3), np.uint8)
    page[:] = paper
    return page


@pytest.mark.parametrize(("level", "status"), [(159, "dark"), (160, "applied")])
def test_paper_darker_than_160_is_skipped(level: int, status: str) -> None:
    page = flat_page((level, level, level))
    result = cleanup.clean_pixels(page, 100, ColourMode.GREY, CleanupPolicy.STRONG)
    assert result.status.value == status
    assert assert_matches_reference(page, 100, ColourMode.GREY, CleanupPolicy.STRONG) == status


@pytest.mark.parametrize(
    ("paper", "status"), [((232, 224, 216), "applied"), ((232, 224, 215), "stock")]
)
def test_paper_with_a_chroma_above_16_is_stock_in_colour(
    paper: tuple[int, int, int], status: str
) -> None:
    page = flat_page(paper)
    colour = cleanup.clean_pixels(page, 100, ColourMode.COLOUR, CleanupPolicy.STRONG)
    assert colour.status.value == status
    assert cleanup.clean_pixels(page, 100, ColourMode.GREY, CleanupPolicy.STRONG).status.value == (
        "applied"
    )


def test_a_colour_page_with_no_paper_pixel_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provably unreachable on a real page (the brightest pixel is always paper), but it is a
    status of the contract, so its guard is exercised with an empty chroma histogram."""
    monkeypatch.setattr(
        cleanup,
        "_survey",
        lambda work, cancel: (np.zeros((1, 1), np.int64), np.zeros(256, np.int64)),
    )
    for output in OUTPUTS:
        result = cleanup.clean_pixels(
            fx.shaded_paper().pixels, fx.DPI, output, CleanupPolicy.STRONG
        )
        assert result.status is cleanup.CleanupStatus.NO_PAPER and result.pixels is None


EDGE_DPI = 127  # a 4 mm cell is exactly 20 pixels and the work grid is the page


def edge_page(value: int, period: int) -> np.ndarray:
    """Paper 200 with a one pixel line of ``value`` on every ``period``-th row (a line that thin
    never reaches the background)."""
    page = np.empty((200, 200, 3), np.uint8)
    page[:] = 200
    page[::period] = value
    return page


@pytest.mark.parametrize(
    ("value", "period", "protected"),
    [
        (184, 4, False),  # exactly 92% of the paper: not a photograph pixel
        (156, 4, False),  # exactly 78%: ink, not a photograph pixel
        (170, 5, True),  # exactly 20% of every cell: protected
        (170, 7, False),  # 15% of every cell: not
    ],
)
def test_the_photograph_thresholds_are_strict_and_the_cell_share_is_inclusive(
    value: int, period: int, protected: bool
) -> None:
    page = edge_page(value, period)
    assert_matches_reference(page, EDGE_DPI, ColourMode.GREY, CleanupPolicy.STRONG)
    out = cleanup.clean_pixels(page, EDGE_DPI, ColourMode.GREY, CleanupPolicy.STRONG).pixels
    assert out is not None
    if protected:
        assert np.array_equal(out, page[..., 0])
    else:
        assert (out[1] > 200).all()


def test_paper_pixels_at_exactly_90_percent_count_towards_the_paper_chroma() -> None:
    page = np.empty((200, 200, 3), np.uint8)
    page[:] = 200
    page[np.arange(200) % 5 < 3] = (120, 205, 205)  # grey level 180, 90% of the paper
    result = cleanup.clean_pixels(page, EDGE_DPI, ColourMode.COLOUR, CleanupPolicy.STRONG)
    assert result.status is cleanup.CleanupStatus.STOCK
    assert_matches_reference(page, EDGE_DPI, ColourMode.COLOUR, CleanupPolicy.STRONG)


def test_a_pixel_brighter_than_the_paper_keeps_its_hue() -> None:
    page = flat_page((232, 232, 232))
    page[80:100, 60:100] = (243, 240, 238)
    assert_matches_reference(page, 100, ColourMode.COLOUR, CleanupPolicy.STRONG)
    out = cleanup.clean_pixels(page, 100, ColourMode.COLOUR, CleanupPolicy.STRONG).pixels
    assert out is not None
    red, green, blue = (int(v) for v in out[90, 80])
    assert red > green > blue  # clipped to white channel by channel, it would not be


# --- black and white, off ----------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_black_and_white_is_byte_identical_whatever_the_policy(name: str) -> None:
    page = page_of(fx.FIXTURES[name]())
    plain = render_page(page, ColourMode.BW)
    assert np.array_equal(render_page(page, ColourMode.BW, CleanupPolicy.STRONG), plain)
    assert (
        encode_page(page, ColourMode.BW, CleanupPolicy.STRONG).data
        == encode_page(page, ColourMode.BW).data
    )


def test_a_one_bit_page_is_not_cleaned() -> None:
    bits = np.where(fx.shaded_paper().pixels[..., 0] > 200, 255, 0).astype(np.uint8)
    page = LoadedPage(bits, ColourMode.BW, fx.DPI)
    assert np.array_equal(render_page(page, ColourMode.GREY, CleanupPolicy.STRONG), bits)


def test_off_is_the_plain_render_and_status_off() -> None:
    fixture = fx.shaded_paper()
    result = cleanup.clean_pixels(fixture.pixels, fx.DPI, ColourMode.COLOUR, CleanupPolicy.OFF)
    assert result.status is cleanup.CleanupStatus.OFF and result.pixels is None
    assert np.array_equal(render(fixture, ColourMode.COLOUR, CleanupPolicy.OFF), fixture.pixels)
    bw = cleanup.clean_pixels(fixture.pixels, fx.DPI, ColourMode.BW, CleanupPolicy.STRONG)
    assert bw.status is cleanup.CleanupStatus.BW and bw.pixels is None


def test_the_effective_policy_of_a_mode() -> None:
    assert effective_cleanup(CleanupPolicy.STRONG, ColourMode.BW) is CleanupPolicy.OFF
    assert effective_cleanup(CleanupPolicy.STRONG, ColourMode.GREY) is CleanupPolicy.STRONG
    assert effective_cleanup(CleanupPolicy.LIGHT, ColourMode.COLOUR) is CleanupPolicy.LIGHT
    assert effective_cleanup(CleanupPolicy.OFF, ColourMode.GREY) is CleanupPolicy.OFF


def test_an_encoded_page_records_the_effective_policy() -> None:
    page = page_of(fx.shaded_paper())
    assert encode_page(page, ColourMode.GREY, CleanupPolicy.LIGHT).cleanup is CleanupPolicy.LIGHT
    assert encode_page(page, ColourMode.BW, CleanupPolicy.LIGHT).cleanup is CleanupPolicy.OFF
    assert encode_page(page, ColourMode.GREY).cleanup is CleanupPolicy.OFF


def test_encoding_without_a_policy_is_what_it_was() -> None:
    page = page_of(fx.shaded_paper())
    assert (
        encode_page(page, ColourMode.COLOUR).data
        == encode_page(page, ColourMode.COLOUR, CleanupPolicy.OFF).data
    )


# --- cancel and memory -------------------------------------------------------------------------


class Trip(threading.Event):
    """Not set for the first ``calls`` checks, set from then on."""

    def __init__(self, calls: int) -> None:
        super().__init__()
        self.calls = calls
        self.seen = 0

    def is_set(self) -> bool:
        self.seen += 1
        return self.seen > self.calls


@pytest.mark.parametrize("calls", [1, 6, 14])
def test_a_cancel_before_a_later_band_stops_in_either_pass(
    calls: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cleanup, "BAND_ROWS", 64)
    pixels = fx.shaded_paper().pixels
    before = pixels.copy()
    bands = -(-pixels.shape[0] // 64)
    assert calls < bands < 2 * bands
    with pytest.raises(DocumentCancelledError, match="cleanup cancelled"):
        cleanup.clean_pixels(
            pixels, fx.DPI, ColourMode.COLOUR, CleanupPolicy.STRONG, cancel=Trip(calls)
        )
    assert np.array_equal(pixels, before)


def test_a_cancel_in_the_second_pass_is_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cleanup, "BAND_ROWS", 64)
    pixels = fx.shaded_paper().pixels
    bands = -(-pixels.shape[0] // 64)
    with pytest.raises(DocumentCancelledError):
        cleanup.clean_pixels(
            pixels, fx.DPI, ColourMode.COLOUR, CleanupPolicy.STRONG, cancel=Trip(bands + 2)
        )


def test_a_cancel_that_is_never_set_changes_nothing() -> None:
    pixels = fx.shaded_paper().pixels
    free = cleanup.clean_pixels(pixels, fx.DPI, ColourMode.GREY, CleanupPolicy.LIGHT).pixels
    kept = cleanup.clean_pixels(
        pixels, fx.DPI, ColourMode.GREY, CleanupPolicy.LIGHT, cancel=threading.Event()
    ).pixels
    assert free is not None and np.array_equal(free, kept)


def test_the_peak_memory_stays_near_twice_the_page() -> None:
    page = fx.odd_size_page(300, 2480, 1748).pixels  # A5 at 300 dpi, colour
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        result = cleanup.clean_pixels(page, 300, ColourMode.COLOUR, CleanupPolicy.STRONG)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert result.status is cleanup.CleanupStatus.APPLIED
    assert peak <= 2 * page.nbytes + 40 * 1024 * 1024, peak
