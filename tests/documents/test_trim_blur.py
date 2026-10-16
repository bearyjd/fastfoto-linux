"""The last check on a cut strip judges a lightly blurred copy of it.

Scanner noise is no cluster of its own, so it cannot cancel a cut that is certainly safe, and a
small dot of two or three pixels, which a clean copy would not call a cluster, grows into one.
"""

from dataclasses import replace

import numpy as np

from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import LEGAL_MM, LETTER_MM, Scene, paper_scene, with_text
from tests.documents.helpers import colour_page
from tests.documents.trim_helpers import RECEIPT_MM, letter_text, mm

NOISE_DPI = 200
NOISE_SIGMA = 5  # grey levels of Gaussian noise on every channel
NOISE_TAIL_TONE = 253
DOT_DPI = 300  # 0.3 mm is 4 pixels here, so a 3-pixel dot is under it
DOT_PX = 3
DOT_Y_MM = 40.0  # below the end of the paper


def noisy_receipt() -> Scene:
    scene = paper_scene(
        dpi=NOISE_DPI,
        paper_mm=RECEIPT_MM,
        scan_mm=LETTER_MM,
        offset_mm=60.0,
        noise=0,
        tail_tone=NOISE_TAIL_TONE,
    )
    for row in range(8):
        scene = with_text(scene, 6, 10 + row * 20, 10)
    field = np.random.default_rng(0).normal(0, NOISE_SIGMA, scene.image.shape)
    image = np.clip(scene.image.astype(np.float32) + field, 0, 255).round()
    return replace(scene, image=image.astype(np.uint8))


def test_a_receipt_scanned_with_noise_still_loses_its_tail() -> None:
    scene = noisy_receipt()
    result = trim_page(colour_page(scene))
    assert scene.paper_end <= result.page.pixels.shape[0] <= scene.paper_end + mm(6, NOISE_DPI)


def test_a_dot_of_three_pixels_in_the_tail_keeps_it() -> None:
    scene = letter_text(paper_scene(dpi=DOT_DPI, paper_mm=LETTER_MM, scan_mm=LEGAL_MM))
    row, column = scene.paper_end + mm(DOT_Y_MM, DOT_DPI), mm(100.0, DOT_DPI)
    image = scene.image.copy()
    image[row : row + DOT_PX, column : column + DOT_PX] = 0
    result = trim_page(colour_page(replace(scene, image=image)))
    assert result.page.pixels.shape[0] >= row + DOT_PX
