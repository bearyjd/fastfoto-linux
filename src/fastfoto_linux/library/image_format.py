"""Which image format a library file is, and which module reads and edits its Orientation.

The suffix picks the format the user meant; the first bytes say what the file is. A file whose
bytes are of the other supported format is refused (``FormatMismatchError``) rather than guessed
at. A suffix this tool does not know (a hand-edited plan can name anything) is decided by the
bytes alone, and a file that is neither format is refused with ``UnsupportedFormatError``. A known
suffix over bytes of neither format goes to that suffix's module, which refuses it with its own
reason. Every refusal is a ``JpegExifError``: the row fails, the run goes on.
"""

from pathlib import PurePosixPath
from types import MappingProxyType, ModuleType

from fastfoto_linux.library import jpeg_exif, png_exif
from fastfoto_linux.library.exif_errors import FormatMismatchError, UnsupportedFormatError

SUFFIX_CODECS = MappingProxyType(
    {".jpg": jpeg_exif, ".jpeg": jpeg_exif, ".jpe": jpeg_exif, ".png": png_exif}
)
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})  # what a library walk lists
PNG_SUFFIX = ".png"


def _by_bytes(data: bytes) -> ModuleType | None:
    if data.startswith(png_exif.PNG_SIGNATURE):
        return png_exif
    return jpeg_exif if data.startswith(jpeg_exif.SOI) else None


def codec_of(data: bytes) -> ModuleType:
    """The module for the format ``data`` starts as (JPEG unless it starts as a PNG)."""
    return _by_bytes(data) or jpeg_exif


def codec_for(relative: str, data: bytes) -> ModuleType:
    """The module for the file ``relative`` holding ``data``.

    ``FormatMismatchError`` if the bytes of one format sit under the suffix of the other;
    ``UnsupportedFormatError`` if the suffix is unknown and the bytes are of neither format.
    """
    found = _by_bytes(data)
    codec = SUFFIX_CODECS.get(PurePosixPath(relative).suffix.lower())
    if codec is None:
        if found is None:
            raise UnsupportedFormatError("the file is not a JPEG or a PNG")
        return found
    if found is not None and found is not codec:
        raise FormatMismatchError("the file's contents do not match its name")
    return codec
