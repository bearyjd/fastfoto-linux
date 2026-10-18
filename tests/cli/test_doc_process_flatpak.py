"""``ffscan doc process`` inside the Flatpak: with no OCR the message is the sentence about the
bundle, capitalised and not inside parentheses, and it names no outside install."""

from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.documents import ocr_tools
from fastfoto_linux.documents.ocr_tools import FLATPAK_BROKEN_HINT
from fastfoto_linux.scanner import shim_trust
from tests import _fake_ocrmypdf as fake
from tests.documents.helpers import text_scene, write_pages


@pytest.fixture
def pages(tmp_path: Path) -> list[Path]:
    return write_pages(tmp_path / "raw", [text_scene(1), text_scene(2)])


@pytest.fixture(autouse=True)
def sandbox_without_ocr(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Flatpak whose bundled OCR is gone: the marker file exists and no program is anywhere."""
    folder = tmp_path_factory.mktemp("sandbox")
    marker = folder / ".flatpak-info"
    marker.write_text("[Application]\n", encoding="utf-8")
    monkeypatch.setattr(shim_trust, "FLATPAK_INFO", marker)
    app_bin = folder / "app" / "bin"
    app_bin.mkdir(parents=True)
    monkeypatch.setattr(ocr_tools, "FLATPAK_BIN", app_bin)
    fake.no_ocr_on_path(folder / "usr" / "bin", monkeypatch)


def doc(out: Path, pages: list[Path], *extra: str) -> int:
    return main(["doc", "process", *map(str, pages), "--out", str(out), *extra])


def test_required_ocr_says_the_bundle_is_broken_in_a_sentence_of_its_own(
    pages: list[Path], out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert doc(out, pages, "--ocr", "on") == 3
    err = capsys.readouterr().err
    assert FLATPAK_BROKEN_HINT in err
    assert f"({FLATPAK_BROKEN_HINT}" not in err  # a capital letter does not open a parenthesis
    assert "--ocr on" in err


def test_the_summary_says_the_bundle_is_broken_in_a_sentence_of_its_own(
    pages: list[Path], out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert doc(out, pages) == 0
    lines = capsys.readouterr().out.splitlines()
    assert any(line.startswith("searchable text: no") for line in lines)
    assert any(FLATPAK_BROKEN_HINT in line for line in lines)
    assert not any(f": {FLATPAK_BROKEN_HINT}" in line for line in lines)
