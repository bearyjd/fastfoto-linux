"""Shared builders for the processing and CLI tests: raw pages on disk, JPEG readers."""

from collections.abc import Sequence
from pathlib import Path

import numpy as np
from PIL import ExifTags, Image

from fastfoto_linux.pipeline.process import ProcessSettings
from tests.sides_helpers import Sheet
from tests.synth import make_duplex_sheet, make_frame

DPI = 150
WRITTEN = {"writing": True}
BLANK = {"imprint": False}
DARK_BACK = {"photo_rgb": (70, 70, 70), "imprint": False}
LOGGER = "fastfoto_linux.pipeline.process"


def page_name(number: int) -> str:
    return f"page-{number:04d}.png"


def save_page(directory: Path, number: int, frame: np.ndarray, dpi: int = DPI) -> Path:
    path = directory / page_name(number)
    Image.fromarray(frame).save(path, dpi=(dpi, dpi))
    return path


def plain_sheet(seed: int = 0) -> Sheet:
    return make_duplex_sheet(dpi=DPI, rng_seed=seed)


def written_sheet(seed: int = 0) -> Sheet:
    return make_duplex_sheet(dpi=DPI, rng_seed=seed, back=WRITTEN)


def half_bright_front_sheet() -> Sheet:
    """A dark back and a front whose left half is bright: content cannot tell them apart."""
    (front, box), back = make_duplex_sheet(dpi=DPI, back=DARK_BACK)
    front = front.copy()
    front[box.y : box.y + box.h, box.x : box.x + box.w // 2] = 240
    return (front, box), back


def write_sheets(
    directory: Path,
    sheets: Sequence[Sheet],
    *,
    front_first: bool = False,
    first_number: int = 1,
) -> list[Path]:
    """Pages ``page-NNNN.png`` for ``sheets``; the default is back first (face-down loading)."""
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for (front, _), (back, _) in sheets:
        for frame in (front, back) if front_first else (back, front):
            paths.append(save_page(directory, first_number + len(paths), frame))
    return paths


def write_front_pages(directory: Path, count: int, *, first_number: int = 1) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    return [
        save_page(directory, first_number + i, make_frame(dpi=DPI, side="front", rng_seed=i)[0])
        for i in range(count)
    ]


def workspace(tmp_path: Path) -> tuple[Path, Path]:
    """``(raw directory, existing output root)``."""
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir()
    out.mkdir()
    return raw, out


def settings_for(out: Path, **overrides) -> ProcessSettings:
    """Settings for a face-down batch (back page first) unless overridden."""
    return ProcessSettings(output_root=out, **{"expect_front_first": False, **overrides})


def jpeg_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def jpeg_mean(path: Path) -> float:
    with Image.open(path) as image:
        return float(np.asarray(image.convert("L")).mean())


def original_date(path: Path) -> str | None:
    with Image.open(path) as image:
        return image.getexif().get_ifd(ExifTags.IFD.Exif).get(ExifTags.Base.DateTimeOriginal)


def digitized_date(path: Path) -> str | None:
    with Image.open(path) as image:
        return image.getexif().get_ifd(ExifTags.IFD.Exif).get(ExifTags.Base.DateTimeDigitized)


def invert(img: np.ndarray, dpi: int) -> np.ndarray:
    """An enhancer that really changes the picture (unlike an identity one, which writes no _a)."""
    return 255 - img


def jpeg_names(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.glob("*.jpg"))
