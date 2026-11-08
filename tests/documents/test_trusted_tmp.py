"""The OCR cache tests get a temp folder the cache trusts, without hiding a broken guard."""

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.documents import _trusted_tmp

FOREIGN_UID = 65534  # what a rootless container shows for the host's root


def fake_owner(monkeypatch: pytest.MonkeyPatch, folder: Path, uid: int, mode: int) -> None:
    original = Path.stat

    def info(path: Path, **kwargs: object) -> os.stat_result:
        result = original(path, **kwargs)
        if path != folder:
            return result
        fields = list(result)
        fields[0], fields[4] = stat.S_IFDIR | mode, uid
        return os.stat_result(fields)

    monkeypatch.setattr(Path, "stat", info)


def fake_mounts(monkeypatch: pytest.MonkeyPatch, readonly: Path | None = None) -> None:
    def mount(path: Path) -> SimpleNamespace:
        return SimpleNamespace(f_flag=os.ST_RDONLY if path == readonly else 0)

    monkeypatch.setattr(os, "statvfs", mount)


@pytest.fixture
def all_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every real folder looks root- or user-owned and private, whatever this machine's /tmp is."""
    original = Path.stat

    def info(path: Path, **kwargs: object) -> os.stat_result:
        fields = list(original(path, **kwargs))
        fields[0], fields[4] = stat.S_IFDIR | 0o755, os.getuid()
        return os.stat_result(fields)

    monkeypatch.setattr(Path, "stat", info)
    fake_mounts(monkeypatch)


def test_trusted_ancestors_raise_no_problem(tmp_path: Path, all_trusted: None) -> None:
    assert _trusted_tmp.untrusted_ancestor(tmp_path) is None


def test_foreign_owned_writable_ancestor_is_named_with_its_uid(
    tmp_path: Path, all_trusted: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_owner(monkeypatch, tmp_path.parent, FOREIGN_UID, 0o1777)
    problem = _trusted_tmp.untrusted_ancestor(tmp_path)
    assert problem is not None
    assert str(tmp_path.parent) in problem and str(FOREIGN_UID) in problem


def test_foreign_owner_on_a_readonly_mount_is_trusted(
    tmp_path: Path, all_trusted: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_owner(monkeypatch, tmp_path.parent, FOREIGN_UID, 0o1777)
    fake_mounts(monkeypatch, readonly=tmp_path.parent)
    assert _trusted_tmp.untrusted_ancestor(tmp_path) is None


@pytest.mark.parametrize("mode", [0o775, 0o757])
def test_shared_writable_ancestor_without_sticky_bit_is_untrusted(
    tmp_path: Path, all_trusted: None, monkeypatch: pytest.MonkeyPatch, mode: int
) -> None:
    fake_owner(monkeypatch, tmp_path.parent, 0, mode)
    problem = _trusted_tmp.untrusted_ancestor(tmp_path)
    assert problem is not None and str(tmp_path.parent) in problem


def test_shared_writable_ancestor_with_sticky_bit_is_trusted(
    tmp_path: Path, all_trusted: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_owner(monkeypatch, tmp_path.parent, 0, 0o1777)
    assert _trusted_tmp.untrusted_ancestor(tmp_path) is None


def probe(untrusted: set[Path]) -> object:
    return lambda path: f"{path} is foreign" if path.resolve() in untrusted else None


def test_trusted_tmp_path_is_used_as_is(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_trusted_tmp, "untrusted_ancestor", probe(set()))
    assert list(_trusted_tmp.trusted_tmp_path(tmp_path)) == [tmp_path]


@pytest.mark.parametrize("locked_mode", [0o500, 0o200, 0o000])
def test_untrusted_tmp_path_moves_to_the_runtime_dir_and_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locked_mode: int
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    runtime.chmod(0o711)  # explicit: a umask would mask mkdir(mode=...)
    link = tmp_path / "runtime-link"
    link.symlink_to(runtime)  # production compares resolved paths, so the stand-in must be one
    work = tmp_path / "work"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(link))
    monkeypatch.setattr(_trusted_tmp, "untrusted_ancestor", probe({work.resolve()}))
    fixture = _trusted_tmp.trusted_tmp_path(work)
    moved = next(fixture)
    assert moved.parent == runtime.resolve() and moved == moved.resolve() and moved.is_dir()
    locked = moved / "locked"
    (locked / "inner" / "deeper").mkdir(parents=True)
    (locked / "inner" / "file").write_bytes(b"x")
    (locked / "inner").chmod(locked_mode)  # a test that left a folder it cannot delete from
    locked.chmod(locked_mode)
    with pytest.raises(StopIteration):
        next(fixture)
    assert list(runtime.iterdir()) == []
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o711  # the runtime dir itself is untouched


@pytest.mark.parametrize("runtime", [None, "relative/run", "untrusted"])
def test_without_a_trusted_place_it_skips_locally_and_names_the_problem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime: str | None
) -> None:
    untrusted_runtime = tmp_path / "untrusted"
    untrusted_runtime.mkdir()
    untrusted_runtime = untrusted_runtime.resolve()
    if runtime is None:
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    else:
        target = untrusted_runtime if runtime == "untrusted" else Path(runtime)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(target))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(
        _trusted_tmp, "untrusted_ancestor", probe({tmp_path.resolve(), untrusted_runtime})
    )
    with pytest.raises(pytest.skip.Exception, match=r"is foreign.*--basetemp"):
        next(_trusted_tmp.trusted_tmp_path(tmp_path))


def test_without_a_trusted_place_ci_fails_instead_of_skipping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("CI", "true")
    monkeypatch.setattr(_trusted_tmp, "untrusted_ancestor", probe({tmp_path.resolve()}))
    with pytest.raises(BaseException, match=r"is foreign.*--basetemp") as outcome:
        next(_trusted_tmp.trusted_tmp_path(tmp_path))
    assert outcome.type is pytest.fail.Exception  # a skip would hide the problem in CI
