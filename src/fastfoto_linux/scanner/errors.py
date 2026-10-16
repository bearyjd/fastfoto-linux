"""Exceptions raised by the scanner transport layer."""

from pathlib import Path


class ScannerError(Exception):
    """Base class for every scanner transport failure."""


class ScannerNotFoundError(ScannerError):
    """No FF-680W was found on USB and no network host was given."""


class ShimMissingError(ScannerError):
    """The scanner is on USB but the USB gap shim library cannot be found."""


STUCK_MESSAGE = "The scanner isn't answering. Switch it off and on, then try again."
NO_ANSWER_MESSAGE = (
    "The scanner isn't answering. It may be busy with another device, or stuck — "
    "switch it off and on, then try again."
)
DISCONNECTED_MESSAGE = "The scanner disappeared (it may have restarted) — try again."
IN_USE_MESSAGE = "The scanner is in use by another program. Close it and try again."


class ScannerStuckError(ScannerError):
    """The scanner is on USB but does not answer, even after it was nudged (see ``unstick``)."""

    def __init__(self, message: str = STUCK_MESSAGE) -> None:
        super().__init__(message)


class ScannerDisconnectedError(ScannerError):
    """The scanner vanished from USB while it was being checked (it may have restarted)."""

    def __init__(self, message: str = DISCONNECTED_MESSAGE) -> None:
        super().__init__(message)


class ScannerInUseError(ScannerError):
    """Another program holds the scanner's USB interface, so nothing was sent to it."""

    def __init__(self, message: str = IN_USE_MESSAGE) -> None:
        super().__init__(message)


class InvalidHostError(ScannerError, ValueError):
    """A network host is not a plain IPv4 address or hostname."""


class InvalidConfigDirError(ScannerError, ValueError):
    """A SANE config directory path cannot be used in ``SANE_CONFIG_DIR``."""


class InvalidShimPathError(ScannerError, ValueError):
    """The USB gap shim path cannot be used in ``LD_PRELOAD``."""


class OutputDirError(ScannerError, OSError):
    """The output directory cannot be created, listed or written to."""


class OutputNotEmptyError(ScannerError, FileExistsError):
    """The output directory already holds pages for this job's file prefix."""


class NoDocumentsError(ScannerError):
    """The document feeder was empty, so no page was scanned."""


class ScanCancelledError(ScannerError):
    """The scan was cancelled by the caller; ``pages`` are the pages finished before that."""

    def __init__(self, message: str, *, pages: tuple[Path, ...] = ()) -> None:
        super().__init__(message)
        self.pages = pages


class ScanError(ScannerError):
    """scanimage failed, timed out or could not be started.

    ``pages`` holds the page files that were completed before the failure, so a caller can
    keep them; ``returncode`` is None when scanimage never produced an exit status.
    """

    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        pages: tuple[Path, ...] = (),
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.pages = pages
