"""Talk to a real FF-680W. Read-only: this opens the device and lists options, never scans."""

import os
import subprocess

import pytest

from fastfoto_linux.scanner import (
    ScannerNotFoundError,
    ShimMissingError,
    default_shim_candidates,
    resolve_target,
)

LIST_OPTIONS_TIMEOUT_S = 60


@pytest.mark.hardware
def test_scanimage_lists_options_on_the_real_scanner_through_the_shim() -> None:
    try:
        target = resolve_target(shim_candidates=default_shim_candidates(os.environ))
    except (ScannerNotFoundError, ShimMissingError) as exc:
        pytest.skip(f"no usable FF-680W: {exc}")
    env = target.env(os.environ)

    proc = subprocess.run(  # no shell; "-A" opens the device and prints options, no scan
        ["scanimage", "-d", target.device, "-A"],
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=LIST_OPTIONS_TIMEOUT_S,
        check=False,
    )

    lists_source_option = "--source" in proc.stdout
    assert proc.returncode == 0, "scanimage -A failed"
    assert lists_source_option, "scanimage -A did not list the --source option"
