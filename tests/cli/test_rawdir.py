"""The raw page directory: temporary, or kept under ``.raw/<UTC stamp>/``."""

import errno
import logging
import os
import re
import shutil
from pathlib import Path

import pytest

from fastfoto_linux.session import raw as rawdir


@pytest.fixture
def fixed_stamp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rawdir, "utc_stamp", lambda: "20261013T230000Z")


def test_the_real_stamp_is_utc_and_safe_on_fat_drives() -> None:
    assert re.fullmatch(r"\d{8}T\d{6}Z", rawdir.utc_stamp())


def test_a_temporary_dir_is_created_hidden_inside_the_root(tmp_path) -> None:
    raw = rawdir.create_raw_dir(tmp_path, keep=False)
    assert raw.is_dir()
    assert raw.parent == tmp_path
    assert raw.name.startswith(".")


def test_a_kept_dir_is_created_under_dot_raw(tmp_path, fixed_stamp) -> None:
    raw = rawdir.create_raw_dir(tmp_path, keep=True)
    assert raw == tmp_path / ".raw" / "20261013T230000Z"
    assert raw.is_dir()


def test_settling_without_keep_removes_the_temporary_dir(tmp_path) -> None:
    raw = rawdir.create_raw_dir(tmp_path, keep=False)
    (raw / "page-0001.png").write_bytes(b"x")
    assert rawdir.settle_raw_dir(raw, tmp_path, keep=False) is None
    assert not raw.exists()


def test_settling_with_keep_moves_the_temporary_dir_under_dot_raw(tmp_path, fixed_stamp) -> None:
    raw = rawdir.create_raw_dir(tmp_path, keep=False)
    (raw / "page-0001.png").write_bytes(b"x")
    kept = rawdir.settle_raw_dir(raw, tmp_path, keep=True)
    assert kept == tmp_path / ".raw" / "20261013T230000Z"
    assert (kept / "page-0001.png").read_bytes() == b"x"
    assert not raw.exists()


def test_a_dir_already_under_dot_raw_stays_put(tmp_path, fixed_stamp) -> None:
    raw = rawdir.create_raw_dir(tmp_path, keep=True)
    (raw / "page-0001.png").write_bytes(b"x")
    assert rawdir.settle_raw_dir(raw, tmp_path, keep=True) == raw
    assert (raw / "page-0001.png").exists()


@pytest.mark.parametrize("keep", [False, True])
def test_an_empty_dir_is_never_worth_keeping(tmp_path, keep) -> None:
    raw = rawdir.create_raw_dir(tmp_path, keep=keep)
    assert rawdir.settle_raw_dir(raw, tmp_path, keep=keep) is None
    assert not raw.exists()


def test_two_scans_in_the_same_second_can_share_the_folder(tmp_path, fixed_stamp) -> None:
    first = rawdir.create_raw_dir(tmp_path, keep=True)
    assert rawdir.create_raw_dir(tmp_path, keep=True) == first


def test_an_empty_kept_dir_takes_its_empty_dot_raw_parent_with_it(tmp_path, fixed_stamp) -> None:
    raw = rawdir.create_raw_dir(tmp_path, keep=True)
    assert rawdir.settle_raw_dir(raw, tmp_path, keep=True) is None
    assert not (tmp_path / ".raw").exists()


def test_an_earlier_scan_keeps_dot_raw_alive(tmp_path, fixed_stamp) -> None:
    earlier = tmp_path / ".raw" / "20200101T000000Z"
    earlier.mkdir(parents=True)
    (earlier / "page-0001.png").write_bytes(b"x")
    raw = rawdir.create_raw_dir(tmp_path, keep=True)
    assert rawdir.settle_raw_dir(raw, tmp_path, keep=True) is None
    assert (earlier / "page-0001.png").exists()


def _stuck_move(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str) -> Path:
    """A temporary raw dir with a page whose move to ``.raw/<stamp>`` is bound to fail."""
    raw = rawdir.create_raw_dir(tmp_path, keep=False)
    (raw / "page-0001.png").write_bytes(b"x")
    if how == "file-in-the-way":
        (tmp_path / ".raw").write_text("not a folder")
    else:

        def refuse(self, target):
            raise OSError(errno.EXDEV, "Invalid cross-device link")

        monkeypatch.setattr(Path, "rename", refuse)
    return raw


@pytest.mark.parametrize("how", ["file-in-the-way", "rename-refused"])
def test_a_move_that_fails_reports_where_the_pages_still_are(
    tmp_path, fixed_stamp, monkeypatch, caplog, how
) -> None:
    raw = _stuck_move(tmp_path, monkeypatch, how)
    with caplog.at_level(logging.ERROR, logger=rawdir.__name__):
        assert rawdir.settle_raw_dir(raw, tmp_path, keep=True) == raw
    assert (raw / "page-0001.png").read_bytes() == b"x"
    assert str(raw) in caplog.text


def _watch_syncs(monkeypatch: pytest.MonkeyPatch, fail_on: Path | None = None) -> list[str]:
    """Record which folders are fsynced; fail with EIO for ``fail_on``."""
    synced: list[str] = []
    real_fsync = os.fsync

    def spy(fd: int) -> None:
        where = os.readlink(f"/proc/self/fd/{fd}")
        synced.append(where)
        if fail_on is not None and where == str(fail_on.resolve()):
            raise OSError(errno.EIO, "Input/output error")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)
    return synced


def test_the_output_folder_is_synced_before_the_raw_pages_are_deleted(
    tmp_path, monkeypatch
) -> None:
    synced = _watch_syncs(monkeypatch)
    seen_by_rmtree: list[list[str]] = []
    real_rmtree = shutil.rmtree

    def rmtree(path, *args, **kwargs):
        seen_by_rmtree.append(list(synced))
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", rmtree)
    raw = rawdir.create_raw_dir(tmp_path, keep=False)
    (raw / "page-0001.png").write_bytes(b"x")
    assert rawdir.settle_raw_dir(raw, tmp_path, keep=False) is None
    assert seen_by_rmtree == [[str(tmp_path.resolve())]]
    assert not raw.exists()


def test_raw_pages_are_kept_when_the_output_folder_cannot_be_synced(
    tmp_path, monkeypatch, caplog
) -> None:
    _watch_syncs(monkeypatch, fail_on=tmp_path)
    raw = rawdir.create_raw_dir(tmp_path, keep=False)
    (raw / "page-0001.png").write_bytes(b"x")
    with caplog.at_level(logging.ERROR, logger=rawdir.__name__):
        assert rawdir.settle_raw_dir(raw, tmp_path, keep=False) == raw
    assert (raw / "page-0001.png").exists()
    assert "Input/output error" in caplog.text


def test_a_dir_that_cannot_be_listed_is_left_alone_and_reported(
    tmp_path, monkeypatch, caplog
) -> None:
    raw = rawdir.create_raw_dir(tmp_path, keep=False)
    (raw / "page-0001.png").write_bytes(b"x")

    def refuse(self):
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(Path, "iterdir", refuse)
    for keep in (False, True):  # unknown contents: never deleted, never moved
        with caplog.at_level(logging.ERROR, logger=rawdir.__name__):
            assert rawdir.settle_raw_dir(raw, tmp_path, keep=keep) == raw
        assert str(raw) in caplog.text
        assert "Input/output error" in caplog.text
        caplog.clear()
    assert (raw / "page-0001.png").read_bytes() == b"x"


def test_an_empty_dir_that_cannot_be_removed_is_reported_not_raised(
    tmp_path, monkeypatch, caplog
) -> None:
    raw = rawdir.create_raw_dir(tmp_path, keep=False)

    def refuse(self):
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(Path, "rmdir", refuse)
    with caplog.at_level(logging.ERROR, logger=rawdir.__name__):
        assert rawdir.settle_raw_dir(raw, tmp_path, keep=False) is None  # no pages are in it
    assert str(raw) in caplog.text
    assert "Input/output error" in caplog.text
