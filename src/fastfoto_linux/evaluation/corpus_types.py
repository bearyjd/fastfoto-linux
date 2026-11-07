"""Types of the corpus manifest: the error, the items, and the manifest that pins a directory."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


class CorpusError(ValueError):
    """The corpus manifest, its location or one of its files is not acceptable."""


@dataclass(frozen=True)
class CorpusItem:
    id: str
    path: str
    sha256: str
    kind: str
    split: str
    source: str
    licence: str
    consent_scope: str
    annotations: Mapping[str, object]
    group: str | None = None


@dataclass(frozen=True)
class CorpusManifest:
    """A validated manifest. ``root_fd`` pins the manifest's directory; the caller closes it."""

    split_seed: str
    items: tuple[CorpusItem, ...]
    sha256: str
    root: Path | None = None
    root_fd: int | None = field(default=None, repr=False)

    def close(self) -> None:
        if self.root_fd is not None:
            fd = self.root_fd
            object.__setattr__(self, "root_fd", None)  # frozen: only close() lets go of the fd
            os.close(fd)

    def __enter__(self) -> "CorpusManifest":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
