"""One bad sheet in a batch: raise (and end the iterator) or report it and carry on."""

import logging
from pathlib import Path

import pytest

from fastfoto_linux.pipeline import sides
from fastfoto_linux.pipeline.sides import BackPolicy, BatchError, assemble_photos, iter_photos
from tests.crop_helpers import background_only
from tests.sides_helpers import SIDES_LOGGER, Loader, batch, page_number
from tests.synth import make_duplex_sheet, make_frame

DPI = 150
BLANK = {"imprint": False}


def _four_sheets() -> tuple[list[Path], Loader]:
    sheets = [make_duplex_sheet(dpi=DPI, rng_seed=10 * i, back=BLANK) for i in range(4)]
    return batch(sheets, (False,) * 4, DPI)


def _truncated_page(loader: Loader, bad: int) -> Loader:
    """The loader, except that page number ``bad`` fails the way a truncated file does."""

    def load(path: Path):
        if page_number(path) == bad:
            raise OSError("image file is truncated")
        return loader(path)

    return load


def test_without_a_callback_the_error_is_raised_and_the_iterator_ends() -> None:
    pages, loader = _four_sheets()
    photos = iter_photos(pages, duplex=True, loader=_truncated_page(loader, 3))
    assert next(photos).index == 0
    with pytest.raises(BatchError, match=r"sheet 2.*page-003\.png.*truncated") as caught:
        next(photos)
    assert caught.value.sheet == 2
    with pytest.raises(StopIteration):  # a generator is finished once an error left it
        next(photos)


def test_a_corrupt_middle_sheet_goes_to_the_callback_and_the_other_sheets_still_come(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pages, loader = _four_sheets()
    errors: list[BatchError] = []
    with caplog.at_level(logging.ERROR, logger=SIDES_LOGGER):
        photos = list(
            iter_photos(
                pages, duplex=True, loader=_truncated_page(loader, 3), on_sheet_error=errors.append
            )
        )
    assert [e.sheet for e in errors] == [2]
    assert "page-003.png" in str(errors[0])
    assert [p.index for p in photos] == [0, 2, 3]  # the index is the sheet's place in the batch
    assert [tuple(map(page_number, p.source_pages)) for p in photos] == [(2, 1), (6, 5), (8, 7)]
    assert any("sheet 2" in r.getMessage() for r in caplog.records)


def test_assemble_photos_returns_the_surviving_photos_and_reports_each_failure() -> None:
    pages, loader = _four_sheets()
    errors: list[BatchError] = []
    failing = _truncated_page(_truncated_page(loader, 3), 8)
    photos = assemble_photos(pages, duplex=True, loader=failing, on_sheet_error=errors.append)
    assert [p.index for p in photos] == [0, 2]
    assert [e.sheet for e in errors] == [2, 4]


def test_the_callback_sees_a_sheet_without_any_photo_too() -> None:
    pages, loader = _four_sheets()
    blank = background_only(DPI)
    errors: list[BatchError] = []

    def load(path: Path):
        return (blank, DPI) if page_number(path) in (3, 4) else loader(path)

    photos = assemble_photos(pages, duplex=True, loader=load, on_sheet_error=errors.append)
    assert [e.sheet for e in errors] == [2]
    assert len(photos) == 3


def _crash_second_crop(monkeypatch: pytest.MonkeyPatch) -> None:
    real, calls = sides.crop, []

    def flaky(frame, box):
        calls.append(box)
        if len(calls) == 2:
            raise ValueError("box lies outside the frame")
        return real(frame, box)

    monkeypatch.setattr(sides, "crop", flaky)


def test_a_crop_failure_names_the_sheet(monkeypatch: pytest.MonkeyPatch) -> None:
    pages, loader = _four_sheets()
    _crash_second_crop(monkeypatch)  # NEVER crops only the front: the second crop is sheet 2's
    with pytest.raises(BatchError, match=r"sheet 2.*outside the frame") as caught:
        assemble_photos(pages, duplex=True, back_policy=BackPolicy.NEVER, loader=loader)
    assert caught.value.sheet == 2
    assert isinstance(caught.value.__cause__, ValueError)


def test_a_crop_failure_goes_to_the_callback_too(monkeypatch: pytest.MonkeyPatch) -> None:
    pages, loader = _four_sheets()
    _crash_second_crop(monkeypatch)
    errors: list[BatchError] = []
    photos = assemble_photos(
        pages,
        duplex=True,
        back_policy=BackPolicy.NEVER,
        loader=loader,
        on_sheet_error=errors.append,
    )
    assert [e.sheet for e in errors] == [2]
    assert [p.index for p in photos] == [0, 2, 3]


def test_simplex_and_dangling_pages_use_the_callback_as_well() -> None:
    fronts = {
        Path(f"page-{n:03d}.png"): (make_frame(dpi=DPI, side="front")[0], DPI) for n in (1, 2, 3)
    }

    def load(path: Path):
        if page_number(path) == 2:
            raise OSError("disk gone")
        return fronts[path]

    errors: list[BatchError] = []
    photos = assemble_photos(list(fronts), duplex=False, loader=load, on_sheet_error=errors.append)
    assert [p.index for p in photos] == [0, 2]
    assert [e.sheet for e in errors] == [2]

    pages, loader = _four_sheets()
    errors.clear()
    photos = assemble_photos(
        pages[:3],
        duplex=True,
        allow_odd=True,
        loader=_truncated_page(loader, 3),
        on_sheet_error=errors.append,
    )
    assert [p.index for p in photos] == [0]
    assert [e.sheet for e in errors] == [2]
