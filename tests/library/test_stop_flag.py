"""The stop handler takes no lock, so a second signal cannot make it wait for itself.

A signal handler runs on the thread it interrupted. ``threading.Event.set`` holds a lock that is not
re-entrant, so a second Ctrl-C landing inside it ran the handler again and waited for the lock the
first run held: the process slept for good and the workers stayed alive. This is a rare race with
real keyboards, so the test lands a second signal at every step of the handler, one by one.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

RUN_TIMEOUT_S = 10  # the sweep takes well under a second; a hang is killed after this
MIN_STEPS = 8  # a sweep over less than this did not look at the handler
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.timeout(60)
def test_a_second_signal_at_any_step_of_the_stop_handler_does_not_hang_it() -> None:
    command = [sys.executable, "-m", "tests.library.stop_flag_runner"]
    try:
        done = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_S,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"the stop handler hung (no exit within {RUN_TIMEOUT_S} s) on a second signal")
    assert done.returncode == 0, done.stderr
    found = re.fullmatch(r"swept (\d+)", done.stdout.strip())
    assert found is not None, done.stdout
    assert int(found[1]) >= MIN_STEPS
