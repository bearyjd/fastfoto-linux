"""The worker pool must not import modules from the folder the user happens to be in.

The pool's helper process is started with ``python -c ...``, which puts the current folder first
on its import path; a file such as ``struct.py`` in the library would then be run by ``check``.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from fastfoto_linux.library import decide as decide_module
from tests.library.jpeg_helpers import sideways_jpeg, write_file

SAFE_PATH = "PYTHONSAFEPATH"
PLANTED = ("struct", "json", "socket")
RUNNER = "import sys\nfrom fastfoto_linux.cli.app import main\nsys.exit(main(sys.argv[1:]))\n"
DEADLINE_S = 120


def planted_source(marker: Path) -> str:
    return f"open({str(marker)!r}, 'w').close()\nraise ImportError('planted module')\n"


@pytest.mark.timeout(180)
def test_modules_planted_in_the_current_folder_are_not_run_by_the_workers(tmp_path: Path) -> None:
    library, markers, plan = tmp_path / "lib", tmp_path / "markers", tmp_path / "plan.csv"
    markers.mkdir()
    for index in range(4):
        write_file(library, f"p{index}.jpg", sideways_jpeg(90, None))
    for name in PLANTED:
        (library / f"{name}.py").write_text(planted_source(markers / name))
    runner = tmp_path / "runner" / "run.py"  # not in the library: the parent must stay clean
    runner.parent.mkdir()
    runner.write_text(RUNNER)
    env = {key: value for key, value in os.environ.items() if key not in (SAFE_PATH, "PYTHONPATH")}
    done = subprocess.run(
        [sys.executable, str(runner), "library", "check", ".", "--plan", str(plan), "--jobs", "2"],
        cwd=library,
        env=env,
        capture_output=True,
        text=True,
        timeout=DEADLINE_S,
        check=False,
    )
    assert sorted(path.name for path in markers.iterdir()) == [], "planted code was run"
    assert done.returncode == 0, done.stderr
    assert plan.read_text().count(",rotate,") == 4  # the pool did its work as usual


def test_the_pool_runs_with_a_safe_import_path_and_the_environment_is_restored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SAFE_PATH, raising=False)
    with decide_module._pool(1):
        assert os.environ.get(SAFE_PATH) == "1"
    assert SAFE_PATH not in os.environ


def test_an_environment_value_that_was_already_set_comes_back_after_the_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SAFE_PATH, "previous")
    with decide_module._pool(1):
        assert os.environ[SAFE_PATH] == "1"
    assert os.environ[SAFE_PATH] == "previous"


def test_the_environment_is_restored_when_the_pool_is_left_by_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SAFE_PATH, raising=False)
    with pytest.raises(KeyboardInterrupt), decide_module._pool(1):
        raise KeyboardInterrupt
    assert SAFE_PATH not in os.environ
