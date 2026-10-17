"""What a failed ``ocrmypdf`` run says, from its documented exit code alone.

The tool's output is never read (it holds the recognised text), so the only evidence of what went
wrong is how it ended. Each code of OCRmyPDF's "return code policy" has one fixed hint. Code 3
("a required program is missing") also covers missing language data, which is the usual cause, so
its hint names what to install: the Homebrew formulae on a system that uses Homebrew, else the
Fedora packages.
"""

import signal

from fastfoto_linux.documents.ocr_tools import (
    BREW_INSTALL_HINT,
    BREW_LANG_HINT,
    TOOL,
    uses_homebrew,
)

MISSING_DEPENDENCY = 3
_LANGPACK = "tesseract-langpack-{}"
_ORIENTATION_DATA = "tesseract-osd"  # --rotate-pages needs it
_INSTALL = "sudo dnf install"

_HINTS = {
    1: "it did not accept its options; check --lang",
    2: "it could not read the PDF it was given",
    4: "it wrote a file that is not a valid PDF",
    5: "it has no permission to read or write its files; check the permissions and the free "
    "space of the temporary folder",
    6: "the pages already contain text, so there was nothing to do",
    7: "a program it runs (Tesseract, Ghostscript) failed; run ocrmypdf on a page by hand to "
    "see why",
    8: "the PDF is encrypted",
    9: "Tesseract rejected its configuration",
    10: "PDF/A conversion failed",
    15: "it failed for a reason it does not name",
    130: "it was interrupted",
}


def _install_command(langs: str) -> str:
    if uses_homebrew():
        return f"{BREW_INSTALL_HINT} (English, page rotation), {BREW_LANG_HINT} (other languages)"
    packages = [_LANGPACK.format(code) for code in langs.split("+")] + [_ORIENTATION_DATA]
    return f"{_INSTALL} {' '.join(packages)}"


def _missing_dependency(langs: str) -> str:
    return (
        "a program or language data it needs is missing; install Tesseract and the language "
        f"data: {_install_command(langs)}"
    )


def _signal_name(number: int) -> str:
    try:
        return signal.Signals(number).name
    except ValueError:
        return "unknown signal"


def describe_exit(status: int, langs: str) -> str:
    """One line about how ``ocrmypdf`` ended with ``status`` (negative: killed by a signal)."""
    if status < 0:
        return f"{TOOL} was killed by signal {-status} ({_signal_name(-status)})"
    hint = _missing_dependency(langs) if status == MISSING_DEPENDENCY else _HINTS.get(status)
    base = f"{TOOL} exited with status {status}"
    return f"{base}: {hint}" if hint else base
