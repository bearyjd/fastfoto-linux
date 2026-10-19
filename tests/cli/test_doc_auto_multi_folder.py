"""Mixed-folder input supports initial Auto, but cannot reread a reduced cached source."""

from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from tests.documents.auto_helpers import pdf_modes, write_auto_pages


def mixed_pages(tmp_path: Path) -> tuple[Path, ...]:
    return (
        *write_auto_pages(tmp_path / "first", ("stamp",)),
        *write_auto_pages(tmp_path / "second", ("text",)),
    )


def test_global_auto_works_across_input_folders(tmp_path: Path) -> None:
    code = main(
        [
            "doc",
            "process",
            *map(str, mixed_pages(tmp_path)),
            "--out",
            str(tmp_path),
            "--ocr",
            "off",
            "--simplex",
            "--colour",
            "auto",
        ]
    )
    assert code == 0
    assert pdf_modes(tmp_path / "Document_0001.pdf") == ["/DeviceRGB", "bw"]


def test_an_override_that_matches_actual_cached_mode_needs_no_reread(tmp_path: Path) -> None:
    code = main(
        [
            "doc",
            "process",
            *map(str, mixed_pages(tmp_path)),
            "--out",
            str(tmp_path),
            "--ocr",
            "off",
            "--simplex",
            "--colour",
            "bw",
            "--page-colour",
            "1:bw",
        ]
    )
    assert code == 0
    assert pdf_modes(tmp_path / "Document_0001.pdf") == ["bw", "bw"]


def test_a_richer_override_requires_raw_sources_in_one_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "doc",
            "process",
            *map(str, mixed_pages(tmp_path)),
            "--out",
            str(tmp_path),
            "--ocr",
            "off",
            "--simplex",
            "--colour",
            "bw",
            "--page-colour",
            "1:colour",
        ]
    )
    assert code == 2
    error = capsys.readouterr().err
    assert "--page-colour" in error
    assert "one folder" in error
    assert not list(tmp_path.glob("*.pdf"))
