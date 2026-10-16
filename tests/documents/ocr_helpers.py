"""A two-page PDF and a way to run the OCR step on it against the fake ``ocrmypdf``."""

import io
from pathlib import Path

import img2pdf
import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.documents.ocr import OcrOutcome, run_ocr
from tests import _fake_ocrmypdf as fake

TIMEOUT_S = 20.0
SHORT_TIMEOUT_S = 1.5
SHORT_GRACE_S = 0.5


def _jpeg(seed: int) -> bytes:
    pixels = np.random.default_rng(seed).integers(0, 256, (40, 30, 3), dtype=np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, "JPEG", dpi=(100, 100))
    return buffer.getvalue()


PLAIN = img2pdf.convert(_jpeg(1), _jpeg(2))


def run_fake(
    executable: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    langs: str = "eng",
    staging_parent: Path | None = None,
    **spec: object,
) -> OcrOutcome:
    """``run_ocr`` on ``PLAIN`` with the fake told what to do (staging in the default place
    unless ``staging_parent`` says otherwise)."""
    fake.configure(monkeypatch, **spec)
    return run_ocr(
        PLAIN,
        executable=str(executable),
        langs=langs,
        page_count=2,
        staging_parent=staging_parent,
        timeout_s=SHORT_TIMEOUT_S,
        grace_s=SHORT_GRACE_S,
    )
