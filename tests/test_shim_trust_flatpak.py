"""Inside a Flatpak a system install's /app belongs to root, which the sandbox shows as nobody.

The shim is trusted there only when all three hold: this is a Flatpak sandbox, the path is
under /app, and /app is a read-only mount (so nothing in the sandbox could have changed it).
Only the owner check is relaxed, and only for the overflow uid; the rest still applies.
"""

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from fastfoto_linux.scanner import shim_trust
from fastfoto_linux.scanner.shim_trust import OVERFLOW_UID, select_shim

NAME = "ff680w_usb_gap.so"
OTHER_UID = 54321
READ_ONLY = os.ST_RDONLY


@pytest.fixture
def app(tmp_path: Path) -> Path:
    """tmp_path/app: a stand-in for /app, with the shim in lib/fastfoto-linux."""
    shim = tmp_path / "app" / "lib" / "fastfoto-linux" / NAME
    shim.parent.mkdir(parents=True)
    shim.write_bytes(b"")
    shim.chmod(0o755)
    return tmp_path / "app"


@pytest.fixture
def shim(app: Path) -> Path:
    return app / "lib" / "fastfoto-linux" / NAME


def sandbox(
    monkeypatch: pytest.MonkeyPatch,
    app: Path,
    *,
    flatpak: bool = True,
    read_only: bool = True,
    owner: int | None = OVERFLOW_UID,
) -> None:
    """Make ``app`` look like /app in a sandbox: owned by ``owner``, read-only, with the marker."""
    info = app.parent / ".flatpak-info"
    if flatpak:
        info.write_text("[Application]\n")
    monkeypatch.setattr(shim_trust, "FLATPAK_INFO", info)
    monkeypatch.setattr(shim_trust, "FLATPAK_APP_ROOT", app)
    real_lstat, real_statvfs = os.lstat, os.statvfs

    def lstat(path: str | Path, *args: object, **kwargs: object) -> os.stat_result:
        found = real_lstat(path, *args, **kwargs)  # type: ignore[arg-type]
        if owner is None or not Path(path).is_relative_to(app):
            return found
        fields = list(found)
        fields[stat.ST_UID] = owner
        return os.stat_result(fields)

    def statvfs(path: str | Path) -> SimpleNamespace:
        found = real_statvfs(path)
        flags = found.f_flag | READ_ONLY if read_only else found.f_flag & ~READ_ONLY
        return SimpleNamespace(f_flag=flags)

    monkeypatch.setattr(os, "lstat", lstat)
    monkeypatch.setattr(os, "statvfs", statvfs)


def test_a_read_only_app_owned_by_nobody_is_trusted_inside_a_flatpak(
    shim: Path, app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox(monkeypatch, app)
    assert select_shim([shim]) == shim_trust.ShimChoice(path=shim, refused=())


def test_a_user_install_whose_files_belong_to_the_user_needs_no_exception(
    shim: Path, app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox(monkeypatch, app, owner=None, read_only=False)
    assert select_shim([shim]).path == shim


def test_outside_a_flatpak_nobody_owned_files_are_still_refused_with_the_uid(
    shim: Path, app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox(monkeypatch, app, flatpak=False)
    choice = select_shim([shim])
    assert choice.path is None
    assert f"owned by uid {OVERFLOW_UID}" in choice.refused[0]


def test_a_writable_app_is_still_refused(
    shim: Path, app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox(monkeypatch, app, read_only=False)
    assert select_shim([shim]).path is None


def test_another_owner_than_nobody_is_still_refused(
    shim: Path, app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox(monkeypatch, app, owner=OTHER_UID)
    choice = select_shim([shim])
    assert choice.path is None
    assert f"owned by uid {OTHER_UID}" in choice.refused[0]


def test_a_shim_outside_app_is_still_refused_even_when_nobody_owns_it(
    app: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "home" / "lib" / NAME
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_bytes(b"")
    sandbox(monkeypatch, app)
    real_lstat = os.lstat

    def lstat(path: str | Path, *args: object, **kwargs: object) -> os.stat_result:
        fields = list(real_lstat(path, *args, **kwargs))  # type: ignore[arg-type]
        fields[stat.ST_UID] = OVERFLOW_UID
        return os.stat_result(fields)

    monkeypatch.setattr(os, "lstat", lstat)
    assert select_shim([elsewhere]).path is None


def test_a_folder_that_merely_starts_with_the_name_of_app_is_not_app(
    app: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lookalike = tmp_path / "app2" / NAME
    lookalike.parent.mkdir()
    lookalike.write_bytes(b"")
    sandbox(monkeypatch, app)
    real_lstat = os.lstat

    def lstat(path: str | Path, *args: object, **kwargs: object) -> os.stat_result:
        fields = list(real_lstat(path, *args, **kwargs))  # type: ignore[arg-type]
        fields[stat.ST_UID] = OVERFLOW_UID
        return os.stat_result(fields)

    monkeypatch.setattr(os, "lstat", lstat)
    assert select_shim([lookalike]).path is None


def test_a_link_in_app_to_a_file_outside_it_is_judged_by_where_it_leads(
    app: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside" / NAME
    outside.parent.mkdir()
    outside.write_bytes(b"")
    link = app / "lib" / "fastfoto-linux" / "link.so"
    link.symlink_to(outside)
    sandbox(monkeypatch, app)
    real_lstat = os.lstat

    def lstat(path: str | Path, *args: object, **kwargs: object) -> os.stat_result:
        found = real_lstat(path, *args, **kwargs)  # type: ignore[arg-type]
        if Path(path) != outside:
            return found
        fields = list(found)
        fields[stat.ST_UID] = OVERFLOW_UID
        return os.stat_result(fields)

    monkeypatch.setattr(os, "lstat", lstat)
    assert select_shim([link]).path is None


def test_the_folders_above_app_get_no_exception(
    shim: Path, app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox(monkeypatch, app)
    real_lstat = os.lstat
    parent = app.parent

    def lstat(path: str | Path, *args: object, **kwargs: object) -> os.stat_result:
        found = real_lstat(path, *args, **kwargs)  # type: ignore[arg-type]
        if Path(path) != parent:
            return found
        fields = list(found)
        fields[stat.ST_UID] = OVERFLOW_UID
        return os.stat_result(fields)

    monkeypatch.setattr(os, "lstat", lstat)
    monkeypatch.setattr(shim_trust, "SHIM_TRUST_ROOT", parent)
    choice = select_shim([shim])
    assert choice.path is None
    assert str(parent) in choice.refused[0]


@pytest.mark.parametrize("bits", [0o777, 0o757, 0o775])
def test_writable_by_everyone_or_another_group_is_still_refused_in_app(
    shim: Path, app: Path, monkeypatch: pytest.MonkeyPatch, bits: int
) -> None:
    sandbox(monkeypatch, app)
    shim.parent.chmod(bits)
    monkeypatch.setattr(os, "getegid", lambda: os.stat(shim).st_gid + 1)
    assert select_shim([shim]).path is None
