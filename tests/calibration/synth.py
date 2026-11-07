"""Tiny synthetic corpora for the calibration tests: generated pixels, nothing from a scanner."""

import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from fastfoto_linux.cli.app import main
from fastfoto_linux.evaluation.redeye_split import derived_split
from tests.corpus.helpers import SEED, document, encode, sha
from tests.doc_synth import to_bilevel
from tests.documents.auto_helpers import auto_page
from tests.documents.deskew_fixtures import PAPER, skewed, text_page

DOC_DPI = 150
AUTO_DPI = 100


def png(pixels: np.ndarray, *, dpi: int | None = None, bilevel: bool = False) -> bytes:
    picture = Image.fromarray(pixels >= 128) if bilevel else Image.fromarray(pixels)
    extra = {} if dpi is None else {"dpi": (dpi, dpi)}
    out = io.BytesIO()
    picture.save(out, "PNG", **extra)
    return out.getvalue()


def text_png(tenths: int, seed: int = 1) -> bytes:
    """A page of text turned clockwise by ``tenths``/10 degrees (so ``-tenths`` levels it)."""
    rng = np.random.default_rng(seed)
    page = text_page(rng, dpi=DOC_DPI, width_mm=100, height_mm=130, margin_mm=10)
    return png(skewed(page, tenths), dpi=DOC_DPI)


def blank_png() -> bytes:
    return png(np.full((768, 591), PAPER, np.uint8), dpi=DOC_DPI)


def colour_png(case: str) -> bytes:
    return png(auto_page(case, AUTO_DPI).pixels, dpi=AUTO_DPI)


def bilevel_png() -> bytes:
    return png(to_bilevel(auto_page("text", AUTO_DPI).pixels), dpi=AUTO_DPI, bilevel=True)


def wb_png(cast: bool) -> bytes:
    """A grey ramp, with a warm cast when ``cast``."""
    ramp = np.tile(np.linspace(0, 255, 160), (60, 1))
    gains = (1.0, 0.8, 0.55) if cast else (1.0, 1.0, 1.0)
    return png(np.stack([ramp * g for g in gains], axis=-1).astype(np.uint8))


def detail_png(seed: int = 0) -> bytes:
    """A noisy picture with a soft vertical step at x = 80."""
    rng = np.random.default_rng(seed)
    base = np.full((96, 128), 90.0)
    base[:, 82:] = 190.0
    base[:, 79:82] = [110.0, 140.0, 170.0]  # 3-pixel ramp
    pixels = base[..., None] + rng.normal(0, 8, (96, 128, 3))
    return png(np.clip(pixels, 0, 255).astype(np.uint8))


DESKEW_NOTE = {"correction_tenths": [0]}
WB_NOTE = {"neutral_boxes": [[60, 20, 40, 20]], "cast": False}
DETAIL_NOTE = {
    "dpi": 300,
    "flat_boxes": [[4, 4, 56, 88]],
    "edge_boxes": [{"box": [66, 10, 28, 70], "axis": "h"}],
}


@dataclass(frozen=True)
class Entry:
    name: str
    data: bytes
    kind: str
    split: str = "tuning"
    annotations: dict = field(default_factory=dict)


def _group_for(split: str, digest: str) -> str:
    for number in range(10_000):
        group = f"g{number}"
        if derived_split(SEED, group, digest) == split:
            return group
    raise AssertionError("no group found")


def write_corpus(root: Path, entries: list[Entry]) -> Path:
    """Write the files and a MANIFEST.json; each item's group is chosen to land in its split."""
    root.mkdir(parents=True, exist_ok=True)
    items = []
    for entry in entries:
        (root / f"{entry.name}.png").write_bytes(entry.data)
        digest = sha(entry.data)
        group = _group_for(entry.split, digest)
        items.append(
            {
                "id": f"item-{entry.name}",
                "path": f"{entry.name}.png",
                "sha256": digest,
                "kind": entry.kind,
                "split": entry.split,
                "group": group,
                "source": "synthetic test pixels",
                "licence": "CC0-1.0",
                "consent_scope": "private-eval",
                "annotations": entry.annotations,
            }
        )
    manifest = root / "MANIFEST.json"
    manifest.write_bytes(encode(document(items)))
    return manifest


def manifest_sha(manifest: Path) -> str:
    return sha(manifest.read_bytes())


def run_cli(*argv: object) -> int:
    return main(["eval", *map(str, argv)])


def reports(out: Path) -> list[Path]:
    return sorted(out.glob("run-*/report.json"))
