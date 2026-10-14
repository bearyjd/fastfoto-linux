"""Backs dropped by the policy are reported; a lone last page is an incomplete sheet."""

import pytest

from fastfoto_linux.pipeline.process import process_pages
from fastfoto_linux.pipeline.sides import BackPolicy
from tests.process_helpers import (
    BLANK,
    DPI,
    page_name,
    plain_sheet,
    settings_for,
    workspace,
    write_front_pages,
    write_sheets,
    written_sheet,
)
from tests.synth import make_duplex_sheet

NEAR_WHITE = (245, 245, 245)  # a front that scores exactly like a back


def test_backs_without_writing_are_counted_and_their_pages_named(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), written_sheet(1), plain_sheet(2)])
    result = process_pages(pages, settings_for(out))
    assert result.dropped_backs == (page_name(1), page_name(5))  # the back is scanned first
    assert result.backs_dropped == 2
    assert result.backs_kept == 1


@pytest.mark.parametrize("policy", [BackPolicy.ALWAYS, BackPolicy.NEVER])
def test_only_the_auto_policy_drops_backs_for_lack_of_writing(tmp_path, policy) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1)])
    result = process_pages(pages, settings_for(out, back_policy=policy))
    assert result.dropped_backs == ()


def test_a_sheet_that_failed_drops_nothing(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1)])
    pages[2].write_bytes(b"not a png")
    result = process_pages(pages, settings_for(out))
    assert result.dropped_backs == (page_name(1),)


def test_an_uncertain_sheet_keeps_its_back_so_nothing_is_dropped(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    tie = make_duplex_sheet(dpi=DPI, front={"photo_rgb": NEAR_WHITE}, back=BLANK)
    result = process_pages(write_sheets(raw, [tie]), settings_for(out))
    assert result.dropped_backs == ()


def test_a_simplex_batch_has_no_backs_to_drop(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    result = process_pages(write_front_pages(raw, 2), settings_for(out, duplex=False))
    assert result.dropped_backs == ()


def test_a_lone_last_page_that_looks_like_a_back_is_an_incomplete_sheet(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1)])[:3]  # the jam hit mid-sheet
    result = process_pages(pages, settings_for(out))
    assert result.failed == ()
    (issue,) = result.uncertain
    assert (issue.sheet, issue.pages) == (2, (page_name(3),))
    assert "incomplete sheet" in issue.reason
    assert "told apart" not in issue.reason


def test_a_lone_last_front_page_is_an_incomplete_sheet_too(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1)], front_first=True)[:3]
    result = process_pages(pages, settings_for(out, expect_front_first=True))
    (issue,) = result.uncertain
    assert (issue.sheet, issue.pages) == (2, (page_name(3),))
    assert "incomplete sheet" in issue.reason


def test_every_page_of_a_simplex_batch_is_complete(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    result = process_pages(write_front_pages(raw, 3), settings_for(out, duplex=False))
    assert result.uncertain == ()
