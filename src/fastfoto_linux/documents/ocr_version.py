"""Which version of ocrmypdf will run, and which options that version accepts.

The version of the app's own module comes from its installed metadata; a program is asked once
(``ocrmypdf --version``, with a short time limit) and the answer is remembered. That one line is
the only output of ocrmypdf that is ever read: it holds no document text. A version that cannot
be told is "unknown", and unknown gets the command that every version accepts.
"""

import functools
import importlib.metadata
import logging
import re
import subprocess
import sys

from fastfoto_linux.documents.ocr_tools import TOOL, ocr_environment

logger = logging.getLogger(__name__)

metadata_version = importlib.metadata.version  # a name a test replaces
VERSION_TIMEOUT_S = 10.0
RASTERIZER_FIRST_MAJOR = 17  # older versions do not know --rasterizer (and use Ghostscript)
_NUMBER = re.compile(r"\d+(?:\.\d+)*")
_MAJOR = re.compile(r"\d+")


def _first_number(text: str) -> str | None:
    found = _NUMBER.search(text)
    return found.group(0) if found else None


def _module_version() -> str | None:
    try:
        return _first_number(metadata_version(TOOL))
    except importlib.metadata.PackageNotFoundError:
        return None


@functools.cache
def program_version(executable: str) -> str | None:
    """The version ``executable --version`` prints, or None when it does not say. Remembered."""
    try:
        done = subprocess.run(  # an argument list, never a shell
            [executable, "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=VERSION_TIMEOUT_S,
            env=ocr_environment(),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        logger.debug("could not ask %s for its version: %s", executable, error)
        return None
    return _first_number(done.stdout.decode(errors="replace"))


def ocrmypdf_version(executable: str) -> str | None:
    """The version of what ``executable`` runs: the app's own module when it is the interpreter,
    else the program; None when it is not known."""
    if executable == sys.executable:
        return _module_version()
    return program_version(executable)


def accepts_rasterizer(version: str | None) -> bool:
    """True when ``version`` is known to accept ``--rasterizer`` (ocrmypdf 17 and up)."""
    major = _MAJOR.match(version or "")
    return major is not None and int(major.group(0)) >= RASTERIZER_FIRST_MAJOR
