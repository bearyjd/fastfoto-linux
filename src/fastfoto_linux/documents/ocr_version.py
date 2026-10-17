"""Which version of ocrmypdf will run, and which options that version accepts.

The version of the app's own module comes from its installed metadata; a program is asked
(``ocrmypdf --version``, in a session of its own, with a short time limit, and everything it
started is stopped when it does not answer in time) and an answer is remembered. A failure is not
remembered: the next run asks again. That one line is the only output of ocrmypdf that is ever
read: it holds no document text. A version that cannot be told is "unknown", and unknown gets the
command that every version accepts.
"""

import contextlib
import functools
import importlib.metadata
import logging
import os
import re
import signal
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


class VersionUnknownError(Exception):
    """A program did not say its version."""


def _stop_group(process: subprocess.Popen[bytes]) -> None:
    """SIGKILL the group of ``process`` (it leads its own: start_new_session) before it is reaped,
    so that the group still is ours and nothing it started is left behind."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)


@functools.cache  # an exception is not remembered, so only an answer is
def remembered_version(executable: str) -> str:
    """The version ``executable --version`` prints; VersionUnknownError when it does not say."""
    try:
        with subprocess.Popen(  # an argument list, never a shell
            [executable, "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=ocr_environment(),
            start_new_session=True,
        ) as process:
            try:
                stdout, _ = process.communicate(timeout=VERSION_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                _stop_group(process)
                raise
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VersionUnknownError(f"could not ask {executable} for its version: {error}") from error
    version = _first_number(stdout.decode(errors="replace"))
    if version is None:
        raise VersionUnknownError(f"{executable} did not say a version")
    return version


def program_version(executable: str) -> str | None:
    """The version ``executable --version`` prints, or None when it does not say. An answer is
    remembered; a failure is asked again the next time."""
    try:
        return remembered_version(executable)
    except VersionUnknownError as error:
        logger.debug("%s", error)
        return None


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
