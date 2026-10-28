"""``review.json``: a draft as JSON, and JSON read back as a draft *only if every part is right*.

The file is untrusted input (it lies in a folder anyone with the user's rights can write to, and
may come from another version or a damaged disk). ``decode_review`` checks each value by its
type (a bool is no number), its range and its meaning, bounds every list, and refuses the whole
file with ``ReviewFormatError`` at the first thing wrong: a file is used completely or not at all.
The page names in the file must be those of the pages given, in order, so it can name no other
file. It holds no pixels and no ink maps (the neighbour flags are settled before it is saved).
"""

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from fastfoto_linux.documents.assess import MAX_BOXES
from fastfoto_linux.documents.cleanup_json import uses_cleanup
from fastfoto_linux.documents.colour_json import decode_decision, decode_policy
from fastfoto_linux.documents.crop_json import (
    CropFormatError,
    parse_crop,
    uses_crop,
)
from fastfoto_linux.documents.deskew_json import DeskewFormatError, parse_deskew, uses_deskew
from fastfoto_linux.documents.despeckle_json import uses_despeckle
from fastfoto_linux.documents.draft import (
    QUARTER_TURNS,
    BoxN,
    DocumentDraft,
    Flag,
    PageAnalysis,
    PageEdit,
    TrimBox,
)
from fastfoto_linux.documents.draft_encode import edit_page_json, options_json, page_json
from fastfoto_linux.documents.loader import MAX_DPI, MIN_DPI
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode, ColourPolicy
from fastfoto_linux.documents.ocr import OcrMode, validate_langs
from fastfoto_linux.documents.page_crop import PageCrop
from fastfoto_linux.documents.settings import DocumentSettings
from fastfoto_linux.documents.sidecar_versions import (
    CLEANUP_VERSION,
    CROP_VERSION,  # noqa: F401 - the tests read it here
    DESPECKLE_VERSION,
    READ_VERSIONS,
    check_edit_keys,
    version_for,
)
from fastfoto_linux.output.errors import InvalidPrefixError
from fastfoto_linux.output.naming import sanitise_prefix

MAX_PAGES = 2000  # a document of more pages than this is not reviewed from a file
MAX_FILE_BYTES = 1 << 40  # the size of one page file
MAX_MTIME_NS = 1 << 63
MAX_TRIM_PX = 100_000
MAX_VERSION = 1_000_000
MAX_DETAIL = 8
MAX_KEY_CHARS = len(str(MAX_PAGES))  # a page number as a key
MAX_TEXT = 255
_WORD = re.compile(r"[a-z0-9_]{1,40}")


class ReviewFormatError(ValueError):
    """The sidecar cannot be used; the message says what is wrong with it."""


@dataclass(frozen=True)
class StoredOptions:
    """The document options the draft was made with, for a front end to offer again."""

    name: str
    colour: ColourPolicy | ColourMode
    ocr: OcrMode
    langs: str


@dataclass(frozen=True)
class StoredReview:
    """A sidecar, read and checked: the draft as saved (its ``raw_dir`` is None; its analysis may
    be stale, see ``draft_store``), the version of the analysis it was made by and the options."""

    draft: DocumentDraft
    analysis_version: int
    options: StoredOptions | None
    fallback_dpi: int | None = None
    fallback_dpi_known: bool = False


# --- writing -------------------------------------------------------------------------------


def encode_review(
    draft: DocumentDraft, settings: DocumentSettings | None, analysis_version: int
) -> bytes:
    """The JSON of ``draft`` (and the options of ``settings``, if given). The draft's read-only
    maps are written out by hand. The lowest format version that fits is written (see
    ``sidecar_versions``): 2 exactly as it always was, 3 for paper cleanup, 4 for a crop, 5 for
    despeckle, 6 for a deskew angle."""
    deskew = uses_deskew(draft)
    despeckle = uses_despeckle(draft)
    cropped = deskew or despeckle or uses_crop(draft)  # versions 5 and 6 have the shape of 4
    cleanup = cropped or uses_cleanup(draft)
    data: dict[str, Any] = {
        "version": version_for(
            deskew=deskew, despeckle=despeckle, cropped=cropped, cleanup=cleanup
        ),
        "analysis_version": analysis_version,
        "duplex": draft.duplex,
        "keep_blank": draft.keep_blank,
        "pages": [page_json(page) for page in draft.pages],
        "edits": {
            str(number): edit_page_json(edit, cleanup=cleanup, cropped=cropped, deskew=deskew)
            for number, edit in sorted(draft.edits.items())
        },
        "order": list(draft.order),
        "splits": sorted(draft.splits),
        "part_names": {str(number): name for number, name in sorted(draft.part_names.items())},
    }
    if cleanup:
        data["cleanup"] = draft.cleanup.value
    if data["version"] >= DESPECKLE_VERSION:
        data["despeckle"] = draft.despeckle
    if settings is not None:
        data["fallback_dpi"] = settings.fallback_dpi
    options = None if settings is None else options_json(settings)
    if options is not None:
        data["options"] = options
    return json.dumps(data, separators=(",", ":"), allow_nan=False).encode("utf-8")


# --- reading -------------------------------------------------------------------------------


def _reject_constant(name: str) -> Any:
    raise ReviewFormatError(f"{name} is no number")


def _whole(value: Any, what: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ReviewFormatError(f"{what} must be a whole number from {low} to {high}")
    return value


def _flag(value: Any, what: str) -> bool:
    if type(value) is not bool:
        raise ReviewFormatError(f"{what} must be true or false")
    return value


def _list(value: Any, what: str, longest: int) -> list[Any]:
    if type(value) is not list or len(value) > longest:
        raise ReviewFormatError(f"{what} must be a list of at most {longest} items")
    return value


def _dict(value: Any, what: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ReviewFormatError(f"{what} must be an object")
    return value


def _text(value: Any, what: str) -> str:
    if type(value) is not str or not 0 < len(value) <= MAX_TEXT:
        raise ReviewFormatError(f"{what} must be text of 1 to {MAX_TEXT} characters")
    return value


def _clean_name(value: Any, what: str) -> str:
    text = _text(value, what)
    try:
        clean = sanitise_prefix(text)
    except InvalidPrefixError as error:
        raise ReviewFormatError(f"{what} is not a usable name") from error
    if clean != text:
        raise ReviewFormatError(f"{what} is not a clean name")
    return clean


def _number_key(key: str, what: str, count: int) -> int:
    if len(key) > MAX_KEY_CHARS or not key.isascii() or not key.isdecimal() or str(int(key)) != key:
        raise ReviewFormatError(f"{what} has the key {key[:20]!r}, which is no page number")
    return _whole(int(key), f"{what} key", 1, count)


def _box(value: Any) -> BoxN:
    corners = _list(value, "a mark", 4)
    if len(corners) != 4:  # noqa: PLR2004 - x0, y0, x1, y1
        raise ReviewFormatError("a mark must have four numbers")
    for corner in corners:
        if type(corner) not in (int, float) or not math.isfinite(corner) or not 0 <= corner <= 1:
            raise ReviewFormatError("a mark must be four numbers from 0 to 1")
    return BoxN(*(float(corner) for corner in corners))


def _trim(entry: dict[str, Any]) -> TrimBox:
    sides = _list(entry.get("trim"), "trim", 4)
    if len(sides) != 4:  # noqa: PLR2004 - left, right, top, bottom
        raise ReviewFormatError("trim must have four numbers")
    cut = [_whole(side, "a trim side", 0, MAX_TRIM_PX) for side in sides]
    return TrimBox(*cut, band_bottom=_flag(entry.get("band_bottom"), "band_bottom"))


def _flags(value: Any) -> frozenset[Flag]:
    names = _list(value, "flags", len(Flag))
    try:
        flags = frozenset(Flag(name) for name in names if type(name) is str)
    except ValueError as error:
        raise ReviewFormatError("a flag is unknown") from error
    if len(flags) != len(names):
        raise ReviewFormatError("flags must be known names, each once")
    return flags


def _details(value: Any) -> tuple[str, ...]:
    words = _list(value, "detail", MAX_DETAIL)
    if not all(type(w) is str and _WORD.fullmatch(w) for w in words):
        raise ReviewFormatError("detail must be short plain words")
    return tuple(words)


def _page(value: Any, number: int, name: str, count: int, version: int) -> PageAnalysis:
    entry = _dict(value, f"page {number}")
    if entry.get("name") != name:
        raise ReviewFormatError(f"page {number} is not the page file {name}")
    partner = entry.get("partner")
    if partner is not None:
        partner = _whole(partner, "a partner", 1, count)
        if partner == number:
            raise ReviewFormatError(f"page {number} is its own partner")
    return PageAnalysis(
        number=number,
        name=name,
        size=_whole(entry.get("size"), "size", 0, MAX_FILE_BYTES),
        mtime_ns=_whole(entry.get("mtime_ns"), "mtime_ns", -MAX_MTIME_NS, MAX_MTIME_NS),
        dpi=_whole(entry.get("dpi"), "dpi", MIN_DPI, MAX_DPI),
        trim=_trim(entry),
        blank=_flag(entry.get("blank"), "blank"),
        partner=partner,
        flags=_flags(entry.get("flags")),
        marks=tuple(_box(box) for box in _list(entry.get("marks"), "marks", MAX_BOXES)),
        detail=_details(entry.get("detail")),
        colour=decode_decision(entry.get("colour"), version),
    )


def _cleanup(value: Any, what: str) -> CleanupPolicy:
    try:
        if type(value) is not str:
            raise ValueError(what)
        return CleanupPolicy(value)
    except ValueError as error:
        raise ReviewFormatError(f"{what} must be off, light or strong") from error


def _crop(entry: dict[str, Any]) -> PageCrop | None:
    try:
        return parse_crop(entry.get("crop"), "an edit's crop")
    except CropFormatError as error:
        raise ReviewFormatError(str(error)) from error


def _deskew(entry: dict[str, Any]) -> int | None:
    try:
        return parse_deskew(entry.get("deskew"), "an edit's deskew")
    except DeskewFormatError as error:
        raise ReviewFormatError(str(error)) from error


def _edits(value: Any, count: int, version: int) -> Mapping[int, PageEdit]:
    edits: dict[int, PageEdit] = {}
    for key, raw in _dict(value, "edits").items():
        number = _number_key(key, "edits", count)
        entry = _dict(raw, "an edit")
        problem = check_edit_keys(entry, version)
        if problem is not None:
            raise ReviewFormatError(problem)
        include = entry.get("include")
        if include is not None:
            include = _flag(include, "include")
        turns = _whole(entry.get("turns"), "turns", 0, QUARTER_TURNS - 1)
        edits[number] = PageEdit(
            include,
            turns,
            decode_policy(entry.get("colour"), version),
            None
            if entry.get("cleanup") is None
            else _cleanup(entry["cleanup"], "an edit's cleanup"),
            _crop(entry),
            _deskew(entry),
        )
    return MappingProxyType(edits)


def _order(value: Any, count: int) -> tuple[int, ...]:
    order = _list(value, "order", count)
    numbers = tuple(_whole(n, "an order entry", 1, count) for n in order)
    if numbers and sorted(numbers) != list(range(1, count + 1)):
        raise ReviewFormatError("order must name every page once")
    return numbers


def _splits(value: Any, count: int) -> frozenset[int]:
    numbers = [_whole(n, "a split", 1, count) for n in _list(value, "splits", count)]
    if len(set(numbers)) != len(numbers):
        raise ReviewFormatError("a split is given twice")
    return frozenset(numbers)


def _part_names(value: Any, count: int) -> Mapping[int, str]:
    return MappingProxyType(
        {
            _number_key(key, "part_names", count): _clean_name(name, "a part name")
            for key, name in _dict(value, "part_names").items()
        }
    )


def _options(value: Any, version: int) -> StoredOptions | None:
    if value is None:
        return None
    entry = _dict(value, "options")
    try:
        colour = (ColourMode if version == 1 else ColourPolicy)(
            _text(entry.get("colour"), "colour")
        )
        ocr = OcrMode(_text(entry.get("ocr"), "ocr"))
        langs = validate_langs(_text(entry.get("langs"), "langs"))
    except ValueError as error:
        raise ReviewFormatError(f"the options are not usable: {error}") from error
    return StoredOptions(_clean_name(entry.get("name"), "the name"), colour, ocr, langs)


def decode_review(data: bytes, names: Sequence[str]) -> StoredReview:
    """The sidecar in ``data`` for pages with these file names, or ReviewFormatError (also for
    any other failure of reading it: whatever the input does, it never raises anything else)."""
    try:
        return _decode(data, names)
    except ReviewFormatError:
        raise
    except (ValueError, OverflowError, RecursionError, MemoryError, TypeError, KeyError) as error:
        raise ReviewFormatError(f"cannot be decoded ({type(error).__name__})") from error


def _decode(data: bytes, names: Sequence[str]) -> StoredReview:
    try:
        loaded = json.loads(data, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as error:  # not JSON, not UTF-8, nested without end
        raise ReviewFormatError(f"not readable JSON ({type(error).__name__})") from error
    top = _dict(loaded, "the file")
    count = len(names)
    if not 1 <= count <= MAX_PAGES:
        raise ReviewFormatError(f"{count} pages are not 1 to {MAX_PAGES}")
    format_version = top.get("version")
    if type(format_version) is not int or format_version not in READ_VERSIONS:
        raise ReviewFormatError("the format version is not one this program reads")
    if format_version < CLEANUP_VERSION and "cleanup" in top:
        raise ReviewFormatError("cleanup needs format version 3")
    if format_version < DESPECKLE_VERSION and "despeckle" in top:
        raise ReviewFormatError("despeckle needs format version 5")
    despeckle = format_version >= DESPECKLE_VERSION and _flag(top.get("despeckle"), "despeckle")
    entries = _list(top.get("pages"), "pages", count)
    if len(entries) != count:
        raise ReviewFormatError(f"the file has {len(entries)} pages, the folder {count}")
    pages = tuple(
        _page(entry, number, name, count, top["version"])
        for number, (entry, name) in enumerate(zip(entries, names, strict=True), start=1)
    )
    draft = DocumentDraft(
        pages=pages,
        raw_dir=None,
        duplex=_flag(top.get("duplex"), "duplex"),
        keep_blank=_flag(top.get("keep_blank"), "keep_blank"),
        edits=_edits(top.get("edits", {}), count, top["version"]),
        order=_order(top.get("order", []), count),
        splits=_splits(top.get("splits", []), count),
        part_names=_part_names(top.get("part_names", {}), count),
        cleanup=(
            _cleanup(top.get("cleanup"), "cleanup")
            if top["version"] >= CLEANUP_VERSION
            else CleanupPolicy.OFF
        ),
        despeckle=despeckle,
    )
    version = _whole(top.get("analysis_version"), "analysis_version", 0, MAX_VERSION)
    dpi = top.get("fallback_dpi")
    if dpi is not None:
        dpi = _whole(dpi, "fallback_dpi", MIN_DPI, MAX_DPI)
    return StoredReview(
        draft,
        version,
        _options(top.get("options"), top["version"]),
        dpi,
        "fallback_dpi" in top,
    )
