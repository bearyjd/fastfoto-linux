"""``ffscan`` entry point: parse the command line, set up logging, map failures to exit codes."""

import argparse
import contextlib
import logging
import signal
import sys
import threading
import traceback
from collections.abc import Generator, Sequence
from types import FrameType

from fastfoto_linux.cli import cmd_devices, cmd_doc, cmd_library, cmd_process, cmd_scan
from fastfoto_linux.cli.errors import (
    EXIT_INTERRUPTED,
    EXIT_NO_DOCUMENTS,
    EXIT_PROCESSING_ERROR,
    EXIT_SCANNER,
    EXIT_USAGE,
    CliError,
)
from fastfoto_linux.cli.options import add_log_options
from fastfoto_linux.library import stopping
from fastfoto_linux.scanner import (
    NoDocumentsError,
    ScannerDisconnectedError,
    ScannerInUseError,
    ScannerNotFoundError,
    ScannerStuckError,
    ShimMissingError,
)

PROG = "ffscan"
LOG_FORMAT = "%(levelname)s: %(message)s"
PACKAGE_LOGGER = "fastfoto_linux"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Developer command line for the Epson FastFoto FF-680W on Linux.",
    )
    add_log_options(parser, default=False)
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for module in (cmd_devices, cmd_scan, cmd_process, cmd_doc, cmd_library):
        module.add_parser(commands)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``ffscan`` and return its exit code.

    0 ok, 1 processing error, 2 usage, 3 scanner not found, USB shim missing, scanner not
    answering or held by another program, 4 no documents in the feeder, 130 interrupted
    (Ctrl-C, SIGTERM or SIGHUP). User-facing errors are one line on stderr; ``--debug`` adds
    the traceback.
    """
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exit_:  # argparse: --help (0) or a usage error (2)
        code = exit_.code
        return code if isinstance(code, int) else EXIT_USAGE
    with _signals_as_interrupt(), _logging(verbose=args.verbose, debug=args.debug):
        try:
            return args.handler(args)
        except KeyboardInterrupt:
            with contextlib.suppress(OSError):  # a hung-up terminal must not change the exit code
                print(f"{PROG}: interrupted", file=sys.stderr)
            return EXIT_INTERRUPTED
        except Exception as error:  # every failure ends as one line, not a traceback
            return _report(error, debug=args.debug)


def exit_code_for(error: Exception) -> int:
    if isinstance(error, CliError):
        return error.code
    if isinstance(
        error,
        ScannerNotFoundError
        | ShimMissingError
        | ScannerStuckError
        | ScannerInUseError
        | ScannerDisconnectedError,
    ):
        return EXIT_SCANNER
    if isinstance(error, NoDocumentsError):
        return EXIT_NO_DOCUMENTS
    return EXIT_PROCESSING_ERROR


def _report(error: Exception, *, debug: bool) -> int:
    message = " ".join(str(error).split()) or type(error).__name__
    with contextlib.suppress(OSError):  # a hung-up terminal must not change the exit code
        if debug:
            traceback.print_exception(error, file=sys.stderr)
        print(f"{PROG}: error: {message}", file=sys.stderr)
    return exit_code_for(error)


def _raise_interrupt(signum: int, frame: FrameType | None) -> None:
    if stopping.stop_under_way():
        return  # a pooled run is already being stopped; this is a further signal for the same stop
    raise KeyboardInterrupt


@contextlib.contextmanager
def _signals_as_interrupt() -> Generator[None]:
    """Make SIGTERM and SIGHUP act like Ctrl-C for the length of one command.

    Without it, closing the terminal kills ``ffscan`` at once: scanimage, which runs in its own
    session, keeps scanning into a raw folder nobody is told about. As a KeyboardInterrupt the
    signal stops scanimage and keeps the raw pages. The previous handlers come back afterwards;
    outside the main thread (an embedding program) signals are left alone, and so is a signal
    that is ignored (``nohup ffscan scan &``: whoever ignored it wants the scan to outlive the
    terminal).

    Ctrl-C goes through the same handler, which lets a stop that a pooled run has begun
    (``stopping.stop_under_way``) finish: a further signal of any of the three, before ``main`` has
    said "interrupted", is ignored instead of raising again or, with the originals back, killing
    the process by default.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    stopping.forget_stop()
    previous = {
        signum: signal.signal(signum, _raise_interrupt)
        for signum in stopping.STOP_SIGNALS
        if signal.getsignal(signum) is not signal.SIG_IGN
    }
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler if handler is not None else signal.SIG_DFL)
        stopping.forget_stop()


@contextlib.contextmanager
def _logging(*, verbose: bool, debug: bool) -> Generator[None]:
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
