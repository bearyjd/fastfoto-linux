"""GUI test fixtures. A scanner may be attached while these run: nothing may reach it."""

from pathlib import Path

import pytest

from fastfoto_linux.documents import ocr_tools
from fastfoto_linux.documents.ocr_languages import Inventory, Language
from tests.cli.fakes import block_hardware, refuse

WORKER_TRANSPORT = (
    "resolve_target",
    "run_session",
    "process_pages",
    "run_document_session",
    "build_document",
)


@pytest.fixture(autouse=True)
def no_hardware(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test hands the worker its fakes; the real transport refuses to run."""
    block_hardware(monkeypatch)
    for name in WORKER_TRANSPORT:
        monkeypatch.setattr(f"fastfoto_linux.gui.worker.{name}", refuse)
    monkeypatch.setattr("fastfoto_linux.gui.worker.require_languages", lambda _langs: None)
    # OCR models are another machine dependency. GUI tests provide an installed inventory;
    # language-picker tests replace it with their own missing/downloadable models.
    monkeypatch.setattr(
        "fastfoto_linux.documents.ocr_languages.discover_languages",
        lambda **_options: Inventory(
            tuple(
                Language(code, name, 100, installed=True)
                for code, name in (("eng", "English"), ("deu", "German"), ("spa", "Spanish"))
            )
        ),
    )


@pytest.fixture
def out(tmp_path: Path) -> Path:
    root = tmp_path / "out"
    root.mkdir()
    return root


@pytest.fixture
def ocrmypdf_comes_with_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app's own environment has ocrmypdf, so only Tesseract (a program) is missing: the hint
    a test sees does not depend on whether the environment it runs in has the ocr extra. For the
    tests that look at the hint of a machine without Tesseract."""
    monkeypatch.setattr(ocr_tools, "OCR_MODULE", "json")
