"""The format versions of the review sidecar (see ``draft_json``)."""

FORMAT_VERSION = 5  # the newest version written
DESPECKLE_VERSION = 5  # the shape of version 4 plus a top-level "despeckle"
CROP_VERSION = 4  # the first version that holds a page crop
CLEANUP_VERSION = 3  # the first version that holds paper cleanup
DEFAULT_VERSION = 2  # what a draft with none of these is written as, byte for byte as before
READ_VERSIONS = (1, 2, 3, 4, 5)


def version_for(*, despeckle: bool, cropped: bool, cleanup: bool) -> int:
    """The lowest version that can hold a draft with these features."""
    if despeckle:
        return DESPECKLE_VERSION
    return CROP_VERSION if cropped else CLEANUP_VERSION if cleanup else DEFAULT_VERSION
