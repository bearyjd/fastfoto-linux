"""``eval deskew``: the page skew estimate against annotated corrections."""

from fastfoto_linux.documents.deskew import SkewStatus, estimate_skew
from fastfoto_linux.evaluation.calib_annotations import DeskewNote
from fastfoto_linux.evaluation.calib_metrics import (
    proportion_entry,
    sample_status,
    skew_error_deg,
    wrong_direction,
)
from fastfoto_linux.evaluation.calib_pages import decode_page, page_digest
from fastfoto_linux.evaluation.stats import nearest_rank

FEATURE = "deskew"
KIND = "document"
digest = page_digest
P90 = 90


def measure(data: bytes, note: DeskewNote, settings: object = None) -> dict[str, object]:
    """One page: whether the estimate was applied (not an abstain) and how far off it was."""
    estimate = estimate_skew(decode_page(data, note.dpi))
    if estimate.status is not SkewStatus.ESTIMATED:
        return {"applied": False}
    return {
        "applied": True,
        "error": skew_error_deg(estimate.tenths, note.correction_tenths),
        "wrong": wrong_direction(estimate.tenths, note.correction_tenths),
    }


def aggregate(rows: list[dict[str, object]], settings: object = None) -> dict[str, object]:
    applied = [row for row in rows if row["applied"]]
    errors = [float(row["error"]) for row in applied]  # type: ignore[arg-type]
    status = sample_status(len(applied))
    return {
        "n": len(rows),
        "applied": len(applied),
        "status": status,
        "abstain": proportion_entry(len(rows) - len(applied), len(rows)),
        "mae_deg": sum(errors) / len(errors) if errors and status is None else None,
        "p90_abs_err_deg": nearest_rank(errors, P90) if status is None else None,
        "wrong_direction": proportion_entry(sum(bool(r["wrong"]) for r in applied), len(applied)),
    }
