"""Where the OCR programs are, and what to install when one is missing.

``ocrmypdf`` comes with the app (it is installed into the app's own environment); Tesseract does
not, because it is a program, not a Python package. On an immutable system (Bazzite, Silverblue)
without root, Tesseract comes from Homebrew, whose folder is not on the PATH of a program started
from a menu entry, so it is looked for there as well.
"""

from pathlib import Path

BREW_BIN = Path("/home/linuxbrew/.linuxbrew/bin")
OSTREE_MARKER = Path("/run/ostree-booted")  # exists on an rpm-ostree system
TOOL = "ocrmypdf"
OCR_MODULE = TOOL  # the module that, when the running interpreter can import it, is run with -m
TESSERACT = "tesseract"
BREW = "brew"
BREW_INSTALL_HINT = "brew install tesseract"  # includes the English and orientation data
BREW_LANG_HINT = "brew install tesseract-lang"  # every other language
DNF_INSTALL_HINT = (
    "sudo dnf install tesseract tesseract-osd"  # OSD data is what --rotate-pages needs
)


def locate_ocrmypdf() -> str | None:
    """How to run ``ocrmypdf``, whether or not Tesseract is there: the running interpreter when it
    can import the module (run with ``-m ocrmypdf``), else ``ocrmypdf`` on PATH, else in Homebrew's
    folder; None when it is nowhere."""
    raise NotImplementedError


def find_tesseract() -> str | None:
    """The ``tesseract`` on PATH, or in Homebrew's folder, or None."""
    raise NotImplementedError


def find_ocrmypdf() -> str | None:
    """What runs OCR here: ``locate_ocrmypdf()`` when Tesseract is there as well, else None."""
    raise NotImplementedError


def ocr_environment() -> dict[str, str]:
    """A copy of the environment for ``ocrmypdf``: PATH leads with Homebrew's folder (when it
    exists) and the folder of the running interpreter, so that it finds Tesseract and its own
    helpers."""
    raise NotImplementedError


def uses_homebrew() -> bool:
    """True on an immutable system or where ``brew`` is installed: Tesseract comes from there."""
    raise NotImplementedError


def ocr_install_hint() -> str:
    """The command that installs Tesseract on this system."""
    raise NotImplementedError
