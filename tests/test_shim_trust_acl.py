"""The shim's trust: a group that lists its own user, and POSIX ACLs (mode bits do not show them).

Review round 3. ``setfacl -m u:nobody:rwx dir`` raises the group bits of ``dir`` to the mask, and
the user's private group passes them, so the mode alone cannot tell who else may write.
"""

import errno
import os
import pwd
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from fastfoto_linux.scanner.shim_trust import select_shim
from tests import test_shim_trust
from tests.test_shim_trust import OTHER_UID, STRANGER, private_group

shim = test_shim_trust.shim  # the fixture
ME = "alice"
NOBODY = 65534
HOME_ACL_USER = 107  # the user:107:r-x entry the real home folder carries
ACL_VERSION = 2
ACL_UNDEFINED_ID = 0xFFFFFFFF
USER_OBJ, USER, GROUP_OBJ, GROUP, MASK, OTHER = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20
READ_EXECUTE, ALL = 0o5, 0o7


def acl(*entries: tuple[int, int, int]) -> bytes:
    """A ``system.posix_acl_access`` value: a version, then (tag, permissions, id) entries."""
    return struct.pack("<I", ACL_VERSION) + b"".join(struct.pack("<HHI", *e) for e in entries)


def acl_with(named: tuple[int, int, int], *, mask: int | None = READ_EXECUTE) -> bytes:
    """An ACL with one named entry, the owner's and other's entries, and (maybe) a mask."""
    entries = [
        (USER_OBJ, ALL, ACL_UNDEFINED_ID),
        named,
        (GROUP_OBJ, READ_EXECUTE, ACL_UNDEFINED_ID),
    ]
    if mask is not None:
        entries.append((MASK, mask, ACL_UNDEFINED_ID))
    entries.append((OTHER, READ_EXECUTE, ACL_UNDEFINED_ID))
    return acl(*entries)


def with_acls(monkeypatch: pytest.MonkeyPatch, blobs: dict[Path, bytes | int]) -> None:
    """Give some paths an access list (a number: the error reading it); the rest have none."""

    def getxattr(path: str | Path, attribute: str, *, follow_symlinks: bool = True) -> bytes:
        assert attribute == "system.posix_acl_access"
        assert not follow_symlinks  # a link is looked at itself, not at what it leads to
        found = blobs.get(Path(path), errno.ENODATA)
        if isinstance(found, int):
            raise OSError(found, os.strerror(found))
        return found

    monkeypatch.setattr(os, "getxattr", getxattr)


def as_user(monkeypatch: pytest.MonkeyPatch, name: str | None) -> None:
    """The user this process runs as is ``name`` (None: the system does not know the user)."""

    def getpwuid(uid: int) -> pwd.struct_passwd:
        if name is None:
            raise KeyError(uid)
        return pwd.struct_passwd((name, "x", uid, uid, "", "", ""))

    monkeypatch.setattr(pwd, "getpwuid", getpwuid)


def test_a_private_group_that_lists_its_own_user_is_still_private(
    shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``jd:x:1000:jd`` is the user's own group, not a shared one."""
    shim.chmod(0o775)
    shim.parent.chmod(0o775)
    private_group(monkeypatch, shim, [ME])
    as_user(monkeypatch, ME)
    assert select_shim([shim]).path == shim


@pytest.mark.parametrize("members", [[ME, STRANGER], [STRANGER, ME]])
def test_a_group_that_lists_the_user_and_someone_else_is_shared(
    shim: Path, monkeypatch: pytest.MonkeyPatch, members: list[str]
) -> None:
    shim.parent.chmod(0o775)
    private_group(monkeypatch, shim, members)
    as_user(monkeypatch, ME)
    choice = select_shim([shim])
    assert choice.path is None
    assert "writable by group" in choice.refused[0]


def test_a_group_that_lists_a_member_when_the_user_is_unknown_is_shared(
    shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shim.parent.chmod(0o775)
    private_group(monkeypatch, shim, [ME])
    as_user(monkeypatch, None)
    assert select_shim([shim]).path is None


# -- POSIX ACLs: the mode bits do not tell who else can write ---------------------------------


def test_the_acl_of_a_real_home_folder_is_accepted(
    shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """user:107:r-x with mask r-x: someone else may look in, nobody else may change anything."""
    named = (USER, READ_EXECUTE, HOME_ACL_USER)
    with_acls(monkeypatch, {shim.parent.parent: acl_with(named)})
    assert select_shim([shim]).path == shim


@pytest.mark.parametrize("where", ["shim", "folder", "grandparent"])
def test_a_named_user_who_can_write_through_an_acl_is_refused(
    shim: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    path = {"shim": shim, "folder": shim.parent, "grandparent": shim.parent.parent}[where]
    with_acls(monkeypatch, {path: acl_with((USER, ALL, NOBODY), mask=ALL)})
    choice = select_shim([shim])
    assert choice.path is None
    assert str(path) in choice.refused[0]
    assert "access list" in choice.refused[0]
    assert f"setfacl -x u:{NOBODY} {path}" in choice.refused[0]


def test_a_named_group_that_can_write_through_an_acl_is_refused(
    shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_acls(monkeypatch, {shim.parent: acl_with((GROUP, ALL, OTHER_UID), mask=ALL)})
    choice = select_shim([shim])
    assert choice.path is None
    assert f"setfacl -x g:{OTHER_UID} {shim.parent}" in choice.refused[0]


def test_a_named_entry_that_the_mask_makes_read_only_is_accepted(
    shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """u:nobody:rwx with the mask r-x: what the entry grants is cut down to r-x."""
    blobs = {
        shim.parent: acl_with((USER, ALL, NOBODY), mask=READ_EXECUTE),
        shim.parent.parent: acl_with((GROUP, ALL, OTHER_UID), mask=READ_EXECUTE),
    }
    with_acls(monkeypatch, blobs)
    assert select_shim([shim]).path == shim


def test_a_named_user_with_write_but_no_mask_is_refused(
    shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_acls(monkeypatch, {shim.parent: acl_with((USER, ALL, NOBODY), mask=None)})
    assert select_shim([shim]).path is None


@pytest.mark.parametrize("who", [0, os.geteuid()])
def test_an_acl_entry_for_root_or_the_user_may_write(
    shim: Path, monkeypatch: pytest.MonkeyPatch, who: int
) -> None:
    with_acls(monkeypatch, {shim.parent: acl_with((USER, ALL, who), mask=ALL)})
    assert select_shim([shim]).path == shim


def test_an_acl_entry_for_the_private_group_may_write_but_not_for_a_shared_one(
    shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gid = shim.stat().st_gid
    private_group(monkeypatch, shim, [])
    with_acls(monkeypatch, {shim.parent: acl_with((GROUP, ALL, gid), mask=ALL)})
    assert select_shim([shim]).path == shim
    with_acls(monkeypatch, {shim.parent: acl_with((GROUP, ALL, gid + 1), mask=ALL)})
    assert select_shim([shim]).path is None


@pytest.mark.parametrize("error", [errno.ENODATA, errno.ENOTSUP])
def test_no_acl_or_a_file_system_without_acls_is_fine(
    shim: Path, monkeypatch: pytest.MonkeyPatch, error: int
) -> None:
    with_acls(monkeypatch, {path: error for path in (shim, *shim.parents)})
    assert select_shim([shim]).path == shim


def test_another_error_reading_an_acl_refuses_and_says_so(
    shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_acls(monkeypatch, {shim.parent: errno.EACCES})
    choice = select_shim([shim])
    assert choice.path is None
    assert str(shim) in choice.refused[0]
    assert "cannot be examined" in choice.refused[0]


@pytest.mark.parametrize(
    "blob",
    [b"", b"\x02\x00", struct.pack("<I", 3), acl(*[(USER, ALL, NOBODY)])[:-3]],
    ids=["empty", "short", "version", "cut"],
)
def test_an_acl_that_cannot_be_read_is_refused(
    shim: Path, monkeypatch: pytest.MonkeyPatch, blob: bytes
) -> None:
    with_acls(monkeypatch, {shim.parent: blob})
    choice = select_shim([shim])
    assert choice.path is None
    assert "access list" in choice.refused[0]
    assert str(shim.parent) in choice.refused[0]


def set_acl(folder: Path, entry: str) -> None:
    setfacl = shutil.which("setfacl")
    if setfacl is None:
        pytest.skip("setfacl is not installed")
    done = subprocess.run([setfacl, "-m", entry, str(folder)], capture_output=True, check=False)
    if done.returncode != 0:
        pytest.skip(f"this file system takes no ACLs here: {done.stderr.decode().strip()}")


def test_a_real_acl_that_lets_another_user_write_is_refused(
    shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kernel's own value: setfacl raises the group bits, and the private group passes them."""
    set_acl(shim.parent, f"u:{NOBODY}:rwx")
    private_group(monkeypatch, shim, [])
    choice = select_shim([shim])
    assert choice.path is None
    assert "access list" in choice.refused[0]


def test_a_real_read_only_acl_is_accepted(shim: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    set_acl(shim.parent, f"u:{NOBODY}:r-x")
    private_group(monkeypatch, shim, [])
    assert select_shim([shim]).path == shim
