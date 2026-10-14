"""The raw page directory: temporary, or kept under ``.raw/<UTC stamp>/``."""

import re

import pytest

from fastfoto_linux.cli import rawdir


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
