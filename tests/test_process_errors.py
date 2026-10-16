"""``process_pages``: one bad sheet never loses the others; inputs are validated up front."""

import errno
import logging

import numpy as np
import pytest

from fastfoto_linux.output import OutputRootMissingError
from fastfoto_linux.pipeline import process
from fastfoto_linux.pipeline.process import ProcessSettings, SheetIssue, process_pages
from fastfoto_linux.pipeline.sides import BackPolicy, BatchError
from tests.process_helpers import (
    BLANK,
    DPI,
    LOGGER,
    jpeg_names,
    page_name,
    plain_sheet,
    settings_for,
    workspace,
    write_sheets,
)
from tests.synth import make_duplex_sheet

NEAR_WHITE = (245, 245, 245)  # a front that scores exactly like a back


def test_an_unreadable_sheet_is_reported_and_the_others_are_written(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1), plain_sheet(2)])
    for page in pages[2:4]:  # both pages: with one readable page the sheet is saved whole
        page.write_bytes(b"this is not a png")
    result = process_pages(pages, settings_for(out))
    assert result.photos == 2
    assert jpeg_names(out) == ["FastFoto_0001.jpg", "FastFoto_0002.jpg"]
    (issue,) = result.failed
    assert issue.sheet == 2
    assert issue.pages == (page_name(3), page_name(4))
    assert issue.reason == "a page of the sheet could not be read"


def test_a_failing_writer_loses_only_its_own_sheet(tmp_path, monkeypatch) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1), plain_sheet(2)])
    real_write = process.write_photo
    calls = []

    def flaky_write(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_write(*args, **kwargs)

    monkeypatch.setattr(process, "write_photo", flaky_write)
    result = process_pages(pages, settings_for(out))
    assert result.photos == 2
    assert result.degraded == ()
    (issue,) = result.failed
    assert (issue.sheet, issue.pages) == (2, (page_name(3), page_name(4)))
    assert "No space left" in issue.reason
    assert jpeg_names(out) == ["FastFoto_0001.jpg", "FastFoto_0002.jpg"]


def secret_path(tmp_path) -> str:
    return str(tmp_path / "private-album" / "FastFoto_0002.jpg")


@pytest.mark.parametrize(
    ("make_error", "plain"),
    [
        (
            lambda path: OSError(errno.ENOSPC, "No space left on device", path),
            "the photo could not be saved (No space left on device)",
        ),
        (lambda path: OSError(f"boom at {path}"), "the photo could not be processed"),
        (lambda path: ValueError(f"bad value in {path}"), "the photo could not be processed"),
    ],
    ids=["os-error", "os-error-without-text", "other"],
)
def test_a_writer_failure_gives_a_plain_reason_and_the_details_go_to_debug(
    tmp_path, monkeypatch, caplog, make_error, plain
) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1)])
    secret = secret_path(tmp_path)
    real_write = process.write_photo
    calls = []

    def flaky_write(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise make_error(secret)
        return real_write(*args, **kwargs)

    monkeypatch.setattr(process, "write_photo", flaky_write)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        result = process_pages(pages, settings_for(out))
    (issue,) = result.failed
    assert issue.reason == plain
    records = [r for r in caplog.records if r.name == LOGGER]
    assert [r.getMessage() for r in records if r.levelno >= logging.ERROR] == [f"sheet 2: {plain}"]
    assert not [r for r in records if r.levelno > logging.DEBUG and str(tmp_path) in r.getMessage()]
    assert any(r.levelno == logging.DEBUG and secret in r.getMessage() for r in records)


def test_ctrl_c_is_not_swallowed(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet()])

    def interrupted(img: np.ndarray, dpi: int) -> np.ndarray:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        process_pages(pages, settings_for(out, enhancers=(interrupted,)))


def test_an_uncertain_sheet_keeps_its_back_whatever_the_policy_and_is_listed(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    tie = make_duplex_sheet(dpi=DPI, front={"photo_rgb": NEAR_WHITE}, back=BLANK)
    pages = write_sheets(raw, [plain_sheet(), tie])
    result = process_pages(pages, settings_for(out, back_policy=BackPolicy.NEVER))
    assert result.failed == ()
    assert [(i.sheet, i.pages) for i in result.uncertain] == [(2, (page_name(3), page_name(4)))]
    assert "told apart" in result.uncertain[0].reason
    assert [w.back is not None for w in result.written] == [False, True]
    assert result.backs_kept == 1


def test_a_missing_output_root_is_refused_before_any_page_is_read(tmp_path) -> None:
    missing = tmp_path / "not-there"
    with pytest.raises(OutputRootMissingError):
        process_pages([tmp_path / "page-0001.png"], settings_for(missing))
    assert not missing.exists()


@pytest.mark.parametrize(
    "bad",
    [
        {"quality": 0},
        {"quality": 101},
        {"album": "///"},
        {"prefix": ".."},
        {"notes": "x" * 10_001},
    ],
    ids=["quality-low", "quality-high", "album", "prefix", "notes"],
)
def test_settings_are_validated_on_construction(tmp_path, bad) -> None:
    with pytest.raises(ValueError):
        ProcessSettings(output_root=tmp_path, **bad)


def test_a_problem_with_the_whole_batch_is_reported_without_a_sheet(tmp_path, monkeypatch) -> None:
    def batch_error(pages, *, on_sheet_error, **kwargs):
        on_sheet_error(BatchError("no pages make sense"))
        return iter(())

    monkeypatch.setattr("fastfoto_linux.pipeline.process.iter_photos", batch_error)
    _, out = workspace(tmp_path)
    result = process_pages([], settings_for(out))
    assert result.failed == (SheetIssue(None, (), "no pages make sense"),)
