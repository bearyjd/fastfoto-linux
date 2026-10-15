"""Why a JPEG cannot be edited safely; every error carries a short ``reason`` for a plan file."""


class JpegExifError(ValueError):
    """The JPEG cannot be edited safely; ``reason`` is a short code fit for a plan file."""

    reason = "bad-exif"


class NotAJpegError(JpegExifError):
    """The bytes are not a well-formed JPEG up to the start of the image data."""

    reason = "unreadable"


class TooManySegmentsError(NotAJpegError):
    """The JPEG has more markers before its image data than a real photo has."""

    reason = "too-many-segments"


class ExifTooLargeError(JpegExifError):
    """The Exif segment would not fit the 64 KiB a JPEG segment can hold."""

    reason = "exif-too-large"


class ExifMalformedError(JpegExifError):
    """The Exif data points outside itself, loops or is oversized; it is not parsed any further."""

    reason = "exif-malformed"


class ExifDuplicateOrientationError(JpegExifError):
    """IFD0 holds more than one Orientation entry, so it is unclear which one a viewer obeys."""

    reason = "exif-duplicate-orientation"


class XmpOrientationError(JpegExifError):
    """An XMP packet has its own ``tiff:Orientation``, which a viewer may prefer to the Exif one."""

    reason = "xmp-orientation"


class ImageTooLargeError(JpegExifError):
    """The JPEG header claims more pixels than this tool decodes."""

    reason = "too-large"
