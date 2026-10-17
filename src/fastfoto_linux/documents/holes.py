"""Holes through the paper (stub: red). The rule is not written yet."""

from collections.abc import Sequence

from fastfoto_linux.documents.marks import Mark
from fastfoto_linux.documents.trim import Trimmed

HOLE_MAX_MM = 8.0
EDGE_ZONE_MM = 25.0
SHIFT_MM = 2.0
MATCH_IOU = 0.5
SIZE_RATIO = 1.5
HOLE_TONE = 160


def all_are_holes(marks: Sequence[Mark], side: Trimmed, partner: Trimmed) -> bool:
    """Stub (red): nothing is a hole."""
    return False
