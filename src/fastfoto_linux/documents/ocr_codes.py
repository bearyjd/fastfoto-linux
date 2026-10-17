"""What a failed ``ocrmypdf`` run says, from its documented exit code alone.

The tool's output is never read (it holds the recognised text), so the only evidence of what went
wrong is how it ended. Each code of OCRmyPDF's "return code policy" has one fixed hint. Code 3
("a required program is missing") also covers missing language data, which is the usual cause, so
its hint names what to install: the Homebrew formulae where brew runs, else the Fedora packages
(with rpm-ostree on an immutable system, dnf otherwise). Inside a Flatpak nothing is installed from
outside: only English comes with it, so another language is named as not bundled, and for English
the bundle is broken. Code 2 is both "the PDF cannot be read"
and the way a command line parser reports options it does not know; the PDF is one this app has
just written, so the hint leads with the options and the version that refused them.
"""

import signal

from fastfoto_linux.documents.ocr_tools import (
    BREW_INSTALL_HINT,
    BREW_LANG_HINT,
    FLATPAK_BROKEN_HINT,
    TOOL,
    on_ostree,
    uses_homebrew,
)
from fastfoto_linux.scanner.shim_trust import inside_flatpak

OPTIONS_REJECTED = 2
MISSING_DEPENDENCY = 3
_LANGPACK = "tesseract-langpack-{}"
_ORIENTATION_DATA = "tesseract-osd"  # --rotate-pages needs it
_BUNDLED_LANG = "eng"  # the only language data the Flatpak brings
_DNF_INSTALL = "sudo dnf install"
_RPM_OSTREE_INSTALL = "rpm-ostree install"

_HINTS = {
    1: "it did not accept its options; check --lang",
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
    packages = " ".join([*(_LANGPACK.format(code) for code in langs.split("+")), _ORIENTATION_DATA])
    if on_ostree():
        return f"{_RPM_OSTREE_INSTALL} {packages} (then reboot)"
    return f"{_DNF_INSTALL} {packages}"


def _flatpak_missing_dependency(langs: str) -> str:
    others = [code for code in langs.split("+") if code != _BUNDLED_LANG]
    if others:
        return (
            f"language data for {', '.join(others)} is not bundled: the Flatpak brings English "
            f"({_BUNDLED_LANG}) only, so ask for {_BUNDLED_LANG}"
        )
    return FLATPAK_BROKEN_HINT[0].lower() + FLATPAK_BROKEN_HINT[1:]


def _missing_dependency(langs: str) -> str:
    if inside_flatpak():
        return _flatpak_missing_dependency(langs)
    return (
        "a program or language data it needs is missing; install Tesseract and the language "
        f"data: {_install_command(langs)}"
    )


def _signal_name(number: int) -> str:
    try:
        return signal.Signals(number).name
    except ValueError:
        return "unknown signal"


def _options_rejected(version: str | None) -> str:
    installed = (
        f"the installed OCRmyPDF (version {version})" if version else "the installed OCRmyPDF"
    )
    return f"{installed} did not accept the options it was given, or could not read the PDF"


def _hint(status: int, langs: str, version: str | None) -> str | None:
    if status == MISSING_DEPENDENCY:
        return _missing_dependency(langs)
    if status == OPTIONS_REJECTED:
        return _options_rejected(version)
    return _HINTS.get(status)


def describe_exit(status: int, langs: str, version: str | None = None) -> str:
    """One line about how ``ocrmypdf`` (of ``version``, when known) ended with ``status``
    (negative: killed by a signal)."""
    if status < 0:
        return f"{TOOL} was killed by signal {-status} ({_signal_name(-status)})"
    hint = _hint(status, langs, version)
    base = f"{TOOL} exited with status {status}"
    return f"{base}: {hint}" if hint else base
