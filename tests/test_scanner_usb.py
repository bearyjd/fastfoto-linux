import logging
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from fastfoto_linux.scanner.usb import (
    DEFAULT_SYSFS_ROOT,
    USB_PRODUCT_ID,
    USB_VENDOR_ID,
    UsbScanner,
    find_usb_scanners,
)
from tests._fake_sysfs import add_usb_device


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "devices"
    path.mkdir()
    return path


def test_ids_and_default_root_match_the_ff680w() -> None:
    assert (USB_VENDOR_ID, USB_PRODUCT_ID) == (0x04B8, 0x016B)
    assert Path("/sys/bus/usb/devices") == DEFAULT_SYSFS_ROOT


def test_no_scanner_returns_empty_list(root: Path) -> None:
    assert find_usb_scanners(root) == []


def test_missing_sysfs_root_returns_empty_list(tmp_path: Path) -> None:
    assert find_usb_scanners(tmp_path / "does-not-exist") == []


def test_sysfs_root_that_is_a_file_returns_empty_list(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("")
    assert find_usb_scanners(not_a_dir) == []


def test_one_scanner_reports_bus_device_and_sysfs_path(root: Path) -> None:
    entry = add_usb_device(root, "3-1", busnum="3", devnum="15")

    assert find_usb_scanners(root) == [UsbScanner(bus=3, device=15, sysfs_path=entry)]


def test_two_scanners_are_sorted_by_bus_then_device_not_by_directory_name(root: Path) -> None:
    add_usb_device(root, "1-a", busnum="2", devnum="9")
    add_usb_device(root, "2-b", busnum="1", devnum="30")
    add_usb_device(root, "3-c", busnum="2", devnum="4")

    found = find_usb_scanners(root)

    assert [(s.bus, s.device) for s in found] == [(1, 30), (2, 4), (2, 9)]


def test_hex_ids_are_case_insensitive_and_tolerate_whitespace(root: Path) -> None:
    add_usb_device(root, "1-1", vendor="04B8\n", product=" 016B ")

    assert len(find_usb_scanners(root)) == 1


@pytest.mark.parametrize(
    ("vendor", "product"),
    [
        ("04b9", "016b"),  # other vendor, same product
        ("04b8", "016c"),  # Epson, other product
        ("1d6b", "0002"),  # a root hub
    ],
)
def test_other_usb_devices_are_ignored(root: Path, vendor: str, product: str) -> None:
    add_usb_device(root, "usb1", vendor=vendor, product=product)

    assert find_usb_scanners(root) == []


def test_interface_entries_without_idvendor_are_skipped(root: Path) -> None:
    add_usb_device(root, "3-1:1.0", vendor=None, product=None, busnum=None, devnum=None)
    add_usb_device(root, "3-1")

    assert [s.sysfs_path.name for s in find_usb_scanners(root)] == ["3-1"]


def test_plain_files_in_the_root_are_skipped(root: Path) -> None:
    (root / "stray-file").write_text("")
    add_usb_device(root, "3-1")

    assert len(find_usb_scanners(root)) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"vendor": "zzzz"},
        {"vendor": ""},
        {"product": "not-hex"},
        {"busnum": None},
        {"devnum": None},
        {"busnum": "three"},
        {"devnum": "0x0f"},
        {"devnum": "0"},
        {"busnum": "-1"},
    ],
)
def test_malformed_entries_are_skipped_and_do_not_hide_good_ones(
    root: Path, overrides: dict[str, str | None]
) -> None:
    add_usb_device(root, "1-bad", **overrides)
    good = add_usb_device(root, "2-good", busnum="2", devnum="7")

    assert find_usb_scanners(root) == [UsbScanner(bus=2, device=7, sysfs_path=good)]


def test_unreadable_attribute_is_skipped(root: Path) -> None:
    broken = add_usb_device(root, "1-broken")
    (broken / "busnum").unlink()
    (broken / "busnum").mkdir()  # reading a directory raises OSError
    good = add_usb_device(root, "2-good")

    assert [s.sysfs_path for s in find_usb_scanners(root)] == [good]


def test_skipped_entries_are_logged_at_debug_level(
    root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    add_usb_device(root, "1-bad", vendor="zzzz")

    with caplog.at_level(logging.DEBUG, logger="fastfoto_linux.scanner.usb"):
        find_usb_scanners(root)

    assert any(record.levelno == logging.DEBUG for record in caplog.records)
    assert all(record.levelno == logging.DEBUG for record in caplog.records)


@pytest.mark.parametrize(
    ("bus", "device", "expected"),
    [
        (1, 2, "epsonds:libusb:001:002"),
        (12, 123, "epsonds:libusb:012:123"),
        (100, 7, "epsonds:libusb:100:007"),
    ],
)
def test_sane_device_name_zero_pads_bus_and_device_to_three_digits(
    bus: int, device: int, expected: str
) -> None:
    scanner = UsbScanner(bus=bus, device=device, sysfs_path=Path("unused"))

    assert scanner.sane_usb_device_name() == expected


def test_usb_scanner_is_frozen() -> None:
    scanner = UsbScanner(bus=1, device=2, sysfs_path=Path("unused"))

    with pytest.raises(FrozenInstanceError):
        scanner.bus = 5  # type: ignore[misc]
