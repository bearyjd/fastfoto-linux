"""The held-out split: derived from a salt, and guarded against leakage."""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fastfoto_linux.evaluation.redeye_manifest import Manifest

HELDOUT_PERCENT = 20


@dataclass(frozen=True)
class Fingerprint:
    id: str
    file_sha256: str
    pixel_sha256: str | None
    group: str | None


def derived_split(salt: str, group: str | None, sha256: str) -> str:
    raise NotImplementedError


def check_declared_splits(manifest: Manifest) -> None:
    """Refuse (``ManifestError``) any declared split that differs from the derived one."""
    raise NotImplementedError


def pixel_digest(img: np.ndarray) -> str:
    """SHA-256 of the decoded RGB bytes plus the shape."""
    raise NotImplementedError


def find_leaks(heldout: Sequence[Fingerprint], tuning: Sequence[Fingerprint]) -> list[str]:
    """Messages (ids and kinds only) for every held-out item that overlaps a tuning item."""
    raise NotImplementedError
