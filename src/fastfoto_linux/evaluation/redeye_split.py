"""The held-out split: derived from a salt, and guarded against leakage."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fastfoto_linux.evaluation.redeye_manifest import Manifest, ManifestError

HELDOUT_PERCENT = 20


@dataclass(frozen=True)
class Fingerprint:
    id: str
    file_sha256: str
    pixel_sha256: str | None
    group: str | None


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


def find_leaks(heldout: Sequence[Fingerprint], tuning: Sequence[Fingerprint]) -> list[str]:
    """Messages (ids and kinds only) for every held-out item that overlaps a tuning item."""
    leaks: list[str] = []
    for held in heldout:
        for tune in tuning:
            shared = [
                kind
                for kind, a, b in (
                    ("id", held.id, tune.id),
                    ("file hash", held.file_sha256, tune.file_sha256),
                    ("pixel hash", held.pixel_sha256, tune.pixel_sha256),
                    ("group", held.group, tune.group),
                )
                if a is not None and a == b
            ]
            if shared:
                leaks.append(
                    f"held-out {held.id!r} shares {', '.join(shared)} with tuning {tune.id!r}"
                )
    return leaks


def count_leaks(
    heldout: Sequence[Fingerprint], tuning: Sequence[Fingerprint]
) -> tuple[int, list[str]]:
    messages = find_leaks(heldout, tuning)
    return len(messages), messages
