"""Locate the FF-680W on USB through sysfs."""

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

USB_VENDOR_ID = 0x04B8
USB_PRODUCT_ID = 0x016B
DEFAULT_SYSFS_ROOT = Path("/sys/bus/usb/devices")

_HEX = 16
_DECIMAL = 10
_SANE_NUMBER_WIDTH = 3


@dataclass(frozen=True)
class UsbScanner:
    """An FF-680W currently enumerated on the USB bus."""

    bus: int
    device: int
    sysfs_path: Path

    def sane_usb_device_name(self) -> str:
        """SANE name of this scanner; the device number changes whenever it re-enumerates."""
        width = _SANE_NUMBER_WIDTH
        return f"epsonds:libusb:{self.bus:0{width}d}:{self.device:0{width}d}"


def find_usb_scanners(sysfs_root: Path = DEFAULT_SYSFS_ROOT) -> list[UsbScanner]:
    """All FF-680W entries under ``sysfs_root``, ordered by bus then device number.

    Entries that are not USB devices (interfaces), belong to other hardware, or have missing or
    malformed attributes are skipped; the reason is logged at debug level.
    """
    try:
        entries = sorted(sysfs_root.iterdir())
    except OSError as exc:
        logger.debug("cannot list %s: %s", sysfs_root, exc)
        return []
    scanners = [scanner for entry in entries if (scanner := _read_scanner(entry)) is not None]
    return sorted(scanners, key=lambda scanner: (scanner.bus, scanner.device))


def _read_scanner(entry: Path) -> UsbScanner | None:
    try:
        vendor = _read_number(entry / "idVendor", _HEX)
        product = _read_number(entry / "idProduct", _HEX)
        if (vendor, product) != (USB_VENDOR_ID, USB_PRODUCT_ID):
            return None
        bus = _read_number(entry / "busnum", _DECIMAL)
        device = _read_number(entry / "devnum", _DECIMAL)
    except (OSError, ValueError) as exc:
        logger.debug("skipping %s: %s", entry, exc)
        return None
    if bus < 1 or device < 1:
        logger.debug("skipping %s: bus %d / device %d out of range", entry, bus, device)
        return None
    return UsbScanner(bus=bus, device=device, sysfs_path=entry)


def _read_number(path: Path, base: int) -> int:
    return int(path.read_text().strip(), base)
