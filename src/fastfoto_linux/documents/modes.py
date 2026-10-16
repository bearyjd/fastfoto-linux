"""Colour modes of a page and what a requested mode can do to a page of a given kind."""

from enum import StrEnum


class ColourMode(StrEnum):
    """What a page holds (its kind), or what the user wants the PDF page to hold."""

    COLOUR = "colour"
    GREY = "grey"
    BW = "bw"


def output_mode(kind: ColourMode, requested: ColourMode) -> ColourMode:
    """The mode a page of ``kind`` is written in when ``requested`` is asked for.

    A page can lose colour but never gain it: colour -> grey -> black and white.
    """
    raise NotImplementedError
