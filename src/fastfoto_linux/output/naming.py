"""Album folder and file naming, FastFoto style, with path-traversal protection."""

from dataclasses import dataclass
from pathlib import Path

DEFAULT_PREFIX = "FastFoto"
MAX_ALBUM_CHARS = 120
MAX_COMPONENT_BYTES = 255
INDEX_WIDTH = 4


@dataclass(frozen=True)
class PhotoPaths:
    """The three file names one photo can produce; which are written is the caller's choice."""

    original: Path
    enhanced: Path
    back: Path


def sanitise_album(album: str) -> str:
    """Turn user text into one safe folder name; raise InvalidAlbumError if nothing is left."""
    raise NotImplementedError


def sanitise_prefix(prefix: str) -> str:
    """Reduce ``prefix`` to ``[A-Za-z0-9_-]``; raise InvalidPrefixError if nothing is left."""
    raise NotImplementedError


def default_prefix(album: str | None) -> str:
    """FastFoto names files after the album folder; fall back to DEFAULT_PREFIX."""
    raise NotImplementedError


def album_dir(output_root: Path, album: str | None) -> Path:
    """Resolved folder for ``album`` under ``output_root`` (``output_root`` when no album)."""
    raise NotImplementedError


def next_index(directory: Path, prefix: str) -> int:
    """One more than the highest ``<prefix>_NNNN*`` number in ``directory`` (1 when none)."""
    raise NotImplementedError


def photo_paths(directory: Path, prefix: str, index: int) -> PhotoPaths:
    """Paths of the original, enhanced (``_a``) and back (``_b``) files for ``index``."""
    raise NotImplementedError
