"""Qt tests: skipped when PySide6 or Kirigami is missing, unless ``FASTFOTO_REQUIRE_QT=1``.

The Ubuntu jobs have no Qt, so these skip there. The Fedora job sets the variable, so that a
missing PySide6 or Kirigami fails the job instead of silently skipping every test.
"""

import os

import pytest

REQUIRE_QT = os.environ.get("FASTFOTO_REQUIRE_QT") == "1"


def unavailable(reason: str) -> None:
    """Skip the test, or fail it where Qt is required."""
    if REQUIRE_QT:
        pytest.fail(f"{reason}, but FASTFOTO_REQUIRE_QT=1")
    pytest.skip(reason)


def require_qt() -> None:
    """Call at the top of a test module, before it imports PySide6."""
    try:
        import PySide6.QtQml  # noqa: F401
    except ImportError as error:
        if REQUIRE_QT:
            raise
        pytest.skip(f"PySide6 is not installed ({error})", allow_module_level=True)
