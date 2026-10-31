"""A preset sets the quality: ProcessSettings refuses any explicit quality next to one."""

from pathlib import Path

import pytest

from fastfoto_linux.output import DEFAULT_QUALITY
from fastfoto_linux.output.presets import ExportPreset
from fastfoto_linux.pipeline.process import ProcessSettings


@pytest.mark.parametrize("quality", [DEFAULT_QUALITY, 90, 1])
@pytest.mark.parametrize("preset", list(ExportPreset))
def test_any_explicit_quality_with_a_preset_is_refused(
    tmp_path: Path, preset: ExportPreset, quality: int
) -> None:
    with pytest.raises(ValueError, match="not both"):
        ProcessSettings(output_root=tmp_path, preset=preset, quality=quality)


def test_a_preset_alone_and_a_quality_alone_are_fine(tmp_path: Path) -> None:
    assert ProcessSettings(output_root=tmp_path, preset=ExportPreset.SMALL).quality is None
    assert ProcessSettings(output_root=tmp_path, quality=90).effective_quality == 90


def test_no_quality_means_the_default(tmp_path: Path) -> None:
    settings = ProcessSettings(output_root=tmp_path)

    assert settings.quality is None
    assert settings.effective_quality == DEFAULT_QUALITY
