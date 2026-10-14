"""Pairing pages into photos: which side is the front, back policies, odd and simplex batches."""

import logging
import weakref
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
NOTE = {"note": True, "imprint": False}
IMPRINT_ONLY = {"imprint": True}
BLANK = {"imprint": False}
PALE = (185, 185, 185)  # a pale print: its own crop works, but it is not paper
SNOW = (220, 220, 220)  # as bright as paper and nearly the scanner background: no crop of its own
NEAR_WHITE = (245, 245, 245)  # a front that scores exactly like a back
CREAM = (235, 228, 210)


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


# --- hard cases: pale fronts, cream backs and ties ---------------------------------------------


@pytest.mark.parametrize("expect_front_first", [None, True, False])
def test_pale_front_is_found_by_score_even_against_the_page_order(
    expect_front_first: bool | None,
) -> None:
    sheet = make_duplex_sheet(dpi=DPI, front={"photo_rgb": PALE}, back=WRITTEN)
    pages, loader = batch([sheet], (False,), DPI)  # parity says back first; so does the score
    (photo,) = assemble_photos(
        pages,
        duplex=True,
        back_policy=BackPolicy.ALWAYS,
        expect_front_first=expect_front_first,
        loader=loader,
    )
    assert tuple(map(page_number, photo.source_pages)) == (2, 1)
    assert np.median(photo.front) == pytest.approx(185, abs=3)
    assert photo.side_uncertain == (expect_front_first is True)  # only that one contradicts it


def test_cream_back_against_a_bright_front_is_decided_by_content_not_parity() -> None:
    """Cream paper must score as paper: parity here points the wrong way, and NEVER would then
    drop the real photo."""
    sheet = make_duplex_sheet(
        dpi=DPI, front={"photo_rgb": PALE}, back={"photo_rgb": CREAM, "imprint": False}
    )
    pages, loader = batch([sheet], (False,), DPI)
    (photo,) = assemble_photos(pages, duplex=True, back_policy=BackPolicy.NEVER, loader=loader)
    assert tuple(map(page_number, photo.source_pages)) == (2, 1)
    assert np.median(photo.front) == pytest.approx(185, abs=3)
    assert not photo.side_uncertain


def test_snow_front_has_no_crop_of_its_own_and_scores_as_paper_so_the_sheet_is_uncertain() -> None:
    sheet = make_duplex_sheet(dpi=DPI, front={"photo_rgb": SNOW}, back=WRITTEN)
    pages, loader = batch([sheet], (False,), DPI)
    (photo,) = assemble_photos(
        pages, duplex=True, back_policy=BackPolicy.NEVER, expect_front_first=False, loader=loader
    )
    assert photo.side_uncertain
    assert photo.back is not None  # an uncertain sheet keeps its back whatever the policy
    assert tuple(map(page_number, photo.source_pages)) == (2, 1)  # the expected parity decided
    assert np.median(photo.front) == pytest.approx(220, abs=3)
    _, truth = sheet[0]
    assert photo.front.shape[1] == pytest.approx(truth.w, abs=mm_to_px(2, DPI))


def _tie_sheet():
    """A near-white front: it scores like its back, so content cannot tell the sides apart."""
    return make_duplex_sheet(dpi=DPI, front={"photo_rgb": NEAR_WHITE}, back=BLANK)


@pytest.mark.parametrize("front_first", [True, False])
def test_tie_falls_back_to_the_expected_parity_and_is_logged(
    front_first: bool, caplog: pytest.LogCaptureFixture
) -> None:
    pages, loader = batch([_tie_sheet()], (front_first,), DPI)
    with caplog.at_level(logging.INFO, logger=SIDES_LOGGER):
        (photo,) = assemble_photos(
            pages,
            duplex=True,
            back_policy=BackPolicy.ALWAYS,
            expect_front_first=front_first,
            loader=loader,
        )
    assert page_number(photo.source_pages[0]) == (1 if front_first else 2)
    assert photo.side_uncertain
    assert any("parity" in r.getMessage() for r in caplog.records)


def test_tie_on_the_first_sheet_without_any_hint_still_returns_the_photo(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pages, loader = batch([_tie_sheet()], (False,), DPI)
    with caplog.at_level(logging.INFO, logger=SIDES_LOGGER):
        (photo,) = assemble_photos(pages, duplex=True, back_policy=BackPolicy.NEVER, loader=loader)
    assert photo.side_uncertain
    assert photo.back is not None  # never dropped when the sides are uncertain
    assert tuple(map(page_number, photo.source_pages)) == (1, 2)  # no hint at all: first = front
    assert any("parity" in r.getMessage() for r in caplog.records)


def _mixed_batch(order: tuple[bool, bool, bool]):
    """Two clear sheets and, third, a tie sheet; ``order`` says front-first per sheet."""
    sheets = [*_sheets(WRITTEN, IMPRINT_ONLY), _tie_sheet()]
    return batch(sheets, order, DPI)


def test_tie_mid_batch_follows_the_parity_the_batch_has_shown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pages, loader = _mixed_batch((False, False, False))
    with caplog.at_level(logging.INFO, logger=SIDES_LOGGER):
        photos = assemble_photos(pages, duplex=True, back_policy=BackPolicy.NEVER, loader=loader)
    assert [p.side_uncertain for p in photos] == [False, False, True]
    assert tuple(map(page_number, photos[2].source_pages)) == (6, 5)
    assert photos[2].back is not None  # ... but not of an uncertain one
    assert photos[0].back is None  # NEVER drops the backs of confident sheets ...
    assert photos[1].back is None
    assert any("majority" in r.getMessage() for r in caplog.records)


def test_tie_mid_batch_follows_a_front_first_batch_too() -> None:
    pages, loader = _mixed_batch((True, True, True))
    photos = assemble_photos(pages, duplex=True, loader=loader)
    assert tuple(map(page_number, photos[2].source_pages)) == (5, 6)


def test_a_wrong_majority_guess_still_keeps_both_images() -> None:
    pages, loader = _mixed_batch((False, False, True))  # the tie sheet breaks the batch's habit
    photos = assemble_photos(pages, duplex=True, back_policy=BackPolicy.NEVER, loader=loader)
    last = photos[2]
    assert last.side_uncertain
    assert tuple(map(page_number, last.source_pages)) == (6, 5)  # a guess, flagged
    assert last.back is not None
    assert last.front.shape[:2] == pytest.approx(last.back.shape[:2], abs=mm_to_px(2, DPI))


def test_expected_parity_overrides_the_batch_majority() -> None:
    pages, loader = _mixed_batch((False, False, False))
    photos = assemble_photos(pages, duplex=True, expect_front_first=True, loader=loader)
    assert tuple(map(page_number, photos[2].source_pages)) == (5, 6)
    assert photos[2].side_uncertain


def test_an_even_split_of_resolved_sheets_falls_back_to_front_first() -> None:
    sheets = [*_sheets(WRITTEN, IMPRINT_ONLY), _tie_sheet()]
    pages, loader = batch(sheets, (True, False, False), DPI)
    photos = assemble_photos(pages, duplex=True, loader=loader)
    assert tuple(map(page_number, photos[2].source_pages)) == (5, 6)


def test_uncertain_sheets_do_not_count_towards_the_majority() -> None:
    sheets = [_tie_sheet(), *_sheets(WRITTEN), _tie_sheet()]
    pages, loader = batch(sheets, (True, False, False), DPI)
    photos = assemble_photos(pages, duplex=True, loader=loader)
    assert [p.side_uncertain for p in photos] == [True, False, True]
    assert tuple(map(page_number, photos[0].source_pages)) == (1, 2)  # nothing resolved yet
    assert tuple(map(page_number, photos[2].source_pages)) == (6, 5)  # one back-first sheet


def test_content_contradicting_the_expected_parity_is_logged_and_flags_the_sheet(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pages, loader = batch(_sheets(WRITTEN), (False,), DPI)
    with caplog.at_level(logging.INFO, logger=SIDES_LOGGER):
        (photo,) = assemble_photos(pages, duplex=True, expect_front_first=True, loader=loader)
    assert tuple(map(page_number, photo.source_pages)) == (2, 1)  # content wins
    assert photo.side_uncertain
    assert any("contradict" in r.getMessage() for r in caplog.records)


def test_content_agreeing_with_the_expected_parity_logs_no_contradiction(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pages, loader = batch(_sheets(WRITTEN), (False,), DPI)
    with caplog.at_level(logging.DEBUG, logger=SIDES_LOGGER):
        assemble_photos(pages, duplex=True, expect_front_first=False, loader=loader)
    assert not any("contradict" in r.getMessage() for r in caplog.records)


def test_a_clear_decision_logs_no_parity_fallback(caplog: pytest.LogCaptureFixture) -> None:
    pages, loader = batch(_sheets(WRITTEN), (False,), DPI)
    with caplog.at_level(logging.DEBUG, logger=SIDES_LOGGER):
        assemble_photos(pages, duplex=True, expect_front_first=True, loader=loader)
    assert not any("parity" in r.getMessage() for r in caplog.records)


def test_short_dated_notes_keep_the_back_under_auto() -> None:
    sheets = [make_duplex_sheet(dpi=DPI, back=NOTE), make_duplex_sheet(dpi=DPI, back=IMPRINT_ONLY)]
    pages, loader = batch(sheets, (False, False), DPI)
    photos = assemble_photos(pages, duplex=True, back_policy=BackPolicy.AUTO, loader=loader)
    assert [p.back_has_writing for p in photos] == [True, False]
    assert [p.back is not None for p in photos] == [True, False]


def test_back_writing_evidence_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    pages, loader = batch([make_duplex_sheet(dpi=DPI, back=NOTE)], (False,), DPI)
    with caplog.at_level(logging.INFO, logger=SIDES_LOGGER):
        assemble_photos(pages, duplex=True, loader=loader)
    messages = [r.getMessage() for r in caplog.records]
    assert any("2 candidate" in m and "2 pen stroke" in m for m in messages)


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


def test_simplex_page_without_a_photo_is_an_error_naming_the_page() -> None:
    blank = background_only(DPI)
    with pytest.raises(BatchError, match=r"page-001\.png.*no photo"):
        assemble_photos([Path("page-001.png")], duplex=False, loader=lambda _: (blank, DPI))


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


# --- memory, loader errors and dangling pages ------------------------------------------------


def test_at_most_one_sheet_of_frames_is_alive_at_a_time() -> None:
    sheets = _sheets(WRITTEN, BLANK, IMPRINT_ONLY, WRITTEN)
    pages, loader = batch(sheets, (False,) * 4, DPI)
    alive, peak = 0, 0

    def released() -> None:
        nonlocal alive
        alive -= 1

    def counting(path: Path):
        nonlocal alive, peak
        frame, dpi = loader(path)
        fresh = frame.copy()
        weakref.finalize(fresh, released)
        alive += 1
        peak = max(peak, alive)
        return fresh, dpi

    photos = list(iter_photos(pages, duplex=True, loader=counting))
    assert len(photos) == 4
    assert peak <= 2, f"{peak} full frames were alive at once"
    assert alive == 0


def test_loader_failure_names_the_sheet_and_the_page() -> None:
    pages, loader = batch(_sheets(BLANK, BLANK), (False, False), DPI)

    def failing(path: Path):
        if page_number(path) == 4:
            raise ValueError("file has no dpi metadata")
        return loader(path)

    with pytest.raises(BatchError, match=r"sheet 2.*page-004\.png.*no dpi metadata") as caught:
        assemble_photos(pages, duplex=True, loader=failing)
    assert isinstance(caught.value.__cause__, ValueError)


def test_simplex_loader_failure_names_the_page() -> None:
    def failing(path: Path):
        raise OSError("disk gone")

    with pytest.raises(BatchError, match=r"sheet 1.*page-001\.png.*disk gone"):
        assemble_photos([Path("page-001.png")], duplex=False, loader=failing)


def test_dangling_page_that_looks_like_a_back_is_flagged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pages, loader = batch(_sheets(BLANK, BLANK), (False, False), DPI)
    with caplog.at_level(logging.WARNING, logger=SIDES_LOGGER):
        photos = assemble_photos(pages[:3], duplex=True, allow_odd=True, loader=loader)
    assert photos[1].side_uncertain  # page 3 is a back, so its front is missing
    assert photos[1].back is None
    assert not photos[0].side_uncertain
    assert any("looks like a back" in r.getMessage() for r in caplog.records)


def test_dangling_page_that_looks_like_a_front_is_not_flagged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pages, loader = batch(_sheets(BLANK, BLANK), (False, True), DPI)  # sheet 2: front first
    with caplog.at_level(logging.WARNING, logger=SIDES_LOGGER):
        photos = assemble_photos(pages[:3], duplex=True, allow_odd=True, loader=loader)
    assert not photos[1].side_uncertain
    assert not [r for r in caplog.records if r.name == SIDES_LOGGER]


def test_confident_photos_are_not_marked_uncertain() -> None:
    pages, loader = batch(_sheets(WRITTEN, BLANK), (False, True), DPI)
    assert not any(p.side_uncertain for p in assemble_photos(pages, duplex=True, loader=loader))
    fronts = {Path("page-001.png"): (make_frame(dpi=DPI, side="front")[0], DPI)}
    (photo,) = assemble_photos(list(fronts), duplex=False, loader=lambda path: fronts[path])
    assert not photo.side_uncertain
