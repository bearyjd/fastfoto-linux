"""Album folder and file naming, FastFoto style, with path-traversal protection."""

import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.output.errors import InvalidAlbumError, InvalidPrefixError

logger = logging.getLogger(__name__)

DEFAULT_PREFIX = "FastFoto"
MAX_ALBUM_CHARS = 120
MAX_COMPONENT_BYTES = 255
INDEX_WIDTH = 4
MAX_INDEX_DIGITS = 9
MAX_INDEX = 10**MAX_INDEX_DIGITS - 1
# Room kept free after the stem: "_" + the widest index + "_a.jpg", plus the 14 extra bytes of
# the ".<name>.<8 hex digits>.tmp" staging name used while a file is being written.
FILE_SUFFIX_BYTES = len("_") + MAX_INDEX_DIGITS + len("_a.jpg")
STAGING_OVERHEAD_BYTES = len(".") + len(".") + 8 + len(".tmp")
MAX_PREFIX_BYTES = MAX_COMPONENT_BYTES - FILE_SUFFIX_BYTES - STAGING_OVERHEAD_BYTES

_PATH_SEPARATORS = "/\\"
_STRIPPED_EDGES = ". "
# Control, format (e.g. bidi overrides), surrogate and line/paragraph separator characters.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})
# <prefix>_NNNN[_x].ext, with the prefix folded for case- and normalisation-blind matching.
_INDEXED_NAME = rf"_([0-9]{{{INDEX_WIDTH},{MAX_INDEX_DIGITS}}})(?:_[a-z])?\.[a-z0-9]+"


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


def _fold(text: str) -> str:
    """Canonical caseless form, so ``Beach`` matches ``beach`` and composed matches decomposed."""
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", text).casefold())


def next_index(directory: Path, prefix: str) -> int:
    """One more than the highest ``<prefix>_NNNN[_a].ext`` number in ``directory`` (1 when none).

    Matching ignores case and Unicode normalisation, covers any extension and the ``_a``/``_b``
    style suffix, and skips folders, so a folder holding only ``_a``/``_b`` files still
    continues correctly. Names that merely contain a number (``Trip_2020_0003.jpg`` for prefix
    ``Trip``, ``IMG_20200101_123456.jpg``) do not count. Counting too much is harmless: it only
    skips a number. A stray number too large to have a successor (``MAX_INDEX``) is ignored
    with a warning, so one odd file cannot make the whole prefix unusable.
    """
    pattern = re.compile(re.escape(_fold(prefix)) + _INDEXED_NAME)
    try:
        entries = list(directory.iterdir())
    except FileNotFoundError:
        return 1
    highest = 0
    for entry in entries:
        match = None if entry.is_dir() else pattern.fullmatch(_fold(entry.name))
        if match is None:
            continue
        number = int(match.group(1))
        if number >= MAX_INDEX:
            logger.warning("ignoring %s: its number leaves no room for a next photo", entry.name)
            continue
        highest = max(highest, number)
    return highest + 1


def photo_paths(directory: Path, prefix: str, index: int) -> PhotoPaths:
    """Paths of the original, enhanced (``_a``) and back (``_b``) files for ``index``."""
    if not 1 <= index <= MAX_INDEX:
        raise ValueError(f"index must be 1-{MAX_INDEX}, got {index}")
    stem = f"{prefix}_{index:0{INDEX_WIDTH}d}"
    return PhotoPaths(
        original=directory / f"{stem}.jpg",
        enhanced=directory / f"{stem}_a.jpg",
        back=directory / f"{stem}_b.jpg",
    )


def unprocessed_paths(directory: Path, prefix: str, index: int) -> tuple[Path, Path]:
    """Paths of the whole-page front and back files for ``index`` (stub: red commit)."""
    raise NotImplementedError
