"""SIGTERM and SIGHUP end ``check`` like Ctrl-C does, and cannot cut the cleanup short either.

``ffscan`` turns them into KeyboardInterrupt (``cli.app``); a second one of any of the three,
arriving while the workers are being stopped, would abort the stopping and leave workers behind.
"""

import contextlib
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ALL_COMPLETED
from pathlib import Path

import pytest

from fastfoto_linux.cli import app as app_module
from fastfoto_linux.library import decide as decide_module
from fastfoto_linux.library import stopping
from tests.library import crash_worker
from tests.library.jpeg_helpers import sideways_jpeg, write_file
from tests.library.test_interrupt import (
    EXIT_DEADLINE_S,
    INTERRUPTED_EXITS,
    ORPHAN_DEADLINE_S,
    REPO_ROOT,
    START_DEADLINE_S,
    WORKERS,
    FakeProcess,
    group_is_gone,
    wait_until,
)

STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
PAIRS = [
    (signal.SIGINT, signal.SIGTERM),
    (signal.SIGTERM, signal.SIGINT),
    (signal.SIGTERM, signal.SIGHUP),
    (signal.SIGHUP, signal.SIGTERM),
    (signal.SIGTERM, signal.SIGTERM),
]
MAX_SLICE_S = 1.0
PAIR_IDS = [f"{first.name}-then-{second.name}" for first, second in PAIRS]


def handlers() -> dict[signal.Signals, object]:
    return {number: signal.getsignal(number) for number in STOP_SIGNALS}


def test_the_teardown_ignores_every_stop_signal_and_puts_them_back() -> None:
    with app_module._signals_as_interrupt():
        before = handlers()
        with stopping.interrupts_ignored():
            assert {number: signal.getsignal(number) for number in STOP_SIGNALS} == dict.fromkeys(
                STOP_SIGNALS, signal.SIG_IGN
            )
        assert handlers() == before


@pytest.mark.parametrize("first", STOP_SIGNALS, ids=lambda number: number.name)
def test_the_first_stop_signal_interrupts_and_every_further_one_is_ignored(
    first: signal.Signals,
) -> None:
    with app_module._signals_as_interrupt():
        before = handlers()
        with stopping.first_interrupt_only():
            with pytest.raises(KeyboardInterrupt):
                signal.raise_signal(first)
            for number in STOP_SIGNALS:
                assert signal.getsignal(number) is signal.SIG_IGN
                signal.raise_signal(number)  # no exception: the cleanup is not interrupted
        assert handlers() == before


class PoolWithAnotherSignal:
    """A pool whose list of workers is read just as the cleanup starts: the moment a second
    stop signal is most likely to land."""

    process = FakeProcess()
    second = signal.SIGINT

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        PoolWithAnotherSignal.process = FakeProcess()

    @property
    def _processes(self) -> dict[int, FakeProcess]:
        os.kill(os.getpid(), PoolWithAnotherSignal.second)
        return {1: PoolWithAnotherSignal.process}

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        pass


@pytest.mark.timeout(30)
@pytest.mark.parametrize(("first", "second"), PAIRS, ids=PAIR_IDS)
def test_a_second_stop_signal_cannot_cut_the_cleanup_short(
    monkeypatch: pytest.MonkeyPatch, first: signal.Signals, second: signal.Signals
) -> None:
    monkeypatch.setattr(decide_module, "ProcessPoolExecutor", PoolWithAnotherSignal)
    PoolWithAnotherSignal.second = second
    with app_module._signals_as_interrupt():
        before = handlers()
        with pytest.raises(KeyboardInterrupt), decide_module._pool(2):
            os.kill(os.getpid(), first)  # the first one, inside the pool's block
            time.sleep(5)
        assert handlers() == before
    assert PoolWithAnotherSignal.process.calls[:2] == ["terminate", "join"]


@pytest.mark.timeout(60)
@pytest.mark.parametrize(("first", "second"), PAIRS[:4], ids=PAIR_IDS[:4])
@pytest.mark.parametrize("gap_s", [0.0, 0.03])
def test_two_stop_signals_to_check_leave_no_plan_and_no_workers(
    tmp_path: Path, first: signal.Signals, second: signal.Signals, gap_s: float
) -> None:
    library, plan, busy = tmp_path / "lib", tmp_path / "plan.csv", tmp_path / "busy"
    busy.mkdir()
    for index in range(4 * WORKERS):
        write_file(library, f"p{index}.jpg", sideways_jpeg(90, None))
    command = [
        *(sys.executable, "-m", "tests.library.sigint_runner"),
        *("library", "check", str(library), "--plan", str(plan), "--jobs", str(WORKERS)),
    ]
    with (tmp_path / "output.txt").open("w") as output:
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
        )
    try:
        assert wait_until(lambda: len(list(busy.iterdir())) >= WORKERS, START_DEADLINE_S)
        os.kill(process.pid, first)  # the check process only: workers are left to its cleanup
        time.sleep(gap_s)
        with contextlib.suppress(ProcessLookupError):
            os.kill(process.pid, second)
        try:
            code = process.wait(timeout=EXIT_DEADLINE_S)
        except subprocess.TimeoutExpired:
            pytest.fail(f"check was still running {EXIT_DEADLINE_S} s after the signals")
        killed_by_signal = (-first, -second)  # a signal that lands after the cleanup is final
        assert code in (*INTERRUPTED_EXITS, *killed_by_signal)
        assert not plan.exists()
        assert wait_until(lambda: group_is_gone(process.pid), ORPHAN_DEADLINE_S), (
            "worker processes are still running after check exited"
        )
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


@pytest.mark.timeout(120)
def test_waits_for_workers_are_made_in_slices_so_a_stray_signal_is_acted_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The kernel may hand a signal to a thread other than the main one, which then stays blocked
    in an untimed wait; every wait for a worker therefore has a timeout."""
    names = [f"{c}.jpg" for c in "abc"] + [crash_worker.POISON]
    for name in names:
        write_file(tmp_path, name, sideways_jpeg(90, None))
    timeouts: list[float | None] = []
    real = decide_module.wait

    def spy(futures, timeout=None, return_when=ALL_COMPLETED):
        timeouts.append(timeout)
        return real(futures, timeout=timeout, return_when=return_when)

    monkeypatch.setattr(decide_module, "wait", spy)
    rows = decide_module.decide_files(tmp_path, sorted(names), 2, worker=crash_worker.die_on_poison)
    assert len(rows) == len(names)  # the pool, and the lone retry of the file that kills it, ran
    assert timeouts
    assert all(seconds is not None and seconds <= MAX_SLICE_S for seconds in timeouts)
