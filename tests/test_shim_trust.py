"""The shim is preloaded into scanimage, so it and every folder above it must be trusted."""

import grp
import os
import tempfile
from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.scanner import ShimMissingError, shim_trust
from fastfoto_linux.scanner.shim_trust import select_shim
from fastfoto_linux.scanner.target import resolve_target
from tests._fake_sysfs import add_usb_device
from tests.cli.fakes import SCANNER, fake_usb

NAME = "ff680w_usb_gap.so"
OTHER_UID = 54321
STRANGER = "someone"


@pytest.fixture
def shim(tmp_path: Path) -> Path:
    """tmp_path/lib/deep/NAME: a shim in a folder two levels below the test's folder."""
    path = tmp_path / "lib" / "deep" / NAME
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")
    path.chmod(0o755)
    return path


def group(gid: int, members: list[str]) -> grp.struct_group:
    return grp.struct_group(("g", "x", gid, members))


def as_owner(monkeypatch: pytest.MonkeyPatch, owners: dict[Path, int]) -> None:
    """Report another owner for some paths (a test cannot chown to root)."""
    real = os.lstat

    def lstat(path: str | Path, *args: object, **kwargs: object) -> os.stat_result:
        found = real(path, *args, **kwargs)  # type: ignore[arg-type]
        uid = owners.get(Path(path))
        if uid is None:
            return found
        fields = list(found)
        fields[4] = uid
        return os.stat_result(fields)

    monkeypatch.setattr(os, "lstat", lstat)


def private_group(monkeypatch: pytest.MonkeyPatch, path: Path, members: list[str]) -> None:
    """Make the file's group the user's own, with ``members`` listed in it."""
    gid = path.stat().st_gid
    monkeypatch.setattr(os, "getegid", lambda: gid)
    monkeypatch.setattr(grp, "getgrgid", lambda number: group(number, members))


def test_an_ordinary_shim_in_private_folders_is_chosen(shim: Path) -> None:
    assert select_shim([shim]) == shim_trust.ShimChoice(path=shim, refused=())


def test_a_user_private_group_may_write_under_umask_002(
    shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shim.chmod(0o775)
    for folder in (shim.parent, shim.parent.parent):
        folder.chmod(0o775)
    private_group(monkeypatch, shim, [])
    assert select_shim([shim]).path == shim


def test_a_group_with_other_members_may_not_write(
    shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shim.parent.chmod(0o775)
    private_group(monkeypatch, shim, [STRANGER])
    choice = select_shim([shim])
    assert choice.path is None
    assert str(shim.parent) in choice.refused[0]
    assert "writable by group" in choice.refused[0]
    assert f"chmod g-w {shim.parent}" in choice.refused[0]


def test_a_group_that_is_not_the_users_own_may_not_write(
    shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shim.chmod(0o775)
    private_group(monkeypatch, shim, [])
    monkeypatch.setattr(os, "getegid", lambda: shim.stat().st_gid + 1)
    assert select_shim([shim]).path is None


def test_a_group_the_system_does_not_know_may_not_write(
    shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shim.chmod(0o775)
    private_group(monkeypatch, shim, [])

    def unknown(number: int) -> grp.struct_group:
        raise KeyError(number)

    monkeypatch.setattr(grp, "getgrgid", unknown)
    assert select_shim([shim]).path is None


def test_root_owned_files_and_folders_are_trusted(
    shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    everything = {shim: 0, shim.parent: 0, shim.parent.parent: 0}
    as_owner(monkeypatch, everything)
    monkeypatch.setattr(os, "geteuid", lambda: OTHER_UID)
    assert select_shim([shim]).path == shim


def test_a_file_that_someone_else_owns_is_refused_with_the_uid(
    shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    as_owner(monkeypatch, {shim: OTHER_UID})
    choice = select_shim([shim])
    assert choice.path is None
    assert f"owned by uid {OTHER_UID}" in choice.refused[0]
    assert str(shim) in choice.refused[0]


@pytest.mark.parametrize("mode", [0o777, 0o1777, 0o757])
def test_a_folder_that_anyone_can_write_to_is_refused_even_when_sticky(
    shim: Path, mode: int
) -> None:
    shim.parent.chmod(mode)
    choice = select_shim([shim])
    assert choice.path is None
    assert f"chmod o-w {shim.parent}" in choice.refused[0]


def test_a_folder_further_up_that_anyone_can_write_to_is_refused(shim: Path) -> None:
    shim.parent.parent.chmod(0o777)  # the grandparent
    choice = select_shim([shim])
    assert choice.path is None
    assert str(shim.parent.parent) in choice.refused[0]


def test_a_file_that_anyone_can_write_to_is_refused(shim: Path) -> None:
    shim.chmod(0o757)
    assert select_shim([shim]).path is None


def test_a_link_in_a_folder_anyone_can_write_to_is_refused_though_its_target_is_fine(
    shim: Path, tmp_path: Path
) -> None:
    open_folder = tmp_path / "open"
    open_folder.mkdir()
    open_folder.chmod(0o777)
    link = open_folder / NAME
    link.symlink_to(shim)
    choice = select_shim([link])
    assert choice.path is None
    assert str(open_folder) in choice.refused[0]


def test_a_shim_reached_through_a_link_to_a_folder_is_chosen(shim: Path, tmp_path: Path) -> None:
    """/home is a link on some systems; a link's own mode bits (always 777) say nothing."""
    folder_link = tmp_path / "home"
    folder_link.symlink_to(shim.parent.parent)
    assert select_shim([folder_link / "deep" / NAME]).path == shim


def test_a_candidate_that_is_missing_or_vanished_is_not_found_and_not_an_error(
    shim: Path, tmp_path: Path
) -> None:
    dangling = tmp_path / "dangling.so"
    dangling.symlink_to(tmp_path / "gone.so")
    assert select_shim([tmp_path / "nope.so", dangling, tmp_path]) == shim_trust.ShimChoice(None)
    shim.unlink()
    assert select_shim([shim]) == shim_trust.ShimChoice(None)


def test_a_link_loop_is_not_a_crash(tmp_path: Path) -> None:
    loop = tmp_path / "loop.so"
    loop.symlink_to(loop)
    assert select_shim([loop]).path is None


def test_a_refused_candidate_is_skipped_for_a_good_one(shim: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad.so"
    bad.write_bytes(b"")
    bad.chmod(0o666)
    choice = select_shim([bad, shim])
    assert choice.path == shim
    assert len(choice.refused) == 1


def test_the_real_policy_walks_up_to_the_root_and_refuses_the_shared_tmp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Path("/") == shim_trust.DEFAULT_TRUST_ROOT
    temp = Path(tempfile.gettempdir()).resolve()
    if not temp.stat().st_mode & 0o002:
        pytest.skip(f"{temp} is not a shared folder here")
    monkeypatch.setattr(shim_trust, "SHIM_TRUST_ROOT", shim_trust.DEFAULT_TRUST_ROOT)
    with tempfile.TemporaryDirectory(dir=temp) as folder:
        path = Path(folder) / NAME
        path.write_bytes(b"")
        path.chmod(0o755)
        choice = select_shim([path])
    assert choice.path is None
    assert str(temp) in choice.refused[0]


# -- the people who see the reason -----------------------------------------------------------


@pytest.fixture
def usb(tmp_path: Path) -> Path:
    sysfs = tmp_path / "sysfs"
    add_usb_device(sysfs, "1-1")
    return sysfs


def test_the_missing_shim_error_leads_with_the_reason_and_the_fix(shim: Path, usb: Path) -> None:
    shim.parent.chmod(0o775)
    with pytest.raises(ShimMissingError) as caught:
        resolve_target(sysfs_root=usb, shim_candidates=[shim])
    message = str(caught.value)
    assert message.index(f"chmod g-w {shim.parent}") < message.index("searched")


def test_ffscan_devices_applies_the_same_policy_and_says_why(
    shim: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    shim.parent.chmod(0o777)
    fake_usb(monkeypatch, scanners=[SCANNER], shims=[shim])
    assert main(["devices"]) == 3
    out, err = capsys.readouterr()
    assert "shim: found" not in out
    assert f"chmod o-w {shim.parent}" in out + err


def test_ffscan_devices_still_finds_a_trusted_shim(
    shim: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_usb(monkeypatch, scanners=[SCANNER], shims=[shim])
    assert main(["devices"]) == 0
    assert "shim: found" in capsys.readouterr().out
