"""A side column is cut only when essentially all of it is backing, so a tilted receipt keeps
its corners, and a tab of paper that sticks out stops the cut where it starts."""

import cv2
import numpy as np
import pytest

from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import BACKING_RGB, LETTER_MM, PAPER_TONE, Scene, paper_scene, with_text
from tests.doc_synth import with_tinted_block as tinted
from tests.documents.trim_helpers import DPI, RECEIPT_MM, mm

EDGE_MM = 2.0  # the text starts this far from the edge of the receipt
INK_BELOW = 128
ROWS_MM = (10, 50, 100, 150, 190)
SCAN_MM = (LETTER_MM[0], 250.0)
CENTRED_MM = (LETTER_MM[0] - RECEIPT_MM[0]) / 2
TAB_MM = 15.0
TAB_HEIGHT_MM = 12.0  # 4.8% of the rows: more than the 1% a column may differ in


def receipt_scene(*, tab: bool = False) -> Scene:
    scene = paper_scene(dpi=DPI, paper_mm=RECEIPT_MM, scan_mm=SCAN_MM, offset_mm=CENTRED_MM)
    if tab:
        scene = tinted(scene, -TAB_MM, 80.0, (TAB_MM, TAB_HEIGHT_MM), (PAPER_TONE,) * 3)
        scene = with_text(scene, 1.5 - TAB_MM, 83.0, 4)
    for y in ROWS_MM:
        scene = with_text(scene, EDGE_MM, y, 10)
    return scene


def tilted(image: np.ndarray, degrees: float) -> np.ndarray:
    """The frame turned about its centre, the corners filled with the scanner's backing."""
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), degrees, 1.0)
    border = tuple(int(channel) for channel in BACKING_RGB)
    return cv2.warpAffine(
        image, matrix, (width, height), flags=cv2.INTER_LINEAR, borderValue=border
    )


def ink_cut_off(image: np.ndarray) -> tuple[int, int]:
    """(ink pixels in the frame, ink pixels that trimming removes)."""
    result = trim_page(LoadedPage(image, ColourMode.COLOUR, DPI))
    ink = image.min(axis=2) < INK_BELOW
    height, width = ink.shape
    cut = ink[:, : result.left].sum() + ink[:, width - result.right :].sum()
    return int(ink.sum()), int(cut + ink[height - result.bottom :].sum())


@pytest.mark.parametrize("degrees", [-5, -4, -3, -2, -1, 1, 2, 3, 4, 5])
def test_a_tilted_receipt_loses_no_ink_to_the_side_or_bottom_cuts(degrees: float) -> None:
    ink, cut = ink_cut_off(tilted(receipt_scene().image, degrees))
    assert ink > 0
    assert cut == 0


def test_a_tab_of_paper_sticking_out_stops_the_side_cut_where_the_tab_starts() -> None:
    scene = receipt_scene(tab=True)
    ink, cut = ink_cut_off(scene.image)
    assert ink > 0
    assert cut == 0
    result = trim_page(LoadedPage(scene.image, ColourMode.COLOUR, DPI))
    assert abs(result.left - (scene.paper_x[0] - mm(TAB_MM))) <= 1


def test_a_short_tab_of_paper_is_found_too_because_the_rows_are_sampled_densely() -> None:
    """4 mm of 200 is 2% of the rows: more than the 1% a column may differ in."""
    scene = tinted(receipt_scene(), -TAB_MM, 80.0, (TAB_MM, 4.0), (PAPER_TONE,) * 3)
    scene = with_text(scene, 1.5 - TAB_MM, 80.7, 4)
    ink, cut = ink_cut_off(scene.image)
    assert ink > 0
    assert cut == 0
