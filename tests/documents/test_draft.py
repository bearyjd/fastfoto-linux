"""``TrimBox``: the crop that ``trim_page`` made, kept as four numbers and applied again."""

import dataclasses

import numpy as np
import pytest

from fastfoto_linux.documents.draft import TrimBox
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import Scene, paper_scene, with_text
from tests.doc_synth_band import banded_scene
from tests.doc_synth_holes import SMALL_MM
from tests.documents.helpers import bw_page, colour_page, grey_page

DPIS = [200, 300, 600]
WIDTH_MM = SMALL_MM[0]


def _written(scene: Scene) -> Scene:
    return with_text(scene, 12.0, 30.0, 12)


def _scenes(dpi: int) -> dict[str, Scene]:
    return {
        "plain": _written(paper_scene(dpi=dpi, paper_mm=SMALL_MM)),
        "tail": _written(paper_scene(dpi=dpi, paper_mm=SMALL_MM, scan_mm=(WIDTH_MM, 150.0))),
        "backing at the sides": _written(
            paper_scene(
                dpi=dpi, paper_mm=SMALL_MM, scan_mm=(WIDTH_MM + 30.0, 150.0), offset_mm=15.0
            )
        ),
        "band": banded_scene(dpi=dpi, width_mm=WIDTH_MM, paper_mm=60.0, top_mm=2.0),
    }


def _box(scene: Scene) -> TrimBox:
    return TrimBox.from_trimmed(trim_page(colour_page(scene)))


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("name", ["plain", "tail", "backing at the sides", "band"])
def test_applying_the_box_gives_the_page_trim_page_gave(dpi: int, name: str) -> None:
    page = colour_page(_scenes(dpi)[name])
    trimmed = trim_page(page)
    box = TrimBox.from_trimmed(trimmed)
    again = box.apply(page)
    assert again.pixels.shape == trimmed.page.pixels.shape
    assert np.array_equal(again.pixels, trimmed.page.pixels)
    assert (again.kind, again.dpi) == (page.kind, page.dpi)


@pytest.mark.parametrize("name", ["tail", "backing at the sides", "band"])
@pytest.mark.parametrize("make", [grey_page, bw_page], ids=["grey", "1-bit"])
def test_applying_the_box_gives_the_same_grey_and_one_bit_pages(name: str, make) -> None:
    page: LoadedPage = make(_scenes(200)[name])
    trimmed = trim_page(page)
    again = TrimBox.from_trimmed(trimmed).apply(page)
    assert np.array_equal(again.pixels, trimmed.page.pixels)
    assert again.kind is page.kind


def test_the_fixtures_make_every_kind_of_cut() -> None:
    boxes = [_box(scene) for scene in _scenes(200).values()]
    assert any(box.bottom > 0 for box in boxes)
    assert any(box.left > 0 and box.right > 0 for box in boxes)
    assert any(box.top > 0 for box in boxes)
    assert any(box.band_bottom for box in boxes)
    assert _box(_scenes(200)["plain"]) == TrimBox(0, 0, 0, 0)


def test_the_box_holds_what_trimmed_reports() -> None:
    trimmed = trim_page(colour_page(_scenes(200)["band"]))
    box = TrimBox.from_trimmed(trimmed)
    assert (box.left, box.right, box.top, box.bottom) == (
        trimmed.left,
        trimmed.right,
        trimmed.top,
        trimmed.bottom,
    )
    assert box.band_bottom is trimmed.band_bottom


def test_applying_a_box_does_not_change_the_page_it_is_given() -> None:
    page = colour_page(_scenes(200)["tail"])
    before = page.pixels.copy()
    _box(_scenes(200)["tail"]).apply(page)
    assert np.array_equal(page.pixels, before)


def test_a_box_is_a_value() -> None:
    box = TrimBox(1, 2, 3, 4)
    assert box == TrimBox(1, 2, 3, 4)
    assert hash(box) == hash(TrimBox(1, 2, 3, 4))
    with pytest.raises(dataclasses.FrozenInstanceError):
        box.left = 5  # type: ignore[misc]


def test_a_box_cannot_cut_a_negative_number_of_pixels() -> None:
    with pytest.raises(ValueError, match="negative"):
        TrimBox(-1, 0, 0, 0)


def test_a_box_that_leaves_nothing_of_the_page_is_refused() -> None:
    page = colour_page(_scenes(200)["plain"])
    height, width = page.pixels.shape[:2]
    with pytest.raises(ValueError, match="nothing"):
        TrimBox(width, 0, 0, 0).apply(page)
    with pytest.raises(ValueError, match="nothing"):
        TrimBox(0, 0, height, 0).apply(page)
