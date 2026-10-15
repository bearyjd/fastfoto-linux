"""What a scan session is asked to do."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from fastfoto_linux.pipeline.process import ProcessSettings
from fastfoto_linux.scanner import ScanTarget


class RawPolicy(StrEnum):
    """What happens to the raw scanner pages once the photos are made."""

    KEEP = "keep"
    AUTO = "auto"
    DISCARD = "discard"


@dataclass(frozen=True)
class ScanRequest:
    """Stub: the real class validates on construction."""

    target: ScanTarget
    dpi: int
    duplex: bool
    settings: ProcessSettings
    raw_policy: RawPolicy = RawPolicy.AUTO
    raw_parent: Path | None = None

    @property
    def raw_root(self) -> Path:
        raise NotImplementedError
