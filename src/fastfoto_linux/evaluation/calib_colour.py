"""``eval autocolour``: the automatic colour mode against annotated least-rich-sufficient modes."""

from fastfoto_linux.documents.auto_colour import classify_colour
from fastfoto_linux.evaluation.calib_annotations import ColourNote
from fastfoto_linux.evaluation.calib_metrics import proportion_entry
from fastfoto_linux.evaluation.calib_pages import decode_page
from fastfoto_linux.evaluation.redeye_split import pixel_digest

FEATURE = "autocolour"
KIND = "document"
RICHNESS = {"bw": 0, "grey": 1, "colour": 2}


def digest(data: bytes, note: ColourNote) -> str:
    return pixel_digest(decode_page(data, note.dpi).pixels)


def measure(data: bytes, note: ColourNote, settings: object = None) -> dict[str, object]:
    """A loss: the chosen mode is poorer than the label (a meaningful mark is dropped).
    Over-retention: it is richer than the label (more than was needed)."""
    chosen = RICHNESS[classify_colour(decode_page(data, note.dpi)).mode.value]
    wanted = RICHNESS[note.label]
    return {"loss": chosen < wanted, "over": chosen > wanted}


def aggregate(rows: list[dict[str, object]], settings: object = None) -> dict[str, object]:
    n = len(rows)
    return {
        "n": n,
        "colour_loss": proportion_entry(sum(bool(r["loss"]) for r in rows), n),
        "over_retention": proportion_entry(sum(bool(r["over"]) for r in rows), n),
    }
