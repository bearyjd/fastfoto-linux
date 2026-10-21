"""The cleanup policy on settings, drafts and edits, and what an analysis does with it."""

from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.documents import (
    CleanupPolicy,
    ColourPolicy,
    DocumentSettings,
    DocumentSettingsError,
    check_settings,
)
from fastfoto_linux.documents import analyse as analyse_module
from fastfoto_linux.documents.analyse import ANALYSIS_VERSION, analyse_document
from fastfoto_linux.documents.cleanup import page_cleanup
from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.draft_edit import PageEdits, set_cleanup, set_document_cleanup
from fastfoto_linux.documents.errors import DocumentEditError
from fastfoto_linux.documents.loader import load_page
from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import write_png
from tests.documents import cleanup_fixtures as fx
from tests.documents.edit_helpers import draft_of
from tests.documents.store_helpers import store_settings


def test_the_settings_default_is_off(tmp_path: Path) -> None:
    assert DocumentSettings(output_root=tmp_path).cleanup is CleanupPolicy.OFF
    assert [p.value for p in CleanupPolicy] == ["off", "light", "strong"]


def test_a_cleanup_that_is_no_policy_is_refused(tmp_path: Path) -> None:
    for bad in ("medium", None, True, "light"):  # a plain string is no policy either
        with pytest.raises(DocumentSettingsError, match="cleanup must be off, light or strong"):
            check_settings(DocumentSettings(output_root=tmp_path, cleanup=bad))  # type: ignore[arg-type]
    check_settings(DocumentSettings(output_root=tmp_path, cleanup=CleanupPolicy.STRONG))


def test_a_page_edit_validates_its_cleanup() -> None:
    assert PageEdit().cleanup is None
    assert PageEdit(cleanup=CleanupPolicy.LIGHT).cleanup is CleanupPolicy.LIGHT
    with pytest.raises(ValueError, match="cleanup"):
        PageEdit(cleanup="light")  # type: ignore[arg-type]


def test_a_draft_follows_no_cleanup_by_default() -> None:
    assert draft_of(1).cleanup is CleanupPolicy.OFF


def test_set_cleanup_is_pure_and_clears_with_none() -> None:
    draft = draft_of(3)
    changed = set_cleanup(draft, 2, CleanupPolicy.STRONG)
    assert draft.edits == {} and changed is not draft
    assert changed.edits[2].cleanup is CleanupPolicy.STRONG
    assert set_cleanup(changed, 2, None) == draft  # no edit is left behind


def test_set_cleanup_keeps_the_other_edits() -> None:
    draft = replace(draft_of(2), edits={1: PageEdit(False, 2, ColourPolicy.GREY)})
    edited = set_cleanup(draft, 1, CleanupPolicy.OFF)
    assert edited.edits[1] == PageEdit(False, 2, ColourPolicy.GREY, CleanupPolicy.OFF)


def test_an_override_of_off_is_an_edit() -> None:
    assert set_cleanup(draft_of(1), 1, CleanupPolicy.OFF).edits == {
        1: PageEdit(cleanup=CleanupPolicy.OFF)
    }


@pytest.mark.parametrize("bad", ["strong", 1, True])
def test_set_cleanup_refuses_a_wrong_type_and_a_missing_page(bad: object) -> None:
    with pytest.raises(DocumentEditError):
        set_cleanup(draft_of(2), 1, bad)  # type: ignore[arg-type]
    with pytest.raises(DocumentEditError):
        set_cleanup(draft_of(2), 3, CleanupPolicy.LIGHT)


def test_set_document_cleanup_is_pure_and_checked() -> None:
    draft = draft_of(2)
    assert set_document_cleanup(draft, CleanupPolicy.LIGHT).cleanup is CleanupPolicy.LIGHT
    assert draft.cleanup is CleanupPolicy.OFF
    for bad in ("light", None):
        with pytest.raises(DocumentEditError):
            set_document_cleanup(draft, bad)  # type: ignore[arg-type]


def test_page_cleanup_uses_the_override_first() -> None:
    draft = set_document_cleanup(draft_of(3), CleanupPolicy.LIGHT)
    draft = set_cleanup(draft, 2, CleanupPolicy.OFF)
    draft = set_cleanup(draft, 3, CleanupPolicy.STRONG)
    assert [page_cleanup(draft, page) for page in draft.pages] == [
        CleanupPolicy.LIGHT,
        CleanupPolicy.OFF,
        CleanupPolicy.STRONG,
    ]


def test_the_command_line_edits_have_no_cleanup() -> None:
    assert "cleanup" not in PageEdits.__dataclass_fields__


# --- the analysis ------------------------------------------------------------------------------


def shaded_pages(folder: Path) -> list[Path]:
    folder.mkdir()
    page = fx.odd_size_page(100, 400, 300).pixels
    return [write_png(folder / f"page-{n:04d}.png", page, dpi=100) for n in (1, 2)]


def settings_for(tmp_path: Path, **changes: object) -> DocumentSettings:
    return store_settings(tmp_path, keep_blank=True, duplex=False, **changes)


def test_an_analysed_draft_carries_the_settings_level(tmp_path: Path) -> None:
    pages = shaded_pages(tmp_path / "pages")
    for level in CleanupPolicy:
        draft = analyse_document(
            pages, settings_for(tmp_path, cleanup=level, colour=ColourPolicy.GREY)
        )
        assert draft.cleanup is level
        assert all(
            page.encoded is not None and page.encoded.cleanup is level for page in draft.pages
        )


def test_an_encoded_page_records_the_effective_level_for_black_and_white(tmp_path: Path) -> None:
    pages = shaded_pages(tmp_path / "pages")
    settings = settings_for(tmp_path, cleanup=CleanupPolicy.STRONG, colour=ColourPolicy.BW)
    draft = analyse_document(pages, settings)
    assert draft.cleanup is CleanupPolicy.STRONG
    assert all(page.encoded.cleanup is CleanupPolicy.OFF for page in draft.pages)  # type: ignore[union-attr]
    plain = analyse_document(pages, replace(settings, cleanup=CleanupPolicy.OFF))
    assert [p.encoded.data for p in draft.pages] == [p.encoded.data for p in plain.pages]  # type: ignore[union-attr]


def test_cleanup_off_leaves_the_default_bytes_alone(tmp_path: Path) -> None:
    pages = shaded_pages(tmp_path / "pages")
    off = analyse_document(pages, settings_for(tmp_path, colour=ColourPolicy.COLOUR))
    light = analyse_document(
        pages, settings_for(tmp_path, colour=ColourPolicy.COLOUR, cleanup=CleanupPolicy.LIGHT)
    )
    assert off.pages[0].encoded.data != light.pages[0].encoded.data  # type: ignore[union-attr]
    assert off.pages == light.pages  # the verdicts are the same: the analysis is not the render


def test_the_analysis_judges_the_raw_pixels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pages = shaded_pages(tmp_path / "pages")
    raw = trim_page(load_page(pages[0], fallback_dpi=None)).page.pixels.tobytes()
    seen: dict[str, list[bytes]] = {"assess": [], "classify": [], "thumb": []}
    for name, target in (("assess", "assess_page"), ("classify", "classify_colour")):
        original = getattr(analyse_module, target)

        def spy(first, *args, _name=name, _original=original):
            pixels = first.page.pixels if hasattr(first, "page") else first.pixels
            seen[_name].append(pixels.tobytes())
            return _original(first, *args)

        monkeypatch.setattr(analyse_module, target, spy)
    settings = settings_for(tmp_path, cleanup=CleanupPolicy.STRONG, colour=ColourPolicy.COLOUR)
    analyse_document(pages[:1], replace(settings, keep_blank=False))
    assert seen["assess"] == [raw]
    assert seen["classify"] == [raw]


def test_the_analysis_version_is_unchanged() -> None:
    assert ANALYSIS_VERSION == 3
