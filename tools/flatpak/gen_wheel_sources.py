"""Write the Flatpak modules that install the Python wheels offline (stub: see the tests)."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


class WheelSelectionError(Exception):
    """No wheel (or no usable one) for a package."""


@dataclass(frozen=True)
class Wheel:
    name: str
    version: str
    filename: str
    url: str
    sha256: str


def runtime_wheels(lock: Mapping[str, Any]) -> tuple[Wheel, ...]:
    raise NotImplementedError


def runtime_module(lock: Mapping[str, Any]) -> dict[str, Any]:
    raise NotImplementedError


def build_wheels(
    requirements: str, lookup: Callable[[str, str], Sequence[Mapping[str, str]]]
) -> tuple[Wheel, ...]:
    raise NotImplementedError


def build_module(wheels: Sequence[Wheel]) -> dict[str, Any]:
    raise NotImplementedError


def render(module: Mapping[str, Any]) -> str:
    raise NotImplementedError


def main(
    argv: Sequence[str] | None = None,
    *,
    lookup: Callable[[str, str], Sequence[Mapping[str, str]]] | None = None,
) -> int:
    raise NotImplementedError
