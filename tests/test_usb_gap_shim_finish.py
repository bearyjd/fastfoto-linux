"""The shim keeps sending when a bulk OUT to the FF-680W times out half-way (C-level tests).

A send that times out having sent only part of its payload makes the scanner swallow every later
byte, waiting for the rest. The shim sends the remainder with the same per-call timeout until all
of it went or ``FF680W_OUT_FINISH_MS`` has passed. The same stub libusb and driver as in
``test_usb_gap_shim`` stand in for the library; the stub's plans script each call's result, and
the bytes it receives are compared with the buffer the driver sent.
"""

import re
import time
from pathlib import Path

import pytest

from tests.test_usb_gap_shim import (
    SUPPORT_DIR,
    Harness,
    gcc,
    ms_between,
    pytestmark,  # noqa: F401 - the same gcc / Linux conditions
)

FINISH_ENV = "FF680W_OUT_FINISH_MS"
TIMEOUT = -7
NO_DEVICE = -4
PATTERN_MODULUS = 251
RESULT = re.compile(r"(\w+) ep=([0-9a-f]+) rc=(-?\d+) transferred=(-?\d+)")
README = Path(__file__).resolve().parent.parent / "tools" / "usb-gap-shim" / "README.md"


@pytest.fixture(scope="module")
def harness(tmp_path_factory: pytest.TempPathFactory) -> Harness:
    built = Harness(tmp_path_factory.mktemp("usb_gap_shim_finish"))
    built.build()
    return built


@pytest.fixture(scope="module")
def fake_clock(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A virtual CLOCK_MONOTONIC that only sleeping moves forward (see fake_clock.c)."""
    library = tmp_path_factory.mktemp("usb_gap_shim_clock") / "fake_clock.so"
    gcc("-shared", "-fPIC", "-o", library, SUPPORT_DIR / "fake_clock.c")
    return library


def pattern(length: int) -> bytes:
    return bytes(i % PATTERN_MODULUS for i in range(length))


class Sent:
    """One driver run: the result it printed, the calls the stub saw and the bytes it got."""

    def __init__(
        self,
        harness: Harness,
        tmp_path: Path,
        script: list[str],
        *,
        variant: str = "shim",
        **env: str,
    ) -> None:
        self.sent_file = tmp_path / "sent.bin"
        started = time.monotonic()
        result, self.calls = harness.execute(
            script, gap_us=0, variant=variant, env={"STUB_SENT": str(self.sent_file), **env}
        )
        self.elapsed_s = time.monotonic() - started
        match = RESULT.search(result.stdout)
        assert match, result.stdout
        _, endpoint, rc, transferred = match.groups()
        self.endpoint, self.rc, self.transferred = int(endpoint, 16), int(rc), int(transferred)

    @property
    def out_calls(self) -> int:
        return sum(1 for call in self.calls if not call.is_in)

    @property
    def stream(self) -> bytes:
        return self.sent_file.read_bytes() if self.sent_file.exists() else b""


def send(
    harness: Harness, tmp_path: Path, length: int, plan: str, *, variant: str = "shim", **env: str
) -> Sent:
    return Sent(harness, tmp_path, [f"send:A:{length}"], variant=variant, STUB_OUT_PLAN=plan, **env)


# --- the remainder is sent -----------------------------------------------------------------------


def test_a_partial_send_is_continued_until_every_byte_went(
    harness: Harness, tmp_path: Path
) -> None:
    run = send(harness, tmp_path, 1000, "t100,t0,ok")

    assert (run.rc, run.transferred) == (0, 1000)
    assert run.out_calls == 3
    assert run.stream == pattern(1000)  # the remainder was sent from the right place


def test_a_send_that_went_in_one_piece_is_not_repeated(harness: Harness, tmp_path: Path) -> None:
    run = send(harness, tmp_path, 1000, "ok")

    assert (run.rc, run.transferred, run.out_calls) == (0, 1000, 1)


def test_a_timeout_that_took_nothing_is_retried_from_the_start(
    harness: Harness, tmp_path: Path
) -> None:
    run = send(harness, tmp_path, 300, "t0,t0,ok")

    assert (run.rc, run.transferred, run.out_calls) == (0, 300, 3)
    assert run.stream == pattern(300)


def test_a_timeout_after_all_the_bytes_went_is_a_success(harness: Harness, tmp_path: Path) -> None:
    run = send(harness, tmp_path, 500, "t500")

    assert (run.rc, run.transferred, run.out_calls) == (0, 500, 1)


def test_a_null_transferred_pointer_is_allowed(harness: Harness, tmp_path: Path) -> None:
    run = Sent(harness, tmp_path, ["send:A:1000:null"], STUB_OUT_PLAN="t100,ok")

    assert run.rc == 0
    assert run.out_calls == 2
    assert run.stream == pattern(1000)


# --- it gives up ---------------------------------------------------------------------------------


def test_a_send_that_never_completes_gives_up_after_the_time_allowed(
    harness: Harness, tmp_path: Path
) -> None:
    run = send(harness, tmp_path, 1000, "t0", **{FINISH_ENV: "300", "STUB_TIMEOUT_MS": "50"})

    assert (run.rc, run.transferred) == (TIMEOUT, 0)
    assert 0.3 <= run.elapsed_s < 3.0
    assert 3 <= run.out_calls <= 12


def test_the_total_of_a_send_that_only_got_part_of_the_way_is_reported(
    harness: Harness, tmp_path: Path
) -> None:
    run = send(harness, tmp_path, 1000, "t10", **{FINISH_ENV: "300", "STUB_TIMEOUT_MS": "50"})

    assert run.rc == TIMEOUT
    assert 10 < run.transferred < 1000  # several calls' worth, and never a success
    assert run.stream == pattern(1000)[: run.transferred]


def test_another_error_stops_the_retries_and_keeps_the_total(
    harness: Harness, tmp_path: Path
) -> None:
    run = send(harness, tmp_path, 1000, f"t100,e{NO_DEVICE}")

    assert (run.rc, run.transferred, run.out_calls) == (NO_DEVICE, 100, 2)


def test_zero_turns_the_retries_off(harness: Harness, tmp_path: Path) -> None:
    run = send(harness, tmp_path, 1000, "t100,ok", **{FINISH_ENV: "0"})

    assert (run.rc, run.transferred, run.out_calls) == (TIMEOUT, 100, 1)


@pytest.mark.parametrize(
    "value",
    ["", "abc", "12x", "-5", "99999999999999999999", "600001"],
    ids=["empty", "word", "trailing-junk", "negative", "out-of-range", "above-the-cap"],
)
def test_an_unusable_value_means_the_default_and_the_retries_stay_on(
    harness: Harness, tmp_path: Path, value: str
) -> None:
    run = send(harness, tmp_path, 1000, "t100,ok", **{FINISH_ENV: value})

    assert (run.rc, run.transferred, run.out_calls) == (0, 1000, 2)


# --- the default time -----------------------------------------------------------------------------

VIRTUAL_CALL_MS = 1000  # every OUT call of these tests "waits" this long, in virtual time


@pytest.mark.parametrize(
    ("setting", "calls"),
    [(None, 30), ("30000", 30), ("10000", 10)],
    ids=["unset-is-30-s", "30-s", "10-s"],
)
def test_the_time_allowed_for_finishing_a_send_defaults_to_30_seconds(
    harness: Harness, fake_clock: Path, tmp_path: Path, setting: str | None, calls: int
) -> None:
    """On a virtual clock, 30 s of calls that take 1 s each and take nothing are 30 calls."""
    env = {
        "LD_PRELOAD": f"{fake_clock}:{harness.shim}",  # the clock first, so that it is the one used
        "STUB_TIMEOUT_MS": str(VIRTUAL_CALL_MS),
    }
    if setting is not None:
        env[FINISH_ENV] = setting

    run = send(harness, tmp_path, 1000, "t0", **env)

    assert (run.rc, run.transferred, run.out_calls) == (TIMEOUT, 0, calls)
    assert run.elapsed_s < 3.0  # the 30 seconds were virtual


# --- no busy spin --------------------------------------------------------------------------------


def test_a_timeout_that_returns_at_once_with_nothing_sent_is_not_retried_in_a_busy_spin(
    harness: Harness, tmp_path: Path
) -> None:
    """A transfer that times out instantly (no time spent waiting) must not be hammered."""
    run = send(harness, tmp_path, 1000, "t0", **{FINISH_ENV: "300", "STUB_TIMEOUT_MS": "0"})

    assert (run.rc, run.transferred) == (TIMEOUT, 0)
    assert 0.3 <= run.elapsed_s < 3.0
    assert 50 <= run.out_calls <= 400  # about one try per millisecond; a spin makes thousands


# --- what is left alone --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("vid", "pid"), [("1234", "5678"), ("04b8", "0000")], ids=["other-vendor", "other-product"]
)
def test_another_device_is_not_retried(
    harness: Harness, tmp_path: Path, vid: str, pid: str
) -> None:
    run = send(harness, tmp_path, 1000, "t100,ok", STUB_VID=vid, STUB_PID=pid)

    assert (run.rc, run.transferred, run.out_calls) == (TIMEOUT, 100, 1)


def test_a_device_whose_identity_cannot_be_read_is_not_retried(
    harness: Harness, tmp_path: Path
) -> None:
    """Fail closed: finishing a send is only right for the FF-680W, so with no proof it is not.

    (The gap, whose worst case is a 2 ms delay, is applied anyway: see test_usb_gap_shim.)
    """
    run = send(harness, tmp_path, 1000, "t100,ok", variant="noident")

    assert (run.rc, run.transferred, run.out_calls) == (TIMEOUT, 100, 1)


def test_an_in_transfer_is_never_retried(harness: Harness, tmp_path: Path) -> None:
    result, calls = harness.execute(["recv:A:512"], gap_us=0, env={"STUB_IN_PLAN": "t5,ok"})

    assert RESULT.search(result.stdout).groups()[2:] == (str(TIMEOUT), "5")
    assert len(calls) == 1


def test_the_gap_before_the_first_out_is_kept_and_the_retries_add_no_gap(
    harness: Harness, tmp_path: Path
) -> None:
    gap_ms = 200
    _, calls = harness.execute(
        ["in:A", "send:A:1000"],
        gap_us=gap_ms * 1000,
        env={"STUB_OUT_PLAN": "t100,ok", "STUB_SENT": str(tmp_path / "sent.bin")},
    )

    read, first, second = calls
    assert ms_between(read, first) >= gap_ms
    assert ms_between(first, second) < gap_ms / 2


# --- the README ----------------------------------------------------------------------------------


def test_the_readme_describes_the_setting_and_does_not_claim_a_fix() -> None:
    text = README.read_text()

    assert FINISH_ENV in text
    assert "expected to prevent the stuck state" in text
    assert "needs a hardware test" in text
    assert "identity" in text  # what happens when the device cannot be told apart
    assert "prevents the stuck" not in text  # it has not been tried on the scanner yet
