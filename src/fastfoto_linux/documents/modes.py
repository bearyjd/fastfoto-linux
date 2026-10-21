"""Colour modes of a page and what a requested mode can do to a page of a given kind."""

from enum import StrEnum


class ColourMode(StrEnum):
    """What a page holds (its kind), or what the user wants the PDF page to hold."""

    COLOUR = "colour"
    GREY = "grey"
    BW = "bw"


class ColourPolicy(StrEnum):
    """A requested output policy; Auto is never a source pixel kind."""

    AUTO = "auto"
    COLOUR = "colour"
    GREY = "grey"
    BW = "bw"


class CleanupPolicy(StrEnum):
    """How far the paper tone of a grey or colour page is lightened. Off by default."""

    OFF = "off"
    LIGHT = "light"
    STRONG = "strong"


_RICHNESS = {ColourMode.COLOUR: 2, ColourMode.GREY: 1, ColourMode.BW: 0}


def output_mode(kind: ColourMode, requested: ColourMode) -> ColourMode:
    """The mode a page of ``kind`` is written in when ``requested`` is asked for.

    A page can lose colour but never gain it: colour -> grey -> black and white.
    """
    return min(kind, requested, key=_RICHNESS.__getitem__)
