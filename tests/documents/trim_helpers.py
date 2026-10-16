"""Scenes and checks shared by the trim tests."""

from fastfoto_linux.documents.trim import Trimmed
from tests.doc_synth import LETTER_MM, Scene, paper_scene, px, with_text

DPI = 100
RECEIPT_MM = (80.0, 200.0)


def mm(value: float, dpi: int = DPI) -> int:
    return px(value, dpi)


def letter_text(scene: Scene) -> Scene:
    """A few lines on the upper part of the page, like a short letter."""
    for row in range(6):
        scene = with_text(scene, 25, 30 + row * 8, 30)
    return scene


def receipt(dpi: int = DPI, *, offset_mm: float = 60.0) -> Scene:
    scene = paper_scene(dpi=dpi, paper_mm=RECEIPT_MM, scan_mm=LETTER_MM, offset_mm=offset_mm)
    for row in range(8):
        scene = with_text(scene, 6, 10 + row * 20, 10)
    return scene


def assert_contains_content(scene: Scene, result: Trimmed, *, margin_px: int = 0) -> None:
    """The kept area holds the whole content box and ``margin_px`` below it (when that exists)."""
    assert scene.content is not None
    x0, _, x1, y1 = scene.content
    kept_h, kept_w = result.page.pixels.shape[:2]
    assert result.left <= x0
    assert x1 <= result.left + kept_w
    assert y1 + min(margin_px, scene.height - y1) <= kept_h
