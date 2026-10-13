"""Behavioural tests for tools/usb-gap-shim (LD_PRELOAD shim for the FF-680W USB quirk).

The FF-680W ignores a bulk OUT sent back-to-back with the end of its previous bulk IN reply, so
the shim delays such an OUT. libusb is not needed: a stub shared library stands in for it and
logs a CLOCK_MONOTONIC timestamp for every bulk call, and a small C driver replays IN/OUT
sequences against that stub with the shim preloaded. Assertions are made on the logged timestamps.

Everything is compiled with ``gcc`` (never ``cc``) in a temp dir; the module is skipped only when
``gcc`` or LD_PRELOAD support is missing.
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SHIM_DIR = REPO / "tools" / "usb-gap-shim"
SUPPORT_DIR = Path(__file__).resolve().parent / "usb_gap_shim"

GCC = shutil.which("gcc")
pytestmark = [
    pytest.mark.skipif(sys.platform != "linux", reason="LD_PRELOAD shim is Linux-only"),
    pytest.mark.skipif(GCC is None, reason="gcc not found; needed to build the shim and stubs"),
]

GAP_ENV = "FF680W_USB_GAP_US"
DEFAULT_GAP_MS = 2.0
NS_PER_MS = 1_000_000


@dataclass(frozen=True)
class Call:
    handle: str
    endpoint: int
    t_ns: int

    @property
    def is_in(self) -> bool:
        return bool(self.endpoint & 0x80)


def ms_between(first: Call, second: Call) -> float:
    return (second.t_ns - first.t_ns) / NS_PER_MS


def gcc(*args: str | Path) -> None:
    subprocess.run(
        [GCC, "-Wall", "-Wextra", "-Werror", *map(str, args)],
        check=True,
        capture_output=True,
        text=True,
    )


class Harness:
    """Compiled shim, stub libraries and driver, plus a way to run scripts against them."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.shim = root / "ff680w_usb_gap.so"
        self.driver = root / "driver"
        self.libdirs = {"full": root / "full", "noident": root / "noident"}
        self._runs = 0

    def build(self) -> None:
        # -Werror applies to the shim (and, harmlessly, to the test C code).
        gcc(
            "-shared",
            "-fPIC",
            "-pthread",
            "-o",
            self.shim,
            SHIM_DIR / "ff680w_usb_gap.c",
            "-ldl",
        )
        stub = SUPPORT_DIR / "stub_libusb.c"
        for variant, extra in (("full", []), ("noident", ["-DSTUB_NO_IDENTITY"])):
            self.libdirs[variant].mkdir()
            gcc("-shared", "-fPIC", *extra, "-o", self.libdirs[variant] / "libstubusb.so", stub)
        gcc(
            SUPPORT_DIR / "driver.c",
            "-o",
            self.driver,
            f"-L{self.libdirs['full']}",
            "-lstubusb",
        )

    def run(
        self,
        script: list[str],
        *,
        gap_us: int | str | None = None,
        env: dict[str, str] | None = None,
        variant: str = "shim",
    ) -> list[Call]:
        """Replay ``script`` and return the logged bulk calls.

        variant: "shim" = shim preloaded; "bare" = no shim; "noident" = shim preloaded and the
        stub lacks the descriptor functions (symbol lookup fails inside the shim).
        """
        self._runs += 1
        log = self.root / f"run{self._runs}.log"
        libdir = self.libdirs["noident" if variant == "noident" else "full"]
        run_env = {
            "PATH": os.environ.get("PATH", ""),
            "LD_LIBRARY_PATH": str(libdir),
            "STUB_LOG": str(log),
        }
        if variant != "bare":
            run_env["LD_PRELOAD"] = str(self.shim)
        if gap_us is not None:
            run_env[GAP_ENV] = str(gap_us)
        run_env.update(env or {})
        subprocess.run(
            [str(self.driver), *script], env=run_env, check=True, capture_output=True, text=True
        )
        calls = []
        for line in log.read_text().splitlines():
            handle, endpoint, t_ns = line.split()
            calls.append(Call(handle, int(endpoint, 16), int(t_ns)))
        return calls


@pytest.fixture(scope="session")
def harness(tmp_path_factory: pytest.TempPathFactory) -> Harness:
    built = Harness(tmp_path_factory.mktemp("usb_gap_shim"))
    built.build()
    return built


def test_without_shim_out_follows_in_back_to_back(harness: Harness) -> None:
    """Sanity check of the harness: this is the condition that wedges the scanner."""
    calls = harness.run(["in:A", "out:A"] * 20, variant="bare")
    deltas = [ms_between(i, o) for i, o in zip(calls[0::2], calls[1::2], strict=True)]
    assert min(deltas) < DEFAULT_GAP_MS, deltas


def test_out_after_in_is_delayed_by_the_configured_gap(harness: Harness) -> None:
    gap_ms = 20
    calls = harness.run(["in:A", "out:A"], gap_us=gap_ms * 1000)
    delta = ms_between(calls[0], calls[1])
    assert gap_ms <= delta < gap_ms + 150, f"OUT came {delta:.1f} ms after IN"


def test_default_gap_is_two_milliseconds(harness: Harness) -> None:
    calls = harness.run(["in:A", "out:A"] * 5)
    for i, o in zip(calls[0::2], calls[1::2], strict=True):
        assert ms_between(i, o) >= DEFAULT_GAP_MS


@pytest.mark.parametrize("value", ["", "abc", "12x", "-5"])
def test_unusable_gap_value_falls_back_to_the_default(harness: Harness, value: str) -> None:
    calls = harness.run(["in:A", "out:A"] * 5, gap_us=value)
    for i, o in zip(calls[0::2], calls[1::2], strict=True):
        assert ms_between(i, o) >= DEFAULT_GAP_MS


def test_zero_gap_disables_the_delay(harness: Harness) -> None:
    # With the default (2 ms) in force every pair would be at least 2 ms apart.
    calls = harness.run(["in:A", "out:A"] * 20, gap_us=0)
    deltas = [ms_between(i, o) for i, o in zip(calls[0::2], calls[1::2], strict=True)]
    assert min(deltas) < DEFAULT_GAP_MS, deltas


@pytest.mark.parametrize(
    ("vid", "pid"),
    [("1234", "5678"), ("04b8", "0000"), ("1234", "016b")],
    ids=["other-vendor", "other-epson-product", "other-vendor-same-pid"],
)
def test_other_devices_are_not_delayed(harness: Harness, vid: str, pid: str) -> None:
    gap_ms = 300
    calls = harness.run(
        ["in:A", "out:A"], gap_us=gap_ms * 1000, env={"STUB_VID": vid, "STUB_PID": pid}
    )
    delta = ms_between(calls[0], calls[1])
    assert delta < gap_ms / 3, f"non-FF-680W device delayed {delta:.1f} ms"


def test_unresolvable_device_identity_still_applies_the_gap(harness: Harness) -> None:
    """Fail-safe: if VID/PID cannot be looked up the shim must err on the side of delaying."""
    gap_ms = 20
    calls = harness.run(
        ["in:A", "out:A"],
        gap_us=gap_ms * 1000,
        env={"STUB_VID": "1234", "STUB_PID": "5678"},
        variant="noident",
    )
    delta = ms_between(calls[0], calls[1])
    assert gap_ms <= delta < gap_ms + 150, f"OUT came {delta:.1f} ms after IN"


def test_in_after_out_is_not_delayed(harness: Harness) -> None:
    gap_ms = 100
    calls = harness.run(["in:A", "out:A", "in:A"], gap_us=gap_ms * 1000)
    assert ms_between(calls[1], calls[2]) < gap_ms / 2


def test_out_after_out_is_not_delayed(harness: Harness) -> None:
    gap_ms = 100
    calls = harness.run(["in:A", "out:A", "out:A"], gap_us=gap_ms * 1000)
    assert ms_between(calls[1], calls[2]) < gap_ms / 2


def test_out_without_a_previous_in_is_not_delayed(harness: Harness) -> None:
    gap_ms = 300
    calls = harness.run(["out:A", "out:A"], gap_us=gap_ms * 1000)
    assert ms_between(calls[0], calls[1]) < gap_ms / 3


def test_gap_longer_than_one_second_is_honoured(harness: Harness) -> None:
    """Regression: nanosleep() got tv_nsec >= 1e9, failed with EINVAL and never slept."""
    gap_ms = 1200
    calls = harness.run(["in:A", "out:A"], gap_us=gap_ms * 1000)
    delta = ms_between(calls[0], calls[1])
    assert gap_ms <= delta < gap_ms + 400, f"OUT came {delta:.1f} ms after IN"


def test_handles_keep_independent_timestamps(harness: Harness) -> None:
    gap_ms = 300
    calls = harness.run(["in:A", "out:B", "out:A"], gap_us=gap_ms * 1000)
    in_a, out_b, out_a = calls
    assert ms_between(in_a, out_b) < gap_ms / 3, "B was delayed by A's IN"
    assert ms_between(in_a, out_a) >= gap_ms, "A's own IN no longer enforced a gap"


def test_another_handles_later_in_does_not_extend_the_wait(harness: Harness) -> None:
    gap_ms = 150
    calls = harness.run(["in:A", f"sleep:{gap_ms + 30}", "in:B", "out:A"], gap_us=gap_ms * 1000)
    in_a, in_b, out_a = calls
    assert ms_between(in_b, out_a) < gap_ms / 2, "A waited again because B just did an IN"
    assert ms_between(in_a, out_a) >= gap_ms


def test_closed_handle_address_reuse_resolves_identity_again(harness: Harness) -> None:
    """A new device opened at a recycled handle address must not inherit the old verdict."""
    gap_ms = 300
    calls = harness.run(
        [
            "open:A:1234:5678",
            "in:A",
            "out:A",
            "close:A",
            "open:A:04b8:016b",
            "in:A",
            "out:A",
        ],
        gap_us=gap_ms * 1000,
    )
    first_in, first_out, second_in, second_out = calls
    assert ms_between(first_in, first_out) < gap_ms / 3, "other device was delayed"
    assert ms_between(second_in, second_out) >= gap_ms, "FF-680W reusing the address not delayed"


def test_makefile_builds_the_shim(tmp_path: Path) -> None:
    makefile = SHIM_DIR / "Makefile"
    assert makefile.is_file(), "tools/usb-gap-shim/Makefile is missing"
    if shutil.which("make") is None:
        pytest.skip("make not found")
    for name in ("Makefile", "ff680w_usb_gap.c"):
        shutil.copy(SHIM_DIR / name, tmp_path / name)
    result = subprocess.run(
        ["make", "-C", str(tmp_path)], check=True, capture_output=True, text=True
    )
    assert (tmp_path / "ff680w_usb_gap.so").is_file()
    assert "gcc " in result.stdout, result.stdout
    assert "-Werror" in result.stdout, result.stdout
