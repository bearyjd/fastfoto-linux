"""A blank back is still blank after the band is cut: the kept edge line is margin, not a mark.

``is_blank`` takes the rows the white tail lost out of its 5 mm bottom margin, because they were
part of the scanner's frame. After a band cut the new edge IS the paper's edge, so the margin is
measured from it in full (``Trimmed.tail_rows``); the top margin always was.
"""

from pathlib import Path

import pytest

from fastfoto_linux.documents import DocumentSettings, OcrMode, build_document
from fastfoto_linux.documents.blank import is_blank
from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import EDGE_LINE_MM, Scene, banded_scene, with_text
from tests.documents.helpers import colour_page, text_scene, write_pages

DPIS = (200, 300, 600)
MARK_MM = 1.5  # a mark small enough to lie wholly inside the 5 mm margin
LINE_MM = 2.5  # a line of text, as high as a letter


def back(dpi: int, **kwargs) -> Scene:
    """The back of a sheet: nothing printed, the band and the edge line at both edges."""
    small = {"width_mm": 90.0, "paper_mm": 40.0} if dpi >= 600 else {}
    return banded_scene(dpi=dpi, top_mm=1.5, **{**small, **kwargs})


def blank_after_trim(scene: Scene) -> bool:
    trimmed = trim_page(colour_page(scene))
    return is_blank(trimmed.page, trimmed_bottom=trimmed.tail_rows)


def paper_mm_of(scene: Scene) -> float:
    """Height of the paper proper (between the two edge lines), in mm."""
    return (scene.paper_end - scene.paper_top) / scene.dpi * 25.4 - 2 * EDGE_LINE_MM


@pytest.mark.parametrize("dpi", DPIS)
def test_a_blank_back_with_the_band_and_the_edge_line_at_both_edges_is_blank(dpi: int) -> None:
    assert blank_after_trim(back(dpi))


@pytest.mark.parametrize("dpi", DPIS)
def test_the_band_cut_is_what_makes_it_blank_the_bottom_margin_is_not_shrunk(dpi: int) -> None:
    trimmed = trim_page(colour_page(back(dpi)))
    assert trimmed.band_bottom
    assert trimmed.tail_rows == 0
    assert trimmed.bottom > 0
    assert trimmed.top > 0


@pytest.mark.parametrize("dpi", DPIS)
def test_a_line_of_text_six_millimetres_above_the_bottom_paper_edge_is_not_blank(dpi: int) -> None:
    scene = back(dpi)
    scene = with_text(scene, 10, paper_mm_of(scene) - 6.0 - LINE_MM + EDGE_LINE_MM, 30)
    assert not blank_after_trim(scene)


@pytest.mark.parametrize("dpi", DPIS)
def test_a_line_of_text_six_millimetres_below_the_top_edge_is_not_blank(dpi: int) -> None:
    assert not blank_after_trim(with_text(back(dpi), 10, 6.0, 30))


@pytest.mark.parametrize("dpi", DPIS)
def test_a_mark_two_millimetres_from_the_bottom_paper_edge_is_inside_the_margin(dpi: int) -> None:
    scene = back(dpi)
    y_mm = paper_mm_of(scene) + EDGE_LINE_MM - 2.0
    assert blank_after_trim(with_text(scene, 30, y_mm, 3, height_mm=MARK_MM))


@pytest.mark.parametrize("dpi", DPIS)
def test_a_mark_two_millimetres_from_the_top_edge_is_inside_the_margin(dpi: int) -> None:
    assert blank_after_trim(with_text(back(dpi), 30, 0.5, 3, height_mm=MARK_MM))


def build(tmp_path: Path, scenes: list[Scene]):
    pages = write_pages(tmp_path / "raw", scenes)
    out = tmp_path / "out"
    out.mkdir()
    return build_document(pages, DocumentSettings(output_root=out, ocr=OcrMode.OFF))


def test_a_blank_back_with_a_band_is_left_out_of_the_pdf(tmp_path: Path) -> None:
    result = build(tmp_path, [text_scene(1, 200), back(200)])
    assert result.dropped == (2,)
    assert result.pages_in_pdf == 1


def test_a_back_with_a_line_of_text_and_a_band_is_kept(tmp_path: Path) -> None:
    result = build(tmp_path, [text_scene(1, 200), with_text(back(200), 10, 30.0, 30)])
    assert result.dropped == ()
    assert result.pages_in_pdf == 2
