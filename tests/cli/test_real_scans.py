"""``ffscan process`` over the private 8-page duplex batch. Counts and booleans only (never CI)."""

import re
from pathlib import Path

import pytest
from PIL import Image

from fastfoto_linux.cli import main
from tests.conftest import REAL_SCANS_DIR
from tests.process_helpers import original_date

pytestmark = pytest.mark.real_scans

EXPECTED_PAGES = 8
DATE = "1975-06"
EXIF_DATE = "1975:06:01 00:00:00"
ORIGINAL = re.compile(r"FastFoto_(\d{4})\.jpg")
BACK = re.compile(r"FastFoto_(\d{4})_b\.jpg")


@pytest.fixture(scope="module")
def album(tmp_path_factory) -> tuple[int, Path]:
    pages = sorted(REAL_SCANS_DIR.glob("photo-*.png"))
    assert len(pages) == EXPECTED_PAGES, f"expected {EXPECTED_PAGES} pages, found {len(pages)}"
    out = tmp_path_factory.mktemp("album")
    code = main(["process", *map(str, pages), "--out", str(out), "--date", DATE])
    return code, out


def _numbers(out: Path, pattern: re.Pattern[str]) -> list[str]:
    return sorted(m.group(1) for p in out.iterdir() if (m := pattern.fullmatch(p.name)))


def test_the_run_succeeds(album) -> None:
    assert album[0] == 0


def test_four_fronts_are_written_and_named(album) -> None:
    assert _numbers(album[1], ORIGINAL) == ["0001", "0002", "0003", "0004"]


def test_only_the_handwritten_backs_of_sheets_3_and_4_are_kept(album) -> None:
    assert _numbers(album[1], BACK) == ["0003", "0004"]


def test_the_front_of_page_2_is_turned_upright(album) -> None:
    sizes = {}
    for number in ("0001", "0002", "0003", "0004"):
        with Image.open(album[1] / f"FastFoto_{number}.jpg") as image:
            sizes[number] = image.size
    portrait = {n for n, (width, height) in sizes.items() if height > width}
    assert portrait == {"0001"}  # page 2 is scanned sideways; the others are upright


def test_every_jpeg_carries_the_date(album) -> None:
    jpegs = sorted(album[1].glob("*.jpg"))
    assert len(jpegs) >= 6
    assert {original_date(p) for p in jpegs} == {EXIF_DATE}
