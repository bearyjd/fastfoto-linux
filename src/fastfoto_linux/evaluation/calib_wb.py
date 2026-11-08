"""``eval wb``: colour error of a neutral patch under each white balance setting.

``restore`` is the colour restoration (``enhance.restore_colour``), named for what it is: there is
no automatic white balance. The other settings are the white balance part of the editor presets
(``mono`` has a neutral one, so it equals ``none``).
"""

from threading import Event

import numpy as np

from fastfoto_linux.enhance.restore import restore_colour
from fastfoto_linux.evaluation.calib_annotations import WbNote, check_inside
from fastfoto_linux.evaluation.calib_metrics import neutral_de00, sample_status
from fastfoto_linux.evaluation.calib_pages import decode_photo, photo_digest
from fastfoto_linux.evaluation.stats import nearest_rank
from fastfoto_linux.gui.photoeditpresets import preset
from fastfoto_linux.photo_edits.color import apply_white_balance

FEATURE = "wb"
KIND = "photo"
digest = photo_digest
SETTINGS = ("none", "restore", "warm", "cool", "faded", "mono")
PRESET_SETTINGS = ("warm", "cool", "faded", "mono")
RESTORE_DPI = 300.0
MEDIAN, P90 = 50, 90


def render(rgb: np.ndarray, setting: str) -> np.ndarray:
    """A new image: ``rgb`` under ``setting`` (the input is never changed)."""
    if setting == "restore":
        return restore_colour(rgb.copy(), RESTORE_DPI)
    out = rgb.copy()
    if setting in PRESET_SETTINGS:
        apply_white_balance(out, preset(setting).white_balance, Event())
    return out


def measure(data: bytes, note: WbNote, settings: object = None) -> dict[str, object]:
    rgb = decode_photo(data)
    check_inside(note.neutral_boxes, rgb.shape[1], rgb.shape[0])
    errors = {s: neutral_de00(render(rgb, s), note.neutral_boxes) for s in SETTINGS}
    return {"cast": note.cast, "de": errors}


def _summary(values: list[float]) -> dict[str, object]:
    status = sample_status(len(values))
    return {
        "n": len(values),
        "status": status,
        "median_de00": nearest_rank(values, MEDIAN) if status is None else None,
        "p90_de00": nearest_rank(values, P90) if status is None else None,
    }


def _improvement(none: object, restore: object) -> float | None:
    if type(none) is not float or type(restore) is not float or none <= 0:
        return None
    return (none - restore) / none


def aggregate(rows: list[dict[str, object]], settings: object = None) -> dict[str, object]:
    per_setting = {}
    for name in SETTINGS:
        everyone = [float(r["de"][name]) for r in rows]  # type: ignore[index]
        cast = [float(r["de"][name]) for r in rows if r["cast"]]  # type: ignore[index]
        per_setting[name] = {"all_items": _summary(everyone), "cast_items": _summary(cast)}
    gain = _improvement(
        per_setting["none"]["cast_items"]["median_de00"],
        per_setting["restore"]["cast_items"]["median_de00"],
    )
    return {"n": len(rows), "settings": per_setting, "improvement_vs_none_restore": gain}
