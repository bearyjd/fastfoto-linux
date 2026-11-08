"""Which image format a library file is, and which module reads and edits its Orientation.

The suffix picks the format the user meant; the first bytes say what the file is. A file whose
bytes are of the other supported format is refused (``FormatMismatchError``) rather than guessed
at. A file that is neither is handed to its suffix's module, which refuses it with its own reason.
"""

from pathlib import PurePosixPath
from types import MappingProxyType, ModuleType

from fastfoto_linux.library import jpeg_exif, png_exif
from fastfoto_linux.library.exif_errors import FormatMismatchError

SUFFIX_CODECS = MappingProxyType({".jpg": jpeg_exif, ".jpeg": jpeg_exif, ".png": png_exif})
IMAGE_SUFFIXES = frozenset(SUFFIX_CODECS)
PNG_SUFFIX = ".png"


def codec_of(data: bytes) -> ModuleType:
    """The module for the format ``data`` starts as (JPEG unless it starts as a PNG)."""
    return png_exif if data.startswith(png_exif.PNG_SIGNATURE) else jpeg_exif


def codec_for(relative: str, data: bytes) -> ModuleType:
    """The module for the file ``relative`` holding ``data``; ``FormatMismatchError`` if the
    bytes of one format sit under the suffix of the other."""
    codec = SUFFIX_CODECS[PurePosixPath(relative).suffix.lower()]
    starts_png = data.startswith(png_exif.PNG_SIGNATURE)
    starts_jpeg = data.startswith(jpeg_exif.SOI)
    if (codec is png_exif and starts_jpeg) or (codec is jpeg_exif and starts_png):
        raise FormatMismatchError("the file's contents do not match its name")
    return codec
