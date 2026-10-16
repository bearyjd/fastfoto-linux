"""The note "our last scan here ended badly" goes stale (review round 2, item 3).

A note from before the scanner was last switched off and on, or from another boot of the computer,
or from days ago says nothing about the scanner's session now, so it must not unlock filler. The
note keeps the boot id (``/proc/sys/kernel/random/boot_id``, when it can be read) and the UTC time;
it is ignored when the boot ids differ or when it is older than 24 hours.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fastfoto_linux.scanner import precheck, unclean
from fastfoto_linux.scanner.errors import ScannerStuckError
from tests.unstick_fakes import FakeClock, FakeScanner

DEVICE = "epsonds:libusb:001:004"
WHEN = datetime(2026, 10, 15, 12, 34, 56, tzinfo=UTC)
BOOT = "0b1c2d3e-4f50-4a61-8b72-93a4b5c6d7e8"  # made up
OTHER_BOOT = "9f8e7d6c-5b4a-4938-a271-605f4e3d2c1b"  # made up
ONE_SECOND = timedelta(seconds=1)
DAY = timedelta(hours=24)


@pytest.fixture
def boot_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "boot_id"
    path.write_text(f"{BOOT}\n")
    monkeypatch.setattr(unclean, "BOOT_ID_PATH", path)
    return path


# --- the boot id --------------------------------------------------------------------------------


def test_a_note_from_the_same_boot_counts(boot_id: Path) -> None:
    unclean.mark(1, 4, now=WHEN)

    assert unclean.is_marked(1, 4, now=WHEN)


def test_a_note_from_another_boot_is_ignored(boot_id: Path) -> None:
    unclean.mark(1, 4, now=WHEN)
    boot_id.write_text(f"{OTHER_BOOT}\n")

    assert not unclean.is_marked(1, 4, now=WHEN)


def test_without_a_readable_boot_id_the_note_has_none_and_the_age_decides(
    boot_id: Path,
) -> None:
    boot_id.unlink()

    unclean.mark(1, 4, now=WHEN)

    assert unclean.marker_path().read_text() == "001:004 2026-10-15T12:34:56Z\n"
    assert unclean.is_marked(1, 4, now=WHEN)
    assert not unclean.is_marked(1, 4, now=WHEN + DAY + ONE_SECOND)


@pytest.mark.parametrize("content", ["", "\n", "not-a-boot-id\n", f"{BOOT} {BOOT}\n"])
def test_a_boot_id_that_is_not_one_counts_as_unreadable(boot_id: Path, content: str) -> None:
    boot_id.write_text(content)

    unclean.mark(1, 4, now=WHEN)

    assert unclean.marker_path().read_text() == "001:004 2026-10-15T12:34:56Z\n"


def test_a_note_with_a_boot_id_counts_when_the_boot_id_cannot_be_read_now(boot_id: Path) -> None:
    unclean.mark(1, 4, now=WHEN)
    boot_id.unlink()

    assert unclean.is_marked(1, 4, now=WHEN)


def test_a_note_without_a_boot_id_counts_when_the_boot_id_can_be_read_now(boot_id: Path) -> None:
    boot_id.unlink()
    unclean.mark(1, 4, now=WHEN)
    boot_id.write_text(f"{BOOT}\n")

    assert unclean.is_marked(1, 4, now=WHEN)


# --- the age ------------------------------------------------------------------------------------


def test_a_note_just_under_24_hours_old_counts(boot_id: Path) -> None:
    unclean.mark(1, 4, now=WHEN)

    assert unclean.is_marked(1, 4, now=WHEN + DAY - ONE_SECOND)


def test_a_note_just_over_24_hours_old_is_ignored(boot_id: Path) -> None:
    unclean.mark(1, 4, now=WHEN)

    assert not unclean.is_marked(1, 4, now=WHEN + DAY + ONE_SECOND)


def test_a_note_dated_in_the_future_is_ignored(boot_id: Path) -> None:
    unclean.mark(1, 4, now=WHEN + timedelta(hours=1))

    assert not unclean.is_marked(1, 4, now=WHEN)


def test_the_age_is_measured_from_now_by_default(boot_id: Path) -> None:
    unclean.mark(1, 4)
    assert unclean.is_marked(1, 4)

    unclean.mark(1, 4, now=datetime.now(UTC) - DAY - ONE_SECOND)
    assert not unclean.is_marked(1, 4)


# --- what it means for the check ----------------------------------------------------------------


def filler_sent_by_the_next_check() -> int:
    clock = FakeClock()
    scanner = FakeScanner(clock, swallow=None)  # busy elsewhere: silent, and it swallows filler

    @contextmanager
    def opener(bus: int, address: int) -> Iterator[FakeScanner]:
        yield scanner

    with pytest.raises(ScannerStuckError):
        precheck.check_scanner(DEVICE, env={}, opener=opener, clock=clock)
    return scanner.filler_bytes


def test_a_fresh_note_from_this_boot_lets_the_check_send_filler(boot_id: Path) -> None:
    unclean.mark(1, 4)

    assert filler_sent_by_the_next_check() > 0


def test_a_note_from_another_boot_does_not_let_the_check_send_filler(boot_id: Path) -> None:
    unclean.mark(1, 4)
    boot_id.write_text(f"{OTHER_BOOT}\n")

    assert filler_sent_by_the_next_check() == 0


def test_a_note_from_two_days_ago_does_not_let_the_check_send_filler(boot_id: Path) -> None:
    unclean.mark(1, 4, now=datetime.now(UTC) - 2 * DAY)

    assert filler_sent_by_the_next_check() == 0
