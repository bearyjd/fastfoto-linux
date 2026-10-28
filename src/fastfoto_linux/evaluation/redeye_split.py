"""The held-out split: derived from a salt, and guarded against leakage."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fastfoto_linux.evaluation.redeye_manifest import Manifest, ManifestError

HELDOUT_PERCENT = 20
MAX_LEAK_EXAMPLES = 5
_KINDS = ("id", "file hash", "pixel hash", "group")


@dataclass(frozen=True)
class Fingerprint:
    id: str
    file_sha256: str
    pixel_sha256: str | None
    group: str | None


def _keys(print_: Fingerprint) -> list[tuple[str, str]]:
    values = (print_.id, print_.file_sha256, print_.pixel_sha256, print_.group)
    return [(kind, v) for kind, v in zip(_KINDS, values, strict=True) if v is not None]


def derived_split(salt: str, group: str | None, sha256: str) -> str:
    """ "heldout" for ``HELDOUT_PERCENT`` of the (salt, group-or-hash) space, else "tuning"."""
    digest = hashlib.sha256(f"{salt}:{group or sha256}".encode()).hexdigest()
    return "heldout" if int(digest[:8], 16) % 100 < HELDOUT_PERCENT else "tuning"


def check_declared_splits(manifest: Manifest) -> None:
    """Refuse (``ManifestError``) any declared split that differs from the derived one."""
    for item in manifest.images:
        if item.split != derived_split(manifest.split_salt, item.group, item.sha256):
            raise ManifestError(f"declared split of image {item.id!r} differs from the derived one")


def pixel_digest(img: np.ndarray) -> str:
    """SHA-256 of the decoded RGB bytes plus the shape."""
    digest = hashlib.sha256(str(img.shape).encode())
    digest.update(np.ascontiguousarray(img).tobytes())
    return digest.hexdigest()


def count_leaks(
    heldout: Sequence[Fingerprint], tuning: Sequence[Fingerprint]
) -> tuple[int, list[str]]:
    """How many held-out items overlap a tuning item, and a few example messages.

    Indexed by key, so time and memory are linear however many items share a key.
    """
    index: dict[str, dict[str, str]] = {kind: {} for kind in _KINDS}
    for tune in tuning:
        for kind, value in _keys(tune):
            index[kind].setdefault(value, tune.id)
    total = 0
    examples: list[str] = []
    for held in heldout:
        shared = [(kind, index[kind][v]) for kind, v in _keys(held) if v in index[kind]]
        if not shared:
            continue
        total += 1
        if len(examples) < MAX_LEAK_EXAMPLES:
            kinds = ", ".join(kind for kind, _ in shared)
            examples.append(f"held-out {held.id!r} shares {kinds} with tuning {shared[0][1]!r}")
    return total, examples


def find_leaks(heldout: Sequence[Fingerprint], tuning: Sequence[Fingerprint]) -> list[str]:
    """Example messages (ids and kinds only) for held-out items that overlap a tuning item."""
    return count_leaks(heldout, tuning)[1]
