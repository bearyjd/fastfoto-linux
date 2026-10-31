"""Photo export presets through ``write_photo`` and ``write_unprocessed``, read back from disk."""

from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import pytest
from PIL import Image, JpegImagePlugin

from fastfoto_linux.output import writer
from fastfoto_linux.output.errors import OutputCollisionError
from fastfoto_linux.output.presets import ExportPreset
from fastfoto_linux.output.writer import write_photo, write_unprocessed
from tests._output_helpers import DPI, make_root, names
from tests.test_output_nopreset_pin import ALBUM, DATE, NOTES, NOW, SCANNED, textured

PRESETS = [None, *ExportPreset]
ORIENTATION = 0x0112
EXIF_IFD = 0x8769
DATETIME_ORIGINAL, DATETIME_DIGITIZED, SOFTWARE, DATETIME = 0x9003, 0x9004, 0x0131, 0x0132
ICC = "icc_profile"


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(writer, "_now", lambda: NOW)


def write(root: Path, array: np.ndarray, preset: ExportPreset | None, **extra):
    return write_photo(
        array,
        dpi=DPI,
        output_root=root,
        album=ALBUM,
        date=DATE,
        notes=NOTES,
        scanned_at=SCANNED,
        preset=preset,
        **extra,
    )


def opened(path: Path) -> Image.Image:
    picture = Image.open(path)
    picture.load()
    return picture


def expected_ext(preset: ExportPreset | None) -> str:
    return ".png" if preset is ExportPreset.LOSSLESS else ".jpg"


def test_high_quality_equals_the_no_preset_bytes(tmp_path: Path) -> None:
    plain = write(make_root(tmp_path, "a"), textured(), None).original
    high = write(make_root(tmp_path, "b"), textured(), ExportPreset.HIGH_QUALITY).original

    assert plain is not None and high is not None
    assert plain.read_bytes() == high.read_bytes()


@pytest.mark.parametrize("preset", PRESETS, ids=str)
def test_metadata_dpi_and_orientation_survive_every_preset(
    tmp_path: Path, preset: ExportPreset | None
) -> None:
    array = textured((64, 96))
    path = write(make_root(tmp_path), array, preset).original
    assert path is not None and path.suffix == expected_ext(preset)

    picture = opened(path)
    exif = picture.getexif()
    sub = exif.get_ifd(EXIF_IFD)
    assert exif[SOFTWARE]
    assert exif[DATETIME] == NOW.strftime("%Y:%m:%d %H:%M:%S")
    assert sub[DATETIME_ORIGINAL] == DATE.exif_datetime
    assert sub[DATETIME_DIGITIZED] == SCANNED.strftime("%Y:%m:%d %H:%M:%S")
    assert ORIENTATION not in exif
    assert ICC not in picture.info
    xmp = picture.info["xmp"].decode("utf-8")
    assert escape(NOTES) in xmp
    assert ALBUM in xmp
    assert round(picture.info["dpi"][0]) == DPI
    assert picture.size == (96, 64)  # upright: still landscape


def test_lossless_names_and_pixels_for_every_file(tmp_path: Path) -> None:
    front, enhanced, back = textured(seed=1), textured(seed=2), textured(seed=3)
    result = write(make_root(tmp_path), front, ExportPreset.LOSSLESS, enhanced=enhanced, back=back)

    assert names(result.directory) == ["Summer_0001.png", "Summer_0001_a.png", "Summer_0001_b.png"]
    for path, array in ((result.original, front), (result.enhanced, enhanced), (result.back, back)):
        assert path is not None
        assert np.array_equal(np.asarray(opened(path).convert("RGB")), array)


def test_lossless_whole_pages_are_png(tmp_path: Path) -> None:
    front, back = textured(seed=1), textured(seed=4)
    result = write_unprocessed(
        front,
        dpi=DPI,
        output_root=make_root(tmp_path),
        reason="no photo found",
        back=back,
        album=ALBUM,
        preset=ExportPreset.LOSSLESS,
    )

    assert names(result.directory) == [
        "Summer_0001_unprocessed.png",
        "Summer_0001_unprocessed_b.png",
    ]
    assert result.original is not None
    assert np.array_equal(np.asarray(opened(result.original)), front)


def test_small_downscales_whole_pages_too(tmp_path: Path) -> None:
    result = write_unprocessed(
        np.zeros((100, 3000, 3), dtype=np.uint8),
        dpi=300,
        output_root=make_root(tmp_path),
        reason="no photo found",
        preset=ExportPreset.SMALL,
    )

    assert result.original is not None
    assert opened(result.original).size[0] == 2048


def test_small_on_a_large_textured_photo(tmp_path: Path) -> None:
    rng = np.random.default_rng(3)
    ramp = np.linspace(0, 200, 2200, dtype=np.float32)[None, :, None]
    array = np.clip(ramp + rng.integers(0, 55, size=(1400, 2200, 3)), 0, 255).astype(np.uint8)
    high = write(make_root(tmp_path, "h"), array, ExportPreset.HIGH_QUALITY).original
    small = write(make_root(tmp_path, "s"), array, ExportPreset.SMALL).original
    assert high is not None and small is not None

    picture = opened(small)
    assert max(picture.size) == 2048
    assert JpegImagePlugin.get_sampling(picture) == 2
    assert round(picture.info["dpi"][0]) == round(DPI * 2048 / 2200)
    assert small.stat().st_size < 0.5 * high.stat().st_size


def test_small_does_not_enlarge_a_small_photo(tmp_path: Path) -> None:
    path = write(make_root(tmp_path), textured((64, 96)), ExportPreset.SMALL).original

    assert path is not None
    picture = opened(path)
    assert picture.size == (96, 64)
    assert round(picture.info["dpi"][0]) == DPI


def test_an_existing_png_takes_the_number_for_a_jpeg(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    folder = root / ALBUM
    folder.mkdir()
    (folder / "Summer_0001.png").write_bytes(b"theirs")

    result = write(root, textured(), None)

    assert result.index == 2


def test_a_png_planted_after_numbering_is_skipped_by_a_jpeg_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_root(tmp_path)
    folder = root / ALBUM
    folder.mkdir()
    (folder / "Summer_0002.png").write_bytes(b"theirs")
    monkeypatch.setattr(writer, "next_index", lambda directory, prefix: 2)

    result = write(root, textured(), None)

    assert result.index == 3
    assert (folder / "Summer_0002.png").read_bytes() == b"theirs"


def test_a_jpeg_planted_after_numbering_is_skipped_by_a_png_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_root(tmp_path)
    folder = root / ALBUM
    folder.mkdir()
    (folder / "Summer_0001_b.jpg").write_bytes(b"theirs")
    monkeypatch.setattr(writer, "next_index", lambda directory, prefix: 1)

    result = write(root, textured(), ExportPreset.LOSSLESS)

    assert result.index == 2
    assert (folder / "Summer_0001_b.jpg").read_bytes() == b"theirs"


def test_giving_up_still_reports_a_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_root(tmp_path)
    folder = root / ALBUM
    folder.mkdir()
    for index in range(1, writer.MAX_INDEX_ATTEMPTS + 1):
        (folder / f"Summer_{index:04d}.png").write_bytes(b"theirs")
    monkeypatch.setattr(writer, "next_index", lambda directory, prefix: 1)

    with pytest.raises(OutputCollisionError):
        write(root, textured(), None)


@pytest.mark.parametrize("bad", ["small", 1, True, b"small"])
def test_the_writer_refuses_a_preset_that_is_not_a_member(tmp_path: Path, bad: object) -> None:
    with pytest.raises(ValueError, match="preset must be lossless, high-quality or small"):
        write(make_root(tmp_path), textured(), bad)  # type: ignore[arg-type]
    assert list((tmp_path / "out").iterdir()) == []


@pytest.mark.parametrize("preset", PRESETS, ids=str)
def test_every_file_of_a_sheet_keeps_its_date_and_xmp(
    tmp_path: Path, preset: ExportPreset | None
) -> None:
    result = write(
        make_root(tmp_path, "a"),
        textured(seed=1),
        preset,
        enhanced=textured(seed=2),
        back=textured(seed=3),
    )
    whole = write_unprocessed(
        textured(seed=4),
        dpi=DPI,
        output_root=make_root(tmp_path, "b"),
        reason="no photo found",
        back=textured(seed=5),
        album=ALBUM,
        date=DATE,
        notes=NOTES,
        scanned_at=SCANNED,
        preset=preset,
    )

    paths = [*result.paths, *whole.paths]
    assert len(paths) == 5
    for path in paths:
        assert path.suffix == expected_ext(preset)
        picture = opened(path)
        assert picture.getexif().get_ifd(EXIF_IFD)[DATETIME_ORIGINAL] == DATE.exif_datetime
        xmp = picture.info["xmp"].decode("utf-8")
        assert escape(NOTES) in xmp
        assert ALBUM in xmp
