"""``ffscan library``: find and fix sideways photos in an existing library, losslessly."""

import argparse
import contextlib
import logging
import os
import sys
from collections.abc import Iterator
from pathlib import Path

from fastfoto_linux.cli.errors import EXIT_OK, EXIT_PROCESSING_ERROR, EXIT_USAGE, CliError
from fastfoto_linux.cli.options import common_parent, prepare_output_root
from fastfoto_linux.library.apply import apply_plan
from fastfoto_linux.library.decide import decide_files
from fastfoto_linux.library.plan import PlanError, read_plan, write_plan
from fastfoto_linux.library.safety import UnsafePathError, check_plan_output, check_roots
from fastfoto_linux.library.summary import fix_problems, format_check, format_fix, summarize_check
from fastfoto_linux.library.walk import walk_library

logger = logging.getLogger(__name__)

MAX_DEFAULT_JOBS = 4


def _jobs(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"jobs must be a whole number of at least 1, got {text!r}")
    return value


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser(
        "library",
        help="fix sideways photos in an existing library",
        description="Two steps, so nothing is written before you have looked: 'check' makes a "
        "plan, 'fix' writes corrected copies of the photos the plan says to rotate into a "
        "separate folder. Only the EXIF Orientation tag changes; the library is never modified.",
    )
    commands = parser.add_subparsers(dest="library_command", required=True, metavar="COMMAND")
    _add_check(commands)
    _add_fix(commands)


def _add_check(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = commands.add_parser(
        "check",
        parents=[common_parent()],
        help="decide which photos are sideways and write a plan",
        description="Walk SRC, decide each JPEG's orientation from the faces in it and write the "
        "plan as a CSV file. Nothing else is written.",
    )
    parser.add_argument("src", type=Path, metavar="SRC", help="the library folder (read only)")
    parser.add_argument(
        "--plan", type=Path, required=True, metavar="PLAN.csv", help="plan to write"
    )
    default_jobs = min(MAX_DEFAULT_JOBS, os.cpu_count() or 1)
    parser.add_argument(
        "--jobs",
        type=_jobs,
        default=default_jobs,
        metavar="N",
        help=f"worker processes (default: {default_jobs})",
    )
    parser.set_defaults(handler=run_check)


def _add_fix(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = commands.add_parser(
        "fix",
        parents=[common_parent()],
        help="write corrected copies of the photos a plan says to rotate",
        description="For each 'rotate' row of the plan write DEST/<path>: the file from SOURCE "
        "with only its EXIF Orientation tag changed. Existing files in DEST are never replaced "
        "and rows whose file changed since the check are refused.",
    )
    parser.add_argument("plan", type=Path, metavar="PLAN.csv", help="plan made by 'check'")
    parser.add_argument("--source", type=Path, required=True, metavar="SRC", help="the library")
    parser.add_argument("--out", type=Path, required=True, metavar="DEST", help="folder for copies")
    parser.add_argument("--mkdir", action="store_true", help="create --out if it does not exist")
    parser.set_defaults(handler=run_fix)


@contextlib.contextmanager
def _as_usage_errors() -> Iterator[None]:
    try:
        yield
    except (UnsafePathError, PlanError) as error:
        raise CliError(str(error), EXIT_USAGE) from error


def _existing_folder(path: Path) -> Path:
    if not path.is_dir():
        raise CliError(f"{path} is not a folder", EXIT_USAGE)
    return path


def run_check(args: argparse.Namespace) -> int:
    src = _existing_folder(args.src)
    with _as_usage_errors():
        plan_path = check_plan_output(args.plan, src)
    walk = walk_library(src)
    logger.info("found %d JPEG files; deciding with %d worker(s)", len(walk.jpegs), args.jobs)
    rows = decide_files(src, walk.jpegs, args.jobs)
    write_plan(plan_path, rows)
    print(format_check(summarize_check(walk, rows), args.plan))
    return EXIT_OK


def run_fix(args: argparse.Namespace) -> int:
    src = _existing_folder(args.source)
    with _as_usage_errors():
        check_roots(src, args.out)
        rows = read_plan(args.plan, src)
    prepare_output_root(args)
    with _as_usage_errors():
        result = apply_plan(rows, src, args.out)
    print(format_fix(result, args.out))
    problems = fix_problems(result)
    for line in problems:
        print(line, file=sys.stderr)
    return EXIT_PROCESSING_ERROR if problems else EXIT_OK
