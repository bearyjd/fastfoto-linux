"""Pairing pages into photos: which side is the front, back policies, odd and simplex batches."""

import logging
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.pipeline.geometry import mm_to_px
from fastfoto_linux.pipeline.sides import (
    BackPolicy,
    BatchError,
    Photo,
    assemble_photos,
    iter_photos,
)
from tests.crop_helpers import background_only
from tests.sides_helpers import SIDES_LOGGER, batch, page_number
from tests.synth import make_duplex_sheet, make_frame

DPI = 150
DARK = 150  # a front's median grey stays below this, a back's above 240
PAPER = 240

WRITTEN = {"writing": True}
IMPRINT_ONLY = {"imprint": True}
BLANK = {"imprint": False}


def _sheets(*backs: dict, dpi: int = DPI):
    return [make_duplex_sheet(dpi=dpi, rng_seed=10 * i, back=back) for i, back in enumerate(backs)]


def _is_front(img: np.ndarray) -> bool:
    return bool(np.median(img) < DARK)


def _is_back(img: np.ndarray) -> bool:
    return bool(np.median(img) > PAPER)


@pytest.mark.parametrize("dpi", [150, 300])
@pytest.mark.parametrize("expect_front_first", [None, True, False])
def test_fronts_and_backs_are_found_whatever_the_page_order(
    dpi: int, expect_front_first: bool | None
) -> None:
    sheets = _sheets(WRITTEN, IMPRINT_ONLY, dpi=dpi)
    for order in ((True, True), (False, False), (True, False), (False, True)):
        pages, loader = batch(sheets, order, dpi)
        photos = assemble_photos(
            pages,
            duplex=True,
            back_policy=BackPolicy.ALWAYS,
            expect_front_first=expect_front_first,
            loader=loader,
        )
        assert len(photos) == 2
        for index, photo in enumerate(photos):
            front_page, back_page = photo.source_pages
            assert page_number(front_page) == 2 * index + (1 if order[index] else 2)
            assert page_number(back_page) == 2 * index + (2 if order[index] else 1)
            assert _is_front(photo.front)
            assert photo.back is not None
            assert _is_back(photo.back)
            assert photo.dpi == dpi


def test_photo_indices_and_source_pages_follow_the_batch() -> None:
    sheets = _sheets(WRITTEN, BLANK, IMPRINT_ONLY)
    pages, loader = batch(sheets, (False, False, False), DPI)
    photos = assemble_photos(pages, duplex=True, loader=loader)
    assert [p.index for p in photos] == [0, 1, 2]
    assert [tuple(map(page_number, p.source_pages)) for p in photos] == [(2, 1), (4, 3), (6, 5)]


def test_front_and_back_come_out_the_size_of_the_photo() -> None:
    sheets = _sheets(WRITTEN)
    pages, loader = batch(sheets, (False,), DPI)
    (photo,) = assemble_photos(pages, duplex=True, back_policy=BackPolicy.ALWAYS, loader=loader)
    _, front_box = sheets[0][0]
    tolerance = mm_to_px(2, DPI)
    assert photo.front.shape[1] == pytest.approx(front_box.w, abs=tolerance)
    assert photo.front.shape[0] == pytest.approx(front_box.h, abs=tolerance)
    assert photo.back is not None
    assert photo.back.shape[:2] == pytest.approx(photo.front.shape[:2], abs=tolerance)


# --- back writing and back policy ------------------------------------------------------------


def test_back_writing_is_reported_per_photo() -> None:
    sheets = _sheets(WRITTEN, IMPRINT_ONLY, BLANK)
    pages, loader = batch(sheets, (False, True, False), DPI)
    photos = assemble_photos(pages, duplex=True, loader=loader)
    assert [p.back_has_writing for p in photos] == [True, False, False]


def test_auto_keeps_only_backs_with_writing() -> None:
    sheets = _sheets(WRITTEN, IMPRINT_ONLY, BLANK)
    pages, loader = batch(sheets, (False, False, False), DPI)
    photos = assemble_photos(pages, duplex=True, back_policy=BackPolicy.AUTO, loader=loader)
    assert [p.back is not None for p in photos] == [True, False, False]


def test_always_keeps_every_back_and_never_keeps_none() -> None:
    sheets = _sheets(WRITTEN, BLANK)
    pages, loader = batch(sheets, (False, False), DPI)
    always = assemble_photos(pages, duplex=True, back_policy=BackPolicy.ALWAYS, loader=loader)
    never = assemble_photos(pages, duplex=True, back_policy=BackPolicy.NEVER, loader=loader)
    assert all(p.back is not None for p in always)
    assert all(p.back is None for p in never)
    assert [p.back_has_writing for p in never] == [True, False]  # detection still reported


def test_a_dropped_back_still_lists_its_page_as_a_source() -> None:
    pages, loader = batch(_sheets(BLANK), (False,), DPI)
    (photo,) = assemble_photos(pages, duplex=True, back_policy=BackPolicy.NEVER, loader=loader)
    assert tuple(map(page_number, photo.source_pages)) == (2, 1)


# --- hard cases: bright fronts and ties ------------------------------------------------------


@pytest.mark.parametrize("expect_front_first", [None, True, False])
def test_snow_bright_front_is_found_by_score_even_against_the_page_order(
    expect_front_first: bool | None,
) -> None:
    """A flat grey-220 front is nearly the scanner background, so its own box is not found."""
    sheet = make_duplex_sheet(dpi=DPI, front={"photo_rgb": (220, 220, 220)}, back=WRITTEN)
    pages, loader = batch([sheet], (False,), DPI)  # parity says back first; so does the score
    (photo,) = assemble_photos(
        pages,
        duplex=True,
        back_policy=BackPolicy.ALWAYS,
        expect_front_first=expect_front_first,
        loader=loader,
    )
    assert tuple(map(page_number, photo.source_pages)) == (2, 1)
    assert np.median(photo.front) == pytest.approx(220, abs=3)
    _, truth = sheet[0]
    assert photo.front.shape[1] == pytest.approx(truth.w, abs=mm_to_px(2, DPI))


def test_snow_front_scanned_first_is_still_the_front() -> None:
    sheet = make_duplex_sheet(dpi=DPI, front={"photo_rgb": (220, 220, 220)}, back=BLANK)
    pages, loader = batch([sheet], (True,), DPI)
    (photo,) = assemble_photos(pages, duplex=True, back_policy=BackPolicy.ALWAYS, loader=loader)
    assert tuple(map(page_number, photo.source_pages)) == (1, 2)


@pytest.mark.parametrize("front_first", [True, False])
def test_tie_falls_back_to_the_expected_parity_and_is_logged(
    front_first: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """A near-white front scores like a back: the two sides look alike."""
    sheet = make_duplex_sheet(dpi=DPI, front={"photo_rgb": (245, 245, 245)}, back=BLANK)
    pages, loader = batch([sheet], (front_first,), DPI)
    with caplog.at_level(logging.INFO, logger=SIDES_LOGGER):
        (photo,) = assemble_photos(
            pages,
            duplex=True,
            back_policy=BackPolicy.ALWAYS,
            expect_front_first=front_first,
            loader=loader,
        )
    assert page_number(photo.source_pages[0]) == (1 if front_first else 2)
    assert any("parity" in r.getMessage() for r in caplog.records)


def test_tie_without_an_expectation_is_an_error_naming_the_setting() -> None:
    sheet = make_duplex_sheet(dpi=DPI, front={"photo_rgb": (245, 245, 245)}, back=BLANK)
    pages, loader = batch([sheet], (False,), DPI)
    with pytest.raises(BatchError, match="expect_front_first"):
        assemble_photos(pages, duplex=True, expect_front_first=None, loader=loader)


def test_a_clear_decision_logs_no_parity_fallback(caplog: pytest.LogCaptureFixture) -> None:
    pages, loader = batch(_sheets(WRITTEN), (False,), DPI)
    with caplog.at_level(logging.DEBUG, logger=SIDES_LOGGER):
        assemble_photos(pages, duplex=True, expect_front_first=True, loader=loader)
    assert not any("parity" in r.getMessage() for r in caplog.records)


# --- odd counts, simplex, errors --------------------------------------------------------------


def test_odd_page_count_in_a_duplex_batch_is_an_error() -> None:
    pages, loader = batch(_sheets(BLANK, BLANK), (False, False), DPI)
    with pytest.raises(BatchError, match="odd"):
        assemble_photos(pages[:3], duplex=True, loader=loader)


def test_odd_page_error_is_raised_when_the_iterator_is_created_not_consumed() -> None:
    pages, loader = batch(_sheets(BLANK), (False,), DPI)
    with pytest.raises(BatchError, match="odd"):
        iter_photos(pages[:1], duplex=True, loader=loader)


def test_allow_odd_treats_the_last_page_as_a_front_without_a_back() -> None:
    sheets = _sheets(WRITTEN, BLANK)
    pages, loader = batch(sheets, (False, False), DPI)
    photos = assemble_photos(pages[:3], duplex=True, allow_odd=True, loader=loader)
    assert len(photos) == 2
    last = photos[1]
    assert last.back is None
    assert not last.back_has_writing
    assert tuple(map(page_number, last.source_pages)) == (3,)
    assert photos[0].back is not None


def test_simplex_batches_are_all_fronts_and_odd_counts_are_fine() -> None:
    fronts = [make_frame(dpi=DPI, side="front", rng_seed=s)[0] for s in range(3)]
    pages = [Path(f"page-{i + 1:03d}.png") for i in range(3)]
    frames = {path: (frame, DPI) for path, frame in zip(pages, fronts, strict=True)}
    photos = assemble_photos(pages, duplex=False, loader=lambda path: frames[path])
    assert [p.index for p in photos] == [0, 1, 2]
    assert all(p.back is None and not p.back_has_writing for p in photos)
    assert all(_is_front(p.front) for p in photos)
    assert [tuple(map(page_number, p.source_pages)) for p in photos] == [(1,), (2,), (3,)]


def test_no_pages_give_no_photos() -> None:
    assert assemble_photos([], duplex=True) == ()
    assert assemble_photos([], duplex=False) == ()


def test_sheet_without_any_photo_is_an_error_naming_the_sheet() -> None:
    blank = background_only(DPI)
    pages = [Path("page-001.png"), Path("page-002.png")]
    with pytest.raises(BatchError, match=r"sheet 1.*no photo"):
        assemble_photos(pages, duplex=True, loader=lambda _: (blank, DPI))


def test_pages_of_one_sheet_must_share_a_resolution() -> None:
    sheet = _sheets(BLANK)[0]
    (front, _), (back, _) = sheet
    frames = {Path("page-001.png"): (back, 150), Path("page-002.png"): (front, 300)}
    with pytest.raises(BatchError, match="dpi"):
        assemble_photos(list(frames), duplex=True, loader=lambda path: frames[path])


def test_iter_photos_loads_one_sheet_at_a_time() -> None:
    pages, loader = batch(_sheets(WRITTEN, BLANK, BLANK), (False, False, False), DPI)
    loaded: list[Path] = []

    def counting(path: Path):
        loaded.append(path)
        return loader(path)

    photos = iter_photos(pages, duplex=True, loader=counting)
    assert loaded == []
    first = next(photos)
    assert len(loaded) == 2
    assert first.index == 0
    next(photos)
    assert len(loaded) == 4


def test_default_loader_reads_png_files_with_their_dpi(tmp_path: Path) -> None:
    sheets = _sheets(WRITTEN)
    pages, loader = batch(sheets, (False,), DPI)
    for path in pages:
        frame, dpi = loader(path)
        Image.fromarray(frame).save(tmp_path / path.name, dpi=(dpi, dpi))
    (photo,) = assemble_photos([tmp_path / p.name for p in pages], duplex=True)
    assert photo.dpi == DPI
    assert photo.back_has_writing
    assert photo.back is not None


def test_photo_is_immutable_and_hashable() -> None:
    pages, loader = batch(_sheets(BLANK), (False,), DPI)
    (photo,) = assemble_photos(pages, duplex=True, loader=loader)
    assert isinstance(photo, Photo)
    with pytest.raises(AttributeError):
        photo.index = 5  # type: ignore[misc]
    assert isinstance(hash(photo), int)


def test_photos_do_not_alias_the_loaded_pages() -> None:
    sheets = _sheets(WRITTEN)
    pages, loader = batch(sheets, (False,), DPI)
    page_arrays = [loader(p)[0] for p in pages]
    (photo,) = assemble_photos(pages, duplex=True, back_policy=BackPolicy.ALWAYS, loader=loader)
    assert photo.back is not None
    assert not any(np.shares_memory(photo.front, a) for a in page_arrays)
    assert not any(np.shares_memory(photo.back, a) for a in page_arrays)
