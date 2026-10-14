"""``ffscan`` entry point: parse the command line, set up logging, map failures to exit codes."""

import argparse
import contextlib
import logging
import sys
import traceback
from collections.abc import Iterator, Sequence

from fastfoto_linux.cli import cmd_devices, cmd_process, cmd_scan
from fastfoto_linux.cli.errors import (
    EXIT_INTERRUPTED,
    EXIT_NO_DOCUMENTS,
    EXIT_PROCESSING_ERROR,
    EXIT_SCANNER,
    EXIT_USAGE,
    CliError,
)
from fastfoto_linux.scanner import NoDocumentsError, ScannerNotFoundError, ShimMissingError

PROG = "ffscan"
LOG_FORMAT = "%(levelname)s: %(message)s"
PACKAGE_LOGGER = "fastfoto_linux"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Developer command line for the Epson FastFoto FF-680W on Linux.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for module in (cmd_devices, cmd_scan, cmd_process):
        module.add_parser(commands)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``ffscan`` and return its exit code.

    0 ok, 1 processing error, 2 usage, 3 scanner not found or USB shim missing, 4 no documents
    in the feeder, 130 interrupted. User-facing errors are one line on stderr; ``--debug`` adds
    the traceback.
    """
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exit_:  # argparse: --help (0) or a usage error (2)
        return exit_.code if isinstance(exit_.code, int) else EXIT_USAGE
    with _logging(verbose=args.verbose, debug=args.debug):
        try:
            return args.handler(args)
        except KeyboardInterrupt:
            print(f"{PROG}: interrupted", file=sys.stderr)
            return EXIT_INTERRUPTED
        except Exception as error:  # every failure ends as one line, not a traceback
            return _report(error, debug=args.debug)


def exit_code_for(error: Exception) -> int:
    if isinstance(error, CliError):
        return error.code
    if isinstance(error, ScannerNotFoundError | ShimMissingError):
        return EXIT_SCANNER
    if isinstance(error, NoDocumentsError):
        return EXIT_NO_DOCUMENTS
    return EXIT_PROCESSING_ERROR


def _report(error: Exception, *, debug: bool) -> int:
    if debug:
        traceback.print_exception(error, file=sys.stderr)
    message = " ".join(str(error).split()) or type(error).__name__
    print(f"{PROG}: error: {message}", file=sys.stderr)
    return exit_code_for(error)


@contextlib.contextmanager
def _logging(*, verbose: bool, debug: bool) -> Iterator[None]:
    """Log the package's messages to the current stderr for the length of one command.

    A handler on the package logger, not ``basicConfig``: the root logger stays untouched, and
    repeated calls (tests, an embedding program) leave nothing behind.
    """
    logger = logging.getLogger(PACKAGE_LOGGER)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    level = logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(level)
    try:
        yield
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
