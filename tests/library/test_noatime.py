"""Reading the library must not touch its access times (O_NOATIME), where the system allows it."""

import errno
import os
from pathlib import Path

import pytest

from fastfoto_linux.cli.app import main
from fastfoto_linux.library import fdio
from tests.library.apply_helpers import jpeg
from tests.library.jpeg_helpers import write_file

NO_ATIME = getattr(os, "O_NOATIME", 0)
OLD_NS = 1_000_000_000_000_000_000
NEWER_NS = OLD_NS + 5_000_000_000


@pytest.fixture
def photo(tmp_path: Path) -> Path:
    return write_file(tmp_path / "lib", "a.jpg", jpeg(None))


def spy_on_opens(monkeypatch: pytest.MonkeyPatch, path: Path, refuse_noatime: int | None):
    """Record the flags of every ``os.open`` of ``path``; optionally fail those with O_NOATIME."""
    seen: list[int] = []
    real = os.open

    def spy(name, flags, *args, **kwargs):
        if str(name) == str(path):
            seen.append(flags)
            if refuse_noatime is not None and flags & NO_ATIME:
                raise OSError(refuse_noatime, os.strerror(refuse_noatime), str(name))
        return real(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    return seen


@pytest.mark.skipif(not NO_ATIME, reason="O_NOATIME is Linux only")
def test_a_file_is_opened_with_o_noatime(monkeypatch: pytest.MonkeyPatch, photo: Path) -> None:
    seen = spy_on_opens(monkeypatch, photo, None)
    assert fdio.read_regular(photo).data == photo.read_bytes()
    assert len(seen) == 1
    assert seen[0] & NO_ATIME


@pytest.mark.skipif(not NO_ATIME, reason="O_NOATIME is Linux only")
def test_a_file_that_may_not_be_opened_with_o_noatime_is_opened_without_it(
    monkeypatch: pytest.MonkeyPatch, photo: Path
) -> None:
    """Only the owner (or a privileged process) may use O_NOATIME: others get EPERM."""
    seen = spy_on_opens(monkeypatch, photo, errno.EPERM)
    assert fdio.read_regular(photo).data == photo.read_bytes()
    assert [bool(flags & NO_ATIME) for flags in seen] == [True, False]
    assert seen[1] & os.O_NOFOLLOW  # still never through a link


@pytest.mark.skipif(not NO_ATIME, reason="O_NOATIME is Linux only")
@pytest.mark.parametrize("code", [errno.EACCES, errno.ELOOP, errno.ENOENT])
def test_any_other_failure_is_not_retried_or_hidden(
    monkeypatch: pytest.MonkeyPatch, photo: Path, code: int
) -> None:
    seen = spy_on_opens(monkeypatch, photo, code)
    with pytest.raises(OSError, match=os.strerror(code)) as caught:
        fdio.read_regular(photo)
    assert caught.value.errno == code
    assert len(seen) == 1


def test_a_link_is_still_refused(tmp_path: Path, photo: Path) -> None:
    link = tmp_path / "link.jpg"
    link.symlink_to(photo)
    with pytest.raises(OSError) as caught:
        fdio.read_regular(link)
    assert caught.value.errno == errno.ELOOP


@pytest.mark.skipif(not NO_ATIME, reason="O_NOATIME is Linux only")
def test_check_leaves_the_access_times_of_the_library_alone(tmp_path: Path, photo: Path) -> None:
    control = write_file(tmp_path, "control.bin", b"x")
    for path in (photo, control):
        os.utime(path, ns=(OLD_NS, NEWER_NS))  # older than the modification: relatime updates it
    control.read_bytes()
    if control.stat().st_atime_ns == OLD_NS:
        pytest.skip("this filesystem does not update access times when files are read")
    plan = tmp_path / "plan.csv"
    assert main(["library", "check", str(photo.parent), "--plan", str(plan), "--jobs", "1"]) == 0
    assert photo.stat().st_atime_ns == OLD_NS
