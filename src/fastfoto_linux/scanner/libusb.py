"""A thin ctypes binding of libusb-1.0, enough to talk to the FF-680W's bulk endpoints."""

import contextlib
import time
from collections.abc import Callable, Iterator
from typing import Any

from fastfoto_linux.scanner.errors import ScannerError
from fastfoto_linux.scanner.unstick import UsbTransport

# Tried in order; empty means "libusb cannot be found" (the tests set that, so that nothing
# ever reaches a scanner that happens to be plugged in).
_LIBRARY_NAMES: tuple[str, ...] = ("libusb-1.0.so.0", "libusb-1.0.so")


class CheckUnavailableError(ScannerError):
    """The pre-scan check cannot be done (no libusb, no access); scanning goes on without it."""


class LibusbUnavailableError(CheckUnavailableError):
    """libusb-1.0 cannot be loaded."""


def load_libusb() -> Any:
    """The libusb-1.0 shared library, or LibusbUnavailableError."""
    raise NotImplementedError


@contextlib.contextmanager
def open_scanner(
    bus: int,
    address: int,
    *,
    lib: Any = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[UsbTransport]:
    """Claim the FF-680W at ``bus``:``address`` and give its bulk endpoints; releases on exit.

    Raises ScannerInUseError if another program holds the interface, CheckUnavailableError if
    the device cannot be opened for any other reason.
    """
    raise NotImplementedError
    yield  # pragma: no cover - makes this a generator for the stub
