"""Describe a scanimage batch job and turn it into argv and environment."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

SUPPORTED_DPI = (50, 75, 100, 150, 200, 240, 300, 360, 400, 600)
MAX_LENGTH_MM = 393.7


class Source(StrEnum):
    FRONT = "ADF Front"
    DUPLEX = "ADF Duplex"


class Mode(StrEnum):
    LINEART = "Lineart"
    GRAY = "Gray"
    COLOR = "Color"


@dataclass(frozen=True)
class ScanJob:
    device: str
    output_dir: Path
    source: Source = Source.DUPLEX
    mode: Mode = Mode.COLOR
    resolution: int = 600
    deskew: bool = True
    max_length_mm: float = MAX_LENGTH_MM
    file_prefix: str = "page"


def build_argv(job: ScanJob, scanimage: str = "scanimage") -> tuple[str, ...]:
    raise NotImplementedError


def build_env(
    base_env: Mapping[str, str],
    *,
    shim: Path | None = None,
    sane_config_dir: Path | None = None,
) -> dict[str, str]:
    raise NotImplementedError
