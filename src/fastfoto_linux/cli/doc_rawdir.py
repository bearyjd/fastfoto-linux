"""``ffscan doc process RAWDIR``: a raw folder (``.raw/<stamp>/``) as the input.

The pages are those ``list_pages`` finds, counted from 1 in page order. The edits saved in the
folder's ``review.json`` apply first and the command-line edits on top of them; ``--fresh``
ignores the sidecar. The command never writes into the folder: no sidecar, no thumbnails.
"""

from pathlib import Path

from fastfoto_linux.cli.errors import EXIT_USAGE, CliError
from fastfoto_linux.session.raw import list_pages


def raw_folder(arguments: list[Path]) -> Path | None:
    """The raw folder when the page arguments are one folder, None when they are files. A folder
    among other arguments is a usage error."""
    folders = [argument for argument in arguments if argument.is_dir()]
    if not folders:
        return None
    if len(arguments) > 1:
        raise CliError(
            f"{folders[0]} is a folder: give a raw folder on its own, or page files", EXIT_USAGE
        )
    return folders[0]


def folder_pages(folder: Path) -> list[Path]:
    """The page files of the raw folder, in page order; a folder without any is a usage error."""
    pages = list_pages(folder)
    if not pages:
        raise CliError(f"no page files (page-NNNN.png) in {folder}", EXIT_USAGE)
    return list(pages)
