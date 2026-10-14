"""Album folder and file naming, FastFoto style, with path-traversal protection."""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.output.errors import InvalidAlbumError, InvalidPrefixError

DEFAULT_PREFIX = "FastFoto"
MAX_ALBUM_CHARS = 120
MAX_COMPONENT_BYTES = 255
INDEX_WIDTH = 4
MAX_INDEX_DIGITS = 9
# Room kept free after the stem: "_" + up to 10 digits + "_a.jpg", and the 14 extra bytes of
# the ".<name>.<token>.tmp" staging name used while a file is being written.
FILE_SUFFIX_RESERVE_BYTES = 32
MAX_PREFIX_BYTES = MAX_COMPONENT_BYTES - FILE_SUFFIX_RESERVE_BYTES

_PATH_SEPARATORS = "/\\"
_STRIPPED_EDGES = ". "
# Control, format (e.g. bidi overrides), surrogate and line/paragraph separator characters.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


@dataclass(frozen=True)
class PhotoPaths:
    """The three file names one photo can produce; which are written is the caller's choice."""

    original: Path
    enhanced: Path
    back: Path


def _is_unsafe(char: str) -> bool:
    return char in _PATH_SEPARATORS or unicodedata.category(char) in _UNSAFE_CATEGORIES


def _clean_component(text: str, max_bytes: int) -> str:
    """Reduce ``text`` to one safe path component, or "" if nothing usable is left.

    Path separators, control and format characters become spaces, whitespace is collapsed,
    and leading or trailing dots are dropped, so the result can never be ``.``, ``..`` or
    hidden. It is cut to ``MAX_ALBUM_CHARS`` characters and ``max_bytes`` UTF-8 bytes, on a
    codepoint boundary. Punctuation and non-ASCII letters are kept.
    """
    spaced = "".join(
        " " if _is_unsafe(char) else char for char in unicodedata.normalize("NFC", text)
    )
    name = " ".join(spaced.split())[:MAX_ALBUM_CHARS]
    encoded = name.encode()
    if len(encoded) > max_bytes:
        name = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return name.strip(_STRIPPED_EDGES)


def sanitise_album(album: str) -> str:
    """Turn user text into one safe folder name; raise InvalidAlbumError if nothing is left."""
    name = _clean_component(album, MAX_COMPONENT_BYTES)
    if not name:
        raise InvalidAlbumError(f"album {album!r} has no usable characters for a folder name")
    return name


def sanitise_prefix(prefix: str) -> str:
    """Turn user text into one safe file name stem; raise InvalidPrefixError if none is left.

    Same rules as ``sanitise_album``, but cut shorter so the stem plus ``_NNNN_a.jpg`` (and the
    temporary name used while writing) stays under the 255 byte file name limit. A stem that
    is already clean comes back unchanged.
    """
    name = _clean_component(prefix, MAX_PREFIX_BYTES)
    if not name:
        raise InvalidPrefixError(f"prefix {prefix!r} has no usable characters for a file name")
    return name


def default_prefix(album: str | None) -> str:
    """FastFoto names files after the album folder, so the stem matches the folder name.

    Raises InvalidAlbumError for an unusable album; DEFAULT_PREFIX when there is no album.
    """
    if album is None:
        return DEFAULT_PREFIX
    return sanitise_prefix(sanitise_album(album))


def album_dir(output_root: Path, album: str | None) -> Path:
    """Resolved folder for ``album`` under ``output_root`` (``output_root`` when no album).

    The folder is not created. Raises InvalidAlbumError if the album has no usable name or its
    folder (for instance an existing symlink) resolves outside ``output_root``.
    """
    root = output_root.resolve()
    if album is None:
        return root
    target = (root / sanitise_album(album)).resolve()
    if not target.is_relative_to(root):
        raise InvalidAlbumError(f"album folder for {album!r} resolves outside the output folder")
    return target


def next_index(directory: Path, prefix: str) -> int:
    """One more than the highest ``<prefix>_NNNN*`` number in ``directory`` (1 when none).

    Any file starting with ``<prefix>_`` and at least four digits counts, whatever its suffix
    or extension, so a folder holding only ``_a``/``_b`` files still continues correctly.
    """
    pattern = re.compile(rf"{re.escape(prefix)}_([0-9]{{{INDEX_WIDTH},}})")
    try:
        entries = [entry.name for entry in directory.iterdir()]
    except FileNotFoundError:
        return 1
    matches = (pattern.match(name) for name in entries)
    return max((int(match.group(1)) for match in matches if match), default=0) + 1


def photo_paths(directory: Path, prefix: str, index: int) -> PhotoPaths:
    """Paths of the original, enhanced (``_a``) and back (``_b``) files for ``index``."""
    if index < 1:
        raise ValueError(f"index must be at least 1, got {index}")
    stem = f"{prefix}_{index:0{INDEX_WIDTH}d}"
    return PhotoPaths(
        original=directory / f"{stem}.jpg",
        enhanced=directory / f"{stem}_a.jpg",
        back=directory / f"{stem}_b.jpg",
    )
