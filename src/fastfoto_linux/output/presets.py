"""Export presets: what each preset writes for photos and for document pages.

A pure table module: it imports no image library. ``None`` (no preset) is not in the tables; it
means the encoders' original settings, byte for byte.
"""

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

CHROMA_444 = 0  # Pillow's subsampling values
CHROMA_420 = 2
PRESET_MESSAGE = "preset must be lossless, high-quality or small"


class ExportPreset(StrEnum):
    LOSSLESS = "lossless"
    HIGH_QUALITY = "high-quality"
    SMALL = "small"


PRESET_CHOICES = tuple(preset.value for preset in ExportPreset)


@dataclass(frozen=True)
class PhotoExport:
    """How the scan and process writer encodes a photo; ``quality`` None means PNG."""

    ext: str
    quality: int | None
    subsampling: int | None
    max_edge: int | None


@dataclass(frozen=True)
class DocumentExport:
    """How a colour or grey document page is encoded; ``quality`` None means PNG."""

    quality: int | None
    subsampling: int | None
    max_dpi: int | None


PHOTO_EXPORTS = MappingProxyType(
    {
        ExportPreset.LOSSLESS: PhotoExport(".png", None, None, None),
        ExportPreset.HIGH_QUALITY: PhotoExport(".jpg", 95, CHROMA_444, None),
        ExportPreset.SMALL: PhotoExport(".jpg", 80, CHROMA_420, 2048),
    }
)

DOCUMENT_EXPORTS = MappingProxyType(
    {
        ExportPreset.LOSSLESS: DocumentExport(None, None, None),
        ExportPreset.HIGH_QUALITY: DocumentExport(92, CHROMA_444, None),
        ExportPreset.SMALL: DocumentExport(60, CHROMA_420, 200),
    }
)


def parse_preset(value: object) -> ExportPreset:
    """The preset named exactly ``value`` (a plain ``str``); nothing is trimmed or case-folded.

    Raises ValueError, with a message that does not repeat the input, for anything else.
    """
    if type(value) is str:
        for preset in ExportPreset:
            if value == preset.value:
                return preset
    raise ValueError(PRESET_MESSAGE)
