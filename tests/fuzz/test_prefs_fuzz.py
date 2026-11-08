"""Fuzz the remembered-settings file (gui.json).

Property: whatever the file holds, the three loaders return a usable form or mode (defaults for
anything wrong) and never raise; a value they do take has the right type and is one of the
offered choices; a file past the size cap is not read at all.
"""

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fastfoto_linux.gui import prefs
from fastfoto_linux.gui.docform import DocumentForm
from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.state import Mode
from tests.fuzz.json_strategies import json_values, mutations


@pytest.fixture(scope="module")
def path(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    yield tmp_path_factory.mktemp("fuzz-prefs") / "gui.json"


@pytest.fixture(scope="module", autouse=True)
def _quiet_warnings() -> Iterator[None]:
    """Every bad value is logged on purpose; thousands of lines would only bury a failure."""
    logger = logging.getLogger(prefs.__name__)
    previous = logger.disabled
    logger.disabled = True
    yield
    logger.disabled = previous


def _load_all(path: Path) -> None:
    form = prefs.load_form(path)
    documents = prefs.load_document_form(path)
    mode = prefs.load_mode(path)
    assert isinstance(form, ScanForm)
    assert isinstance(documents, DocumentForm)
    assert isinstance(mode, Mode)
    for name, choices in prefs._CHOICES.items():
        assert getattr(form, name) in choices or getattr(form, name) == getattr(ScanForm(), name)
    for name, choices in prefs._DOCUMENT_CHOICES.items():
        assert getattr(documents, name) in choices or getattr(documents, name) == getattr(
            DocumentForm(), name
        )


def _saved_base(path: Path) -> dict[str, Any]:
    path.unlink(missing_ok=True)
    prefs.save_form(ScanForm(), path)
    prefs.save_document_form(DocumentForm(), path)
    prefs.save_mode(Mode.DOCUMENTS, path)
    return json.loads(path.read_text(encoding="utf-8"))


@given(data=st.binary(max_size=300))
def test_arbitrary_bytes_never_crash_the_loaders(data: bytes, path: Path) -> None:
    path.write_bytes(data)
    _load_all(path)


@given(value=json_values)
def test_arbitrary_json_never_crashes_the_loaders(value: Any, path: Path) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    _load_all(path)


@given(data=st.data())
def test_mutated_settings_load_with_defaults_for_the_bad_parts(
    data: st.DataObject, path: Path
) -> None:
    base = _saved_base(path)
    path.write_text(json.dumps(data.draw(mutations(base))), encoding="utf-8")
    _load_all(path)


@given(depth=st.integers(min_value=50, max_value=3000))
def test_deep_nesting_gives_defaults(depth: int, path: Path) -> None:
    path.write_bytes(b"[" * depth + b"]" * depth)
    assert prefs.load_form(path) == ScanForm()
    assert prefs.load_mode(path) is Mode.PHOTOS


def test_saved_settings_round_trip(path: Path) -> None:
    _saved_base(path)
    assert prefs.load_form(path) == prefs.load_form(path)
    assert prefs.load_mode(path) is Mode.DOCUMENTS
    prefs.save_form(prefs.load_form(path), path)
    assert prefs.load_mode(path) is Mode.DOCUMENTS


def test_a_file_past_the_size_cap_is_not_read(path: Path) -> None:
    _saved_base(path)
    small = path.read_bytes()
    assert prefs.load_mode(path) is Mode.DOCUMENTS
    path.write_bytes(small + b" " * prefs.MAX_PREFS_BYTES)
    assert prefs.load_mode(path) is Mode.PHOTOS
    assert prefs.load_form(path) == ScanForm()
    assert prefs.load_document_form(path) == DocumentForm()
