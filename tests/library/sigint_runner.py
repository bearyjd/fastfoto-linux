"""``ffscan library check`` with workers that stay busy: the process the Ctrl-C test signals."""

import functools
import sys

from fastfoto_linux.cli import cmd_library
from fastfoto_linux.cli.app import main
from fastfoto_linux.library.decide import decide_files
from tests.library import crash_worker


def run(argv: list[str]) -> int:
    cmd_library.decide_files = functools.partial(decide_files, worker=crash_worker.busy_forever)
    return main(argv)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
