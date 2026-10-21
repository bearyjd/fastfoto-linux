"""What paper cleanup leaves alone on the generated pages."""

import numpy as np
import pytest

from fastfoto_linux.documents import cleanup
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode
from tests.documents import cleanup_fixtures as fx
from tests.documents.cleanup_support import NAMES, OUTPUTS, POLICIES, render

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
