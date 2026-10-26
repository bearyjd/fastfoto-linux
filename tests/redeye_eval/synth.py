"""Synthetic evaluation corpora, painted in code: no photographs, no private data.

Faces come from ``KeyedDetector``, a stub that answers with known landmarks for each image, so
neither YuNet nor a model file is needed. Like tests/photo_edits/PROVENANCE.md says of the other
synthetic eyes, these fixtures cannot say anything about real-world precision or recall.
"""

import hashlib
import io
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from fastfoto_linux.enhance.faces import Face
from fastfoto_linux.evaluation.redeye_split import derived_split

SALT = "0123456789abcdef"
HEIGHT, WIDTH = 240, 320
DPI = 300
IOD = 80
CENTRE = (160, 100)
RED = (220, 30, 30)
DARK = (25, 25, 25)
SKIN = (190, 150, 130)
SCORE = 0.97
RIGHTS = {
    "licence": "synthetic",
    "source": "generated in code",
    "consent_scope": None,
    "redistributable": True,
}


@dataclass
class SynthItem:
    id: str
    arr: np.ndarray
    faces: list[dict] = field(default_factory=list)
    negatives: list[dict] = field(default_factory=list)
    detections: list[Face] = field(default_factory=list)
    group: str | None = None
    dpi: int = DPI

    def png(self) -> bytes:
        return png_bytes(self.arr)

    def sha256(self) -> str:
        return hashlib.sha256(self.png()).hexdigest()

    def entry(self, split: str) -> dict:
        entry = {
            "id": self.id,
            "path": f"{self.id}.png",
            "sha256": self.sha256(),
            "dpi": self.dpi,
            "upright": True,
            "split": split,
            "rights": dict(RIGHTS),
            "faces": self.faces,
            "negatives": self.negatives,
        }
        if self.group is not None:
            entry["group"] = self.group
        return entry


def png_bytes(arr: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(arr).save(buffer, format="PNG", compress_level=1)
    return buffer.getvalue()


def pixel_key(arr: np.ndarray) -> str:
    return hashlib.sha256(arr.tobytes()).hexdigest()


def skin() -> np.ndarray:
    arr = np.empty((HEIGHT, WIDTH, 3), dtype=np.uint8)
    arr[:] = SKIN
    arr[..., 0] += (np.arange(WIDTH) // 16).astype(np.uint8)[np.newaxis, :]
    return arr


def disc(arr: np.ndarray, cx: float, cy: float, r: float, colour: tuple[int, int, int]) -> None:
    rows, cols = np.ogrid[: arr.shape[0], : arr.shape[1]]
    arr[(cols + 0.5 - cx) ** 2 + (rows + 0.5 - cy) ** 2 <= r * r] = colour


def eye_points(centre: tuple[int, int] = CENTRE, iod: int = IOD) -> tuple[tuple[float, float], ...]:
    return ((centre[0] - iod / 2, float(centre[1])), (centre[0] + iod / 2, float(centre[1])))


def detection(points: tuple[tuple[float, float], ...], score: float = SCORE) -> Face:
    (x0, y0), (x1, y1) = points
    nose = ((x0 + x1) / 2, y0 + 30.0)
    mouth = ((nose[0] - 10, nose[1] + 20), (nose[0] + 10, nose[1] + 20))
    return Face(x0 - 20, y0 - 30, x1 - x0 + 40, 90.0, (*points, nose, *mouth), score)


def gt_face(face_id: str, points, red: tuple[bool, bool], r: float = 5.0) -> dict:
    eyes = [
        {"x": p[0], "y": p[1], "r": r, "red": flag} for p, flag in zip(points, red, strict=True)
    ]
    return {"id": face_id, "eyes": eyes}


def positive(
    item_id: str,
    *,
    red: tuple[bool, bool] = (True, True),
    centre: tuple[int, int] = CENTRE,
    iod: int = IOD,
    r: float = 5.0,
    score: float = SCORE,
) -> SynthItem:
    arr = skin()
    points = eye_points(centre, iod)
    for point, flag in zip(points, red, strict=True):
        disc(arr, point[0], point[1], r, RED if flag else DARK)
    return SynthItem(item_id, arr, [gt_face("f1", points, red, r)], [], [detection(points, score)])


def _block(arr, x, y):
    arr[y - 30 : y + 30, x - 30 : x + 30] = RED


def _lips(arr, x, y):
    rows, cols = np.ogrid[: arr.shape[0], : arr.shape[1]]
    arr[((cols - x) / 18.0) ** 2 + ((rows - y) / 8.0) ** 2 <= 1.0] = RED


def _jewelry(arr, x, y):
    disc(arr, x, y, 2.0, RED)


def _sign(arr, x, y):
    arr[y - 10 : y - 7, x - 12 : x + 12] = RED
    arr[y - 10 : y + 10, x - 1 : x + 2] = RED


def _flower(arr, x, y):
    disc(arr, x, y, 14.0, RED)


def _text(arr, x, y):
    arr[y - 7 : y + 7, x - 6 : x - 4] = RED
    arr[y - 7 : y + 7, x + 4 : x + 6] = RED


def _spectacles(arr, x, y):
    disc(arr, x, y, 9.0, RED)
    disc(arr, x, y, 6.0, DARK)


def _dark(arr, x, y):
    disc(arr, x, y, 5.0, DARK)


PAINTERS: dict[str, Callable[[np.ndarray, int, int], None]] = {
    "red_clothing": _block,
    "lips": _lips,
    "jewelry": _jewelry,
    "signs": _sign,
    "flowers": _flower,
    "printed_text": _text,
    "spectacles": _spectacles,
    "non_red_pupils": _dark,
}


def negative(item_id: str, category: str, *, score: float = SCORE) -> SynthItem:
    """A face-less or non-red image with the red-looking ``category`` thing on both landmarks."""
    arr = skin()
    points = eye_points()
    for x, y in points:
        PAINTERS[category](arr, int(x), int(y))
    changed = np.any(arr != skin(), axis=2)
    ys, xs = np.nonzero(changed)
    box = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
    faces = []
    if category in ("spectacles", "non_red_pupils"):
        faces = [gt_face("f1", points, (False, False))]
    return SynthItem(
        item_id,
        arr,
        faces,
        [{"category": category, "box": box}],
        [detection(points, score)],
    )


def with_split(item: SynthItem, want: str, salt: str = SALT) -> SynthItem:
    """``item`` nudged (a corner pixel, or its group name) until the derived split is ``want``."""
    for counter in range(2000):
        arr = item.arr.copy()
        arr[0, 0] = (counter % 256, counter // 256, 7)
        group = None if item.group is None else f"{item.group}-{counter}"
        candidate = SynthItem(
            item.id, arr, item.faces, item.negatives, item.detections, group, item.dpi
        )
        if derived_split(salt, group, candidate.sha256()) == want:
            return candidate
    raise AssertionError("no variant found")


class KeyedDetector:
    """Answers with the faces registered for an image's exact pixels, and nothing otherwise."""

    def __init__(self, items: list[SynthItem]) -> None:
        self._faces = {pixel_key(item.arr): tuple(item.detections) for item in items}
        self.calls = 0

    def detect(self, img_rgb: np.ndarray) -> tuple[Face, ...]:
        self.calls += 1
        return self._faces.get(pixel_key(img_rgb), ())


def manifest_dict(
    items: list[SynthItem],
    salt: str = SALT,
    splits: dict[str, str] | None = None,
    default: str | None = None,
):
    """The manifest; a split is the one given for the id, else ``default``, else the derived one."""
    chosen = splits or {}
    return {
        "format": "fastfoto-redeye-eval",
        "version": 1,
        "split_salt": salt,
        "images": [
            item.entry(
                chosen.get(item.id) or default or derived_split(salt, item.group, item.sha256())
            )
            for item in items
        ],
    }


def write_corpus(root: Path, items: list[SynthItem], salt: str = SALT, **kwargs) -> Path:
    """Write the PNGs and ``manifest.json`` under ``root``; return the manifest path."""
    root.mkdir(parents=True, exist_ok=True)
    for item in items:
        (root / f"{item.id}.png").write_bytes(item.png())
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest_dict(items, salt, **kwargs)))
    return path


def clean_heldout_set(prefix: str = "h") -> list[SynthItem]:
    """Held-out items: two positives and a negative of every painted category."""
    items = [
        with_split(positive(f"{prefix}-pos{i}", red=(True, True)), "heldout") for i in range(2)
    ]
    items += [
        with_split(negative(f"{prefix}-neg-{category}", category), "heldout")
        for category in PAINTERS
    ]
    return items
