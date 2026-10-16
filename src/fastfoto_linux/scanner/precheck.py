"""The check before a scan: find out whether the scanner answers, and free it when it does not."""

import logging
import os
import re
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from fastfoto_linux.scanner.errors import ScanCancelledError
from fastfoto_linux.scanner.libusb import (
    CheckUnavailableError,
    LibusbUnavailableError,
    open_scanner,
)
from fastfoto_linux.scanner.unstick import ensure_ready

logger = logging.getLogger(__name__)

SKIP_ENV_VAR = "FF680W_NO_PRECHECK"
FORCE_ENV_VAR = "FF680W_FORCE_UNSTICK"
_USB_DEVICE = re.compile(r"epsonds:libusb:([0-9]+):([0-9]+)")


def usb_address(device: str) -> tuple[int, int] | None:
    """(bus, address) of a SANE name like ``epsonds:libusb:001:004``, None for anything else."""
    match = _USB_DEVICE.fullmatch(device)
    return None if match is None else (int(match.group(1)), int(match.group(2)))


def precheck_applies(device: str, env: Mapping[str, str]) -> bool:
    """True for a USB scanner unless ``FF680W_NO_PRECHECK=1`` turns the check off."""
    return usb_address(device) is not None and env.get(SKIP_ENV_VAR) != "1"


def check_scanner(  # noqa: PLR0913 - keyword-only knobs, most of them test seams
    device: str,
    *,
    env: Mapping[str, str] | None = None,
    cancel: threading.Event | None = None,
    opener: Callable[..., Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
    on_slow: Callable[[], None] | None = None,
) -> None:
    """Run the check for the SANE device ``device``; returns normally when scanning may go on.

    Only a USB scanner is checked (never ``--net``), and not when ``FF680W_NO_PRECHECK=1``.
    Raises ScannerInUseError, ScannerStuckError or ScanCancelledError; every other problem
    (libusb missing, no access) is logged and means "go on without the check". Everything is
    released and closed before this returns, so scanimage can open the scanner afterwards.
    ``opener`` replaces ``open_scanner`` (for tests); ``env`` defaults to the process's.
    """
    address = usb_address(device)
    if address is None or not precheck_applies(device, os.environ if env is None else env):
        return
    if cancel is not None and cancel.is_set():
        raise ScanCancelledError("scan cancelled before the scanner was checked")
    open_ = open_scanner if opener is None else opener
    try:
        with open_(*address) as transport:
            result = ensure_ready(transport, cancel=cancel, clock=clock)
    except LibusbUnavailableError as exc:
        logger.debug("libusb is not available (%s); scanning without the check", exc)
        return
    except CheckUnavailableError as exc:
        logger.info("the scanner could not be checked (%s); scanning without the check", exc)
        return
    logger.debug("the scanner check ended: %s", result.outcome)
