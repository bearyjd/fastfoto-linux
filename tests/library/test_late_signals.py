"""A stop signal that lands after the pool is torn down is ignored until ``main`` has returned.

``first_interrupt_only`` hands the signals back to ``main``'s handlers as its block ends, and
``main`` prints "interrupted" only after that. A further signal in that gap used to raise again
inside the message (an uncaught KeyboardInterrupt) or, once ``main`` had put the original handlers
back, kill the process by the signal's default action: no message, and not exit code 130.
"""

import signal
import subprocess
import sys
from pathlib import Path

import pytest

from fastfoto_linux.cli import cmd_library
from fastfoto_linux.cli.app import main
from tests.library.late_signal_runner import interrupted_in_the_pool

EXIT_INTERRUPTED = 130
RUN_TIMEOUT_S = 60
REPO_ROOT = Path(__file__).resolve().parents[2]
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
PAIRS = [(first, second) for first in STOP_SIGNALS for second in STOP_SIGNALS]
PAIR_IDS = [f"{first.name}-then-{second.name}" for first, second in PAIRS]


def check_argv(tmp_path: Path) -> list[str]:
    library = tmp_path / "lib"
    library.mkdir(exist_ok=True)
    return ["library", "check", str(library), "--plan", str(tmp_path / "plan.csv"), "--jobs", "1"]


@pytest.mark.timeout(120)
@pytest.mark.parametrize(("first", "second"), PAIRS, ids=PAIR_IDS)
def test_a_second_stop_signal_after_the_teardown_still_ends_with_the_message_and_130(
    tmp_path: Path, first: signal.Signals, second: signal.Signals
) -> None:
    command = [
        *(
            sys.executable,
            "-m",
            "tests.library.late_signal_runner",
            str(int(first)),
            str(int(second)),
        ),
        *check_argv(tmp_path),
    ]
    done = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_S,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert done.returncode == EXIT_INTERRUPTED, done.stderr
    assert "ffscan: interrupted" in done.stderr.splitlines()
    assert "Traceback" not in done.stderr
    assert not (tmp_path / "plan.csv").exists()


@pytest.mark.parametrize("first", STOP_SIGNALS, ids=lambda number: number.name)
def test_a_later_command_in_the_same_process_is_not_deaf_to_stop_signals(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, first: signal.Signals
) -> None:
    """Whatever remembers that a stop is under way is forgotten when ``main`` returns."""
    before = {number: signal.getsignal(number) for number in STOP_SIGNALS}
    argv = check_argv(tmp_path)
    monkeypatch.setattr(cmd_library, "decide_files", interrupted_in_the_pool(first))
    assert main(argv) == EXIT_INTERRUPTED
    monkeypatch.setattr(
        cmd_library, "decide_files", lambda *_args, **_kwargs: signal.raise_signal(first)
    )
    assert main(argv) == EXIT_INTERRUPTED
    assert {number: signal.getsignal(number) for number in STOP_SIGNALS} == before
