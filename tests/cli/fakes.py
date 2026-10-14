"""Test doubles for the scanner transport: the CLI tests never start a real scan."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.cli import cmd_devices, cmd_scan
from fastfoto_linux.pipeline.process import ProcessResult, ProcessSettings
from fastfoto_linux.scanner import ScanJob, ScanResult, ScanTarget, UsbScanner
from tests.process_helpers import write_front_pages, write_sheets
from tests.sides_helpers import Sheet

DEVICE = "epsonds:libusb:001:004"
SCANNER = UsbScanner(bus=1, device=4, sysfs_path=Path("/sys/bus/usb/devices/1-4"))
HOST = "203.0.113.7"  # TEST-NET-3: documentation addresses only

# Every place the CLI could reach the scanner from; also the names a different import style
# would use. They all refuse until a test installs a fake.
_TRANSPORT_NAMES = {
    "fastfoto_linux.cli.cmd_scan": ("resolve_target", "run_scan"),
    "fastfoto_linux.cli.cmd_devices": ("find_usb_scanners",),
    "fastfoto_linux.scanner": ("resolve_target", "run_scan", "find_usb_scanners"),
    "fastfoto_linux.scanner.run": ("run_scan",),
    "fastfoto_linux.scanner.target": ("resolve_target",),
    "fastfoto_linux.scanner.usb": ("find_usb_scanners",),
}


def refuse(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("a CLI test reached the scanner transport; fake it explicitly")


def block_hardware(monkeypatch: pytest.MonkeyPatch) -> None:
    for module, names in _TRANSPORT_NAMES.items():
        for name in names:
            monkeypatch.setattr(f"{module}.{name}", refuse)


@dataclass
class FakeTransport:
    """Stands in for ``resolve_target`` and ``run_scan``; records every call.

    ``sheets`` are written as the scanned pages (back page first unless ``front_first``);
    ``front_pages`` are single-sided pages for a simplex scan.
    ``failure`` builds the exception raised once ``pages_before_failure`` pages are on disk;
    ``keep_on_disk`` cuts the files down to the first pages first (a scan that stopped part-way).
    """

    sheets: Sequence[Sheet] = ()
    front_first: bool = False
    front_pages: int = 0
    pages_before_failure: int = 0
    failure: Callable[[tuple[Path, ...]], BaseException] | None = None
    resolve_error: Exception | None = None
    corrupt_page: int | None = None
    keep_on_disk: int | None = None
    resolve_calls: list[dict[str, Any]] = field(default_factory=list)
    config_dir_existed: list[bool] = field(default_factory=list)
    jobs: list[ScanJob] = field(default_factory=list)
    envs: list[Mapping[str, str]] = field(default_factory=list)

    def resolve_target(self, **kwargs: Any) -> ScanTarget:
        self.resolve_calls.append(kwargs)
        config_dir = kwargs.get("config_dir")
        if config_dir is not None:
            self.config_dir_existed.append(Path(config_dir).is_dir())
        if self.resolve_error is not None:
            raise self.resolve_error
        return ScanTarget(device=DEVICE)

    def run_scan(self, job: ScanJob, *, env: Mapping[str, str], **kwargs: Any) -> ScanResult:
        self.jobs.append(job)
        self.envs.append(env)
        job.output_dir.mkdir(parents=True, exist_ok=True)
        pages = write_sheets(job.output_dir, self.sheets, front_first=self.front_first)
        pages += write_front_pages(job.output_dir, self.front_pages, first_number=len(pages) + 1)
        if self.corrupt_page is not None:
            pages[self.corrupt_page - 1].write_bytes(b"not a png")
        on_progress = kwargs.get("on_progress")
        for number in range(1, len(pages) + 1):
            if on_progress is not None:
                on_progress(number)
        if self.keep_on_disk is not None:
            for page in pages[self.keep_on_disk :]:
                page.unlink()
        if self.failure is not None:
            raise self.failure(tuple(pages[: self.pages_before_failure]))
        return ScanResult(pages=tuple(pages))

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cmd_scan, "resolve_target", self.resolve_target)
        monkeypatch.setattr(cmd_scan, "run_scan", self.run_scan)


def spy_process_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[tuple[Path, ...], ProcessSettings]]:
    """Replace ``process_pages`` in both commands by a recorder that returns an empty result."""
    calls: list[tuple[tuple[Path, ...], ProcessSettings]] = []

    def record(pages: Sequence[Path], settings: ProcessSettings) -> ProcessResult:
        calls.append((tuple(pages), settings))
        return ProcessResult()

    monkeypatch.setattr(cmd_scan, "process_pages", record)
    monkeypatch.setattr("fastfoto_linux.cli.cmd_process.process_pages", record)
    return calls


def fake_usb(
    monkeypatch: pytest.MonkeyPatch,
    *,
    scanners: Sequence[UsbScanner] = (),
    shims: Sequence[Path] = (),
) -> None:
    monkeypatch.setattr(cmd_devices, "find_usb_scanners", lambda *a, **k: tuple(scanners))
    monkeypatch.setattr(cmd_devices, "default_shim_candidates", lambda *a, **k: tuple(shims))


def write_dummy_page(directory: Path, name: str) -> Path:
    """A page file that is never read (``process_pages`` is spied on)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"")
    return path


__all__ = [
    "DEVICE",
    "HOST",
    "SCANNER",
    "FakeTransport",
    "block_hardware",
    "fake_usb",
    "refuse",
    "spy_process_pages",
    "write_dummy_page",
]
