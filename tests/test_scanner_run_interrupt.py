"""An interrupt that lands before ``run_scan`` is watching scanimage must still stop it."""

import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.scanner.job import ScanJob
from fastfoto_linux.scanner.run import run_scan
from tests._fake_scanimage import fake_env, install

DEVICE = "epsonds:libusb:001:002"
PAGE_WAIT_S = 10.0


class InterruptingStderr:
    """Stands in for ``proc.stderr``: Ctrl-C lands when ``run_scan`` asks for its descriptor.

    It waits until the fake scanimage has written its first page, which is after the fake has
    installed its SIGTERM handler, so a missing marker can only mean it was never signalled.
    """

    def __init__(self, page: Path) -> None:
        self.page = page

    def fileno(self) -> int:
        deadline = time.monotonic() + PAGE_WAIT_S
        while not self.page.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        raise KeyboardInterrupt


def test_an_interrupt_right_after_scanimage_started_still_stops_it(tmp_path: Path) -> None:
    job = ScanJob(device=DEVICE, output_dir=tmp_path / "scans")
    marker = tmp_path / "sigterm-marker"
    env = fake_env(install(tmp_path / "bin"), pages=1, hang=True, sigterm_marker=str(marker))
    procs: list[subprocess.Popen[bytes]] = []

    def popen(argv: tuple[str, ...], **kwargs: Any) -> "subprocess.Popen[bytes]":
        proc = subprocess.Popen(argv, **kwargs)
        procs.append(proc)
        proc.stderr = InterruptingStderr(job.output_dir / "page-0001.png")  # type: ignore[assignment]
        return proc

    try:
        with pytest.raises(KeyboardInterrupt):
            run_scan(job, env=env, popen=popen)
        assert marker.exists(), "scanimage was left running"
        assert marker.read_text() == "terminated"
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
