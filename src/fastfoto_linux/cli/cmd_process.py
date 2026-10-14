"""``ffscan process``: turn pages that were scanned earlier into album files."""

import argparse
import re
from pathlib import Path

from fastfoto_linux.cli.errors import EXIT_OK, EXIT_PROCESSING_ERROR, EXIT_USAGE, CliError
from fastfoto_linux.cli.options import (
    add_output_options,
    build_settings,
    common_parent,
    prepare_output_root,
)
from fastfoto_linux.cli.summary import print_summary
from fastfoto_linux.pipeline.process import process_pages

_NUMBER = re.compile(r"(\d+)")


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser(
        "process",
        parents=[common_parent()],
        help="process pages scanned earlier",
        description="Crop, pair, orient and write raw scanner pages (PNG) as album photos. "
        "Pages are taken in natural filename order (page-2 before page-10).",
    )
    parser.add_argument("pages", nargs="+", type=Path, metavar="PAGE.png", help="raw page files")
    add_output_options(parser)
    parser.set_defaults(handler=run)


def natural_key(path: Path) -> list[str | int]:
    """Sort key that compares the numbers in a file name as numbers."""
    parts = _NUMBER.split(path.name)  # text, number, text, ... (the text may be empty)
    return [int(part) if index % 2 else part.lower() for index, part in enumerate(parts)]


def existing_pages(pages: list[Path]) -> list[Path]:
    """``pages`` in natural order; a usage error names the first one that is not a file."""
    for page in pages:
        if not page.is_file():
            raise CliError(f"page not found: {page}", EXIT_USAGE)
    return sorted(pages, key=natural_key)


def run(args: argparse.Namespace) -> int:
    pages = existing_pages(args.pages)
    settings = build_settings(args)
    prepare_output_root(args)
    result = process_pages(pages, settings)
    print_summary(result)
    return EXIT_OK if result.ok else EXIT_PROCESSING_ERROR
