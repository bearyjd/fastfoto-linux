"""Encode one photo for the scan and process writer, with or without an export preset."""

import io

import numpy as np
from PIL import Image, PngImagePlugin

from fastfoto_linux.output.presets import CHROMA_444, PHOTO_EXPORTS, ExportPreset
from fastfoto_linux.output.resample import downscale

PNG_COMPRESS_LEVEL = 6
XMP_KEY = "XML:com.adobe.xmp"
JPEG_EXT = ".jpg"


def photo_ext(preset: ExportPreset | None) -> str:
    """The file extension a preset writes; it comes from the table, never from input."""
    return JPEG_EXT if preset is None else PHOTO_EXPORTS[preset].ext


def encode_photo(  # noqa: PLR0913 - one call site; the pieces are the interface
    array: np.ndarray,
    *,
    dpi: int,
    quality: int,
    preset: ExportPreset | None,
    exif: bytes,
    xmp: bytes,
) -> bytes:
    """``array`` (HxWx3 uint8 RGB) as JPEG or PNG bytes carrying ``exif`` and ``xmp``.

    Without a preset: JPEG at ``quality``, 4:4:4, ``dpi``. With one, the row of ``PHOTO_EXPORTS``
    decides; ``small`` also shrinks the picture and scales the dpi tag to match.
    """
    buffer = io.BytesIO()
    if preset is None:
        Image.fromarray(array).save(
            buffer,
            "JPEG",
            quality=quality,
            subsampling=CHROMA_444,
            dpi=(dpi, dpi),
            exif=exif,
            xmp=xmp,
        )
        return buffer.getvalue()
    export = PHOTO_EXPORTS[preset]
    if export.max_edge is not None:
        array, scale = downscale(array, export.max_edge)
        dpi = max(1, round(dpi * scale))
    if export.quality is None:
        info = PngImagePlugin.PngInfo()
        info.add_itxt(XMP_KEY, xmp.decode("utf-8"))
        Image.fromarray(array).save(
            buffer,
            "PNG",
            compress_level=PNG_COMPRESS_LEVEL,
            dpi=(dpi, dpi),
            exif=exif,
            pnginfo=info,
        )
    else:
        Image.fromarray(array).save(
            buffer,
            "JPEG",
            quality=export.quality,
            subsampling=export.subsampling,
            dpi=(dpi, dpi),
            exif=exif,
            xmp=xmp,
        )
    return buffer.getvalue()
