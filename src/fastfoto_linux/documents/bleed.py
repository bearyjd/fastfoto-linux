"""Ink from the other side or from a neighbouring sheet (stub: red commit)."""

from collections.abc import Sequence

from fastfoto_linux.documents.draft import BoxN
from fastfoto_linux.documents.marks import Mark
from fastfoto_linux.documents.trim import Trimmed


def show_through(marks: Sequence[Mark], page: Trimmed, partner: Trimmed) -> bool:
    raise NotImplementedError


def set_off(marks: Sequence[BoxN], neighbours: Sequence[Sequence[BoxN]]) -> bool:
    raise NotImplementedError
