"""The fake ``scanimage`` writes real PNG pages from source images, the way its argv asks."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.scanner import Mode, ScanError, ScanJob, run_scan
from tests._fake_scanimage import fake_env, install
from tests.documents.helpers import blank_scene, text_scene, write_pages

SOURCE_DPI = 100
SCAN_TIMEOUT_S = 30.0


@pytest.fixture
def sources(tmp_path: Path) -> list[Path]:
    return write_pages(tmp_path / "sources", [text_scene(1), blank_scene(2)])


def scan(tmp_path: Path, job_options: dict, **spec):
    bin_dir = install(tmp_path / "bin")
    job = ScanJob(device="fake:0", output_dir=tmp_path / "raw", **job_options)
    return run_scan(job, env=fake_env(bin_dir, **spec), timeout_s=SCAN_TIMEOUT_S)


def test_colour_pages_are_rgb_png_at_the_asked_resolution(tmp_path, sources) -> None:
    result = scan(tmp_path, {"resolution": 200}, page_sources=[str(p) for p in sources])
    assert [page.name for page in result.pages] == ["page-0001.png", "page-0002.png"]
    with Image.open(result.pages[0]) as page, Image.open(sources[0]) as source:
        assert page.mode == "RGB"
        assert round(page.info["dpi"][0]) == 200
        scale = 200 // SOURCE_DPI
        assert page.size == (source.width * scale, source.height * scale)
        expected = np.repeat(np.repeat(np.asarray(source), scale, axis=0), scale, axis=1)
        assert np.array_equal(np.asarray(page), expected)


def test_gray_mode_writes_8_bit_grey_pages(tmp_path, sources) -> None:
    result = scan(
        tmp_path, {"resolution": 100, "mode": Mode.GRAY}, page_sources=[str(p) for p in sources]
    )
    with Image.open(result.pages[0]) as page:
        assert page.mode == "L"
        assert round(page.info["dpi"][0]) == SOURCE_DPI


def test_a_mode_the_fake_cannot_draw_fails_like_a_scanner_that_does_not_know_it(
    tmp_path, sources
) -> None:
    with pytest.raises(ScanError):
        scan(tmp_path, {"mode": Mode.LINEART, "resolution": 100}, page_sources=[str(sources[0])])


def test_no_dpi_leaves_the_resolution_out_of_the_pages(tmp_path, sources) -> None:
    result = scan(tmp_path, {"resolution": 200}, page_sources=[str(sources[0])], no_dpi=True)
    with Image.open(result.pages[0]) as page:
        assert "dpi" not in page.info
