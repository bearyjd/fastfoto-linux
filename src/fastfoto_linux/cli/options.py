"""Command-line options shared by ``scan`` and ``process``, and their turn into settings."""

import argparse
from pathlib import Path

from fastfoto_linux.cli.errors import EXIT_USAGE, CliError
from fastfoto_linux.enhance.orient import auto_orient
from fastfoto_linux.enhance.redeye import remove_red_eye
from fastfoto_linux.enhance.restore import restore_colour
from fastfoto_linux.output import DEFAULT_QUALITY, PhotoDate
from fastfoto_linux.output.errors import InvalidDateError
from fastfoto_linux.output.presets import PRESET_CHOICES, ExportPreset, parse_preset
from fastfoto_linux.output.writer import MAX_QUALITY, MIN_QUALITY
from fastfoto_linux.pipeline.process import Enhancer, ProcessSettings
from fastfoto_linux.pipeline.sides import BackPolicy
from fastfoto_linux.scanner import SUPPORTED_DPI, ScannerError, validate_host

DEFAULT_DPI = 600
FEED_FACE_DOWN = "face-down"
FEED_FACE_UP = "face-up"


def _date(text: str) -> PhotoDate:
    try:
        return PhotoDate.parse(text)
    except InvalidDateError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _quality(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = MIN_QUALITY - 1
    if not MIN_QUALITY <= value <= MAX_QUALITY:
        raise argparse.ArgumentTypeError(
            f"quality must be a whole number from {MIN_QUALITY} to {MAX_QUALITY}, got {text!r}"
        )
    return value


def preset_arg(text: str) -> ExportPreset:
    """``--preset``: an exact preset name; the message never repeats the input."""
    try:
        return parse_preset(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


PRESET_HELP = (
    f"export preset ({', '.join(PRESET_CHOICES)}): lossless writes PNG/Flate, high-quality "
    "keeps full detail at a high JPEG quality, small shrinks pictures for much smaller files; "
    "metadata is kept. Cannot be combined with --quality (default: none, today's output)"
)


def host(text: str) -> str:
    """A plain IPv4 address or hostname (``--net``)."""
    try:
        return validate_host(text)
    except ScannerError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def add_log_options(parser: argparse.ArgumentParser, *, default: bool | str) -> None:
    """``-v`` and ``--debug``; ``default`` is False, or SUPPRESS where another parser has them."""
    parser.add_argument(
        "-v", "--verbose", action="store_true", default=default, help="log progress to stderr"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=default,
        help="log in detail and show tracebacks on errors",
    )


def common_parent() -> argparse.ArgumentParser:
    """``-v`` and ``--debug`` after the command, shared by every command through ``parents=``.

    They are also accepted before the command. A subparser's default would overwrite a value
    given there, so these copies set nothing unless the option is actually present.
    """
    parent = argparse.ArgumentParser(add_help=False)
    add_log_options(parent, default=argparse.SUPPRESS)
    return parent


def add_output_options(parser: argparse.ArgumentParser) -> None:
    """Where and how photos are written, and what is done to them on the way."""
    where = parser.add_argument_group("output")
    where.add_argument("--out", type=Path, required=True, metavar="DIR", help="output folder")
    where.add_argument("--mkdir", action="store_true", help="create --out if it does not exist")
    where.add_argument("--album", help="album folder inside --out (default: --out itself)")
    where.add_argument("--prefix", help="file name prefix (default: the album name, or FastFoto)")
    where.add_argument("--date", type=_date, metavar="YYYY[-MM[-DD]]", help="when the photos date")
    where.add_argument("--notes", help="text stored in every photo's metadata")
    where.add_argument("--quality", type=_quality, default=None, help="JPEG quality (default: 95)")
    where.add_argument("--preset", type=preset_arg, default=None, metavar="NAME", help=PRESET_HELP)
    keep = where.add_mutually_exclusive_group()
    keep.add_argument(
        "--keep-original",
        dest="keep_original",
        action="store_true",
        default=True,
        help="write the plain original next to the enhanced copy (default)",
    )
    keep.add_argument(
        "--enhanced-only",
        dest="keep_original",
        action="store_false",
        help="write only the enhanced copy when there is one",
    )
    pages = parser.add_argument_group("pages")
    pages.add_argument("--simplex", action="store_true", help="every page is a front (no backs)")
    pages.add_argument(
        "--backs",
        choices=[p.value for p in BackPolicy],
        default=BackPolicy.AUTO.value,
        help="which backs to keep: handwritten ones, all or none (default: auto)",
    )
    pages.add_argument(
        "--feed",
        choices=[FEED_FACE_UP, FEED_FACE_DOWN],
        default=FEED_FACE_UP,
        help=(
            "how photos were loaded (top edge first): face-up scans the back first (default); "
            "face-down scans the front first (these names used to mean the opposite)"
        ),
    )
    _add_enhancement_options(parser)


def _add_enhancement_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("enhancement")
    toggle = argparse.BooleanOptionalAction
    group.add_argument("--orient", action=toggle, default=True, help="turn fronts upright by faces")
    group.add_argument("--restore", action=toggle, default=True, help="restore faded colour (_a)")
    group.add_argument(
        "--redeye",
        action=toggle,
        default=False,
        help="remove red eyes in the _a copy (off by default: about 1 in 6 fixes is visibly wrong)",
    )


def add_transport_options(group: "argparse._ArgumentGroup") -> None:
    """How to reach the scanner and what happens to the raw pages: ``--net``, ``--keep-raw``,
    ``--discard-raw``. ``scan`` and ``doc scan`` share them."""
    group.add_argument("--net", type=host, metavar="HOST", help="use a Wi-Fi scanner at HOST")
    raw = group.add_mutually_exclusive_group()
    raw.add_argument(
        "--keep-raw", action="store_true", help="keep the raw pages in DIR/.raw/<UTC time>/"
    )
    raw.add_argument(
        "--discard-raw",
        action="store_true",
        help="delete the raw pages after a clean run even if backs with no writing were dropped",
    )


def add_scan_options(parser: argparse.ArgumentParser) -> None:
    """Options that only matter when pages are scanned."""
    scanning = parser.add_argument_group("scanning")
    scanning.add_argument(
        "--dpi", type=int, choices=SUPPORTED_DPI, default=DEFAULT_DPI, help="scan resolution"
    )
    add_transport_options(scanning)


def prepare_output_root(args: argparse.Namespace) -> Path:
    """``--out`` as an existing folder; it is only created when ``--mkdir`` says so.

    A missing folder is usually an unmounted drive or a typo, so it is not made up silently.
    """
    out: Path = args.out
    if out.is_dir():
        return out
    if out.exists():
        raise CliError(f"{out} exists but is not a folder", EXIT_USAGE)
    if not args.mkdir:
        raise CliError(f"output folder {out} does not exist; create it or pass --mkdir", EXIT_USAGE)
    try:
        out.mkdir(parents=True)
    except OSError as error:
        raise CliError(f"cannot create {out}: {error.strerror or error}") from error
    return out


def build_settings(args: argparse.Namespace) -> ProcessSettings:
    """The processing settings the options describe; a bad value is a usage error.

    Build them before touching the disk or the scanner, so a typo costs nothing.
    """
    enabled = ((args.restore, restore_colour), (args.redeye, remove_red_eye))
    enhancers: tuple[Enhancer, ...] = tuple(func for on, func in enabled if on)
    if args.preset is not None and args.quality is not None:
        raise CliError("--preset sets the quality; use --preset or --quality, not both", EXIT_USAGE)
    try:
        return ProcessSettings(
            output_root=args.out,
            album=args.album,
            prefix=args.prefix,
            date=args.date,
            notes=args.notes,
            duplex=not args.simplex,
            back_policy=BackPolicy(args.backs),
            expect_front_first=args.feed == FEED_FACE_DOWN,
            quality=DEFAULT_QUALITY if args.quality is None else args.quality,
            preset=args.preset,
            keep_original=args.keep_original,
            enhancers=enhancers,
            orienter=auto_orient if args.orient else None,
        )
    except ValueError as error:
        raise CliError(str(error), EXIT_USAGE) from error
