"""Shared by the paper-cleanup pixel tests."""

import numpy as np

from fastfoto_linux.documents import cleanup
from fastfoto_linux.documents.encode import render_page
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
