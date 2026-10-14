"""Turn raw scanner pages into album files: assemble, orient, enhance and write."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from fastfoto_linux.output import DEFAULT_QUALITY, DateRange, PhotoDate, WrittenFiles
from fastfoto_linux.pipeline.sides import BackPolicy

Enhancer = Callable[[np.ndarray, int], np.ndarray]
Orienter = Callable[[np.ndarray, int], np.ndarray]


@dataclass(frozen=True)
class ProcessSettings:
    """Stub."""

    output_root: Path
    album: str | None = None
    prefix: str | None = None
    date: PhotoDate | DateRange | None = None
    notes: str | None = None
    duplex: bool = True
    back_policy: BackPolicy = BackPolicy.AUTO
    expect_front_first: bool | None = None
    quality: int = DEFAULT_QUALITY
    keep_original: bool = True
    enhancers: tuple[Enhancer, ...] = ()
    orienter: Orienter | None = None


@dataclass(frozen=True)
class SheetIssue:
    """Stub."""

    sheet: int | None
    pages: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ProcessResult:
    """Stub."""

    written: tuple[WrittenFiles, ...] = ()
    failed: tuple[SheetIssue, ...] = ()
    uncertain: tuple[SheetIssue, ...] = ()

    @property
    def photos(self) -> int:
        raise NotImplementedError

    @property
    def backs_kept(self) -> int:
        raise NotImplementedError

    @property
    def enhanced(self) -> int:
        raise NotImplementedError


def process_pages(pages: Sequence[Path], settings: ProcessSettings) -> ProcessResult:
    """Stub."""
    raise NotImplementedError
