"""Documents tests never run a real ``ocrmypdf``, even on a machine that has one."""

from pathlib import Path

import pytest

from fastfoto_linux.documents import ocr_tools
from tests import _fake_ocrmypdf as fake


@pytest.fixture(autouse=True)
def no_real_ocr(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    fake.no_ocr_on_path(tmp_path_factory.mktemp("no-ocr"), monkeypatch)


@pytest.fixture
def on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The only folder on PATH."""
    folder = tmp_path / "on-path"
    folder.mkdir()
    monkeypatch.setenv("PATH", str(folder))
    return folder


@pytest.fixture
def brew_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A Homebrew bin folder, which is not on PATH."""
    folder = tmp_path / "linuxbrew" / "bin"
    folder.mkdir(parents=True)
    folder.chmod(0o755)  # whatever the umask: a folder others can write to is not trusted
    monkeypatch.setattr(ocr_tools, "BREW_BIN", folder)
    return folder


@pytest.fixture
def brew_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """``brew`` is looked for by its real name (tests/conftest.py gives it one nobody has)."""
    monkeypatch.setattr(ocr_tools, "BREW", "brew")


@pytest.fixture
def ostree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = tmp_path / "ostree-booted"
    marker.touch()
    monkeypatch.setattr(ocr_tools, "OSTREE_MARKER", marker)


@pytest.fixture
def importable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The running interpreter can import the module that stands for ocrmypdf."""
    monkeypatch.setattr(ocr_tools, "OCR_MODULE", "json")
