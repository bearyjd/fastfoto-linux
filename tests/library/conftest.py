"""Fixtures shared by the library tests."""

from pathlib import Path

import pytest

from tests.library.apply_helpers import FIRST, MTIME_NS, SECOND, THIRD, jpeg
from tests.library.jpeg_helpers import write_file


@pytest.fixture
def lib(tmp_path: Path) -> Path:
    """A library of three photos: two to rotate (tags none and 6) and an upright one."""
    root = tmp_path / "lib"
    write_file(root, FIRST, jpeg(None), mtime_ns=MTIME_NS)
    write_file(root, SECOND, jpeg(6), mtime_ns=MTIME_NS + 10)
    write_file(root, THIRD, jpeg(1), mtime_ns=MTIME_NS + 20)
    return root


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    path = tmp_path / "dest"
    path.mkdir()
    return path
