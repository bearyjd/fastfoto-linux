"""What ``ffscan`` tells the user when the pages have been processed."""

import sys

from fastfoto_linux.pipeline.issues import SheetIssue, failed_sheet_line
from fastfoto_linux.pipeline.process import ProcessResult


def _label(issue: SheetIssue) -> str:
    sheet = "batch" if issue.sheet is None else f"sheet {issue.sheet}"
    return f"{sheet} ({', '.join(issue.pages)})" if issue.pages else sheet


def _enhanced_line(result: ProcessResult) -> str:
    line = f"enhanced: {result.enhanced}"
    return f"{line} ({result.unchanged} unchanged)" if result.unchanged else line


def _print_dropped(result: ProcessResult) -> None:
    print(
        f"backs dropped: {result.backs_dropped} "
        "(no writing detected; use --backs always to keep them)"
    )
    print(f"  {', '.join(result.dropped_backs)}")


def _folders(result: ProcessResult) -> list[str]:
    """The folders the run wrote to, whole pages saved for failed sheets included."""
    files = [*result.written, *(i.saved for i in result.failed if i.saved is not None)]
    return sorted({str(item.directory) for item in files})


def print_summary(result: ProcessResult) -> None:
    """Counts and folders on stdout; sheets that need attention below them.

    Sheets that need a look (``uncertain``) go to stdout with their reason; degraded and failed
    sheets go to stderr. A failed sheet is named by its place in the feed ("photo 4 of 6 fed")
    with the reason and, when its whole pages were saved, the files.
    """
    print(f"photos written: {result.photos}")
    print(f"backs kept: {result.backs_kept}")
    if result.dropped_backs:
        _print_dropped(result)
    print(_enhanced_line(result))
    for folder in _folders(result):
        print(f"output: {folder}")
    if result.uncertain:
        print("please check these sheets:")
        for issue in result.uncertain:
            print(f"  {_label(issue)}: {issue.reason}")
    if result.degraded:
        print(f"{len(result.degraded)} sheet(s) written without an enhanced copy:", file=sys.stderr)
        for issue in result.degraded:
            print(f"  {_label(issue)}: {issue.reason}", file=sys.stderr)
    if result.failed:
        print(f"{len(result.failed)} sheet(s) could not be processed:", file=sys.stderr)
        for issue in result.failed:
            print(f"  {failed_sheet_line(issue, result.sheets)}", file=sys.stderr)
