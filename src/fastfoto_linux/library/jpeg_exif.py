"""Change the EXIF Orientation of a JPEG without touching any other byte of the file."""


class JpegExifError(ValueError):
    """The JPEG cannot be edited safely; ``reason`` is a short code fit for a plan file."""

    reason = "bad-exif"


class NotAJpegError(JpegExifError):
    """The bytes are not a well-formed JPEG up to the start of the image data."""

    reason = "unreadable"


class ExifTooLargeError(JpegExifError):
    """The Exif segment would not fit the 64 KiB a JPEG segment can hold."""

    reason = "exif-too-large"


def read_orientation(data: bytes) -> int | None:
    """The Orientation tag of the JPEG in ``data``; ``None`` when it has no Exif or no tag."""
    raise NotImplementedError


def set_orientation(data: bytes, tag: int) -> bytes:
    """``data`` with its Orientation tag set to ``tag`` (1-8) and every other byte unchanged.

    When the tag is missing, the Exif segment is rebuilt with it; a JPEG without Exif gets a new
    segment after SOI/JFIF. The result is re-read to confirm the tag.
    """
    raise NotImplementedError
