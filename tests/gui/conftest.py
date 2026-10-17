"""GUI test fixtures. A scanner may be attached while these run: nothing may reach it."""

from pathlib import Path

import pytest

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


@pytest.fixture
def out(tmp_path: Path) -> Path:
    root = tmp_path / "out"
    root.mkdir()
    return root
