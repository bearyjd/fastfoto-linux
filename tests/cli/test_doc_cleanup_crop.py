"""``doc process RAWDIR`` applies a crop stored in a version 4 ``review.json``; ``--fresh`` does
not. The crop and the cleanup meet in the pixels the PDF holds."""

from pathlib import Path

import numpy as np
import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.draft_edit import set_crop
from fastfoto_linux.documents.draft_store import REVIEW_FILE, read_review, save_draft
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.page_crop import PageCrop, crop_box
from tests.cli.doc_cleanup_helpers import (
    LIGHT,
    OCR_OFF,
    OFF,
    EncoderSpy,
    expected_pixels,
    pdf_page_sizes,
    raw_folder_of,
)
from tests.documents.store_helpers import analysed, store_settings

pytestmark = pytest.mark.usefixtures("no_real_ocr")

CROP = PageCrop(1000, 2000, 7000, 9000)
DPI = 300
POINTS_PER_INCH = 72


@pytest.fixture
def out(tmp_path: Path) -> Path:
    path = tmp_path / "out"
    path.mkdir()
    return path


@pytest.fixture
def raw(tmp_path: Path, out: Path) -> tuple[Path, tuple[Path, ...]]:
    """A folder of two pages whose sidecar (version 4) crops page 1."""
    folder, pages = raw_folder_of(tmp_path, count=2)
    settings = store_settings(out, duplex=False)
    save_draft(set_crop(analysed(folder, pages, settings), 1, CROP), settings)
    assert read_review(folder, pages) is not None
    return folder, pages


def run(raw: tuple[Path, tuple[Path, ...]], out: Path, *extra: str) -> list[tuple[float, float]]:
    argv = ["doc", "process", str(raw[0]), "--out", str(out), *OCR_OFF, "--colour", "grey", *extra]
    assert main(argv) == 0
    return pdf_page_sizes(out / "Document_0001.pdf")


def points(pixels: tuple[int, int]) -> tuple[float, float]:
    width, height = pixels
    return width * POINTS_PER_INCH / DPI, height * POINTS_PER_INCH / DPI


def trimmed_size(raw: tuple[Path, ...]) -> tuple[int, int]:
    height, width = expected_pixels(raw[0], ColourMode.GREY, OFF).shape[:2]
    return width, height


def cropped_size(raw: tuple[Path, ...]) -> tuple[int, int]:
    width, height = trimmed_size(raw)
    left, top, right, bottom = crop_box(width, height, DPI, CROP)
    return right - left, bottom - top


def close(actual: tuple[float, float], wanted: tuple[float, float]) -> bool:
    return all(abs(a - w) <= 1 for a, w in zip(actual, wanted, strict=True))


def test_the_stored_crop_sets_the_page_size_and_the_pixels(raw, out, monkeypatch) -> None:
    spy = EncoderSpy(monkeypatch)
    sizes = run(raw, out)
    assert close(sizes[0], points(cropped_size(raw[1])))
    assert close(sizes[1], points(trimmed_size(raw[1])))
    assert not close(sizes[0], sizes[1])
    wanted = expected_pixels(raw[1][0], ColourMode.GREY, OFF, PageEdit(crop=CROP))
    assert np.array_equal(spy.jpegs[0], wanted)


def test_a_turn_from_the_command_line_keeps_the_crop(raw, out, monkeypatch) -> None:
    spy = EncoderSpy(monkeypatch)
    sizes = run(raw, out, "--rotate", "1:90")
    width, height = cropped_size(raw[1])
    assert close(sizes[0], points((height, width)))
    wanted = expected_pixels(raw[1][0], ColourMode.GREY, OFF, PageEdit(crop=CROP, quarter_turns=1))
    assert np.array_equal(spy.jpegs[0], wanted)


def test_the_flag_cleans_the_cropped_pixels(raw, out, monkeypatch) -> None:
    spy = EncoderSpy(monkeypatch)
    sizes = run(raw, out, "--cleanup", "light")
    assert close(sizes[0], points(cropped_size(raw[1])))
    wanted = expected_pixels(raw[1][0], ColourMode.GREY, LIGHT, PageEdit(crop=CROP))
    assert np.array_equal(spy.jpegs[0], wanted)
    assert not np.array_equal(
        wanted, expected_pixels(raw[1][0], ColourMode.GREY, OFF, PageEdit(crop=CROP))
    )


def test_fresh_ignores_the_stored_crop(raw, out) -> None:
    sizes = run(raw, out, "--fresh")
    assert close(sizes[0], points(trimmed_size(raw[1])))
    assert close(sizes[1], points(trimmed_size(raw[1])))


def test_the_stored_crop_and_the_sidecar_survive_the_run(raw, out) -> None:
    sidecar = raw[0] / REVIEW_FILE
    before = (sidecar.read_bytes(), sidecar.stat().st_mtime_ns)
    run(raw, out, "--cleanup", "light")
    assert (sidecar.read_bytes(), sidecar.stat().st_mtime_ns) == before
    stored = read_review(raw[0], raw[1])
    assert stored is not None
    assert stored.draft.edits[1] == PageEdit(crop=CROP)
