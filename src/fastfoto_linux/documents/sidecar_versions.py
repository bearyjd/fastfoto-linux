"""The format versions of the review sidecar (see ``draft_json``)."""

from collections.abc import Collection

from fastfoto_linux.documents.cleanup_json import EDIT_KEYS
from fastfoto_linux.documents.crop_json import CROP_EDIT_KEYS
from fastfoto_linux.documents.deskew_json import DESKEW_EDIT_KEYS

DESKEW_VERSION = 6  # the shape of version 5 plus an edit's "deskew"
FORMAT_VERSION = DESKEW_VERSION  # the newest version written
DESPECKLE_VERSION = 5  # the shape of version 4 plus a top-level "despeckle"
CROP_VERSION = 4  # the first version that holds a page crop
CLEANUP_VERSION = 3  # the first version that holds paper cleanup
DEFAULT_VERSION = 2  # what a draft with none of these is written as, byte for byte as before
READ_VERSIONS = (1, 2, 3, 4, 5, 6)


def version_for(*, deskew: bool, despeckle: bool, cropped: bool, cleanup: bool) -> int:
    """The lowest version that can hold a draft with these features."""
    if deskew:
        return DESKEW_VERSION
    if despeckle:
        return DESPECKLE_VERSION
    return CROP_VERSION if cropped else CLEANUP_VERSION if cleanup else DEFAULT_VERSION


_NEEDS = (("crop", CROP_VERSION), ("deskew", DESKEW_VERSION), ("cleanup", CLEANUP_VERSION))
_EXACT = (  # from this version up, an edit has exactly these keys
    (DESKEW_VERSION, DESKEW_EDIT_KEYS, "include, turns, colour, cleanup, crop, deskew"),
    (CROP_VERSION, CROP_EDIT_KEYS, "include, turns, colour, cleanup, crop"),
    (CLEANUP_VERSION, EDIT_KEYS, "include, turns, colour, cleanup"),
)


def check_edit_keys(entry: Collection[str], version: int) -> str | None:
    """What is wrong with the keys of an edit in a file of this ``version``, or None: a key a
    later version added, or not exactly the keys of this version."""
    for key, needed in _NEEDS:
        if version < needed and key in entry:
            return f"{key} needs format version {needed}"
    for first, keys, names in _EXACT:
        if version >= first:
            return None if set(entry) == keys else f"an edit must have exactly {names}"
    return None
