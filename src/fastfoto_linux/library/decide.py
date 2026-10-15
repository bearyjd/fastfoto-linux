"""Decide, for each JPEG, whether its stored orientation needs a further quarter turn."""

import contextlib
import hashlib
import io
import logging
import math
import multiprocessing
import os
import signal
import warnings
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import numpy as np
from PIL import Image

from fastfoto_linux.enhance.faces import FaceDetector
from fastfoto_linux.enhance.orient import WORKING_LONG_SIDE_PX, decide_orientation
from fastfoto_linux.library import fdio
from fastfoto_linux.library.exif_errors import JpegExifError
from fastfoto_linux.library.jpeg_exif import read_orientation, set_orientation
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
WINDOW_PER_WORKER = 2  # files in flight per worker; the few a crash can implicate
# Set when this module is imported, so forkserver workers (which import it too) inherit the limit.
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
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
    with warnings.catch_warnings():
        # Pillow only warns between one and two times the pixel limit; treat that as an error too.
        warnings.simplefilter("error", Image.DecompressionBombWarning)
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
    try:
        found = fdio.read_regular(src / relative)
    except fdio.TooLargeError:
        return _row(relative, Action.SKIP, REASON_TOO_LARGE, (0, 0))
    except OSError:  # gone, a link, a pipe or device, unreadable, changed while it was read
        return _row(relative, Action.SKIP, REASON_UNREADABLE, (0, 0))
    info = (found.size, found.mtime_ns)
    try:
        return _decide_data(relative, found.data, info, detector)
    except JpegExifError as error:
        return _row(relative, Action.SKIP, error.reason, info)
    except (MemoryError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return _row(relative, Action.SKIP, REASON_TOO_LARGE, info)
    except Exception as error:  # any decoder failure on an odd file is a skip, not a crash
        logger.warning("%r: cannot be analysed (%s)", relative, type(error).__name__)
        return _row(relative, Action.SKIP, REASON_UNREADABLE, info)


def _decide_in_worker(src: str, relative: str) -> PlanRow:
    return decide_file(Path(src), relative)


def _ignore_interrupt() -> None:
    """Workers leave Ctrl-C to the parent, which cancels the queue and exits."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)


@contextlib.contextmanager
def _pool(workers: int) -> Iterator[ProcessPoolExecutor]:
    """A worker pool that is shut down at once, queue cancelled, if anything interrupts it."""
    pool = ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("forkserver"),
        initializer=_ignore_interrupt,
    )
    try:
        yield pool
    except BaseException:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown(wait=True)


@dataclass(frozen=True)
class _Job:
    """What every file of one pooled ``check`` shares."""

    src: Path
    workers: int
    worker: Callable[[str, str], PlanRow]
    total: int


def _crashed_row(src: Path, relative: str) -> PlanRow:
    try:
        info = os.lstat(src / relative)
        sizes = (info.st_size, info.st_mtime_ns)
    except OSError:
        sizes = (0, 0)
    return _row(relative, Action.SKIP, REASON_WORKER_CRASHED, sizes)


def _decide_alone(job: _Job, relative: str) -> PlanRow:
    """One file in a worker of its own: if that worker dies, the file is the culprit."""
    with _pool(1) as pool:
        try:
            return pool.submit(job.worker, str(job.src), relative).result()
        except BrokenProcessPool:
            return _crashed_row(job.src, relative)


def _salvage(in_flight: dict[Future[PlanRow], str], done: dict[str, PlanRow]) -> list[str]:
    """Keep the results that finished before the pool broke; the rest are the suspects."""
    suspects = []
    for future, relative in in_flight.items():
        if future.done() and not future.cancelled() and future.exception() is None:
            done[relative] = future.result()
        else:
            suspects.append(relative)
    return suspects


def _log_progress(count: int, total: int) -> None:
    if count % PROGRESS_EVERY == 0:
        logger.info("checked %d of %d files", count, total)


def _run_pool(
    job: _Job, queue: Sequence[str], done: dict[str, PlanRow]
) -> tuple[list[str], list[str]]:
    """Decide ``queue`` into ``done`` until it is empty or the pool breaks.

    Returns ``(suspects, left)``: the files that were in flight when the pool broke, and those
    never submitted. Only a few files are in flight at a time, so a crash implicates few.
    """
    in_flight: dict[Future[PlanRow], str] = {}
    position = 0
    with _pool(job.workers) as pool:
        while position < len(queue) or in_flight:
            while position < len(queue) and len(in_flight) < job.workers * WINDOW_PER_WORKER:
                relative = queue[position]
                position += 1
                try:
                    in_flight[pool.submit(job.worker, str(job.src), relative)] = relative
                except BrokenProcessPool:  # a worker died since the last result came in
                    return [*_salvage(in_flight, done), relative], list(queue[position:])
            finished, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in finished:
                try:
                    row = future.result()
                except BrokenProcessPool:
                    return _salvage(in_flight, done), list(queue[position:])
                done[in_flight.pop(future)] = row
                _log_progress(len(done), job.total)
    return [], []


def _decide_in_pool(job: _Job, relatives: Sequence[str]) -> tuple[PlanRow, ...]:
    done: dict[str, PlanRow] = {}
    queue = list(relatives)
    while queue:
        suspects, queue = _run_pool(job, queue, done)
        for relative in suspects:  # one at a time, each in a worker of its own
            done[relative] = _decide_alone(job, relative)
            _log_progress(len(done), job.total)
    return tuple(done[relative] for relative in relatives)


def decide_files(
    src: Path,
    relatives: Sequence[str],
    jobs: int,
    worker: Callable[[str, str], PlanRow] = _decide_in_worker,
) -> tuple[PlanRow, ...]:
    """``decide_file`` for every path, rows in the order given; ``jobs`` > 1 uses processes.

    A worker that dies (out of memory, a crash in a decoder) costs only the file it was on: that
    file becomes a ``worker-crashed`` skip row and the others carry on. Ctrl-C cancels the queue.
    """
    if jobs < 1:
        raise ValueError(f"jobs must be at least 1, got {jobs}")
    if not relatives:
        return ()
    if jobs == 1:
        return tuple(decide_file(src, relative) for relative in relatives)
    return _decide_in_pool(_Job(src, min(jobs, len(relatives)), worker, len(relatives)), relatives)
