"""The export preset tables and the strict parser of preset names."""

import ast
from pathlib import Path
from types import MappingProxyType

import pytest

from fastfoto_linux.output import presets
from fastfoto_linux.output.presets import (
    DOCUMENT_EXPORTS,
    PHOTO_EXPORTS,
    PRESET_CHOICES,
    ExportPreset,
    parse_preset,
)

MESSAGE = "preset must be lossless, high-quality or small"


class StrSub(str):
    __slots__ = ()


BAD_INPUTS = [
    "Small",
    "SMALL",
    " small",
    "small ",
    "small\n",
    "small\x00",
    "high_quality",
    "high-quality\n",
    "",
    "none",
    b"small",
    None,
    1,
    True,
    ["small"],
    StrSub("small"),
    ExportPreset.SMALL,
]


@pytest.mark.parametrize("preset", list(ExportPreset))
def test_every_preset_has_a_photo_and_a_document_row(preset: ExportPreset) -> None:
    assert preset in PHOTO_EXPORTS
    assert preset in DOCUMENT_EXPORTS


def test_the_tables_are_read_only() -> None:
    assert isinstance(PHOTO_EXPORTS, MappingProxyType)
    assert isinstance(DOCUMENT_EXPORTS, MappingProxyType)
    with pytest.raises(TypeError):
        PHOTO_EXPORTS[ExportPreset.SMALL] = PHOTO_EXPORTS[ExportPreset.LOSSLESS]  # type: ignore[index]
    with pytest.raises(TypeError):
        DOCUMENT_EXPORTS[ExportPreset.SMALL] = DOCUMENT_EXPORTS[ExportPreset.LOSSLESS]  # type: ignore[index]


def test_the_rows_are_frozen() -> None:
    with pytest.raises(AttributeError):
        PHOTO_EXPORTS[ExportPreset.SMALL].quality = 1  # type: ignore[misc]


def test_the_photo_table_matches_the_brief() -> None:
    small, high, lossless = (
        PHOTO_EXPORTS[ExportPreset.SMALL],
        PHOTO_EXPORTS[ExportPreset.HIGH_QUALITY],
        PHOTO_EXPORTS[ExportPreset.LOSSLESS],
    )
    assert (small.ext, small.quality, small.subsampling, small.max_edge) == (".jpg", 80, 2, 2048)
    assert (high.ext, high.quality, high.subsampling, high.max_edge) == (".jpg", 95, 0, None)
    assert (lossless.ext, lossless.quality, lossless.max_edge) == (".png", None, None)


def test_the_document_table_matches_the_brief() -> None:
    small, high, lossless = (
        DOCUMENT_EXPORTS[ExportPreset.SMALL],
        DOCUMENT_EXPORTS[ExportPreset.HIGH_QUALITY],
        DOCUMENT_EXPORTS[ExportPreset.LOSSLESS],
    )
    assert (small.quality, small.subsampling, small.max_dpi) == (60, 2, 200)
    assert (high.quality, high.subsampling, high.max_dpi) == (92, 0, None)
    assert (lossless.quality, lossless.max_dpi) == (None, None)


def test_the_choices_are_the_three_values() -> None:
    assert PRESET_CHOICES == ("lossless", "high-quality", "small")


@pytest.mark.parametrize("preset", list(ExportPreset))
def test_the_exact_values_parse(preset: ExportPreset) -> None:
    assert parse_preset(preset.value) is preset


@pytest.mark.parametrize("bad", BAD_INPUTS, ids=repr)
def test_everything_else_is_refused_without_echoing_it(bad: object) -> None:
    with pytest.raises(ValueError) as caught:
        parse_preset(bad)
    assert str(caught.value) == MESSAGE


def test_the_module_imports_no_image_libraries() -> None:
    tree = ast.parse(Path(presets.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    assert not roots & {"numpy", "PIL", "cv2"}
