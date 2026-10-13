"""Exceptions raised by the scanner transport layer."""

from pathlib import Path


class ScannerError(Exception):
    """Base class for every scanner transport failure."""


class ScannerNotFoundError(ScannerError):
    """No FF-680W was found on USB and no network host was given."""


class ShimMissingError(ScannerError):
    """The scanner is on USB but the USB gap shim library cannot be found."""


class InvalidHostError(ScannerError, ValueError):
    """A network host is not a plain IPv4/IPv6 address or hostname."""


class NoDocumentsError(ScannerError):
    """The document feeder was empty, so no page was scanned."""


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
