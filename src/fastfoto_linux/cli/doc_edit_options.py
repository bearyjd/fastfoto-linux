"""Edit options of ``ffscan doc process``: which pages stay, their order, turns and PDFs."""

import argparse

ANGLES = (90, 180, 270)
EDIT_OPTIONS = ("--drop", "--keep", "--rotate", "--split", "--order", "--part-name", "--dry-run")


def add_edit_options(parser: argparse.ArgumentParser) -> None:
    raise NotImplementedError
