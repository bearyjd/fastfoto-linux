"""Thumbnails are made by ``analyse_document(..., thumbs=dir)`` from the page already decoded."""

import os
import stat
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from fastfoto_linux.documents import analyse as analyse_module
from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.loader import load_page
from fastfoto_linux.documents.thumbs import THUMB_MAX_PX
from tests.documents.draft_helpers import LiveCounter
from tests.documents.store_helpers import raw_folder, store_settings


@pytest.fixture
def pages_and_out(tmp_path: Path) -> tuple[tuple[Path, ...], Path, Path]:
    folder, pages = raw_folder(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    return pages, out, folder


def test_every_page_gets_a_thumbnail_with_a_name_from_its_number(pages_and_out) -> None:
    pages, out, folder = pages_and_out
    draft = analyse_document(pages, store_settings(out), thumbs=folder / "thumbs", encode=False)
    names = [f"page-{n:04d}.jpg" for n in range(1, 5)]
    assert [p.thumb for p in draft.pages] == names
    assert sorted(p.name for p in (folder / "thumbs").iterdir()) == names


def test_a_thumbnail_is_a_small_jpeg_of_the_trimmed_page(pages_and_out) -> None:
    pages, out, folder = pages_and_out
    draft = analyse_document(pages, store_settings(out), thumbs=folder / "thumbs", encode=False)
    for page, path in zip(draft.pages, pages, strict=True):
        trimmed = page.trim.apply(load_page(path)).pixels
        height, width = trimmed.shape[:2]
        with Image.open(folder / "thumbs" / (page.thumb or "")) as image:
            assert image.format == "JPEG"
            assert max(image.size) == min(THUMB_MAX_PX, max(width, height))
            assert abs(image.size[0] / image.size[1] - width / height) < 0.02


@pytest.mark.parametrize("umask", [0o000, 0o077])
def test_thumbnails_are_private(pages_and_out, umask) -> None:
    pages, out, folder = pages_and_out
    previous = os.umask(umask)
    try:
        analyse_document(pages, store_settings(out), thumbs=folder / "thumbs", encode=False)
    finally:
        os.umask(previous)
    assert stat.S_IMODE((folder / "thumbs").stat().st_mode) == 0o700
    modes = {stat.S_IMODE(p.stat().st_mode) for p in (folder / "thumbs").iterdir()}
    assert modes == {0o600}


def test_thumbnails_are_the_same_bytes_every_time(pages_and_out) -> None:
    pages, out, folder = pages_and_out
    analyse_document(pages, store_settings(out), thumbs=folder / "thumbs", encode=False)
    first = {p.name: p.read_bytes() for p in (folder / "thumbs").iterdir()}
    analyse_document(pages, store_settings(out), thumbs=folder / "thumbs", encode=False)
    assert {p.name: p.read_bytes() for p in (folder / "thumbs").iterdir()} == first


def test_without_a_folder_no_thumbnail_is_made(pages_and_out) -> None:
    pages, out, folder = pages_and_out
    draft = analyse_document(pages, store_settings(out), encode=False)
    assert [p.thumb for p in draft.pages] == [None] * 4
    assert not (folder / "thumbs").exists()


def test_thumbnails_cost_no_second_decode_and_no_extra_pixels_in_memory(
    pages_and_out, monkeypatch: pytest.MonkeyPatch
) -> None:
    pages, out, folder = pages_and_out
    plain = LiveCounter()
    monkeypatch.setattr(analyse_module, "load_page", plain)
    analyse_document(pages, store_settings(out), encode=False)
    with_thumbs = LiveCounter()
    monkeypatch.setattr(analyse_module, "load_page", with_thumbs)
    analyse_document(pages, store_settings(out), thumbs=folder / "thumbs", encode=False)
    assert with_thumbs.loads == plain.loads
    assert with_thumbs.peak <= max(plain.peak, 2)


def test_a_thumbnail_that_cannot_be_written_does_not_stop_the_analysis(
    pages_and_out, tmp_path, caplog
) -> None:
    pages, out, _ = pages_and_out
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder")
    draft = analyse_document(pages, store_settings(out), thumbs=blocker / "thumbs", encode=False)
    assert [p.thumb for p in draft.pages] == [None] * 4
    assert any(r.levelname == "WARNING" for r in caplog.records)


def test_a_thumbnail_is_a_jpeg_file_a_viewer_can_open(pages_and_out) -> None:
    pages, out, folder = pages_and_out
    analyse_document(pages, store_settings(out), thumbs=folder / "thumbs", encode=False)
    data = (folder / "thumbs" / "page-0001.jpg").read_bytes()
    assert data[:3] == b"\xff\xd8\xff"
    Image.open(BytesIO(data)).load()
