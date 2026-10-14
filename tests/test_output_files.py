import errno
import fcntl
import logging
import os
import stat
import threading
import time
from pathlib import Path

import pytest

import fastfoto_linux.output.files as files_module
from fastfoto_linux.output.errors import OutputCollisionError, OutputError, OutputLockTimeoutError
from fastfoto_linux.output.files import LOCK_NAME, locked_folder, write_new_files
from fastfoto_linux.output.naming import STAGING_OVERHEAD_BYTES


def listing(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def test_writes_every_file_with_its_content_and_leaves_no_temp_files(tmp_path: Path) -> None:
    write_new_files([(tmp_path / "a.jpg", b"AAA"), (tmp_path / "b.jpg", b"BBB")])

    assert listing(tmp_path) == ["a.jpg", "b.jpg"]
    assert (tmp_path / "a.jpg").read_bytes() == b"AAA"
    assert (tmp_path / "b.jpg").read_bytes() == b"BBB"


def test_new_files_get_the_default_umask_permissions(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    reference.write_bytes(b"")

    write_new_files([(tmp_path / "a.jpg", b"AAA")])

    assert (tmp_path / "a.jpg").stat().st_mode == reference.stat().st_mode


def test_an_existing_file_is_never_overwritten_and_nothing_else_is_written(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.jpg").write_bytes(b"precious")

    with pytest.raises(OutputCollisionError) as raised:
        write_new_files([(tmp_path / "a.jpg", b"new"), (tmp_path / "b.jpg", b"BBB")])

    assert isinstance(raised.value, FileExistsError)
    assert (tmp_path / "a.jpg").read_bytes() == b"precious"
    assert listing(tmp_path) == ["a.jpg"]


def test_a_collision_on_a_later_file_rolls_back_the_earlier_ones(tmp_path: Path) -> None:
    (tmp_path / "b.jpg").write_bytes(b"precious")

    with pytest.raises(OutputCollisionError, match=r"b\.jpg"):
        write_new_files([(tmp_path / "a.jpg", b"AAA"), (tmp_path / "b.jpg", b"new")])

    assert listing(tmp_path) == ["b.jpg"]
    assert (tmp_path / "b.jpg").read_bytes() == b"precious"


def test_an_io_error_part_way_rolls_back_and_removes_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_link = os.link
    calls = []

    def flaky_link(src: Path, dst: Path, **kwargs: bool) -> None:
        calls.append(dst)
        if len(calls) == 2:
            raise OSError(errno.ENOSPC, "No space left on device")
        real_link(src, dst, **kwargs)

    monkeypatch.setattr(os, "link", flaky_link)

    with pytest.raises(OSError, match="No space"):
        write_new_files([(tmp_path / "a.jpg", b"AAA"), (tmp_path / "b.jpg", b"BBB")])

    assert listing(tmp_path) == []


def test_a_missing_directory_fails_cleanly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        write_new_files([(tmp_path / "nope" / "a.jpg", b"AAA")])

    assert listing(tmp_path) == []


def test_filesystems_without_hard_links_still_get_new_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(src: Path, dst: Path, **kwargs: bool) -> None:
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_links)

    write_new_files([(tmp_path / "a.jpg", b"AAA"), (tmp_path / "b.jpg", b"BBB")])

    assert listing(tmp_path) == ["a.jpg", "b.jpg"]
    assert (tmp_path / "b.jpg").read_bytes() == b"BBB"


def test_without_hard_links_an_existing_file_is_still_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(src: Path, dst: Path, **kwargs: bool) -> None:
        raise OSError(errno.ENOTSUP, "Operation not supported")

    monkeypatch.setattr(os, "link", no_links)
    (tmp_path / "b.jpg").write_bytes(b"precious")

    with pytest.raises(OutputCollisionError):
        write_new_files([(tmp_path / "a.jpg", b"AAA"), (tmp_path / "b.jpg", b"new")])

    assert listing(tmp_path) == ["b.jpg"]
    assert (tmp_path / "b.jpg").read_bytes() == b"precious"


def test_without_hard_links_an_io_error_rolls_back_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(src: Path, dst: Path, **kwargs: bool) -> None:
        raise OSError(errno.EPERM, "Operation not permitted")

    real_replace = os.replace
    replaced = []

    def flaky_replace(src: Path, dst: Path) -> None:
        replaced.append(dst)
        if len(replaced) == 2:
            raise OSError(errno.EIO, "Input/output error")
        real_replace(src, dst)

    monkeypatch.setattr(os, "link", no_links)
    monkeypatch.setattr(os, "replace", flaky_replace)

    with pytest.raises(OSError, match="Input/output"):
        write_new_files([(tmp_path / "a.jpg", b"AAA"), (tmp_path / "b.jpg", b"BBB")])

    assert listing(tmp_path) == []


def test_no_items_is_a_no_op(tmp_path: Path) -> None:
    write_new_files([])

    assert listing(tmp_path) == []


# --- durability: fsync the data before publishing, the folder after ----------------------------


def record_events(monkeypatch: pytest.MonkeyPatch, *, hard_links: bool = True) -> list[str]:
    """Log fsync (file or folder) and link calls in order, still performing them."""
    events: list[str] = []
    real_fsync, real_link = os.fsync, os.link

    def fsync(fd: int) -> None:
        events.append("fsync:folder" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync:file")
        real_fsync(fd)

    def link(src: Path, dst: Path, **kwargs: bool) -> None:
        events.append("link")
        if not hard_links:
            raise OSError(errno.EPERM, "Operation not permitted")
        real_link(src, dst, **kwargs)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "link", link)
    return events


def test_data_is_synced_before_publishing_and_the_folder_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = record_events(monkeypatch)

    write_new_files([(tmp_path / "a.jpg", b"AAA"), (tmp_path / "b.jpg", b"BBB")])

    assert events == ["fsync:file", "fsync:file", "link", "link", "fsync:folder"]


def test_data_is_synced_before_publishing_without_hard_links_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = record_events(monkeypatch, hard_links=False)

    write_new_files([(tmp_path / "a.jpg", b"AAA")])

    assert events == ["fsync:file", "link", "fsync:folder"]


def test_each_folder_is_synced_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    events = record_events(monkeypatch)

    write_new_files(
        [
            (tmp_path / "x" / "a.jpg", b"A"),
            (tmp_path / "x" / "b.jpg", b"B"),
            (tmp_path / "y" / "c.jpg", b"C"),
        ]
    )

    assert events.count("fsync:folder") == 2


@pytest.mark.parametrize("code", [errno.EINVAL, errno.ENOTSUP])
def test_a_folder_that_cannot_be_synced_is_tolerated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    real_fsync = os.fsync

    def fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(code, "Not supported here")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)

    write_new_files([(tmp_path / "a.jpg", b"AAA")])

    assert (tmp_path / "a.jpg").read_bytes() == b"AAA"


def test_an_io_error_while_syncing_the_folder_is_reported_without_undoing_the_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_fsync = os.fsync

    def fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, "Input/output error")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)

    with pytest.raises(OSError, match="Input/output"):
        write_new_files([(tmp_path / "a.jpg", b"AAA")])

    assert listing(tmp_path) == ["a.jpg"]


def test_a_full_disk_while_writing_a_temp_file_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = Path.open

    class FullDisk:
        def __init__(self, handle: object) -> None:
            self.handle = handle

        def __enter__(self) -> "FullDisk":
            return self

        def __exit__(self, *exc: object) -> None:
            self.handle.close()  # type: ignore[attr-defined]

        def fileno(self) -> int:
            return self.handle.fileno()  # type: ignore[attr-defined]

        def write(self, data: bytes) -> None:
            self.handle.write(b"partial")  # type: ignore[attr-defined]
            raise OSError(errno.ENOSPC, "No space left on device")

    def full_open(self: Path, mode: str = "r", *args: object, **kwargs: object) -> object:
        handle = real_open(self, mode, *args, **kwargs)  # type: ignore[arg-type]
        return FullDisk(handle) if self.name.endswith(files_module.TEMP_SUFFIX) else handle

    monkeypatch.setattr(Path, "open", full_open)

    with pytest.raises(OSError, match="No space"):
        write_new_files([(tmp_path / "a.jpg", b"AAA")])

    assert listing(tmp_path) == []


def test_a_sync_error_on_a_later_temp_file_cleans_up_the_earlier_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    real_fsync = os.fsync

    def fsync(fd: int) -> None:
        calls.append(fd)
        if len(calls) == 2:
            raise OSError(errno.ENOSPC, "No space left on device")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)

    with pytest.raises(OSError, match="No space"):
        write_new_files([(tmp_path / "a.jpg", b"AAA"), (tmp_path / "b.jpg", b"BBB")])

    assert listing(tmp_path) == []


# --- link hygiene and interrupts ----------------------------------------------------------------


def test_hard_links_never_follow_symlinks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []
    real_link = os.link

    def link(src: Path, dst: Path, **kwargs: bool) -> None:
        seen.append(kwargs)
        real_link(src, dst, **kwargs)

    monkeypatch.setattr(os, "link", link)

    write_new_files([(tmp_path / "a.jpg", b"AAA")])

    assert seen == [{"follow_symlinks": False}]


def test_the_staging_name_is_as_long_as_the_name_length_reserve_assumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lengths = []
    real_link = os.link

    def link(src: Path, dst: Path, **kwargs: bool) -> None:
        lengths.append(len(Path(src).name.encode()) - len(Path(dst).name.encode()))
        real_link(src, dst, **kwargs)

    monkeypatch.setattr(os, "link", link)

    write_new_files([(tmp_path / "a.jpg", b"AAA")])

    assert lengths == [STAGING_OVERHEAD_BYTES]


def test_an_interrupt_right_after_linking_still_removes_the_new_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_link = os.link

    def link_then_interrupt(src: Path, dst: Path, **kwargs: bool) -> None:
        real_link(src, dst, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "link", link_then_interrupt)

    with pytest.raises(KeyboardInterrupt):
        write_new_files([(tmp_path / "a.jpg", b"AAA"), (tmp_path / "b.jpg", b"BBB")])

    assert listing(tmp_path) == []


def test_an_interrupt_never_removes_a_file_someone_else_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(src: Path, dst: Path, **kwargs: bool) -> None:
        Path(dst).write_bytes(b"theirs")
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "link", interrupt)

    with pytest.raises(KeyboardInterrupt):
        write_new_files([(tmp_path / "a.jpg", b"AAA")])

    assert listing(tmp_path) == ["a.jpg"]
    assert (tmp_path / "a.jpg").read_bytes() == b"theirs"


def test_an_interrupt_during_the_fallback_swap_removes_the_reserved_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(src: Path, dst: Path, **kwargs: bool) -> None:
        raise OSError(errno.EPERM, "Operation not permitted")

    def interrupt(src: Path, dst: Path) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "link", no_links)
    monkeypatch.setattr(os, "replace", interrupt)

    with pytest.raises(KeyboardInterrupt):
        write_new_files([(tmp_path / "a.jpg", b"AAA")])

    assert listing(tmp_path) == []


# --- folder lock ----------------------------------------------------------------------------------


def test_the_lock_file_lives_in_the_folder(tmp_path: Path) -> None:
    with locked_folder(tmp_path):
        assert (tmp_path / LOCK_NAME).exists()


def test_the_folder_lock_excludes_other_holders(tmp_path: Path) -> None:
    order: list[str] = []
    inside = threading.Event()

    def first() -> None:
        with locked_folder(tmp_path):
            order.append("first-in")
            inside.set()
            time.sleep(0.2)
            order.append("first-out")

    def second() -> None:
        inside.wait(timeout=5)
        with locked_folder(tmp_path):
            order.append("second-in")

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert order == ["first-in", "first-out", "second-in"]


def test_the_folder_lock_is_released_when_the_block_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError), locked_folder(tmp_path):
        raise RuntimeError("boom")

    with locked_folder(tmp_path):
        pass


def test_a_filesystem_without_locks_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_locks(fd: int, operation: int) -> None:
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(files_module.fcntl, "flock", no_locks)

    with locked_folder(tmp_path):
        pass


def test_other_lock_errors_are_not_hidden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(fd: int, operation: int) -> None:
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(files_module.fcntl, "flock", broken)

    with pytest.raises(OSError, match="Input/output"), locked_folder(tmp_path):
        pass


# --- rollback must not trust inode numbers alone ---------------------------------------------


@pytest.mark.parametrize("hard_links", [True, False])
def test_rollback_never_deletes_an_existing_file_even_when_inode_numbers_repeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hard_links: bool
) -> None:
    monkeypatch.setattr(files_module, "_file_id", lambda info: (1, 0))
    if not hard_links:

        def no_links(src: Path, dst: Path, **kwargs: bool) -> None:
            raise OSError(errno.EPERM, "Operation not permitted")

        monkeypatch.setattr(os, "link", no_links)
    (tmp_path / "b.jpg").write_bytes(b"precious")

    with pytest.raises(OutputCollisionError):
        write_new_files([(tmp_path / "a.jpg", b"AAA"), (tmp_path / "b.jpg", b"new")])

    assert listing(tmp_path) == ["b.jpg"]
    assert (tmp_path / "b.jpg").read_bytes() == b"precious"


def test_rollback_never_touches_a_name_it_did_not_get_to_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(files_module, "_file_id", lambda info: (1, 0))
    (tmp_path / "a.jpg").write_bytes(b"precious")

    with pytest.raises(FileNotFoundError):
        write_new_files([(tmp_path / "a.jpg", b"new"), (tmp_path / "missing" / "b.jpg", b"BBB")])

    assert listing(tmp_path) == ["a.jpg"]
    assert (tmp_path / "a.jpg").read_bytes() == b"precious"


# --- lock timeout, unreadable lock files, symlinked lock files --------------------------------


def test_the_lock_is_polled_without_blocking_and_released_before_closing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operations = []
    real_flock = fcntl.flock

    def flock(fd: int, operation: int) -> None:
        operations.append(operation)
        real_flock(fd, operation)

    monkeypatch.setattr(files_module.fcntl, "flock", flock)

    with locked_folder(tmp_path):
        pass

    assert operations == [fcntl.LOCK_EX | fcntl.LOCK_NB, fcntl.LOCK_UN]


def test_a_filesystem_without_locks_is_never_asked_to_unlock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operations = []

    def no_locks(fd: int, operation: int) -> None:
        operations.append(operation)
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(files_module.fcntl, "flock", no_locks)

    with locked_folder(tmp_path):
        pass

    assert operations == [fcntl.LOCK_EX | fcntl.LOCK_NB]


def test_a_lock_held_too_long_times_out_naming_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(files_module, "LOCK_TIMEOUT_S", 0.3)
    monkeypatch.setattr(files_module, "LOCK_POLL_S", 0.02)
    holder = os.open(tmp_path / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(holder, fcntl.LOCK_EX)
    started = time.monotonic()

    try:
        with (
            caplog.at_level(logging.INFO, logger=files_module.logger.name),
            pytest.raises(OutputLockTimeoutError, match=str(tmp_path)) as raised,
            locked_folder(tmp_path),
        ):
            pass
    finally:
        os.close(holder)

    assert isinstance(raised.value, OutputError)
    assert time.monotonic() - started >= 0.3
    waiting = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(waiting) == 1
    assert str(tmp_path) in waiting[0].getMessage()


def test_a_lock_released_within_the_deadline_is_acquired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(files_module, "LOCK_POLL_S", 0.02)
    holder = os.open(tmp_path / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(holder, fcntl.LOCK_EX)
    threading.Timer(0.2, os.close, args=(holder,)).start()

    with locked_folder(tmp_path):
        pass


@pytest.mark.parametrize("code", [errno.EACCES, errno.EPERM])
def test_a_lock_file_that_cannot_be_opened_means_no_lock_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, code: int
) -> None:
    real_open = os.open

    def deny(path: object, flags: int, mode: int = 0o777, **kwargs: object) -> int:
        if Path(str(path)).name == LOCK_NAME:
            raise OSError(code, "Permission denied")
        return real_open(path, flags, mode, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", deny)
    ran = False

    with caplog.at_level(logging.WARNING, logger=files_module.logger.name), locked_folder(tmp_path):
        ran = True

    assert ran
    assert any(LOCK_NAME in r.getMessage() for r in caplog.records)


def test_a_read_only_lock_file_is_tolerated(tmp_path: Path) -> None:
    lock = tmp_path / LOCK_NAME
    lock.write_bytes(b"")
    lock.chmod(0o444)

    with locked_folder(tmp_path):
        pass


def test_a_symlinked_lock_file_is_refused_and_its_target_left_alone(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.write_bytes(b"keep")
    (tmp_path / LOCK_NAME).symlink_to(target)

    with pytest.raises(OSError, match="symbolic links") as raised, locked_folder(tmp_path):
        pass

    assert raised.value.errno == errno.ELOOP
    assert target.read_bytes() == b"keep"
