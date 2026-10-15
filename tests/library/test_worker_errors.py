"""An exception in a worker, or a read that runs out of memory, costs one file and not the plan."""

from pathlib import Path

import pytest

from fastfoto_linux.library import fdio
from fastfoto_linux.library.decide import decide_file, decide_files
from fastfoto_linux.library.plan import Action
from tests.library import crash_worker
from tests.library.jpeg_helpers import sideways_jpeg, write_file

POOL_TIMEOUT_S = 120


def test_running_out_of_memory_while_reading_skips_the_file_as_too_large(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    write_file(tmp_path, "a.jpg", sideways_jpeg(90, None))

    def no_memory(_path: Path) -> fdio.SourceFile:
        raise MemoryError

    monkeypatch.setattr(fdio, "read_regular", no_memory)
    row = decide_file(tmp_path, "a.jpg")
    assert (row.action, row.reason) == (Action.SKIP, "too-large")


@pytest.mark.timeout(POOL_TIMEOUT_S)
def test_a_worker_that_raises_costs_only_its_file_and_the_rest_are_decided(
    tmp_path: Path,
) -> None:
    names = sorted([*(f"{c}.jpg" for c in "abcdef"), crash_worker.POISON])
    for name in names:
        write_file(tmp_path, name, sideways_jpeg(90, None))
    rows = decide_files(tmp_path, names, jobs=2, worker=crash_worker.raise_on_poison)
    assert [row.path for row in rows] == names
    by_path = {row.path: row for row in rows}
    failed = by_path.pop(crash_worker.POISON)
    assert (failed.action, failed.reason) == (Action.SKIP, "worker-error")
    assert {row.action for row in by_path.values()} == {Action.ROTATE}
