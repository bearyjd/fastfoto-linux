"""Publish a finished PDF into the output folder without overwriting anything."""

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
    """Write ``data`` as ``<name>_NNNN.pdf`` in ``directory`` and return its path.

    ``name`` is cleaned like an album name and the number continues after the highest
    ``<name>_NNNN`` of any kind already there. Takes the folder lock only for the numbering and
    the write; never replaces a file. If a writer that ignores the lock takes the number first,
    the next free one is used.
    """
    prefix = sanitise_prefix(name)
    require_output_folder(directory)
    with locked_folder(directory):
        index = 0
        collision: OutputCollisionError | None = None
        for _ in range(MAX_INDEX_ATTEMPTS):
            index = max(next_index(directory, prefix), index + 1)
            path = pdf_path(directory, prefix, index)
            try:
                write_new_files([(path, data)])
            except OutputCollisionError as error:
                collision = error
                continue
            return path
    raise OutputCollisionError(
        f"no free number for {prefix!r} in {directory} after {MAX_INDEX_ATTEMPTS} attempts"
    ) from collision
