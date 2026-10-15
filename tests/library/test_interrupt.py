"""Ctrl-C during ``check``: prompt exit 130, no plan, no worker left behind, even if it comes twice.

``uv run`` forwards a second SIGINT about 0.2 s after the first; the first one starts the
shutdown, so the second must not be able to leave the process waiting for its workers.
"""

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from fastfoto_linux.library import decide as decide_module
from tests.library import crash_worker
from tests.library.jpeg_helpers import sideways_jpeg, write_file

REPO_ROOT = Path(__file__).resolve().parents[2]
START_DEADLINE_S = 25
EXIT_DEADLINE_S = 12
ORPHAN_DEADLINE_S = 6
SECOND_SIGINT_DELAY_S = 0.2
EXIT_INTERRUPTED = 130
WORKERS = 2


def alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return state != "Z"


def wait_until(condition, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


def group_is_gone(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    return False


@pytest.mark.timeout(60)
def test_two_quick_ctrl_c_stop_check_promptly_with_no_plan_and_no_workers(tmp_path: Path) -> None:
    library, plan, busy = tmp_path / "lib", tmp_path / "plan.csv", tmp_path / "busy"
    busy.mkdir()
    for index in range(4 * WORKERS):
        write_file(library, f"p{index}.jpg", sideways_jpeg(90, None))
    command = [
        sys.executable,
        "-m",
        "tests.library.sigint_runner",
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
        assert wait_until(lambda: len(list(busy.iterdir())) >= WORKERS, START_DEADLINE_S), (
            "the workers never started"
        )
        os.killpg(process.pid, signal.SIGINT)
        time.sleep(SECOND_SIGINT_DELAY_S)
        os.killpg(process.pid, signal.SIGINT)
        try:
            code = process.wait(timeout=EXIT_DEADLINE_S)
        except subprocess.TimeoutExpired:
            pytest.fail(f"check was still running {EXIT_DEADLINE_S} s after Ctrl-C")
        assert code == EXIT_INTERRUPTED
        assert not plan.exists()
        assert wait_until(lambda: group_is_gone(process.pid), ORPHAN_DEADLINE_S), (
            "worker processes are still running after check exited"
        )
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


@pytest.mark.timeout(60)
def test_leaving_the_pool_early_terminates_its_workers_at_once() -> None:
    with pytest.raises(KeyboardInterrupt), decide_module._pool(WORKERS) as pool:
        for _ in range(WORKERS):
            pool.submit(time.sleep, crash_worker.BUSY_SECONDS)
        assert wait_until(lambda: len(pool._processes or {}) == WORKERS, START_DEADLINE_S)
        pids = [process.pid for process in pool._processes.values()]
        raise KeyboardInterrupt
    assert wait_until(lambda: not any(alive(pid) for pid in pids), ORPHAN_DEADLINE_S)


def test_stopping_workers_off_the_main_thread_leaves_the_signal_alone() -> None:
    seen: list[object] = []

    def run() -> None:
        with decide_module._interrupts_ignored():
            seen.append(signal.getsignal(signal.SIGINT))

    before = signal.getsignal(signal.SIGINT)
    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    assert seen == [before]
