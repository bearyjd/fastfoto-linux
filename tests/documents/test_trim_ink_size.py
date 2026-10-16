"""Ink is a cluster of 0.3 mm or more: the pixel count rounds up, so that 0.3 mm is honoured.

0.3 mm is 2.4 pixels at 200 dpi and 7.1 at 600 dpi. A cluster of 2 (0.25 mm) or 7 (0.30 mm less
a hair) pixels is shorter than that, so it is dust; one pixel more is ink.
"""

from dataclasses import replace

import pytest

from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import Scene, paper_scene, px
from tests.documents.helpers import colour_page

PAPER_MM = (40.0, 60.0)
SCAN_MM = (40.0, 90.0)
SPECK_Y_MM = 75.0  # in the tail, 15 mm below the paper
SPECK_X_MM = 15.0
SPECK_TONE = 225  # 30 levels darker than the tail
KEEP_MM = 3.0
ROOM_MM = 5.0


def speck_scene(dpi: int, size_px: int) -> Scene:
    scene = paper_scene(dpi=dpi, paper_mm=PAPER_MM, scan_mm=SCAN_MM)
    image = scene.image.copy()
    top, left = px(SPECK_Y_MM, dpi), px(SPECK_X_MM, dpi)
    image[top : top + size_px, left : left + size_px] = SPECK_TONE
    return replace(scene, image=image)


@pytest.mark.parametrize(
    ("dpi", "size_px", "is_ink"),
    [(200, 2, False), (200, 3, True), (600, 7, False), (600, 8, True)],
)
def test_a_cluster_is_ink_from_0_3_mm_up_rounded_up_to_whole_pixels(
    dpi: int, size_px: int, is_ink: bool
) -> None:
    scene = speck_scene(dpi, size_px)
    kept = trim_page(colour_page(scene)).page.pixels.shape[0]
    speck_bottom = px(SPECK_Y_MM, dpi) + size_px
    if is_ink:
        assert kept >= speck_bottom + px(ROOM_MM, dpi) - 1
    else:
        assert kept <= scene.paper_end + px(KEEP_MM, dpi) + 1
