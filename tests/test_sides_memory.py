"""``iter_photos`` holds one sheet at a time: the previous photo is gone before the next loads."""

import weakref

from fastfoto_linux.pipeline.sides import iter_photos
from tests.sides_helpers import batch, page_number
from tests.synth import make_duplex_sheet

DPI = 150
FIRST_PAGE_OF_SHEET_2 = 3


def test_the_previous_photo_is_released_before_the_next_sheet_is_loaded() -> None:
    sheets = [make_duplex_sheet(dpi=DPI, rng_seed=seed) for seed in (0, 1)]
    pages, loader = batch(sheets, (False, False), DPI)
    released: list[bool] = []
    refs: list[weakref.ref] = []

    def watching(path):
        if page_number(path) == FIRST_PAGE_OF_SHEET_2:
            released.append(refs[0]() is None)
        return loader(path)

    photos = iter_photos(pages, duplex=True, loader=watching)
    first = next(photos)
    refs.append(weakref.ref(first))
    del first
    next(photos)
    assert released == [True]
