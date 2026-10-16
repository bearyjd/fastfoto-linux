"""Why the pages of a batch cannot be turned into photos, one error class per kind of failure."""

import gc
import traceback


class BatchError(ValueError):
    """The pages of a batch cannot be turned into photos (odd page count, no photo, ...).

    ``sheet`` is the 1-based number of the sheet at fault, or None when the batch as a whole is.
    """

    def __init__(self, message: str, *, sheet: int | None = None) -> None:
        super().__init__(message)
        self.sheet = sheet


class NoPhotoOnSheetError(BatchError):
    """No photo could be found on the page(s) of a sheet (two items fed together, say)."""


class UnreadablePageError(BatchError):
    """A page of the sheet could not be loaded (a damaged or missing file, say)."""


class PageResolutionError(BatchError):
    """The two pages of a sheet were scanned at different resolutions."""


def release_frames(error: BaseException) -> None:
    """Free the images that the frames of ``error`` (and its causes) still hold.

    A failed sheet's pages are kept alive by its traceback; whoever goes on to load them again
    would hold them twice. Frames that are still running are left alone. The cyclic garbage that
    a failed search leaves behind (an exception and the frame that raised it) is collected too,
    which is cheap on this rare path and makes the images go now rather than at the next sweep.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        traceback.clear_frames(current.__traceback__)
        current = current.__cause__ or current.__context__
    gc.collect()
