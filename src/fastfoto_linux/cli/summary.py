"""What ``ffscan`` tells the user when the pages have been processed."""

import sys

from fastfoto_linux.pipeline.process import ProcessResult, SheetIssue


def _label(issue: SheetIssue) -> str:
    sheet = "batch" if issue.sheet is None else f"sheet {issue.sheet}"
    return f"{sheet} ({', '.join(issue.pages)})" if issue.pages else sheet


def print_summary(result: ProcessResult) -> None:
    """Counts and folders on stdout; sheets that were lost on stderr.

    The reason a sheet failed was logged as it happened, so the summary only names the sheets.
    """
    print(f"photos written: {result.photos}")
    print(f"backs kept: {result.backs_kept}")
    print(f"enhanced copies: {result.enhanced}")
    for folder in sorted({str(files.directory) for files in result.written}):
        print(f"output: {folder}")
    if result.uncertain:
        print("front and back could not be told apart (the back was kept, please check):")
        for issue in result.uncertain:
            print(f"  {_label(issue)}")
    if result.failed:
        print(f"{len(result.failed)} sheet(s) could not be processed:", file=sys.stderr)
        for issue in result.failed:
            print(f"  {_label(issue)}", file=sys.stderr)
