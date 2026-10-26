"""``--cleanup`` on page files: the level reaches the PDF without a second read of the pages."""

from pathlib import Path

import numpy as np
import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.modes import ColourMode
from tests.cli.doc_cleanup_helpers import (
    LIGHT,
    OCR_OFF,
    OFF,
    STRONG,
    EncoderSpy,
    expected_pixels,
    shaded_pages,
)

pytestmark = pytest.mark.usefixtures("no_real_ocr")


@pytest.fixture
def pages(tmp_path: Path) -> list[Path]:
    return shaded_pages(tmp_path / "raw")


def make(out: Path, pages: list[Path], *extra: str) -> int:
    out.mkdir(exist_ok=True)
    return main(["doc", "process", *map(str, pages), "--out", str(out), *OCR_OFF, *extra])


def test_the_strong_level_is_what_the_page_is_written_with(pages, tmp_path, monkeypatch) -> None:
    spy = EncoderSpy(monkeypatch)
    assert make(tmp_path / "a", pages, "--colour", "grey", "--cleanup", "strong") == 0
    assert len(spy.jpegs) == 1
    assert np.array_equal(spy.jpegs[0], expected_pixels(pages[0], ColourMode.GREY, STRONG))
    assert not np.array_equal(spy.jpegs[0], expected_pixels(pages[0], ColourMode.GREY, OFF))


def test_the_light_level_differs_from_strong(pages, tmp_path, monkeypatch) -> None:
    spy = EncoderSpy(monkeypatch)
    assert make(tmp_path / "a", pages, "--colour", "grey", "--cleanup", "light") == 0
    assert np.array_equal(spy.jpegs[0], expected_pixels(pages[0], ColourMode.GREY, LIGHT))
    assert not np.array_equal(spy.jpegs[0], expected_pixels(pages[0], ColourMode.GREY, STRONG))


def test_without_the_flag_the_page_is_not_cleaned(pages, tmp_path, monkeypatch) -> None:
    spy = EncoderSpy(monkeypatch)
    assert make(tmp_path / "a", pages, "--colour", "grey") == 0
    assert np.array_equal(spy.jpegs[0], expected_pixels(pages[0], ColourMode.GREY, OFF))


def test_an_explicit_off_is_the_same_as_the_flag_left_out(pages, tmp_path, monkeypatch) -> None:
    spy = EncoderSpy(monkeypatch)
    assert make(tmp_path / "a", pages, "--colour", "grey", "--cleanup", "off") == 0
    assert np.array_equal(spy.jpegs[0], expected_pixels(pages[0], ColourMode.GREY, OFF))


@pytest.mark.parametrize(
    "edit", [[], ["--page-colour", "1:grey"]], ids=["no edit (build)", "an edit (analyse)"]
)
def test_both_paths_carry_the_level_and_neither_reads_a_page_again(
    pages, tmp_path, monkeypatch, edit
) -> None:
    spy = EncoderSpy(monkeypatch)
    assert make(tmp_path / "a", pages, "--colour", "grey", "--cleanup", "strong", *edit) == 0
    assert spy.reads == 0
    assert len(spy.jpegs) == 1
    assert np.array_equal(spy.jpegs[0], expected_pixels(pages[0], ColourMode.GREY, STRONG))


def test_a_dry_run_with_the_flag_reads_nothing_again_and_writes_nothing(
    pages, tmp_path, monkeypatch
) -> None:
    spy = EncoderSpy(monkeypatch)
    assert make(tmp_path / "a", pages, "--cleanup", "strong", "--dry-run") == 0
    assert spy.reads == 0
    assert list((tmp_path / "a").iterdir()) == []


def test_a_turned_page_is_cleaned_after_it_is_turned(pages, tmp_path, monkeypatch) -> None:
    spy = EncoderSpy(monkeypatch)
    assert (
        make(tmp_path / "a", pages, "--colour", "grey", "--cleanup", "strong", "--rotate", "1:90")
        == 0
    )
    turned = expected_pixels(pages[0], ColourMode.GREY, STRONG, PageEdit(quarter_turns=1))
    assert spy.reads == 1
    assert np.array_equal(spy.jpegs[-1], turned)
    assert spy.levels == [STRONG]


def test_black_and_white_is_unchanged_by_the_flag(pages, tmp_path, monkeypatch) -> None:
    spy = EncoderSpy(monkeypatch)
    assert make(tmp_path / "a", pages, "--colour", "bw") == 0
    assert make(tmp_path / "b", pages, "--colour", "bw", "--cleanup", "strong") == 0
    assert len(spy.g4) == 2
    assert spy.g4[0] == spy.g4[1]
    assert spy.jpegs == []
