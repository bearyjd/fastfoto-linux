"""The sheets of a batch that need a look, and the line that says what became of one."""

from dataclasses import dataclass

from fastfoto_linux.output import WrittenFiles


@dataclass(frozen=True)
class SheetIssue:
    """A sheet worth telling the user about: ``sheet`` is 1-based, ``pages`` are file names.

    ``saved`` is set on a failed sheet whose whole pages were saved (as ``_unprocessed`` files)
    instead of being lost; ``save_failed`` says that saving them was tried and did not work.
    """

    sheet: int | None
    pages: tuple[str, ...]
    reason: str
    saved: WrittenFiles | None = None
    save_failed: bool = False


def failed_sheet_line(issue: SheetIssue, sheets: int) -> str:
    """One line for a failed sheet: which photo it was in feed order, why, and what was saved.

    ``sheets`` is how many sheets were fed (0 when unknown). Only the feed order is claimed,
    never where in the stack a photo was. A sheet whose pages were saved reads, for example,
    ``photo 4 of 6 fed: <reason> - whole page saved as X_0004_unprocessed.jpg`` (an em dash);
    one that was lost names its pages instead.
    """
    if issue.sheet is None:
        return f"batch: {issue.reason}"
    position = f"photo {issue.sheet} of {sheets} fed" if sheets else f"photo {issue.sheet} fed"
    if issue.saved is None:
        pages = f" ({', '.join(issue.pages)})" if issue.pages else ""
        return f"{position}{pages}: {issue.reason}"
    return f"{position}: {issue.reason} — {_saved_text(issue.saved)}"


def _saved_text(saved: WrittenFiles) -> str:
    names = [path.name for path in (saved.original, saved.back) if path is not None]
    noun = "page" if len(names) == 1 else "pages"
    return f"whole {noun} saved as {' and '.join(names)}"
