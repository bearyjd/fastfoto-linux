"""Where the OCR programs are, and what to install when one is missing.

``ocrmypdf`` comes with the app (it is installed into the app's own environment); Tesseract does
not, because it is a program, not a Python package, except in the Flatpak, which brings both:
inside a Flatpak sandbox the app's own bin folder (``FLATPAK_BIN``) is searched first, Homebrew
never is, and a missing part means the bundle is broken (``FLATPAK_BROKEN_HINT``), so no hint
names a command that installs from outside. On an immutable system (Bazzite, Silverblue)
without root, Tesseract comes from Homebrew, whose folder is not on the PATH of a program started
from a menu entry, so it is looked for there as well, last: the order of the folders is the PATH
the program was started with, then (for the run only) the interpreter's folder, then Homebrew's,
so that Homebrew never shadows the system's own programs. Homebrew's folder is used only when it
is owned by root or by the user and nobody else can write to it (``brew_folder_problem``).

The places that differ from machine to machine are module-level names that a test replaces:
``BREW_BIN``, ``OSTREE_MARKER``, ``OCR_MODULE`` and ``FLATPAK_BIN`` (and, for the sandbox test,
``shim_trust.FLATPAK_INFO``). They are read when a function runs.
"""

import importlib.util
import logging
import os
import shutil
import stat
import sys
from pathlib import Path

from fastfoto_linux.scanner.shim_trust import inside_flatpak

logger = logging.getLogger(__name__)

ROOT_UID = 0
BREW_BIN = Path("/home/linuxbrew/.linuxbrew/bin")
OSTREE_MARKER = Path("/run/ostree-booted")  # exists on an rpm-ostree system
FLATPAK_BIN = Path("/app/bin")  # where the Flatpak puts the programs it brings
FLATPAK_BROKEN_HINT = (
    "The OCR that comes with this Flatpak is missing, so the installation is broken: "
    "reinstall the Flatpak"
)
TOOL = "ocrmypdf"
OCR_MODULE = TOOL  # the module that, when the running interpreter can import it, is run with -m
TESSERACT = "tesseract"
BREW = "brew"
BREW_INSTALL_HINT = "brew install tesseract"  # includes the English and orientation data
BREW_LANG_HINT = "brew install tesseract-lang"  # every other language
DNF_INSTALL_HINT = (
    "sudo dnf install tesseract tesseract-osd"  # OSD data is what --rotate-pages needs
)
RPM_OSTREE_INSTALL_HINT = "rpm-ostree install tesseract tesseract-osd"
OSTREE_NO_BREW_HINT = (
    f"{RPM_OSTREE_INSTALL_HINT} (then reboot), or install Homebrew and run {BREW_INSTALL_HINT}"
)
OCRMYPDF_NAME = "OCRmyPDF"
OCRMYPDF_FIX_HINT = (
    "run the installer again, or pip install 'fastfoto-linux[ocr]' for a development install"
)
TESSERACT_NAME = "Tesseract"
OCR_NEEDS = f"{OCRMYPDF_NAME} and {TESSERACT_NAME}"  # what searchable text needs
OCR_UNAVAILABLE_TEXT = "OCR is not available"


def _module_importable() -> bool:
    try:
        return importlib.util.find_spec(OCR_MODULE) is not None
    except (ImportError, ValueError):
        return False


def brew_folder_problem(mode: int, owner: int, uid: int) -> str | None:
    """Why a folder with permission bits ``mode`` owned by ``owner`` is not to be trusted when
    ``uid`` runs the program, or None when it is."""
    if owner not in (ROOT_UID, uid):
        return f"not owned by root or by the user (owner {owner})"
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        return "writable by its group or by others"
    return None


def _brew_folders() -> list[str]:
    """Homebrew's bin folder as a list of one, or an empty list when it is not there or not to be
    trusted (the reason is logged for ``--debug``). Always empty inside a Flatpak: its sandbox has
    no Homebrew, and the OCR it needs is its own."""
    if inside_flatpak():
        return []
    try:
        info = BREW_BIN.stat()
    except OSError:
        return []
    problem = (
        brew_folder_problem(info.st_mode, info.st_uid, os.getuid())
        if stat.S_ISDIR(info.st_mode)
        else "not a folder"
    )
    if problem is not None:
        logger.debug("ignoring %s: %s", BREW_BIN, problem)
        return []
    return [str(BREW_BIN)]


def _inherited_path() -> str:
    return os.environ.get("PATH", os.defpath)


def _bundled_folders() -> list[str]:
    """The Flatpak's own bin folder as a list of one inside a Flatpak, else an empty list."""
    return [str(FLATPAK_BIN)] if inside_flatpak() else []


def _join(folders: list[str]) -> str:
    """A PATH of ``folders``; an empty entry would mean the current folder, so it is left out."""
    return os.pathsep.join(folder for folder in folders if folder)


def _find(name: str) -> str | None:
    """``name`` in the Flatpak's own folder, else on PATH, else in Homebrew's folder (which a menu
    entry's PATH does not have)."""
    folders = [*_bundled_folders(), _inherited_path(), *_brew_folders()]
    return shutil.which(name, path=_join(folders))


def locate_ocrmypdf() -> str | None:
    """How to run ``ocrmypdf``, whether or not Tesseract is there: the running interpreter when it
    can import the module (it is then run with ``-m ocrmypdf``), else ``ocrmypdf`` on PATH, else
    in Homebrew's folder; None when it is nowhere."""
    if _module_importable():
        return sys.executable
    return _find(TOOL)


def find_tesseract() -> str | None:
    """The ``tesseract`` on PATH, or in Homebrew's folder, or None."""
    return _find(TESSERACT)


def find_ocrmypdf() -> str | None:
    """What runs OCR here: ``locate_ocrmypdf()`` when Tesseract is there as well, else None."""
    found = locate_ocrmypdf()
    return found if found is not None and find_tesseract() is not None else None


def ocr_missing_parts() -> tuple[str, ...]:
    """The names of the OCR parts that are not here, OCRmyPDF first (none: both are)."""
    return tuple(
        name
        for name, found in (
            (OCRMYPDF_NAME, locate_ocrmypdf()),
            (TESSERACT_NAME, find_tesseract()),
        )
        if found is None
    )


def ocr_missing_text() -> str:
    """What stops OCR here, in the words every message uses: "Tesseract is not installed"."""
    missing = ocr_missing_parts()
    if not missing:
        return OCR_UNAVAILABLE_TEXT
    return f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} not installed"


def ocr_environment() -> dict[str, str]:
    """A copy of the environment for ``ocrmypdf``. PATH is the Flatpak's own folder (inside a
    Flatpak), the inherited one (the default path when there is none), then the folder of the
    running interpreter, so that ocrmypdf finds its own helpers, then Homebrew's folder: the order
    in which Tesseract was looked for, the interpreter's folder apart."""
    environment = dict(os.environ)
    folders = [
        *_bundled_folders(),
        _inherited_path(),
        str(Path(sys.executable).parent),
        *_brew_folders(),
    ]
    environment["PATH"] = _join(folders)
    return environment


def uses_homebrew() -> bool:
    """True where ``brew`` can be run: Tesseract then comes from Homebrew."""
    return _find(BREW) is not None


def on_ostree() -> bool:
    """True on an rpm-ostree system (Bazzite, Silverblue), where ``dnf`` cannot install."""
    return OSTREE_MARKER.exists()


def ocr_install_hint() -> str:
    """The command that installs Tesseract on this system: Homebrew's where brew runs, else
    rpm-ostree's (or Homebrew's, once installed) on an immutable system, else dnf's. Inside a
    Flatpak there is none: Tesseract comes with it, and a missing one is a broken bundle."""
    if inside_flatpak():
        return FLATPAK_BROKEN_HINT
    if uses_homebrew():
        return BREW_INSTALL_HINT
    return OSTREE_NO_BREW_HINT if on_ostree() else DNF_INSTALL_HINT


def ocr_fixes() -> tuple[tuple[str, str], ...]:
    """What to do about each missing OCR part, as (part, what to do), Tesseract's first. When
    nothing is missing any more (it was installed while the question was asked), Tesseract's.
    Inside a Flatpak every part has the one fix: reinstall it."""
    missing = ocr_missing_parts()
    if inside_flatpak():
        return tuple((name, FLATPAK_BROKEN_HINT) for name in (missing or (TESSERACT_NAME,)))
    fixes = []
    if TESSERACT_NAME in missing or not missing:
        fixes.append((TESSERACT_NAME, ocr_install_hint()))
    if OCRMYPDF_NAME in missing:
        fixes.append((OCRMYPDF_NAME, OCRMYPDF_FIX_HINT))
    return tuple(fixes)


def ocr_fix_hint() -> str:
    """What to do about the missing OCR part or parts, for a sentence: the one thing to do, or
    each part's with its name when both are missing."""
    fixes = ocr_fixes()
    if len({fix for _, fix in fixes}) == 1:
        return fixes[0][1]
    return "; ".join(f"{name}: {fix}" for name, fix in fixes)
