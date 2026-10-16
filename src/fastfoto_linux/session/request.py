"""What a scan session is asked to do."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from fastfoto_linux.documents import DocumentSettings
from fastfoto_linux.pipeline.process import ProcessSettings
from fastfoto_linux.scanner import MAX_LENGTH_MM, SUPPORTED_DPI, Mode, ScanTarget

DOCUMENT_DPI = (200, 300, 600)
DEFAULT_DOCUMENT_DPI = 300


class RawPolicy(StrEnum):
    """What happens to the raw scanner pages once the photos are made.

    The raw pages always stay when the run was not clean (a scanner error, a cancel, a failed or
    degraded sheet): a lost page means scanning the physical print again.
    ``KEEP`` keeps them after a clean run too. ``AUTO`` keeps them only when a back was dropped
    for lack of writing, so that a back with faint writing is never lost for good. ``DISCARD``
    deletes them after a clean run, even then.
    """

    KEEP = "keep"
    AUTO = "auto"
    DISCARD = "discard"


@dataclass(frozen=True)
class ScanRequest:
    """One scan of the document feeder and the processing of its pages.

    ``duplex`` says whether the feeder scans both sides; it must agree with
    ``settings.duplex``, which says whether the pages are paired as front and back.
    ``raw_parent`` is the folder the raw pages live in (a hidden temporary folder, or ``.raw/``
    for kept pages); it defaults to the output folder, whose file system a kept folder is
    renamed on, and must exist. ``mode`` and ``max_length_mm`` go to scanimage as they are
    (colour, the scanner's full length: what photos have always been scanned with).
    """

    target: ScanTarget
    dpi: int
    duplex: bool
    settings: ProcessSettings
    raw_policy: RawPolicy = RawPolicy.AUTO
    raw_parent: Path | None = None
    mode: Mode = Mode.COLOR
    max_length_mm: float = MAX_LENGTH_MM

    def __post_init__(self) -> None:
        if self.duplex != self.settings.duplex:
            raise ValueError(
                f"the scan is duplex={self.duplex} but the processing settings are "
                f"duplex={self.settings.duplex}; the pages would be paired wrongly"
            )
        if self.dpi not in SUPPORTED_DPI:
            raise ValueError(f"dpi {self.dpi!r} is not supported; use one of {SUPPORTED_DPI}")

    @property
    def raw_root(self) -> Path:
        """The folder the raw pages are created in."""
        return self.settings.output_root if self.raw_parent is None else self.raw_parent


@dataclass(frozen=True)
class DocumentScanRequest:
    """One scan of the document feeder and the PDF made from its pages."""

    target: ScanTarget
    settings: DocumentSettings
    dpi: int = DEFAULT_DOCUMENT_DPI
    duplex: bool = True
    raw_policy: RawPolicy = RawPolicy.AUTO
    raw_parent: Path | None = None
    mode: Mode = Mode.COLOR
    max_length_mm: float = MAX_LENGTH_MM

    @property
    def raw_root(self) -> Path:
        """The folder the raw pages are created in."""
        return self.settings.output_root if self.raw_parent is None else self.raw_parent
