"""Command-line options of ``ffscan doc``, and their turn into settings."""

import argparse
from pathlib import Path

from fastfoto_linux.cli.errors import EXIT_USAGE, CliError
from fastfoto_linux.cli.options import add_transport_options
from fastfoto_linux.documents import (
    DEFAULT_LANGS,
    DEFAULT_NAME,
    CleanupPolicy,
    ColourMode,
    ColourPolicy,
    DocumentSettings,
    OcrMode,
    validate_langs,
)
from fastfoto_linux.documents.loader import MAX_DPI, MIN_DPI
from fastfoto_linux.output.errors import InvalidPrefixError
from fastfoto_linux.output.naming import sanitise_prefix
from fastfoto_linux.session import DEFAULT_DOCUMENT_DPI, DOCUMENT_DPI


def _langs(text: str) -> str:
    try:
        return validate_langs(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _dpi(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = 0
    if not MIN_DPI <= value <= MAX_DPI:
        raise argparse.ArgumentTypeError(
            f"dpi must be a whole number from {MIN_DPI} to {MAX_DPI}, got {text!r}"
        )
    return value


def add_document_options(parser: argparse.ArgumentParser) -> None:
    """Where the PDF goes and how it is made."""
    where = parser.add_argument_group("output")
    where.add_argument("--out", type=Path, required=True, metavar="DIR", help="output folder")
    where.add_argument("--mkdir", action="store_true", help="create --out if it does not exist")
    where.add_argument(
        "--name",
        default=DEFAULT_NAME,
        help=f"file name before _NNNN.pdf, also the PDF's title (default: {DEFAULT_NAME})",
    )
    pdf = parser.add_argument_group("document")
    pdf.add_argument(
        "--colour",
        choices=[mode.value for mode in ColourPolicy],
        default=ColourMode.COLOUR.value,
        help="auto per page, colour, grey or black and white (default: colour)",
    )
    pdf.add_argument(
        "--cleanup",
        choices=[policy.value for policy in CleanupPolicy],
        default=None,
        help="paper cleanup: off, light or strong lightens the paper tone of grey and colour "
        "pages; black and white pages are not changed (default: off, or the level a raw "
        "folder's review.json holds)",
    )
    pdf.add_argument(
        "--despeckle",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="remove small isolated specks from black and white pages (default: off, or what "
        "a raw folder's review.json holds)",
    )
    pdf.add_argument(
        "--keep-blank", action="store_true", help="keep blank pages instead of dropping them"
    )
    pdf.add_argument(
        "--ocr",
        choices=[mode.value for mode in OcrMode],
        default=OcrMode.AUTO.value,
        help="searchable text with ocrmypdf: auto (when installed), on (required) or off",
    )
    pdf.add_argument(
        "--lang",
        type=_langs,
        default=DEFAULT_LANGS,
        metavar="LANGS",
        help="OCR languages as Tesseract codes, e.g. eng or eng+deu (default: eng)",
    )


def add_fallback_dpi_option(parser: argparse.ArgumentParser) -> None:
    """``--dpi`` of ``doc process``: the resolution of a PNG that does not say its own."""
    parser.add_argument_group("pages").add_argument(
        "--dpi",
        type=_dpi,
        metavar="DPI",
        help="resolution for a PNG that does not say; a file that does keeps its own",
    )


def add_pairing_option(parser: argparse.ArgumentParser) -> None:
    """``--simplex`` of ``doc process``: the pages are not the two sides of sheets."""
    parser.add_argument_group("pairing").add_argument(
        "--simplex",
        action="store_true",
        help="every page is a front. Without it the pages are paired in order, 1+2, 3+4 and so "
        "on, as a duplex scan gives them, so that holes through the paper (staples, punches) "
        "do not keep a blank back; an odd last page has no partner",
    )


def add_document_scan_options(parser: argparse.ArgumentParser) -> None:
    """Options that only matter when pages are scanned from the feeder."""
    scanning = parser.add_argument_group("scanning")
    scanning.add_argument(
        "--dpi",
        type=int,
        choices=DOCUMENT_DPI,
        default=DEFAULT_DOCUMENT_DPI,
        help=f"scan resolution (default: {DEFAULT_DOCUMENT_DPI})",
    )
    scanning.add_argument("--simplex", action="store_true", help="every page is a front (no backs)")
    add_transport_options(scanning)


def build_settings(args: argparse.Namespace) -> DocumentSettings:
    """The settings the options describe; a bad value is a usage error, found before any work."""
    try:
        sanitise_prefix(args.name)
    except InvalidPrefixError as error:
        raise CliError(str(error), EXIT_USAGE) from error
    return DocumentSettings(
        output_root=args.out,
        name=args.name,
        colour=ColourPolicy.AUTO if args.colour == ColourPolicy.AUTO else ColourMode(args.colour),
        cleanup=CleanupPolicy(args.cleanup) if args.cleanup is not None else CleanupPolicy.OFF,
        despeckle=args.despeckle is True,
        keep_blank=args.keep_blank,
        ocr=OcrMode(args.ocr),
        langs=args.lang,
        fallback_dpi=args.dpi,
        duplex=not args.simplex,
    )
