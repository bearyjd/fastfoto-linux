"""The mirror is taken in the scanner's frame: each side's trim offsets are added back, x becomes
the frame width less x and y stays. Sides are cut by hand here, with different offsets on each
side, so that every term of that arithmetic matters."""

from dataclasses import replace

import numpy as np
import pytest

from fastfoto_linux.documents.blank import is_blank_beside
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.trim import Trimmed
from tests.doc_synth import Scene, paper_scene, px
from tests.doc_synth_band import with_jpeg
from tests.doc_synth_holes import Hole, dash, disc, with_holes

DPI = 200
FRAME_MM = (100.0, 120.0)
# What each side's trim cut off, in mm: (left, right, top, bottom). All different on purpose.
FRONT_CUT = (4.0, 9.0, 3.0, 2.0)
BACK_CUT = (11.0, 2.0, 8.0, 0.0)
HOLE = dash(20.0, 20.0, 1.8)  # in the frame, 20 mm from its left and its top edges
ROUND = disc(20.0, 30.0, 3.0)


def cut_side(
    holes: list[Hole], cut: tuple[float, float, float, float], *, seed: int, dpi: int = DPI
) -> Trimmed:
    """A side of the frame with the ``holes`` (in frame mm) drawn, then trimmed by hand."""
    scene: Scene = paper_scene(dpi=dpi, paper_mm=FRAME_MM, seed=seed)
    pixels = with_jpeg(with_holes(scene, holes)).image
    left, right, top, bottom = (px(size, dpi) for size in cut)
    kept = np.ascontiguousarray(
        pixels[top : pixels.shape[0] - bottom, left : pixels.shape[1] - right]
    )
    return Trimmed(LoadedPage(kept, ColourMode.COLOUR, dpi), left, right, bottom, top)


def mirrored_in_frame(holes: list[Hole]) -> list[Hole]:
    return [hole.mirrored(FRAME_MM[0]) for hole in holes]


def verdicts(front: Trimmed, back: Trimmed) -> tuple[bool, bool]:
    return is_blank_beside(front, back), is_blank_beside(back, front)


@pytest.mark.parametrize("holes", [[HOLE], [ROUND], [HOLE, ROUND]], ids=["dash", "dot", "both"])
def test_holes_at_the_same_spot_of_the_frame_are_matched_whatever_each_trim_cut(
    holes: list[Hole],
) -> None:
    front = cut_side(holes, FRONT_CUT, seed=1)
    back = cut_side(mirrored_in_frame(holes), BACK_CUT, seed=2)
    assert verdicts(front, back) == (True, True)


@pytest.mark.parametrize("holes", [[HOLE], [ROUND]], ids=["dash", "dot"])
def test_the_other_side_is_matched_whichever_way_round_the_two_are_given(
    holes: list[Hole],
) -> None:
    front = cut_side(holes, BACK_CUT, seed=1)
    back = cut_side(mirrored_in_frame(holes), FRONT_CUT, seed=2)
    assert verdicts(front, back) == (True, True)


@pytest.mark.parametrize(
    ("name", "move"),
    [
        ("left", (3.0, 0.0)),
        ("right", (-3.0, 0.0)),
        ("up", (0.0, -3.0)),
        ("down", (0.0, 3.0)),
    ],
)
def test_a_spot_three_millimetres_off_in_the_frame_is_not_matched(
    name: str, move: tuple[float, float]
) -> None:
    holes = [HOLE, ROUND]
    off = [hole.moved(*move) for hole in mirrored_in_frame(holes)]
    front = cut_side(holes, FRONT_CUT, seed=1)
    back = cut_side(off, BACK_CUT, seed=2)
    assert verdicts(front, back) == (False, False), name


def test_the_trim_offsets_of_the_sides_are_not_mixed_up() -> None:
    """Cut by the other side's offsets the same frame spots fall elsewhere in the pages."""
    holes = [HOLE, ROUND]
    front = cut_side(holes, FRONT_CUT, seed=1)
    back = cut_side(mirrored_in_frame(holes), BACK_CUT, seed=2)
    swapped = replace(back, left=front.left, right=front.right, top=front.top)
    assert verdicts(front, swapped) == (False, False)


def test_sides_of_different_resolutions_are_not_a_sheet() -> None:
    holes = [HOLE, ROUND]
    front = cut_side(holes, FRONT_CUT, seed=1)
    back = cut_side(mirrored_in_frame(holes), BACK_CUT, seed=2)
    other = replace(back, page=replace(back.page, dpi=DPI + 100))
    assert verdicts(front, other) == (False, False)


def test_sides_cut_from_frames_of_different_widths_are_not_a_sheet() -> None:
    holes = [HOLE, ROUND]
    front = cut_side(holes, FRONT_CUT, seed=1)
    back = cut_side(mirrored_in_frame(holes), BACK_CUT, seed=2)
    wider = replace(back, right=back.right + px(8.0, DPI))
    assert verdicts(front, wider) == (False, False)


def test_frames_that_differ_by_a_pixel_or_two_are_one_frame() -> None:
    holes = [HOLE, ROUND]
    front = cut_side(holes, FRONT_CUT, seed=1)
    back = cut_side(mirrored_in_frame(holes), BACK_CUT, seed=2)
    wider = replace(back, right=back.right + 2)
    assert verdicts(front, wider) == (True, True)
