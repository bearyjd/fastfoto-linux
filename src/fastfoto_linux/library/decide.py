"""Decide, for each JPEG, whether its stored orientation needs a further quarter turn."""

import hashlib
import io
import itertools
import logging
import math
import multiprocessing
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import MappingProxyType

import numpy as np
from PIL import Image

from fastfoto_linux.enhance.faces import FaceDetector
from fastfoto_linux.enhance.orient import WORKING_LONG_SIDE_PX, decide_orientation
from fastfoto_linux.library.jpeg_exif import JpegExifError, read_orientation, set_orientation
from fastfoto_linux.library.plan import Action, PlanRow
from fastfoto_linux.library.tags import (
    CLOCKWISE_BY_TAG,
    MIRRORED_TAGS,
    TAG_UPRIGHT,
    compose_tag,
)

logger = logging.getLogger(__name__)

REASON_BACK = "back"
REASON_BACK_LOOKS_LIKE_FRONT = "back-looks-like-front"
REASON_UPRIGHT = "upright"
REASON_UNDECIDED = "undecided"
REASON_UNREADABLE = "unreadable"
REASON_MIRRORED = "mirrored-tag"
REASON_INVALID_TAG = "invalid-tag"
REASON_ROTATE = "faces-upright-after-turn"
REASON_TOO_LARGE = "too-large"
REASON_WORKER_CRASHED = "worker-crashed"
MAX_IMAGE_PIXELS = 200_000_000
BACK_SUFFIX = "_b"
# decide_orientation works at a fixed pixel size and ignores the dpi it is asked to validate.
DETECTION_DPI = 600
PROGRESS_EVERY = 100
CHUNKS_PER_WORKER = 4
MAX_CHUNK = 16
# Pillow's transposes turn counter-clockwise; this maps a clockwise turn of the display.
_PILLOW_TURN = MappingProxyType(
    {
        90: Image.Transpose.ROTATE_270,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_90,
    }
)


def _row(  # noqa: PLR0913
    relative: str,
    action: Action,
    reason: str,
    info: tuple[int, int],
    *,
    rotate_cw: int = 0,
    old_tag: int | None = None,
    new_tag: int | None = None,
    score: float = 0.0,
    sha256: str = "",
) -> PlanRow:
    """A plan row; ``info`` is the file's (size, mtime_ns) as ``fix`` will check them."""
    return PlanRow(
        path=relative,
        action=action,
        rotate_cw=rotate_cw,
        old_tag=old_tag,
        new_tag=new_tag,
        score=score,
        reason=reason,
        size=info[0],
        mtime_ns=info[1],
        sha256=sha256,
    )


def _draft_size(size: tuple[int, int]) -> tuple[int, int] | None:
    """The size to ask the JPEG decoder for, or ``None`` if the image is already small."""
    scale = WORKING_LONG_SIDE_PX / max(size)
    if scale >= 1:
        return None
    return math.ceil(size[0] * scale), math.ceil(size[1] * scale)


def load_working_image(data: bytes, tag: int | None) -> np.ndarray:
    """The photo as displayed (``tag`` applied), RGB uint8, decoded at about the detector size."""
    with Image.open(io.BytesIO(data)) as image:
        requested = _draft_size(image.size)
        if requested is not None:
            image.draft("RGB", requested)
        rgb = image.convert("RGB")
    turn = CLOCKWISE_BY_TAG.get(tag or TAG_UPRIGHT, 0)
    return np.array(rgb if turn == 0 else rgb.transpose(_PILLOW_TURN[turn]))


def _is_back(relative: str) -> bool:
    return Path(relative).stem.lower().endswith(BACK_SUFFIX)


def _decide_data(
    relative: str, data: bytes, info: tuple[int, int], detector: FaceDetector | None
) -> PlanRow:
    stored = read_orientation(data)
    old_tag = TAG_UPRIGHT if stored is None else stored
    handled = old_tag in CLOCKWISE_BY_TAG
    back = _is_back(relative)
    if not (handled or back):
        reason = REASON_MIRRORED if old_tag in MIRRORED_TAGS else REASON_INVALID_TAG
        return _row(relative, Action.SKIP, reason, info, old_tag=old_tag)
    image = load_working_image(data, old_tag if handled else None)
    decision = decide_orientation(image, DETECTION_DPI, detector)
    score = round(max(decision.scores), 3)
    if back:
        reason = REASON_BACK_LOOKS_LIKE_FRONT if decision.confident else REASON_BACK
        return _row(relative, Action.SKIP, reason, info, old_tag=old_tag, score=score)
    if not decision.confident:
        return _row(relative, Action.KEEP, REASON_UNDECIDED, info, old_tag=old_tag, score=score)
    if decision.rotation == 0:
        return _row(relative, Action.KEEP, REASON_UPRIGHT, info, old_tag=old_tag, score=score)
    new_tag = compose_tag(old_tag, decision.rotation)
    set_orientation(data, new_tag)  # a dry run: is the file one that can be written?
    return _row(
        relative,
        Action.ROTATE,
        REASON_ROTATE,
        info,
        rotate_cw=decision.rotation,
        old_tag=old_tag,
        new_tag=new_tag,
        score=score,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def decide_file(src: Path, relative: str, detector: FaceDetector | None = None) -> PlanRow:
    """The plan row for ``src / relative``. Never raises for a bad file: it becomes a skip row."""
    path = src / relative
    try:
        stat = path.stat()
        data = path.read_bytes()
    except OSError:
        return _row(relative, Action.SKIP, REASON_UNREADABLE, (0, 0))
    info = (stat.st_size, stat.st_mtime_ns)
    try:
        return _decide_data(relative, data, info, detector)
    except JpegExifError as error:
        return _row(relative, Action.SKIP, error.reason, info)
    except Exception as error:  # any decoder failure on an odd file is a skip, not a crash
        logger.warning("%s: cannot be analysed (%s)", relative, type(error).__name__)
        return _row(relative, Action.SKIP, REASON_UNREADABLE, info)


def _decide_in_worker(src: str, relative: str) -> PlanRow:
    return decide_file(Path(src), relative)


def _chunk_size(count: int, jobs: int) -> int:
    return min(MAX_CHUNK, max(1, count // (jobs * CHUNKS_PER_WORKER)))


def decide_files(
    src: Path,
    relatives: Sequence[str],
    jobs: int,
    worker: Callable[[str, str], PlanRow] = _decide_in_worker,
) -> tuple[PlanRow, ...]:
    """``decide_file`` for every path, rows in the order given; ``jobs`` > 1 uses processes."""
    if jobs < 1:
        raise ValueError(f"jobs must be at least 1, got {jobs}")
    if not relatives:
        return ()
    if jobs == 1:
        return tuple(decide_file(src, relative) for relative in relatives)
    context = multiprocessing.get_context("forkserver")
    workers = min(jobs, len(relatives))
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
        results = pool.map(
            _decide_in_worker,
            itertools.repeat(str(src)),
            relatives,
            chunksize=_chunk_size(len(relatives), workers),
        )
        rows: list[PlanRow] = []
        for count, row in enumerate(results, start=1):
            rows.append(row)
            if count % PROGRESS_EVERY == 0:
                logger.info("checked %d of %d files", count, len(relatives))
    return tuple(rows)
