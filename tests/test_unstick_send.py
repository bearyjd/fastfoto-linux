"""How long the check keeps offering an OUT, and how it waits between offers (review round 2).

Item 2: the budget for a refused OUT is pinned to 15 s from both sides, so that a change to 14 s or
16 s fails (before, only "between 10 and 20 s" was checked). Item 5: an OUT that times out at once
with nothing taken is followed by a 1 ms nap, so that a refusal costing no time cannot become a
busy loop.
"""

import pytest

from fastfoto_linux.scanner import unstick
from fastfoto_linux.scanner.errors import ScannerStuckError
from fastfoto_linux.scanner.unstick import Outcome
from tests.unstick_fakes import FakeClock, FakeScanner

BUDGET_S = 15.0
SLICE_S = 0.25  # a refused OUT lasts one slice of the check's own choosing
NAP_S = 0.001
EPSILON_S = 1e-6
SPIN_LIMIT = 50_000  # the budget allows about 15,000 offers at 1 ms each; more is a busy loop
FOREVER_S = 1e9


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


class FirstOut:
    """An ``on_write`` hook that remembers when the first OUT was offered and, if asked, makes the
    scanner refuse OUTs for ``refuse_s`` seconds from then on."""

    def __init__(self, clock: FakeClock, refuse_s: float) -> None:
        self.clock = clock
        self.refuse_s = refuse_s
        self.at: float | None = None

    def __call__(self, scanner: FakeScanner) -> None:
        if self.at is None:
            self.at = self.clock.now
            scanner.refuse_out_until_s = self.at + self.refuse_s


def test_an_out_refused_for_14_5_seconds_is_still_waited_out(clock: FakeClock) -> None:
    scanner = FakeScanner(clock)
    scanner.on_write = FirstOut(clock, 14.5)

    result = unstick.ensure_ready(scanner, clock=clock)

    assert result.outcome is Outcome.HEALTHY
    assert scanner.writes[0] == unstick.HELLO


def test_an_out_that_is_never_accepted_ends_the_check_after_exactly_the_budget(
    clock: FakeClock,
) -> None:
    scanner = FakeScanner(clock)
    first = FirstOut(clock, FOREVER_S)
    scanner.on_write = first

    with pytest.raises(ScannerStuckError):
        unstick.ensure_ready(scanner, clock=clock)

    assert first.at is not None
    waited = clock.now - first.at
    assert BUDGET_S - EPSILON_S <= waited <= BUDGET_S + SLICE_S + EPSILON_S


# --- no busy spin -------------------------------------------------------------------------------


class InstantRefusals:
    """A transport whose OUT times out at once with nothing taken, as if the wait cost no time."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.writes = 0

    def write(self, data: bytes, timeout_ms: int) -> int:
        self.writes += 1
        if self.writes > SPIN_LIMIT:
            pytest.fail("busy spin: the OUT was offered again and again without a pause")
        return 0

    def read(self, size: int, timeout_ms: int) -> bytes:
        self.clock.now += timeout_ms / 1000
        return b""


@pytest.fixture
def naps(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> list[float]:
    """Every pause the check asks for; each one moves the fake clock by that long."""
    taken: list[float] = []

    def sleep(seconds: float) -> None:
        taken.append(seconds)
        clock.now += seconds

    monkeypatch.setattr(unstick, "_sleep", sleep)
    return taken


def test_an_out_that_times_out_at_once_with_nothing_taken_is_followed_by_a_nap(
    clock: FakeClock, naps: list[float]
) -> None:
    transport = InstantRefusals(clock)

    with pytest.raises(ScannerStuckError):
        unstick.ensure_ready(transport, clock=clock)

    assert set(naps) == {unstick.RETRY_NAP_S}  # one per refusal; the last needs none: it gives up
    assert transport.writes - 1 <= len(naps) <= transport.writes
    assert unstick.RETRY_NAP_S == NAP_S
    assert transport.writes == pytest.approx(BUDGET_S / NAP_S, abs=5)


def test_an_out_that_ran_out_its_whole_timeout_is_not_followed_by_a_nap(
    clock: FakeClock, naps: list[float]
) -> None:
    scanner = FakeScanner(clock, refuse_out_until_s=3.0)  # each refusal lasts its whole slice

    unstick.ensure_ready(scanner, clock=clock)

    assert naps == []


def test_an_out_that_took_some_bytes_is_not_followed_by_a_nap(
    clock: FakeClock, naps: list[float]
) -> None:
    scanner = FakeScanner(clock, accept_per_call=1)

    unstick.ensure_ready(scanner, clock=clock)

    assert naps == []
