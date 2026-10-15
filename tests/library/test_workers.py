"""The process pool: a worker that dies costs one file, and Ctrl-C stops everything at once."""

import logging
from pathlib import Path
from typing import ClassVar

import pytest

from fastfoto_linux.library import decide as decide_module
from fastfoto_linux.library.decide import decide_files
from fastfoto_linux.library.plan import Action
from tests.library import crash_worker
from tests.library.jpeg_helpers import sideways_jpeg, write_file

POOL_TIMEOUT_S = 120


def photos(root: Path, names: list[str]) -> list[str]:
    for name in names:
        write_file(root, name, sideways_jpeg(90, None))
    return sorted(names)


@pytest.mark.timeout(POOL_TIMEOUT_S)
def test_a_file_that_kills_its_worker_is_skipped_and_every_other_file_is_decided(
    tmp_path: Path,
) -> None:
    names = photos(tmp_path, [f"{c}.jpg" for c in "abcdefgh"] + [crash_worker.POISON])
    rows = decide_files(tmp_path, names, jobs=2, worker=crash_worker.die_on_poison)
    assert [row.path for row in rows] == names
    by_path = {row.path: row for row in rows}
    poisoned = by_path.pop(crash_worker.POISON)
    assert (poisoned.action, poisoned.reason) == (Action.SKIP, "worker-crashed")
    assert {row.action for row in by_path.values()} == {Action.ROTATE}


@pytest.mark.timeout(POOL_TIMEOUT_S)
def test_a_worker_that_dies_once_is_retried_alone_with_the_same_function(tmp_path: Path) -> None:
    library = tmp_path / "lib"
    names = photos(library, ["a.jpg", "b.jpg", crash_worker.FLAKY, "c.jpg"])
    rows = decide_files(library, names, jobs=2, worker=crash_worker.die_once_on_flaky)
    assert (library.parent / crash_worker.MARKER).exists()  # it did die once
    assert {row.action for row in rows} == {Action.ROTATE}


class FakeExecutor:
    """Stands in for the process pool and raises Ctrl-C as soon as work is submitted."""

    instances: ClassVar[list["FakeExecutor"]] = []

    def __init__(self, *_args: object, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.shutdowns: list[tuple[bool, bool]] = []
        FakeExecutor.instances.append(self)

    def submit(self, *_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        self.shutdowns.append((wait, cancel_futures))


@pytest.fixture
def fake_pool(monkeypatch: pytest.MonkeyPatch) -> type[FakeExecutor]:
    FakeExecutor.instances = []
    monkeypatch.setattr(decide_module, "ProcessPoolExecutor", FakeExecutor)
    return FakeExecutor


def test_ctrl_c_cancels_the_queued_files_instead_of_waiting_for_them(
    tmp_path: Path, fake_pool: type[FakeExecutor]
) -> None:
    names = photos(tmp_path, ["a.jpg", "b.jpg", "c.jpg"])
    with pytest.raises(KeyboardInterrupt):
        decide_files(tmp_path, names, jobs=2)
    (pool,) = fake_pool.instances
    assert pool.shutdowns
    assert all(cancel for _, cancel in pool.shutdowns)


def test_workers_ignore_ctrl_c_so_the_parent_alone_decides_what_to_do(
    tmp_path: Path, fake_pool: type[FakeExecutor]
) -> None:
    with pytest.raises(KeyboardInterrupt):
        decide_files(tmp_path, photos(tmp_path, ["a.jpg", "b.jpg"]), jobs=2)
    assert fake_pool.instances[0].kwargs.get("initializer") is not None


def test_progress_is_still_logged_when_the_pool_works_file_by_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(decide_module, "PROGRESS_EVERY", 2)
    names = photos(tmp_path, ["a.jpg", "b.jpg", "c.jpg", "d.jpg"])
    with caplog.at_level(logging.INFO, logger=decide_module.logger.name):
        decide_files(tmp_path, names, jobs=2)
    assert any("checked 4 of 4" in record.getMessage() for record in caplog.records)
