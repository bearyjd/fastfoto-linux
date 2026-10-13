"""Locate the FF-680W on USB through sysfs."""

from dataclasses import dataclass
from pathlib import Path

USB_VENDOR_ID = 0x04B8
USB_PRODUCT_ID = 0x016B
DEFAULT_SYSFS_ROOT = Path("/sys/bus/usb/devices")


@dataclass(frozen=True)
class UsbScanner:
    """An FF-680W currently enumerated on the USB bus."""

    bus: int
    device: int
    sysfs_path: Path

    def sane_usb_device_name(self) -> str:
        raise NotImplementedError


def find_usb_scanners(sysfs_root: Path = DEFAULT_SYSFS_ROOT) -> list[UsbScanner]:
    raise NotImplementedError
