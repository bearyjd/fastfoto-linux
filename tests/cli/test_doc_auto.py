"""Document Auto policy and page overrides have deterministic CLI behavior."""

from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from tests.documents.auto_helpers import pdf_modes, write_auto_pages


def test_auto_cli_exports_a_mixed_document(tmp_path: Path) -> None:
    pages = write_auto_pages(tmp_path / "pages", ("stamp", "gradient", "text"))
    code = main(
        [
            "doc",
            "process",
            *map(str, pages),
            "--out",
            str(tmp_path),
            "--ocr",
            "off",
            "--simplex",
            "--keep-blank",
            "--colour",
            "auto",
        ]
    )
    assert code == 0
    assert pdf_modes(tmp_path / "Document_0001.pdf") == ["/DeviceRGB", "/DeviceGray", "bw"]


def test_page_colour_cli_overrides_a_manual_document_policy(tmp_path: Path) -> None:
    pages = write_auto_pages(tmp_path / "pages", ("stamp", "gradient", "text"))
    code = main(
        [
            "doc",
            "process",
            *map(str, pages),
            "--out",
            str(tmp_path),
            "--ocr",
            "off",
            "--simplex",
            "--keep-blank",
            "--colour",
            "bw",
            "--page-colour",
            "1:colour,2:grey,3:auto",
        ]
    )
    assert code == 0
    assert pdf_modes(tmp_path / "Document_0001.pdf") == ["/DeviceRGB", "/DeviceGray", "bw"]


@pytest.mark.parametrize(
    ("value", "message"),
    [("0:auto", "page 0"), ("2:grey", "page 2"), ("1:auto,1:bw", "twice"), ("1:bad", "mode")],
)
def test_bad_page_colour_is_refused_before_output(
    value: str, message: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pages = write_auto_pages(tmp_path / "pages", ("text",))
    code = main(
        [
            "doc",
            "process",
            *map(str, pages),
            "--out",
            str(tmp_path),
            "--ocr",
            "off",
            "--page-colour",
            value,
        ]
    )
    assert code == 2
    assert message in capsys.readouterr().err
    assert not list(tmp_path.glob("*.pdf"))


def test_auto_dry_run_explains_mode_without_publishing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pages = write_auto_pages(tmp_path / "pages", ("gradient",))
    code = main(
        [
            "doc",
            "process",
            *map(str, pages),
            "--out",
            str(tmp_path),
            "--ocr",
            "off",
            "--colour",
            "auto",
            "--dry-run",
        ]
    )
    assert code == 0
    report = capsys.readouterr().out
    assert "grey" in report
    assert "continuous_tone" in report
    assert not list(tmp_path.glob("*.pdf"))
