"""``ffscan`` starts without loading the PDF libraries; they load when a PDF is made."""

import subprocess
import sys

import pytest

LIBRARIES = ("pikepdf", "img2pdf", "lxml")
TIMEOUT_S = 60


def loaded_after(statement: str) -> list[str]:
    """Which PDF libraries a fresh interpreter has imported after running ``statement``."""
    code = (
        f"import sys; {statement}; print(*[name for name in {LIBRARIES!r} if name in sys.modules])"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        check=True,
        timeout=TIMEOUT_S,
    )
    return done.stdout.split()


@pytest.mark.parametrize(
    "statement",
    [
        "import fastfoto_linux.cli.app",
        "import fastfoto_linux.cli.cmd_doc",
        "import fastfoto_linux.documents",
        "import fastfoto_linux.documents.ocr, fastfoto_linux.documents.pdf",
    ],
)
def test_importing_the_command_line_does_not_load_the_pdf_libraries(statement: str) -> None:
    assert loaded_after(statement) == []


def test_the_probe_sees_a_library_that_is_imported() -> None:
    assert loaded_after("import pikepdf, img2pdf") == ["pikepdf", "img2pdf"]


def test_making_a_pdf_loads_what_it_needs() -> None:
    statement = (
        "import numpy as np; "
        "from datetime import UTC, datetime; "
        "from fastfoto_linux.documents.encode import encode_page; "
        "from fastfoto_linux.documents.loader import LoadedPage; "
        "from fastfoto_linux.documents.modes import ColourMode; "
        "from fastfoto_linux.documents.pdf import assemble_pdf; "
        "page = LoadedPage(np.full((20, 20, 3), 255, np.uint8), ColourMode.COLOUR, 100); "
        "assemble_pdf([encode_page(page, ColourMode.COLOUR)], title='x', created=datetime.now(UTC))"
    )
    assert "img2pdf" in loaded_after(statement)
