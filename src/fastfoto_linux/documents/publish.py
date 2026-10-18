"""Publish a finished PDF into the output folder without overwriting anything."""

import unicodedata
from collections.abc import Sequence
from pathlib import Path

from fastfoto_linux.documents.errors import OutputFolderMissingError
from fastfoto_linux.output.errors import OutputCollisionError
from fastfoto_linux.output.files import locked_folder, write_new_files
from fastfoto_linux.output.naming import next_index, pdf_path, sanitise_prefix

MAX_INDEX_ATTEMPTS = 5


def require_output_folder(directory: Path) -> None:
    """Raise ``OutputFolderMissingError`` unless ``directory`` is an existing folder."""
    if not directory.is_dir():
        raise OutputFolderMissingError(
            f"the output folder {directory} is not an existing folder; create or mount it first"
        )


def publish_pdf(data: bytes, directory: Path, name: str) -> Path:
    """Write ``data`` as ``<name>_NNNN.pdf`` in ``directory`` and return its path: the one-part
    case of ``publish_pdfs``."""
    return publish_pdfs([(name, data)], directory)[0]


def _key(prefix: str) -> str:
    """``prefix`` as the numbering sees it: ``Pages`` and ``pages`` share their numbers."""
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", prefix).casefold())


def _plan(prefixes: Sequence[str], directory: Path, floors: dict[str, int]) -> list[Path]:
    """A path for each prefix: the next free number, above ``floors`` (the numbers a rival took)
    and above the numbers this call already gave to the same name."""
    given: dict[str, int] = {}
    paths: list[Path] = []
    for prefix in prefixes:
        key = _key(prefix)
        index = max(next_index(directory, prefix), floors.get(key, 0) + 1, given.get(key, 0) + 1)
        given[key] = index
        paths.append(pdf_path(directory, prefix, index))
    return paths


def publish_pdfs(parts_data: Sequence[tuple[str, bytes]], directory: Path) -> tuple[Path, ...]:
    """Write every ``(name, data)`` as ``<name>_NNNN.pdf`` in ``directory``, all or none.

    Each name is cleaned like an album name and has its own number: the next after the highest
    ``<name>_NNNN`` of any kind already there (two parts of one name get consecutive numbers).
    Takes the folder lock once, for the numbering and the writing only; never replaces a file.
    If a writer that ignores the lock takes a number first, the next free one is used.
    Returns the paths in the order given.
    """
    prefixes = [sanitise_prefix(name) for name, _ in parts_data]
    require_output_folder(directory)
    if not parts_data:
        return ()
    datas = [data for _, data in parts_data]
    floors: dict[str, int] = {}
    collision: OutputCollisionError | None = None
    with locked_folder(directory):
        for _ in range(MAX_INDEX_ATTEMPTS):
            paths = _plan(prefixes, directory, floors)
            try:
                write_new_files(list(zip(paths, datas, strict=True)))
            except OutputCollisionError as error:
                collision = error
                for prefix, path in zip(prefixes, paths, strict=True):
                    if path.exists():  # the number a rival took
                        floors[_key(prefix)] = int(path.stem.rsplit("_", 1)[1])
                continue
            return tuple(paths)
    raise OutputCollisionError(
        f"no free number for {sorted(set(prefixes))!r} in {directory} "
        f"after {MAX_INDEX_ATTEMPTS} attempts"
    ) from collision
