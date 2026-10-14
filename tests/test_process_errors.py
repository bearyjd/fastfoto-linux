"""``process_pages``: one bad sheet never loses the others; inputs are validated up front."""

import numpy as np
import pytest

from fastfoto_linux.output import OutputRootMissingError
from fastfoto_linux.pipeline.process import ProcessSettings, SheetIssue, process_pages
from fastfoto_linux.pipeline.sides import BackPolicy, BatchError
from tests.process_helpers import (
    BLANK,
    DPI,
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
    pages[2].write_bytes(b"this is not a png")
    result = process_pages(pages, settings_for(out))
    assert result.photos == 2
    assert jpeg_names(out) == ["FastFoto_0001.jpg", "FastFoto_0002.jpg"]
    (issue,) = result.failed
    assert issue.sheet == 2
    assert issue.pages == (page_name(3), page_name(4))
    assert page_name(3) in issue.reason


def test_a_failing_enhancer_loses_only_its_own_photo(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1), plain_sheet(2)])
    calls = []

    def flaky(img: np.ndarray, dpi: int) -> np.ndarray:
        calls.append(1)
        if len(calls) == 2:
            raise ValueError("enhancer exploded")
        return img

    result = process_pages(pages, settings_for(out, enhancers=(flaky,)))
    assert result.photos == 2
    assert jpeg_names(out) == [
        "FastFoto_0001.jpg",
        "FastFoto_0001_a.jpg",
        "FastFoto_0002.jpg",
        "FastFoto_0002_a.jpg",
    ]
    (issue,) = result.failed
    assert issue == SheetIssue(2, (page_name(3), page_name(4)), "enhancer exploded")


def test_a_failing_orienter_is_reported_the_same_way(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1)])

    def broken(img: np.ndarray, dpi: int) -> np.ndarray:
        raise RuntimeError

    result = process_pages(pages, settings_for(out, orienter=broken))
    assert result.photos == 0
    assert [issue.sheet for issue in result.failed] == [1, 2]
    assert all(issue.reason for issue in result.failed)  # never an empty message


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
