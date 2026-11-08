"""Fuzz the remembered-settings file (gui.json).

Property: whatever the file holds, the three loaders return a usable form or mode (defaults for
anything wrong) and never raise; a value they do take has the right type and is one of the
offered choices; a file past the size cap is not read at all.
"""

import json
import logging
from collections.abc import Iterator
from dataclasses import replace
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


# The C JSON scanner raises RecursionError somewhere past 10 000 levels (3.13); 400 000 levels
# are still under every size cap here (2 MB, 8 MB, 1 MiB).
@given(depth=st.sampled_from([1_000, 20_000, 400_000]))
def test_deep_nesting_gives_defaults(depth: int, path: Path) -> None:
    path.write_bytes(b"[" * depth + b"]" * depth)
    assert prefs.load_form(path) == ScanForm()
    assert prefs.load_mode(path) is Mode.PHOTOS


def _other(current: str, choices: Any) -> str:
    return next(choice for choice in sorted(choices) if choice != current)


def _non_default_forms() -> tuple[ScanForm, DocumentForm]:
    defaults, document_defaults = ScanForm(), DocumentForm()
    form = ScanForm(
        output_folder="/srv/scans",
        album="Holiday",
        loaded=_other(defaults.loaded, prefs._CHOICES["loaded"]),
        backs=_other(defaults.backs, prefs._CHOICES["backs"]),
        restore=not defaults.restore,
        orient=not defaults.orient,
        redeye=not defaults.redeye,
        dpi=next(d for d in sorted(prefs._CHOICES["dpi"]) if d != defaults.dpi),
        keep_original=not defaults.keep_original,
        preset=_other(defaults.preset, prefs._CHOICES["preset"]),
    )
    documents = DocumentForm(
        name="Tax papers",
        colour=_other(document_defaults.colour, prefs._DOCUMENT_CHOICES["colour"]),
        dpi=next(d for d in sorted(prefs._DOCUMENT_CHOICES["dpi"]) if d != document_defaults.dpi),
        both_sides=not document_defaults.both_sides,
        keep_blank=not document_defaults.keep_blank,
        searchable=not document_defaults.searchable,
        langs="deu",
        cleanup=_other(document_defaults.cleanup, prefs._DOCUMENT_CHOICES["cleanup"]),
        despeckle=not document_defaults.despeckle,
        deskew=not document_defaults.deskew,
        preset=_other(document_defaults.preset, prefs._DOCUMENT_CHOICES["preset"]),
    )
    return form, documents


def test_non_default_settings_come_back_exactly_from_a_fresh_load(path: Path) -> None:
    form, documents = _non_default_forms()
    assert form != ScanForm() and documents != DocumentForm()
    path.unlink(missing_ok=True)
    prefs.save_form(form, path)
    prefs.save_document_form(documents, path)
    prefs.save_mode(Mode.DOCUMENTS, path)
    expected = replace(form, date="", notes="")  # a batch's date and notes are not remembered
    assert prefs.load_form(path) == expected
    assert prefs.load_document_form(path) == documents
    assert prefs.load_mode(path) is Mode.DOCUMENTS


def test_a_file_past_the_size_cap_is_not_read(path: Path) -> None:
    _saved_base(path)
    small = path.read_bytes()
    assert prefs.load_mode(path) is Mode.DOCUMENTS
    path.write_bytes(small + b" " * prefs.MAX_PREFS_BYTES)
    assert prefs.load_mode(path) is Mode.PHOTOS
    assert prefs.load_form(path) == ScanForm()
    assert prefs.load_document_form(path) == DocumentForm()


def test_a_file_of_exactly_the_size_cap_is_read_and_one_byte_more_is_not(path: Path) -> None:
    _saved_base(path)
    small = path.read_bytes()
    path.write_bytes(small + b" " * (prefs.MAX_PREFS_BYTES - len(small)))
    assert path.stat().st_size == prefs.MAX_PREFS_BYTES
    assert prefs.load_mode(path) is Mode.DOCUMENTS
    path.write_bytes(path.read_bytes() + b" ")
    assert prefs.load_mode(path) is Mode.PHOTOS
