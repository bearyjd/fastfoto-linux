"""``--cleanup`` on a raw folder: the flag beats the stored document level, a page's own level
beats the flag, and the command never writes ``review.json``."""

from pathlib import Path

import pytest

from fastfoto_linux.cli import cmd_doc, main
from fastfoto_linux.documents.draft_edit import set_cleanup, set_document_cleanup
from fastfoto_linux.documents.draft_store import REVIEW_FILE, save_draft
from fastfoto_linux.documents.errors import DocumentEditError
from fastfoto_linux.documents.modes import CleanupPolicy
from tests.cli.doc_cleanup_helpers import (
    LIGHT,
    OCR_OFF,
    OFF,
    STRONG,
    EncoderSpy,
    raw_folder_of,
)
from tests.documents.store_helpers import analysed, store_settings, touch_page

pytestmark = pytest.mark.usefixtures("no_real_ocr")


@pytest.fixture
def out(tmp_path: Path) -> Path:
    path = tmp_path / "out"
    path.mkdir()
    return path


@pytest.fixture
def raw(tmp_path: Path) -> tuple[Path, tuple[Path, ...]]:
    return raw_folder_of(tmp_path, count=2)


def store(
    raw: tuple[Path, tuple[Path, ...]],
    out: Path,
    level: CleanupPolicy,
    page_two: CleanupPolicy | None = None,
) -> None:
    """Save a sidecar made by the code: the document level, and an override of page 2."""
    folder, pages = raw
    settings = store_settings(out, duplex=False)
    draft = set_document_cleanup(analysed(folder, pages, settings), level)
    if page_two is not None:
        draft = set_cleanup(draft, 2, page_two)
    save_draft(draft, settings)


def levels_of(
    raw: tuple[Path, tuple[Path, ...]], out: Path, monkeypatch: pytest.MonkeyPatch, *extra: str
) -> list[CleanupPolicy]:
    """The paper cleanup level each page is written with; the sidecar is not touched."""
    sidecar = raw[0] / REVIEW_FILE
    before = (sidecar.read_bytes(), sidecar.stat().st_mtime_ns) if sidecar.exists() else None
    spy = EncoderSpy(monkeypatch)
    assert main(["doc", "process", str(raw[0]), "--out", str(out), *OCR_OFF, *extra]) == 0
    after = (sidecar.read_bytes(), sidecar.stat().st_mtime_ns) if sidecar.exists() else None
    assert after == before
    return spy.levels


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ([], LIGHT),
        (["--cleanup", "off"], OFF),
        (["--cleanup", "strong"], STRONG),
        (["--cleanup", "light"], LIGHT),
    ],
)
def test_a_fresh_sidecar_level_is_kept_and_the_flag_wins_over_it(
    raw, out, monkeypatch, extra, expected
) -> None:
    store(raw, out, LIGHT)
    assert levels_of(raw, out, monkeypatch, *extra) == [expected, expected]


def test_a_page_override_in_the_sidecar_beats_the_flag(raw, out, monkeypatch) -> None:
    store(raw, out, LIGHT, page_two=STRONG)
    assert levels_of(raw, out, monkeypatch, "--cleanup", "off") == [OFF, STRONG]


def test_a_page_override_beats_the_flag_when_the_sidecar_level_is_off(
    raw, out, monkeypatch
) -> None:
    store(raw, out, OFF, page_two=STRONG)
    assert levels_of(raw, out, monkeypatch, "--cleanup", "light") == [LIGHT, STRONG]
    assert levels_of(raw, out, monkeypatch) == [OFF, STRONG]


@pytest.mark.parametrize(
    ("extra", "expected"),
    [([], LIGHT), (["--cleanup", "off"], OFF), (["--cleanup", "strong"], STRONG)],
)
def test_a_stale_sidecar_keeps_its_level_until_the_flag_says_otherwise(
    raw, out, monkeypatch, extra, expected
) -> None:
    store(raw, out, LIGHT)
    touch_page(raw[1][0])
    assert levels_of(raw, out, monkeypatch, *extra) == [expected, expected]


@pytest.mark.parametrize(
    ("extra", "expected"),
    [([], OFF), (["--cleanup", "light"], LIGHT), (["--cleanup", "strong"], STRONG)],
)
def test_without_a_sidecar_the_flag_is_the_level(raw, out, monkeypatch, extra, expected) -> None:
    assert levels_of(raw, out, monkeypatch, *extra) == [expected, expected]


@pytest.mark.parametrize(
    ("extra", "expected"),
    [(["--fresh"], OFF), (["--fresh", "--cleanup", "light"], LIGHT)],
)
def test_fresh_drops_the_stored_level_and_the_flag_still_applies(
    raw, out, monkeypatch, extra, expected
) -> None:
    store(raw, out, STRONG, page_two=STRONG)
    assert levels_of(raw, out, monkeypatch, *extra) == [expected, expected]


def test_the_flag_is_not_saved_into_a_folder_that_has_no_sidecar(raw, out, monkeypatch) -> None:
    assert levels_of(raw, out, monkeypatch, "--cleanup", "strong") == [STRONG, STRONG]
    assert not (raw[0] / REVIEW_FILE).exists()


def test_a_level_the_draft_refuses_is_a_usage_error(raw, out, monkeypatch, capsys) -> None:
    def refuse(draft: object, policy: object) -> object:
        raise DocumentEditError("paper cleanup must be off, light or strong")

    monkeypatch.setattr(cmd_doc, "set_document_cleanup", refuse)
    argv = ["doc", "process", str(raw[0]), "--out", str(out), *OCR_OFF, "--cleanup", "light"]
    assert main(argv) == 2
    assert "paper cleanup must be" in capsys.readouterr().err
    assert not list(out.glob("*.pdf"))
