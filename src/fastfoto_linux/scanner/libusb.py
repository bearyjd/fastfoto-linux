"""A thin ctypes binding of libusb-1.0, enough to talk to the FF-680W's bulk endpoints.

Nothing here knows the scanner's protocol (that is ``unstick``); this only finds the device by
bus and address, claims its interface, and moves bytes. It is the one place that touches USB, so
it is loaded lazily: a machine without libusb simply cannot run the check.
"""

import contextlib
import ctypes
import logging
import time
from collections.abc import Callable, Iterator
from typing import Any

from fastfoto_linux.scanner.errors import ScannerError, ScannerInUseError
from fastfoto_linux.scanner.unstick import TransportError, UsbTransport
from fastfoto_linux.scanner.usb import USB_PRODUCT_ID, USB_VENDOR_ID

logger = logging.getLogger(__name__)

# Tried in order; empty means "libusb cannot be found" (the tests set that, so that nothing
# ever reaches a scanner that happens to be plugged in).
_LIBRARY_NAMES: tuple[str, ...] = ("libusb-1.0.so.0", "libusb-1.0.so")

INTERFACE = 0
ENDPOINT_OUT = 0x01
ENDPOINT_IN = 0x82
WRITE_TIMEOUT_MS = 1000
# The FF-680W ignores an OUT that follows the end of an IN too closely (0.5 ms is enough).
OUT_AFTER_IN_GAP_S = 0.003
DESCRIPTOR_BYTES = 18
_VENDOR_OFFSET = 8
_PRODUCT_OFFSET = 10

LIBUSB_ERROR_BUSY = -6
LIBUSB_ERROR_TIMEOUT = -7
_ERROR_NAMES = {
    -1: "I/O error",
    -3: "permission denied",
    -4: "no such device",
    -5: "not found",
    -6: "busy",
    -7: "timed out",
    -9: "pipe error",
    -12: "not supported",
}

_PTR = ctypes.POINTER
_SIGNATURES: dict[str, tuple[Any, list[Any]]] = {
    "libusb_init": (ctypes.c_int, [_PTR(ctypes.c_void_p)]),
    "libusb_exit": (None, [ctypes.c_void_p]),
    "libusb_get_device_list": (ctypes.c_ssize_t, [ctypes.c_void_p, _PTR(ctypes.c_void_p)]),
    "libusb_free_device_list": (None, [ctypes.c_void_p, ctypes.c_int]),
    "libusb_get_bus_number": (ctypes.c_uint8, [ctypes.c_void_p]),
    "libusb_get_device_address": (ctypes.c_uint8, [ctypes.c_void_p]),
    "libusb_get_device_descriptor": (ctypes.c_int, [ctypes.c_void_p, ctypes.c_void_p]),
    "libusb_open": (ctypes.c_int, [ctypes.c_void_p, _PTR(ctypes.c_void_p)]),
    "libusb_close": (None, [ctypes.c_void_p]),
    "libusb_claim_interface": (ctypes.c_int, [ctypes.c_void_p, ctypes.c_int]),
    "libusb_release_interface": (ctypes.c_int, [ctypes.c_void_p, ctypes.c_int]),
    "libusb_set_auto_detach_kernel_driver": (ctypes.c_int, [ctypes.c_void_p, ctypes.c_int]),
    "libusb_bulk_transfer": (
        ctypes.c_int,
        [
            ctypes.c_void_p,
            ctypes.c_ubyte,
            ctypes.c_void_p,
            ctypes.c_int,
            _PTR(ctypes.c_int),
            ctypes.c_uint,
        ],
    ),
}


class CheckUnavailableError(ScannerError):
    """The pre-scan check cannot be done (no libusb, no access); scanning goes on without it."""


class LibusbUnavailableError(CheckUnavailableError):
    """libusb-1.0 cannot be loaded."""


def load_libusb() -> Any:
    """The libusb-1.0 shared library, or LibusbUnavailableError.

    Loaded by soname, so that it resolves in a Flatpak sandbox (the runtime ships it) as well as
    on a host.
    """
    for name in _LIBRARY_NAMES:
        try:
            return ctypes.CDLL(name)
        except OSError as exc:
            logger.debug("cannot load %s: %s", name, exc)
    raise LibusbUnavailableError("libusb-1.0 cannot be loaded")


def _declare(lib: Any) -> None:
    """Tell ctypes every signature: undeclared, pointers are passed and returned as 32-bit ints."""
    try:
        for name, (restype, argtypes) in _SIGNATURES.items():
            function = getattr(lib, name)
            function.restype = restype
            function.argtypes = argtypes
    except AttributeError as exc:
        raise LibusbUnavailableError(
            f"this libusb lacks a function the check needs: {exc}"
        ) from exc


def _error_name(code: int) -> str:
    return _ERROR_NAMES.get(code, f"libusb error {code}")


@contextlib.contextmanager
def _context(lib: Any) -> Iterator[ctypes.c_void_p]:
    ctx = ctypes.c_void_p()
    rc = lib.libusb_init(ctypes.pointer(ctx))
    if rc != 0:
        raise CheckUnavailableError(f"libusb could not start: {_error_name(rc)}")
    try:
        yield ctx
    finally:
        lib.libusb_exit(ctx)


def _find_device(
    lib: Any, ctx: ctypes.c_void_p, bus: int, address: int
) -> tuple[ctypes.c_void_p, int]:
    """The device list and the device at ``bus``:``address``, or a CheckUnavailableError."""
    listing = ctypes.c_void_p()
    count = lib.libusb_get_device_list(ctx, ctypes.pointer(listing))
    if count < 0:
        raise CheckUnavailableError(f"cannot list the USB devices: {_error_name(count)}")
    devices = list((ctypes.c_void_p * count).from_address(listing.value or 0))
    for device in devices:
        if (lib.libusb_get_bus_number(device), lib.libusb_get_device_address(device)) == (
            bus,
            address,
        ):
            return listing, device
    lib.libusb_free_device_list(listing, 1)
    raise CheckUnavailableError(f"no USB device at {bus:03d}:{address:03d}")


def _is_scanner(lib: Any, device: int) -> bool:
    descriptor = (ctypes.c_ubyte * DESCRIPTOR_BYTES)()
    if lib.libusb_get_device_descriptor(device, descriptor) != 0:
        return False
    vendor = int.from_bytes(bytes(descriptor[_VENDOR_OFFSET : _VENDOR_OFFSET + 2]), "little")
    product = int.from_bytes(bytes(descriptor[_PRODUCT_OFFSET : _PRODUCT_OFFSET + 2]), "little")
    return (vendor, product) == (USB_VENDOR_ID, USB_PRODUCT_ID)


@contextlib.contextmanager
def _handle(lib: Any, ctx: ctypes.c_void_p, bus: int, address: int) -> Iterator[ctypes.c_void_p]:
    listing, device = _find_device(lib, ctx, bus, address)
    handle = ctypes.c_void_p()
    try:
        if not _is_scanner(lib, device):
            raise CheckUnavailableError(f"the device at {bus:03d}:{address:03d} is not an FF-680W")
        rc = lib.libusb_open(device, ctypes.pointer(handle))
        if rc != 0:
            raise CheckUnavailableError(f"cannot open the scanner: {_error_name(rc)}")
    finally:
        lib.libusb_free_device_list(listing, 1)
    try:
        yield handle
    finally:
        lib.libusb_close(handle)


@contextlib.contextmanager
def _claimed(lib: Any, handle: ctypes.c_void_p) -> Iterator[None]:
    lib.libusb_set_auto_detach_kernel_driver(handle, 1)  # best effort: a kernel driver may hold it
    rc = lib.libusb_claim_interface(handle, INTERFACE)
    if rc == LIBUSB_ERROR_BUSY:
        raise ScannerInUseError
    if rc != 0:
        raise CheckUnavailableError(f"cannot claim the scanner: {_error_name(rc)}")
    try:
        yield
    finally:
        lib.libusb_release_interface(handle, INTERFACE)


class _Transport:
    """The bulk endpoints of an opened scanner, with the gap it needs before an OUT."""

    def __init__(
        self,
        lib: Any,
        handle: ctypes.c_void_p,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self._lib = lib
        self._handle = handle
        self._clock = clock
        self._sleep = sleep
        self._last_in: float | None = None

    def write(self, data: bytes, timeout_ms: int = WRITE_TIMEOUT_MS) -> int:
        self._wait_for_gap()
        buffer = ctypes.create_string_buffer(data, len(data))
        sent = ctypes.c_int(0)
        rc = self._lib.libusb_bulk_transfer(
            self._handle, ENDPOINT_OUT, buffer, len(data), ctypes.pointer(sent), WRITE_TIMEOUT_MS
        )
        if rc != 0 or sent.value != len(data):
            raise TransportError(
                f"bulk OUT: {_error_name(rc)} ({sent.value} of {len(data)} bytes sent)"
            )
        return sent.value

    def read(self, size: int, timeout_ms: int) -> bytes:
        buffer = (ctypes.c_ubyte * size)()
        got = ctypes.c_int(0)
        rc = self._lib.libusb_bulk_transfer(
            self._handle, ENDPOINT_IN, buffer, size, ctypes.pointer(got), timeout_ms
        )
        self._last_in = self._clock()
        if rc not in (0, LIBUSB_ERROR_TIMEOUT):
            raise TransportError(f"bulk IN: {_error_name(rc)}")
        return bytes(buffer[: got.value])

    def _wait_for_gap(self) -> None:
        if self._last_in is None:
            return
        remaining = OUT_AFTER_IN_GAP_S - (self._clock() - self._last_in)
        if remaining > 0:
            self._sleep(remaining)


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

    ``lib`` replaces the loaded libusb (for tests). Raises ScannerInUseError if another program
    holds the interface, CheckUnavailableError if the device cannot be opened for any other
    reason. The interface is released, the device closed and libusb exited on every way out, so
    that nothing is held when scanimage starts.
    """
    library = load_libusb() if lib is None else lib
    _declare(library)
    with (
        _context(library) as ctx,
        _handle(library, ctx, bus, address) as handle,
        _claimed(library, handle),
    ):
        yield _Transport(library, handle, clock, sleep)
