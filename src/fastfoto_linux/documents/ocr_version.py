"""Which version of ocrmypdf will run, and which options that version accepts."""

import functools
import importlib.metadata

metadata_version = importlib.metadata.version  # a name a test replaces
VERSION_TIMEOUT_S = 10.0
RASTERIZER_FIRST_MAJOR = 17  # older versions do not know --rasterizer


@functools.cache
def program_version(executable: str) -> str | None:
    raise NotImplementedError


def ocrmypdf_version(executable: str) -> str | None:
    raise NotImplementedError


def accepts_rasterizer(version: str | None) -> bool:
    raise NotImplementedError
