"""Exit codes of ``ffscan`` and the exception commands raise for a user-facing failure."""

EXIT_OK = 0
EXIT_PROCESSING_ERROR = 1
EXIT_USAGE = 2  # also argparse's own code for a bad command line
EXIT_SCANNER = 3  # scanner not found, or on USB without the gap shim
EXIT_TOOL_MISSING = EXIT_SCANNER  # a tool the command was told to require is not installed
EXIT_NO_DOCUMENTS = 4  # the document feeder is empty
EXIT_INTERRUPTED = 130  # the shell convention for Ctrl-C (128 + SIGINT)


class CliError(Exception):
    """A failure to report as one line on stderr and turn into ``code``."""

    def __init__(self, message: str, code: int = EXIT_PROCESSING_ERROR) -> None:
        super().__init__(message)
        self.code = code
