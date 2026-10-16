"""The check before a scan: find out whether the scanner answers, and free it when it does not."""

import re
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from fastfoto_linux.scanner.libusb import open_scanner

SKIP_ENV_VAR = "FF680W_NO_PRECHECK"
_USB_DEVICE = re.compile(r"epsonds:libusb:([0-9]+):([0-9]+)")


def usb_address(device: str) -> tuple[int, int] | None:
    """(bus, address) of a SANE name like ``epsonds:libusb:001:004``, None for anything else."""
    raise NotImplementedError


def precheck_applies(device: str, env: Mapping[str, str]) -> bool:
    """True for a USB scanner unless ``FF680W_NO_PRECHECK=1`` turns the check off."""
    raise NotImplementedError


def check_scanner(
    device: str,
    *,
    env: Mapping[str, str] | None = None,
    cancel: threading.Event | None = None,
    opener: Callable[..., Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Run the check for the SANE device ``device``; returns normally when scanning may go on.

    Raises ScannerInUseError, ScannerStuckError or ScanCancelledError; every other problem
    (libusb missing, no access) is logged and means "go on without the check".
    """
    opener = open_scanner if opener is None else opener
    raise NotImplementedError
