"""PNG masters through ``check`` and ``fix``: decided like JPEGs, written with only eXIf changed."""

import io
import zlib
from pathlib import Path

import numpy as np
import pytest
from fastfoto_linux.library.png_exif import read_orientation
from PIL import Image

from fastfoto_linux.cli import main
from fastfoto_linux.enhance.faces import FaceDetector
from fastfoto_linux.enhance.orient import WORKING_LONG_SIDE_PX
from fastfoto_linux.library import decide as decide_module
from fastfoto_linux.library.apply import STATUS_FAILED, STATUS_STALE, STATUS_WRITTEN, apply_plan
from fastfoto_linux.library.decide import decide_file, decide_files, load_working_image
from fastfoto_linux.library.plan import Action
from tests.face_images import load_astronaut
from tests.library.jpeg_helpers import (
    make_jpeg,
    rotate_cw,
    rotate_row,
    sideways_jpeg,
    write_file,
)
from tests.library.png_helpers import (
    ORIENTATION_XMP,
    idat_bytes,
    ihdr,
    make_png,
    sideways_png,
    split,
    with_before_idat,
    xmp_packet,
)
from tests.library.test_png_untrusted import rebuilt
from tests.photo_edits.png_helpers import master_png

FRONT = "2001/holiday_0001_a.png"


@pytest.fixture(scope="module")
def detector() -> FaceDetector:
    return FaceDetector()


def decided(tmp_path: Path, detector: FaceDetector, data: bytes, name: str = FRONT):
    write_file(tmp_path, name, data)
    return decide_file(tmp_path, name, detector)


def pixels_of(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as image:
        return np.array(image.convert("RGB"))


# --- deciding -------------------------------------------------------------------------------


@pytest.mark.parametrize(("deviation", "old_tag"), [(0, None), (90, None), (270, 6), (180, 1)])
def test_the_proposed_turn_makes_a_png_portrait_upright(
    tmp_path: Path, detector: FaceDetector, deviation: int, old_tag: int | None
) -> None:
    data = sideways_png(deviation, old_tag)
    row = decided(tmp_path, detector, data)
    assert (row.path, row.old_tag, row.size) == (FRONT, old_tag or 1, len(data))
    if deviation == 0:
        assert (row.action, row.reason) == (Action.KEEP, "upright")
        return
    assert row.action is Action.ROTATE
    assert row.rotate_cw == (360 - deviation) % 360
    shown = rotate_cw(pixels_of(data), {1: 0, 6: 90, 3: 180, 8: 270}[row.new_tag])
    assert shown.shape == load_astronaut().shape
    assert row.sha256


def test_a_png_back_is_never_rotated(tmp_path: Path, detector: FaceDetector) -> None:
    row = decided(tmp_path, detector, sideways_png(90, None), "2001/holiday_0001_b.png")
    assert row.action is Action.SKIP
    assert row.reason in {"back", "back-looks-like-front"}


@pytest.mark.parametrize("mode", ["RGBA", "L", "P", "LA"])
def test_other_png_colour_types_are_analysed_not_crashed_on(
    tmp_path: Path, detector: FaceDetector, mode: str
) -> None:
    row = decided(tmp_path, detector, make_png(load_astronaut(), mode=mode))
    assert row.reason != "unreadable"


def test_a_16_bit_png_is_analysed(tmp_path: Path, detector: FaceDetector) -> None:
    buffer = io.BytesIO()
    gray = (load_astronaut()[..., 0].astype(np.uint16)) * 257
    Image.fromarray(gray, "I;16").save(buffer, "PNG")
    row = decided(tmp_path, detector, buffer.getvalue())
    assert row.reason != "unreadable"


def test_a_png_with_a_hostile_header_claim_is_too_large_and_never_decoded(
    tmp_path: Path, detector: FaceDetector, monkeypatch
) -> None:
    def refuse(*args, **kwargs):
        raise AssertionError("decoded")

    monkeypatch.setattr(decide_module.Image, "open", refuse)
    row = decided(tmp_path, detector, rebuilt(master_png(), ihdr(60_000, 60_000)))
    assert (row.action, row.reason) == (Action.SKIP, "too-large")


def test_a_wide_pixel_format_counts_for_its_memory(tmp_path: Path, detector: FaceDetector) -> None:
    rgba16 = rebuilt(master_png(), ihdr(8_000, 5_000, depth=16, colour=6))  # 40 Mpx, 320 MB
    row = decided(tmp_path, detector, rgba16)
    assert (row.action, row.reason) == (Action.SKIP, "too-large")


@pytest.mark.parametrize(
    ("name", "data"),
    [("a.png", make_jpeg(load_astronaut())), ("a.jpg", make_png(load_astronaut()))],
)
def test_a_file_whose_bytes_do_not_match_its_suffix_is_skipped(
    tmp_path: Path, detector: FaceDetector, name: str, data: bytes
) -> None:
    row = decided(tmp_path, detector, data, name)
    assert (row.action, row.reason) == (Action.SKIP, "wrong-format")


def test_a_png_with_a_conflicting_xmp_orientation_is_skipped_when_it_would_be_rotated(
    tmp_path: Path, detector: FaceDetector
) -> None:
    data = with_before_idat(sideways_png(90, None), xmp_packet(ORIENTATION_XMP, "itxt"))
    row = decided(tmp_path, detector, data)
    assert (row.action, row.reason) == (Action.SKIP, "xmp-orientation")


def test_a_hostile_png_is_a_skip_row_with_a_reason(tmp_path: Path, detector: FaceDetector) -> None:
    row = decided(tmp_path, detector, master_png()[:-30])
    assert (row.action, row.reason) == (Action.SKIP, "unreadable")


def test_ancillary_chunks_never_reach_the_decoder(tmp_path: Path, detector: FaceDetector) -> None:
    bomb = zlib.compress(b"0" * 60_000_000)
    data = with_before_idat(sideways_png(90, None), (b"zTXt", b"k\x00\x00" + bomb))
    row = decided(tmp_path, detector, data)
    assert row.action is Action.ROTATE


def test_a_big_png_is_brought_down_to_the_working_size() -> None:
    big = np.zeros((1800, 2600, 3), np.uint8)
    big[::7] = 200
    image = load_working_image(make_png(big), None)
    assert max(image.shape[:2]) >= WORKING_LONG_SIDE_PX
    assert max(image.shape[:2]) < 2 * WORKING_LONG_SIDE_PX


def test_a_png_working_image_has_its_tag_applied() -> None:
    data = make_png(load_astronaut())
    upright = load_working_image(data, None)
    turned = load_working_image(data, 6)
    assert turned.shape[:2] == upright.shape[:2][::-1]


def test_a_pool_decides_pngs_and_jpegs_together(tmp_path: Path) -> None:
    write_file(tmp_path, "a.png", sideways_png(90, None))
    write_file(tmp_path, "b.jpg", sideways_jpeg(90, None))
    rows = decide_files(tmp_path, ["a.png", "b.jpg"], jobs=2)
    assert [row.action for row in rows] == [Action.ROTATE, Action.ROTATE]


# --- writing --------------------------------------------------------------------------------


def png_row(root: Path, relative: str, old: int, new: int):
    return rotate_row(root, relative, 90, old, new)


def test_fix_writes_a_png_copy_with_only_the_tag_changed(tmp_path: Path) -> None:
    lib, dest = tmp_path / "lib", tmp_path / "dest"
    dest.mkdir()
    data = sideways_png(90, 6)
    write_file(lib, FRONT, data)
    result = apply_plan([png_row(lib, FRONT, 6, 3)], lib, dest)
    assert [o.status for o in result.outcomes] == [STATUS_WRITTEN]
    written = (dest / FRONT).read_bytes()
    assert read_orientation(written) == 3
    assert idat_bytes(written) == idat_bytes(data)
    assert [c for c in split(written) if c[0] != b"eXIf"] == [
        c for c in split(data) if c[0] != b"eXIf"
    ]
    assert (lib / FRONT).read_bytes() == data


def test_fix_adds_the_chunk_to_a_png_without_one(tmp_path: Path) -> None:
    lib, dest = tmp_path / "lib", tmp_path / "dest"
    dest.mkdir()
    write_file(lib, FRONT, sideways_png(90, None))
    apply_plan([png_row(lib, FRONT, 1, 6)], lib, dest)
    assert read_orientation((dest / FRONT).read_bytes()) == 6


def test_fix_refuses_a_row_whose_old_tag_is_not_the_files(tmp_path: Path) -> None:
    lib, dest = tmp_path / "lib", tmp_path / "dest"
    dest.mkdir()
    write_file(lib, FRONT, sideways_png(90, 6))
    result = apply_plan([png_row(lib, FRONT, 1, 3)], lib, dest)
    assert [o.status for o in result.outcomes] == [STATUS_STALE]
    assert not (dest / FRONT).exists()


@pytest.mark.parametrize(
    ("name", "data"),
    [("a.png", make_jpeg(load_astronaut())), ("a.jpg", make_png(load_astronaut()))],
)
def test_fix_refuses_bytes_that_do_not_match_the_suffix(
    tmp_path: Path, name: str, data: bytes
) -> None:
    lib, dest = tmp_path / "lib", tmp_path / "dest"
    dest.mkdir()
    write_file(lib, name, data)
    result = apply_plan([png_row(lib, name, 1, 6)], lib, dest)
    assert [(o.status, o.reason) for o in result.outcomes] == [(STATUS_FAILED, "wrong-format")]
    assert list(dest.iterdir()) == []


def test_fix_refuses_a_png_with_a_conflicting_xmp_orientation(tmp_path: Path) -> None:
    lib, dest = tmp_path / "lib", tmp_path / "dest"
    dest.mkdir()
    write_file(
        lib, FRONT, with_before_idat(sideways_png(90, None), xmp_packet(ORIENTATION_XMP, "ztxt"))
    )
    result = apply_plan([png_row(lib, FRONT, 1, 6)], lib, dest)
    assert [(o.status, o.reason) for o in result.outcomes] == [(STATUS_FAILED, "xmp-orientation")]
    assert list(dest.iterdir()) == []


# --- the command line -----------------------------------------------------------------------


def test_check_then_fix_handle_a_mixed_library(tmp_path: Path, capsys) -> None:
    lib, work, dest = tmp_path / "lib", tmp_path / "work", tmp_path / "dest"
    work.mkdir()
    write_file(lib, "a.png", sideways_png(90, None))
    write_file(lib, "b.jpg", sideways_jpeg(90, None))
    write_file(lib, "c.txt", b"x")
    assert main(["library", "check", str(lib), "--plan", str(work / "plan.csv")]) == 0
    out = capsys.readouterr().out
    assert "files seen: 3 (JPEG: 1, PNG: 1, other formats ignored: 1)" in out
    assert "to rotate: 2" in out
    plan = str(work / "plan.csv")
    assert main(["library", "fix", plan, "--source", str(lib), "--out", str(dest), "--mkdir"]) == 0
    assert "written: 2" in capsys.readouterr().out
    assert read_orientation((dest / "a.png").read_bytes()) == upright_png_tag(dest / "a.png")


def upright_png_tag(path: Path) -> int:
    stored = pixels_of(path.read_bytes())
    for tag, turn in {1: 0, 6: 90, 3: 180, 8: 270}.items():
        shown = rotate_cw(stored, turn)
        if (
            shown.shape == load_astronaut().shape
            and np.abs(shown.astype(int) - load_astronaut().astype(int)).mean() < 12
        ):
            return tag
    raise AssertionError("no tag shows the portrait upright")
