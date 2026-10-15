"""Why a JPEG cannot be edited safely; every error carries a short ``reason`` for a plan file."""


class JpegExifError(ValueError):
    """The JPEG cannot be edited safely; ``reason`` is a short code fit for a plan file."""

    reason = "bad-exif"


class NotAJpegError(JpegExifError):
    """The bytes are not a well-formed JPEG up to the start of the image data."""

    reason = "unreadable"


class ExifTooLargeError(JpegExifError):
    """The Exif segment would not fit the 64 KiB a JPEG segment can hold."""

    reason = "exif-too-large"


class ExifMalformedError(JpegExifError):
    """The Exif data points outside itself, loops or is oversized; it is not parsed any further."""

    reason = "exif-malformed"
