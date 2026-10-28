"""The writing half of ``review.json``: the parts of a draft that become JSON values."""

from typing import Any

from fastfoto_linux.documents.cleanup_json import edit_json
from fastfoto_linux.documents.colour_json import encode_decision
from fastfoto_linux.documents.crop_json import crop_json
from fastfoto_linux.documents.draft import PageAnalysis, PageEdit, sorted_flags
from fastfoto_linux.documents.settings import DocumentSettings
from fastfoto_linux.output.errors import InvalidPrefixError
from fastfoto_linux.output.naming import sanitise_prefix


def page_json(page: PageAnalysis) -> dict[str, Any]:
    return {
        "name": page.name,
        "size": page.size,
        "mtime_ns": page.mtime_ns,
        "dpi": page.dpi,
        "trim": [page.trim.left, page.trim.right, page.trim.top, page.trim.bottom],
        "band_bottom": page.trim.band_bottom,
        "blank": page.blank,
        "partner": page.partner,
        "flags": [str(flag) for flag in sorted_flags(page.flags)],
        "marks": [[box.x0, box.y0, box.x1, box.y1] for box in page.marks],
        "detail": list(page.detail),
        "colour": encode_decision(page.colour),
    }


def options_json(settings: DocumentSettings) -> dict[str, str] | None:
    try:
        name = sanitise_prefix(settings.name)
    except InvalidPrefixError:
        return None
    return {
        "name": name,
        "colour": settings.colour.value,
        "ocr": settings.ocr.value,
        "langs": settings.langs,
    }


def edit_page_json(
    edit: PageEdit, *, cleanup: bool, cropped: bool, deskew: bool = False
) -> dict[str, Any]:
    data = edit_json(edit, with_cleanup=cleanup)
    if cropped:
        data["crop"] = crop_json(edit.crop)
    if deskew:
        data["deskew"] = edit.deskew_tenths
    return data
