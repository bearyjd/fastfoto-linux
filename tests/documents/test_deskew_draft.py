"""Seeding angles into a draft: the kept pages with no angle and no crop, read again from disk."""

import threading
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from fastfoto_linux.documents import build as build_module
from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.build import build_document
from fastfoto_linux.documents.deskew import SkewStatus
from fastfoto_linux.documents.deskew_draft import analyse_and_seed, estimate_deskew, estimate_page
from fastfoto_linux.documents.draft import DocumentDraft, TrimBox
from fastfoto_linux.documents.draft_edit import set_crop, set_deskew, set_included
from fastfoto_linux.documents.errors import (
    DocumentCancelledError,
    DocumentEditError,
    DocumentSettingsError,
)
from fastfoto_linux.documents.page_crop import PageCrop
from fastfoto_linux.documents.settings import check_settings
from tests.doc_synth import write_png
from tests.documents.deskew_fixtures import scatter, skewed, text_page
from tests.documents.store_helpers import store_settings

DPI = 100
SHEETS = {  # page file -> pixels: tilted text, text that cannot be measured, level text
    "page-0001.png": lambda: skewed(text_page(np.random.default_rng(1), dpi=DPI), 41),
    "page-0002.png": lambda: scatter()[::3, ::3],
    "page-0003.png": lambda: skewed(text_page(np.random.default_rng(2), dpi=DPI), -27),
}


@pytest.fixture
def raw(tmp_path: Path) -> tuple[Path, list[Path]]:
    folder = tmp_path / "raw"
    folder.mkdir()
    return folder, [write_png(folder / name, make(), dpi=DPI) for name, make in SHEETS.items()]


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


def draft_of(raw: tuple[Path, list[Path]], out: Path, **changes) -> DocumentDraft:
    settings = store_settings(out, keep_blank=True, duplex=False, **changes)
    return analyse_document(raw[1], settings)


def test_the_tilted_pages_get_their_angle_and_the_others_a_status(raw, out) -> None:
    draft, statuses = estimate_deskew(draft_of(raw, out))
    assert abs(draft.edits[1].deskew_tenths - -41) <= 1
    assert abs(draft.edits[3].deskew_tenths - 27) <= 1
    assert 2 not in draft.edits
    assert statuses[1] is statuses[3] is SkewStatus.ESTIMATED
    assert statuses[2] is not SkewStatus.ESTIMATED


def test_the_input_draft_is_not_changed(raw, out) -> None:
    draft = draft_of(raw, out)
    estimate_deskew(draft)
    assert draft.edits == {}


def test_a_stored_angle_is_kept_and_a_crop_wins(raw, out) -> None:
    draft = set_deskew(draft_of(raw, out), 1, 5)
    draft = set_crop(draft, 3, PageCrop(100, 100, 9000, 9000))
    seeded, statuses = estimate_deskew(draft)
    assert seeded.edits[1].deskew_tenths == 5
    assert 1 not in statuses
    assert seeded.edits[3].deskew_tenths is None
    assert statuses[3] is SkewStatus.CROPPED


def test_a_page_left_out_is_not_measured(raw, out, monkeypatch) -> None:
    draft = set_included(draft_of(raw, out), 1, False)
    seeded, statuses = estimate_deskew(draft)
    assert 1 not in statuses
    assert seeded.edits[1].deskew_tenths is None


def test_without_a_folder_there_is_no_source(raw, out) -> None:
    draft = replace(draft_of(raw, out), raw_dir=None)
    seeded, statuses = estimate_deskew(draft)
    assert set(statuses.values()) == {SkewStatus.NO_SOURCE}
    assert seeded == draft


def test_a_cancel_stops_the_estimate(raw, out) -> None:
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DocumentCancelledError):
        estimate_deskew(draft_of(raw, out), cancel=cancel)


def test_one_page_is_measured_whatever_its_edits(raw, out) -> None:
    draft = set_crop(set_deskew(draft_of(raw, out), 1, 5), 1, PageCrop(100, 100, 9000, 9000))
    assert abs(estimate_page(draft, 1).tenths - -41) <= 1
    assert estimate_page(replace(draft, raw_dir=None), 1).status is SkewStatus.NO_SOURCE


def test_analyse_and_seed_seeds_only_when_asked(raw, out) -> None:
    on = analyse_and_seed(raw[1], store_settings(out, keep_blank=True, duplex=False, deskew=True))
    off = analyse_and_seed(raw[1], store_settings(out, keep_blank=True, duplex=False))
    assert on.edits[1].deskew_tenths is not None
    assert off.edits == {}


def test_build_document_never_estimates_unless_asked(raw, out, monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise AssertionError("the estimator ran")

    monkeypatch.setattr(build_module, "estimate_deskew", refuse)
    build_document(raw[1], store_settings(out, keep_blank=True, duplex=False))


def test_build_document_writes_the_seeded_angles(raw, out, monkeypatch) -> None:
    seen: list[DocumentDraft] = []
    real = build_module.write_document
    monkeypatch.setattr(
        build_module, "write_document", lambda d, *a, **k: (seen.append(d), real(d, *a, **k))[1]
    )
    build_document(raw[1], store_settings(out, keep_blank=True, duplex=False, deskew=True))
    assert abs(seen[0].edits[1].deskew_tenths - -41) <= 1


@pytest.mark.parametrize("bad", ["yes", 1, None])
def test_the_deskew_setting_must_be_a_bool(out, bad) -> None:
    with pytest.raises(DocumentSettingsError, match="deskew"):
        check_settings(store_settings(out, deskew=bad))


@pytest.mark.parametrize("number", [0, 4, -1])
def test_a_page_that_is_not_there_is_refused(raw, out, number: int) -> None:
    with pytest.raises(DocumentEditError):
        estimate_page(draft_of(raw, out), number)


def test_a_trim_box_that_leaves_nothing_is_unsure_not_an_error(raw, out) -> None:
    draft = draft_of(raw, out)
    broken = replace(draft.pages[0], trim=TrimBox(left=10**6, right=0, top=0, bottom=0))
    draft = replace(draft, pages=(broken, *draft.pages[1:]))
    assert estimate_page(draft, 1).status is SkewStatus.UNSURE
    seeded, statuses = estimate_deskew(draft)
    assert statuses[1] is SkewStatus.UNSURE
    assert seeded.edits.get(1) is None
