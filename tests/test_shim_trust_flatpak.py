"""Inside a Flatpak a system install's /app belongs to root, which the sandbox shows as nobody.

The shim is trusted there only when all three hold: this is a Flatpak sandbox, the path is
under /app, and /app is a read-only mount (so nothing in the sandbox could have changed it).
Only the owner check is relaxed, and only for the overflow uid (the kernel's, read from
``/proc/sys/kernel/overflowuid``); the rest still applies.
"""

import errno
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from fastfoto_linux.scanner import shim_trust
from fastfoto_linux.scanner.shim_trust import FALLBACK_OVERFLOW_UID, overflow_uid, select_shim
from tests.test_shim_trust import OTHER_UID
from tests.test_shim_trust_acl import ALL, READ_EXECUTE, USER, acl_with, with_acls

NAME = "ff680w_usb_gap.so"
KERNEL_OVERFLOW_UID = 4242  # not 65534: proves the value comes from the kernel file
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


def sandbox(  # noqa: PLR0913 - the knobs of one stand-in for /app
    monkeypatch: pytest.MonkeyPatch,
    app: Path,
    *,
    flatpak: bool = True,
    read_only: bool = True,
    owner: int | None = FALLBACK_OVERFLOW_UID,
    overflow: int | None = FALLBACK_OVERFLOW_UID,
) -> None:
    """Make ``app`` look like /app in a sandbox: owned by ``owner``, read-only, with the marker.

    ``overflow`` is what the kernel file says (None: there is no such file).
    """
    info = app.parent / ".flatpak-info"
    if flatpak:
        info.write_text("[Application]\n")
    monkeypatch.setattr(shim_trust, "FLATPAK_INFO", info)
    kernel_file = app.parent / "overflowuid"
    if overflow is not None:
        kernel_file.write_text(f"{overflow}\n")
    monkeypatch.setattr(shim_trust, "OVERFLOW_UID_FILE", kernel_file)
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
    assert f"owned by uid {FALLBACK_OVERFLOW_UID}" in choice.refused[0]


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
        fields[stat.ST_UID] = FALLBACK_OVERFLOW_UID
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
        fields[stat.ST_UID] = FALLBACK_OVERFLOW_UID
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
        fields[stat.ST_UID] = FALLBACK_OVERFLOW_UID
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
        fields[stat.ST_UID] = FALLBACK_OVERFLOW_UID
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


# -- Review round 1, item 4: the gaps in the tests ----------------------------------------------


def everything_is_owned_by_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every path looks owned by the overflow uid: only the /app rules can let one through."""
    real_lstat = os.lstat

    def lstat(path: str | Path, *args: object, **kwargs: object) -> os.stat_result:
        fields = list(real_lstat(path, *args, **kwargs))  # type: ignore[arg-type]
        fields[stat.ST_UID] = FALLBACK_OVERFLOW_UID
        return os.stat_result(fields)

    monkeypatch.setattr(os, "lstat", lstat)


@pytest.mark.parametrize("code", [errno.EACCES, errno.EIO])
def test_a_statvfs_that_fails_leaves_the_shim_refused(
    shim: Path, app: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    sandbox(monkeypatch, app)

    def statvfs(path: str | Path) -> SimpleNamespace:
        raise OSError(code, os.strerror(code))

    monkeypatch.setattr(os, "statvfs", statvfs)
    choice = select_shim([shim])
    assert choice.path is None
    assert len(choice.refused) == 1  # it was examined and refused, not skipped as missing


@pytest.mark.parametrize("where", ["shim", "folder"])
def test_a_named_user_who_may_write_is_refused_even_in_a_read_only_app(
    shim: Path, app: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    sandbox(monkeypatch, app)
    target = shim if where == "shim" else shim.parent
    with_acls(monkeypatch, {target: acl_with((USER, ALL, OTHER_UID), mask=ALL)})
    choice = select_shim([shim])
    assert choice.path is None
    assert f"user {OTHER_UID}" in choice.refused[0]


def test_a_named_user_whose_write_the_mask_removes_is_no_reason_to_refuse(
    shim: Path, app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox(monkeypatch, app)
    with_acls(monkeypatch, {shim.parent: acl_with((USER, ALL, OTHER_UID), mask=READ_EXECUTE)})
    assert select_shim([shim]).path == shim


@pytest.mark.parametrize(
    "parts",
    [
        ("..", "elsewhere"),  # /app/../home/u/x.so
        ("lib", "..", "..", "elsewhere"),  # /app/lib/../../tmp/x.so
        ("lib", "fastfoto-linux", "..", "..", "..", "elsewhere"),
    ],
)
def test_a_path_with_dot_dot_is_judged_by_where_it_really_leads(
    app: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parts: tuple[str, ...]
) -> None:
    outside = tmp_path / "elsewhere" / NAME
    outside.parent.mkdir()
    outside.write_bytes(b"")
    sandbox(monkeypatch, app)
    everything_is_owned_by_nobody(monkeypatch)
    candidate = app.joinpath(*parts, NAME)
    assert candidate.resolve() == outside.resolve()  # the sandbox for this test is right
    choice = select_shim([candidate])
    assert choice.path is None
    assert choice.refused


def test_a_path_with_dot_dot_that_stays_in_app_is_trusted_as_the_path_it_leads_to(
    shim: Path, app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox(monkeypatch, app)
    candidate = app / "lib" / "fastfoto-linux" / ".." / "fastfoto-linux" / NAME
    assert select_shim([candidate]).path == shim


def test_the_overflow_uid_is_the_one_the_kernel_reports(
    app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox(monkeypatch, app, overflow=KERNEL_OVERFLOW_UID)
    assert overflow_uid() == KERNEL_OVERFLOW_UID


def test_files_owned_by_the_kernels_overflow_uid_are_trusted_in_app(
    shim: Path, app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox(monkeypatch, app, overflow=KERNEL_OVERFLOW_UID, owner=KERNEL_OVERFLOW_UID)
    assert select_shim([shim]).path == shim


def test_65534_is_not_special_when_the_kernel_reports_another_overflow_uid(
    shim: Path, app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox(monkeypatch, app, overflow=KERNEL_OVERFLOW_UID, owner=FALLBACK_OVERFLOW_UID)
    choice = select_shim([shim])
    assert choice.path is None
    assert f"owned by uid {FALLBACK_OVERFLOW_UID}" in choice.refused[0]


def test_without_the_kernel_file_the_usual_65534_is_assumed(
    shim: Path, app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox(monkeypatch, app, overflow=None)
    assert overflow_uid() == FALLBACK_OVERFLOW_UID == 65534
    assert select_shim([shim]).path == shim


@pytest.mark.parametrize("content", ["", "nobody\n", "-5\n", "99999999999999999999\n"])
def test_a_kernel_file_that_does_not_hold_a_uid_means_65534_too(
    app: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    sandbox(monkeypatch, app)
    shim_trust.OVERFLOW_UID_FILE.write_text(content)
    assert overflow_uid() == FALLBACK_OVERFLOW_UID


def test_the_kernel_file_is_read_each_time_not_remembered(
    app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox(monkeypatch, app, overflow=KERNEL_OVERFLOW_UID)
    assert overflow_uid() == KERNEL_OVERFLOW_UID
    shim_trust.OVERFLOW_UID_FILE.write_text("777\n")
    assert overflow_uid() == 777
