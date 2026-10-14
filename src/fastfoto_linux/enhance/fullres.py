"""Face detection that is precise at full resolution on photos larger than the working size.

YuNet is run on a copy whose long side is at most ``DETECT_LONG_SIDE_PX``; each face found is
then detected again on a crop of the original around it (also kept within that size), because
landmarks from the shrunken copy can be off by more than a pupil is wide. Resizing maps points
with pixel centres: ``full = (small + 0.5) * scale - 0.5``.
"""

import math

import cv2
import numpy as np

from fastfoto_linux.enhance.faces import Face, FaceDetector, default_detector, ensure_rgb_uint8

# Detector input size in pixels (not a physical length).
DETECT_LONG_SIDE_PX = 1000
FACE_CROP_MARGIN = 0.5  # of the face's larger side, added on every side of the crop
# Two refined faces whose eyes are this close (as a fraction of the inter-ocular distance) are one.
DUPLICATE_EYE_FRACTION = 0.5

Box = tuple[int, int, int, int]


def _resized(img: np.ndarray) -> tuple[np.ndarray, float, float]:
    """``img`` shrunk to ``DETECT_LONG_SIDE_PX`` with the exact x and y scales that were used."""
    height, width = img.shape[:2]
    scale = DETECT_LONG_SIDE_PX / max(height, width)
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return cv2.resize(img, size, interpolation=cv2.INTER_AREA), width / size[0], height / size[1]


def _to_full(face: Face, scale_x: float, scale_y: float, left: int, top: int) -> Face:
    def point(x: float, y: float) -> tuple[float, float]:
        return (x + 0.5) * scale_x - 0.5 + left, (y + 0.5) * scale_y - 0.5 + top

    x, y = point(face.x, face.y)
    return Face(
        x=x,
        y=y,
        width=face.width * scale_x,
        height=face.height * scale_y,
        landmarks=tuple(point(px, py) for px, py in face.landmarks),
        score=face.score,
    )


def _detect_region(img: np.ndarray, box: Box, detector: FaceDetector) -> tuple[Face, ...]:
    """Faces in ``img[box]``, in ``img`` coordinates; the region is shrunk if it is too large."""
    left, top, right, bottom = box
    region = img[top:bottom, left:right]
    scale_x = scale_y = 1.0
    if max(region.shape[:2]) > DETECT_LONG_SIDE_PX:
        region, scale_x, scale_y = _resized(region)
    return tuple(_to_full(f, scale_x, scale_y, left, top) for f in detector.detect(region))


def _crop_box(face: Face, shape: tuple[int, ...]) -> Box:
    height, width = shape[:2]
    margin = FACE_CROP_MARGIN * max(face.width, face.height)
    return (
        max(0, math.floor(face.x - margin)),
        max(0, math.floor(face.y - margin)),
        min(width, math.ceil(face.x + face.width + margin)),
        min(height, math.ceil(face.y + face.height + margin)),
    )


def _centre(face: Face) -> tuple[float, float]:
    return face.x + face.width / 2, face.y + face.height / 2


def _refined(img: np.ndarray, coarse: Face, detector: FaceDetector) -> Face:
    """``coarse`` detected again on a crop: the face found there nearest its centre, if any."""
    box = _crop_box(coarse, img.shape)
    if box[0] >= box[2] or box[1] >= box[3]:
        return coarse
    cx, cy = _centre(coarse)
    inside = [
        f
        for f in _detect_region(img, box, detector)
        if coarse.x <= _centre(f)[0] <= coarse.x + coarse.width
        and coarse.y <= _centre(f)[1] <= coarse.y + coarse.height
    ]
    return min(inside, key=lambda f: math.dist(_centre(f), (cx, cy)), default=coarse)


def _same_face(a: Face, b: Face) -> bool:
    (ax0, ay0), (ax1, ay1) = a.landmarks[:2]
    reach = DUPLICATE_EYE_FRACTION * math.dist((ax0, ay0), (ax1, ay1))
    return all(
        math.dist(p, q) <= reach for p, q in zip(a.landmarks[:2], b.landmarks[:2], strict=True)
    )


def _without_duplicates(faces: list[Face]) -> tuple[Face, ...]:
    """One face per person: overlapping coarse boxes can be refined to the same face."""
    kept: list[Face] = []
    for face in faces:
        twin = next((i for i, other in enumerate(kept) if _same_face(face, other)), None)
        if twin is None:
            kept.append(face)
        elif face.score > kept[twin].score:
            kept[twin] = face
    return tuple(kept)


def detect_faces_full_res(
    img: np.ndarray, detector: FaceDetector | None = None
) -> tuple[Face, ...]:
    """Faces in ``img`` (RGB uint8), in its pixel coordinates, landmarks accurate at full size."""
    ensure_rgb_uint8(img)
    active = default_detector() if detector is None else detector
    if max(img.shape[:2]) <= DETECT_LONG_SIDE_PX:
        return active.detect(img)
    whole = (0, 0, img.shape[1], img.shape[0])
    refined = [_refined(img, face, active) for face in _detect_region(img, whole, active)]
    return _without_duplicates(refined)
