"""``ffscan process`` over the private 8-page duplex batch. Counts and booleans only (never CI)."""

import contextlib
import io
import re
from dataclasses import dataclass
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
ENHANCED = re.compile(r"FastFoto_(\d{4})_a\.jpg")
SUMMARY_ENHANCED = re.compile(r"^enhanced: (\d+)(?: \((\d+) unchanged\))?$", re.MULTILINE)
# The private batch is fixed: restore changes three of the four fronts and leaves one as it was.
FRONTS = 4
BACKS = 2
ENHANCED_FRONTS = 3
UNCHANGED_FRONTS = 1
JPEGS = FRONTS + BACKS + ENHANCED_FRONTS


@dataclass(frozen=True)
class Album:
    code: int
    out: Path
    summary: str


@pytest.fixture(scope="module")
def album(tmp_path_factory) -> Album:
    pages = sorted(REAL_SCANS_DIR.glob("photo-*.png"))
    assert len(pages) == EXPECTED_PAGES, f"expected {EXPECTED_PAGES} pages, found {len(pages)}"
    out = tmp_path_factory.mktemp("album")
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(["process", *map(str, pages), "--out", str(out), "--date", DATE])
    return Album(code, out, stdout.getvalue())


def _numbers(out: Path, pattern: re.Pattern[str]) -> list[str]:
    return sorted(m.group(1) for p in out.iterdir() if (m := pattern.fullmatch(p.name)))


def test_the_run_succeeds(album) -> None:
    assert album.code == 0


def test_four_fronts_are_written_and_named(album) -> None:
    assert _numbers(album.out, ORIGINAL) == ["0001", "0002", "0003", "0004"]


def test_only_the_handwritten_backs_of_sheets_3_and_4_are_kept(album) -> None:
    assert _numbers(album.out, BACK) == ["0003", "0004"]


def test_the_summary_reports_the_two_dropped_backs(album) -> None:
    assert "backs dropped: 2 (" in album.summary


def test_three_fronts_have_an_enhanced_copy_and_one_is_reported_unchanged(album) -> None:
    match = SUMMARY_ENHANCED.search(album.summary)
    assert match is not None, "the summary has no 'enhanced: N' line"
    enhanced = _numbers(album.out, ENHANCED)
    assert len(enhanced) == ENHANCED_FRONTS == int(match.group(1))
    assert int(match.group(2) or 0) == UNCHANGED_FRONTS
    assert set(enhanced) <= set(_numbers(album.out, ORIGINAL))


def test_the_album_holds_exactly_the_expected_files(album) -> None:
    assert len(list(album.out.glob("*.jpg"))) == JPEGS
    assert len(list(album.out.iterdir())) == JPEGS + 1  # and the writer's lock file


def test_the_front_of_page_2_is_turned_upright(album) -> None:
    sizes = {}
    for number in ("0001", "0002", "0003", "0004"):
        with Image.open(album.out / f"FastFoto_{number}.jpg") as image:
            sizes[number] = image.size
    portrait = {n for n, (width, height) in sizes.items() if height > width}
    assert portrait == {"0001"}  # page 2 is scanned sideways; the others are upright


def test_every_jpeg_carries_the_date(album) -> None:
    jpegs = sorted(album.out.glob("*.jpg"))
    assert jpegs
    assert {original_date(p) for p in jpegs} == {EXIF_DATE}
