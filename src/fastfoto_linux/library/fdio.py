"""File access through open descriptors, so a path swapped mid-run is never followed."""

MAX_FILE_BYTES = 512 * 1024 * 1024  # a photo larger than this is skipped, never read into memory
