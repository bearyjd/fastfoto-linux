"""Exceptions raised by the album output layer."""


class OutputError(Exception):
    """Base class for every album output failure."""


class InvalidAlbumError(OutputError, ValueError):
    """An album name cannot be turned into a safe folder inside the output root."""


class InvalidPrefixError(OutputError, ValueError):
    """A file prefix has no usable characters left after sanitising."""


class InvalidDateError(OutputError, ValueError):
    """A photo date is not a real calendar date, or a date range is back to front."""


class InvalidNotesError(OutputError, ValueError):
    """Notes are too long to fit in the JPEG metadata segments."""


class InvalidImageError(OutputError, ValueError):
    """An image array is not an HxWx3 uint8 RGB array."""


class OutputCollisionError(OutputError, FileExistsError):
    """A file this photo needs already exists; nothing was overwritten."""
