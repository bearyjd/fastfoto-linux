"""``process_pages``: from raw pages to album files, enhancers and the orienter."""

import logging

import numpy as np
import pytest

from fastfoto_linux.output import PhotoDate
from fastfoto_linux.pipeline.process import ProcessResult, process_pages
from fastfoto_linux.pipeline.sides import BackPolicy
from tests.process_helpers import (
    DPI,
    LOGGER,
    half_bright_front_sheet,
    invert,
    jpeg_mean,
    jpeg_names,
    jpeg_size,
    original_date,
    page_name,
    plain_sheet,
    settings_for,
    workspace,
    write_front_pages,
    write_sheets,
    written_sheet,
)


def test_each_duplex_sheet_becomes_one_original_and_plain_backs_are_dropped(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1), plain_sheet(2)])
    result = process_pages(pages, settings_for(out))
    assert result.photos == 3
    assert result.backs_kept == 0
    assert result.enhanced == 0
    assert result.failed == ()
    assert jpeg_names(out) == ["FastFoto_0001.jpg", "FastFoto_0002.jpg", "FastFoto_0003.jpg"]


@pytest.mark.parametrize(
    ("policy", "backs"),
    [
        (BackPolicy.AUTO, ["FastFoto_0002_b.jpg"]),
        (BackPolicy.ALWAYS, ["FastFoto_0001_b.jpg", "FastFoto_0002_b.jpg", "FastFoto_0003_b.jpg"]),
        (BackPolicy.NEVER, []),
    ],
)
def test_the_back_policy_decides_which_backs_are_written(tmp_path, policy, backs) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), written_sheet(1), plain_sheet(2)])
    result = process_pages(pages, settings_for(out, back_policy=policy))
    assert jpeg_names(out) == sorted(
        ["FastFoto_0001.jpg", "FastFoto_0002.jpg", "FastFoto_0003.jpg", *backs]
    )
    assert result.backs_kept == len(backs)


def test_simplex_treats_every_page_as_a_front(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_front_pages(raw, 2)
    settings = settings_for(out, duplex=False, back_policy=BackPolicy.ALWAYS)
    result = process_pages(pages, settings)
    assert result.photos == 2
    assert result.backs_kept == 0
    assert jpeg_names(out) == ["FastFoto_0001.jpg", "FastFoto_0002.jpg"]


def test_expect_front_first_decides_when_the_content_cannot(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [half_bright_front_sheet()])  # back page first
    for expect_front_first, bright in ((False, True), (True, False)):
        root = out / str(expect_front_first)
        root.mkdir()
        result = process_pages(pages, settings_for(root, expect_front_first=expect_front_first))
        assert len(result.uncertain) == 1
        original = result.written[0].original
        assert original is not None
        assert (jpeg_mean(original) > 120) is bright


def test_album_prefix_date_notes_and_quality_reach_the_files(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet()])
    settings = settings_for(out, album="Trip", date=PhotoDate(1975, 6), notes="Beach day")
    named = settings_for(out, album="Trip", prefix="Beach", quality=30)
    (default,) = process_pages(pages, settings).written
    (small,) = process_pages(pages, named).written
    assert default.original == (out / "Trip" / "Trip_0001.jpg").resolve()
    assert original_date(default.original) == "1975:06:01 00:00:00"
    assert small.original == (out / "Trip" / "Beach_0001.jpg").resolve()
    assert small.original.stat().st_size < default.original.stat().st_size


def test_progress_is_logged_once_per_photo(tmp_path, caplog) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1)])
    with caplog.at_level(logging.INFO, logger=LOGGER):
        process_pages(pages, settings_for(out))
    records = [r for r in caplog.records if r.name == LOGGER and r.levelno == logging.INFO]
    assert len(records) == 2


def test_an_odd_last_page_is_a_front_without_a_back_and_is_warned_about(tmp_path, caplog) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet()])
    pages += write_front_pages(raw, 1, first_number=3)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        result = process_pages(pages, settings_for(out, back_policy=BackPolicy.ALWAYS))
    assert result.photos == 2
    assert result.written[1].back is None
    assert any("odd" in r.getMessage() for r in caplog.records if r.name == LOGGER)


def test_no_pages_is_an_empty_result(tmp_path) -> None:
    _, out = workspace(tmp_path)
    assert process_pages([], settings_for(out)) == ProcessResult()


# --- the orienter and the enhancers -----------------------------------------------------------


def _rotated(img: np.ndarray, dpi: int) -> np.ndarray:
    return np.ascontiguousarray(np.rot90(img))


def test_the_orienter_turns_the_front_only(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet()])
    settings = settings_for(out, back_policy=BackPolicy.ALWAYS, orienter=_rotated)
    (written,) = process_pages(pages, settings).written
    front_w, front_h = jpeg_size(written.original)
    back_w, back_h = jpeg_size(written.back)
    assert front_w < front_h  # the landscape front was turned a quarter
    assert back_w > back_h  # the back stays as scanned


def test_enhancers_get_the_oriented_front_once_per_photo_in_order(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1)])
    calls: list[tuple[str, np.ndarray, int]] = []
    outputs: dict[str, np.ndarray] = {}

    def first(img: np.ndarray, dpi: int) -> np.ndarray:
        calls.append(("first", img, dpi))
        outputs["first"] = img[: img.shape[0] // 2].copy()
        return outputs["first"]

    def second(img: np.ndarray, dpi: int) -> np.ndarray:
        calls.append(("second", img, dpi))
        return img

    settings = settings_for(out, orienter=_rotated, enhancers=(first, second))
    result = process_pages(pages, settings)
    assert [name for name, _, _ in calls] == ["first", "second", "first", "second"]
    assert {dpi for _, _, dpi in calls} == {DPI}
    for written, (_, oriented, _), (_, chained, _) in zip(
        result.written, calls[0::2], calls[1::2], strict=True
    ):
        assert jpeg_size(written.original) == oriented.shape[1::-1]  # the oriented front
        assert chained.shape[0] == oriented.shape[0] // 2  # the second saw the first's output
        assert jpeg_size(written.enhanced) == chained.shape[1::-1]  # the chain's result
    assert result.enhanced == 2
    assert jpeg_names(out) == [
        "FastFoto_0001.jpg",
        "FastFoto_0001_a.jpg",
        "FastFoto_0002.jpg",
        "FastFoto_0002_a.jpg",
    ]


def test_no_enhanced_copy_without_enhancers(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    process_pages(write_sheets(raw, [plain_sheet()]), settings_for(out))
    assert jpeg_names(out) == ["FastFoto_0001.jpg"]


def test_enhanced_only_skips_the_plain_original(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet()])
    settings = settings_for(out, keep_original=False, enhancers=(invert,))
    (written,) = process_pages(pages, settings).written
    assert written.original is None
    assert jpeg_names(out) == ["FastFoto_0001_a.jpg"]


def test_the_page_files_are_never_touched(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet()])
    before = [p.read_bytes() for p in pages]
    process_pages(pages, settings_for(out, orienter=_rotated))
    assert [p.read_bytes() for p in pages] == before
    assert sorted(p.name for p in raw.iterdir()) == [page_name(1), page_name(2)]
