"""Edit options of ``ffscan doc process``: which pages stay, their order, turns and PDFs.

Page numbers are raw numbers: the page's place, counting from 1, in the order the pages are
read (``dropped`` in the summary reports the same numbers). Every option is checked, and its
numbers are checked against the page count, before any page is read.
"""

import argparse
from collections.abc import Iterable

from fastfoto_linux.cli.errors import EXIT_USAGE, CliError
from fastfoto_linux.documents.draft_edit import PageEdits, validate_edits
from fastfoto_linux.documents.errors import DocumentEditError
from fastfoto_linux.output.errors import InvalidPrefixError
from fastfoto_linux.output.naming import sanitise_prefix

ANGLES = (90, 180, 270)  # clockwise
DEGREES_PER_TURN = 90
EDIT_OPTIONS = (
    "--drop",
    "--keep",
    "--rotate",
    "--split",
    "--order",
    "--part-name",
    "--dry-run",
    "--fresh",
)
_ANGLE_WORDS = "90, 180 or 270 (clockwise)"


def add_edit_options(parser: argparse.ArgumentParser) -> None:
    """The options that change what the PDFs hold. Without them the run is as it always was."""
    group = parser.add_argument_group(
        "edits (numbers are pages counted from 1 in the order they are read)"
    )
    group.add_argument("--drop", metavar="N,N", help="leave these pages out, e.g. --drop 2,4,6")
    group.add_argument(
        "--keep", metavar="N,N", help="bring back pages that were dropped as blank, e.g. --keep 3"
    )
    group.add_argument(
        "--rotate",
        metavar="N:ANGLE,N:ANGLE",
        help=f"turn pages clockwise by {_ANGLE_WORDS}, e.g. --rotate 3:90,5:180",
    )
    group.add_argument(
        "--split", metavar="N,N", help="these pages each start a new PDF, e.g. --split 5,9"
    )
    group.add_argument(
        "--order",
        metavar="N,N,...",
        help="the pages in this order: every page number once, e.g. --order 1,3,2,4",
    )
    group.add_argument(
        "--part-name",
        metavar="K=NAME,K=NAME",
        help="name PDF number K (counted from 1 in output order); a name has no commas, "
        'e.g. --part-name "1=Tax return,2=Receipts". Without a name a PDF is called --name '
        "and, when there are several, its number",
    )
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="print what each page would become and write nothing",
    )
    group.add_argument(
        "--fresh",
        action="store_true",
        help="for a raw folder: ignore the edits and the analysis saved in its review.json",
    )


def _usage(message: str) -> CliError:
    return CliError(message, EXIT_USAGE)


def _items(option: str, text: str) -> list[str]:
    items = [item.strip() for item in text.split(",")]
    if not all(items):
        raise _usage(f"{option}: expected a comma-separated list, got {text!r}")
    return items


def _number(option: str, text: str) -> int:
    if not text.isdecimal():
        raise _usage(f"{option}: {text!r} is not a page number")
    return int(text)


def _once(option: str, numbers: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    for number in numbers:
        if number in seen:
            raise _usage(f"{option}: page {number} is given twice")
        seen.add(number)
    return sorted(seen)


def _page_set(option: str, text: str | None) -> frozenset[int]:
    if text is None:
        return frozenset()
    return frozenset(_once(option, (_number(option, item) for item in _items(option, text))))


def _rotations(text: str | None) -> dict[int, int]:
    if text is None:
        return {}
    pairs: list[tuple[int, int]] = []
    for item in _items("--rotate", text):
        page, colon, angle = item.partition(":")
        if not colon or not page.isdecimal():
            raise _usage(f"--rotate: expected PAGE:ANGLE like 3:90, got {item!r}")
        pairs.append((int(page), _angle(angle)))
    _once("--rotate", (page for page, _ in pairs))
    return dict(pairs)


def _angle(text: str) -> int:
    try:
        angle = int(text)
    except ValueError:
        angle = 0
    if angle not in ANGLES:
        raise _usage(f"--rotate: {text!r} is not an angle; use {_ANGLE_WORDS}")
    return angle // DEGREES_PER_TURN


def _order(text: str | None) -> tuple[int, ...]:
    if text is None:
        return ()
    return tuple(_number("--order", item) for item in _items("--order", text))


def _part_names(text: str | None) -> dict[int, str]:
    if text is None:
        return {}
    names: dict[int, str] = {}
    for item in _items("--part-name", text):
        number, equals, name = item.partition("=")
        if not equals or not number.isdecimal() or not name.strip():
            raise _usage(f"--part-name: expected NUMBER=NAME like 1=Tax return, got {item!r}")
        try:
            clean = sanitise_prefix(name)
        except InvalidPrefixError as error:
            raise _usage(f"--part-name: {error}") from error
        if int(number) in names:
            raise _usage(f"--part-name: PDF {number} is named twice")
        names[int(number)] = clean
    return names


def edits_from_args(args: argparse.Namespace, page_count: int) -> PageEdits:
    """The edits the options describe, checked against ``page_count``; a usage error otherwise."""
    edits = PageEdits(
        drop=_page_set("--drop", args.drop),
        keep=_page_set("--keep", args.keep),
        rotate=_rotations(args.rotate),
        split=_page_set("--split", args.split),
        order=_order(args.order),
        part_names=_part_names(args.part_name),
    )
    try:
        validate_edits(edits, page_count)
    except DocumentEditError as error:
        raise _usage(str(error)) from error
    return edits
