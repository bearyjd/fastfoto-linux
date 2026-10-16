"""A speck is dust or a mark by its size in millimetres, whatever the resolution."""

import pytest

from fastfoto_linux.documents.blank import is_blank
from tests.doc_synth import paper_scene, with_solid_block
from tests.documents.helpers import pages_of

DPIS = [200, 300, 600]
SPOT_TONE = 40
SHEET_MM = (60.0, 60.0)
SPOT_AT_MM = 25.0


def verdicts(size_mm: float, dpi: int) -> dict[str, bool]:
    scene = paper_scene(dpi=dpi, paper_mm=SHEET_MM)
    scene = with_solid_block(scene, SPOT_AT_MM, SPOT_AT_MM, size_mm, SPOT_TONE)
    return {kind: is_blank(page) for kind, page in pages_of(scene).items()}


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("size_mm", [0.5, 0.9])
def test_dust_smaller_than_a_millimetre_is_blank_at_every_resolution(
    size_mm: float, dpi: int
) -> None:
    assert verdicts(size_mm, dpi) == {"colour": True, "grey": True, "bw": True}


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("size_mm", [1.3, 2.0])
def test_a_spot_over_a_millimetre_keeps_the_page_at_every_resolution(
    size_mm: float, dpi: int
) -> None:
    assert verdicts(size_mm, dpi) == {"colour": False, "grey": False, "bw": False}
