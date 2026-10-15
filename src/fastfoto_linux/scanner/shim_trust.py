"""Which USB gap shim may be preloaded into scanimage: who owns it and who can change it."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TRUST_ROOT = Path("/")
SHIM_TRUST_ROOT = DEFAULT_TRUST_ROOT


@dataclass(frozen=True)
class ShimChoice:
    """The shim to use (None when no candidate is usable) and why the others were refused."""

    path: Path | None
    refused: tuple[str, ...] = ()


def select_shim(candidates: Sequence[Path]) -> ShimChoice:
    raise NotImplementedError
