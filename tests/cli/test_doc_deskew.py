"""``--deskew`` of ``ffscan doc``: the option, a raw folder's stored angles, the dry run, the three
ways ``doc process`` reaches the writer, and the recovery hint. Every run here has OCR off."""

import json
import shlex
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from fastfoto_linux.cli import cmd_doc, main
from fastfoto_linux.cli.app import build_parser
from fastfoto_linux.cli.doc_options import build_settings
from fastfoto_linux.cli.errors import EXIT_USAGE
from fastfoto_linux.documents import cleanup, write
from fastfoto_linux.documents.draft_edit import set_crop, set_deskew
from fastfoto_linux.documents.draft_store import REVIEW_FILE, read_review, save_draft
from fastfoto_linux.documents.errors import UnsupportedPageError
from fastfoto_linux.documents.page_crop import PageCrop
from fastfoto_linux.session.raw import list_pages
from tests.cli.doc_cleanup_helpers import OCR_OFF
from tests.cli.doc_scan_helpers import doc_scan
from tests.cli.test_doc_scan_recovery import expected, jam_after, printed_command
from tests.doc_synth import write_png
from tests.documents.deskew_fixtures import scatter, skewed, text_page
from tests.documents.store_helpers import analysed, store_settings

pytestmark = pytest.mark.usefixtures("no_real_ocr")

PROCESS = ["doc", "process", "x.png", "--out", "o"]
SCAN = ["doc", "scan", "--out", "o"]
DPI = 100
CROP = PageCrop(100, 100, 9000, 9000)


@pytest.fixture
def out(tmp_path: Path) -> Path:
    path = tmp_path / "out"
    path.mkdir()
    return path


def pages_in(folder: Path) -> list[Path]:
    """Page 1 is text tilted clockwise by 4.1 degrees, page 2 cannot be measured."""
    folder.mkdir(parents=True, exist_ok=True)
    tilted = skewed(text_page(np.random.default_rng(1), dpi=DPI), 41)
    return [
        write_png(folder / "page-0001.png", tilted, dpi=DPI),
        write_png(folder / "page-0002.png", scatter()[::3, ::3], dpi=DPI),
    ]


def raw_of(tmp_path: Path) -> tuple[Path, tuple[Path, ...]]:
    folder = tmp_path / ".raw" / "20261025T120000Z"
    folder.mkdir(parents=True, mode=0o700)
    pages_in(folder)
    return folder, list_pages(folder)


class Angles:
    """The angle each page gets from ``write.edited_page``, in the order written."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.seen: list[tuple[int | None, Any]] = []
        original = write.edited_page

        def spy(page: Any, edit: Any) -> Any:
            self.seen.append((edit.deskew_tenths, edit.crop))
            return original(page, edit)

        monkeypatch.setattr(write, "edited_page", spy)

    @property
    def angles(self) -> list[int | None]:
        return [angle for angle, _ in self.seen]


def run(source: Path | list[Path], out: Path, *extra: str) -> int:
    pages = [source] if isinstance(source, Path) else source
    return main(["doc", "process", *map(str, pages), "--out", str(out), *OCR_OFF, *extra])


def settings_of(argv: list[str]):
    return build_settings(build_parser().parse_args(argv))


def test_the_default_is_none_and_not_given_is_off() -> None:
    parse = build_parser().parse_args
    assert parse(PROCESS).deskew is None
    assert parse([*PROCESS, "--deskew"]).deskew is True
    assert parse([*PROCESS, "--no-deskew"]).deskew is False
    for base in (PROCESS, SCAN):
        assert settings_of(base).deskew is False
        assert settings_of([*base, "--deskew"]).deskew is True
        assert settings_of([*base, "--no-deskew"]).deskew is False


def test_the_help_says_what_it_does(capsys) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["doc", "process", "--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert "--deskew" in text
    assert "straighten pages whose text is tilted by 0.3 to 10 degrees" in text
    assert "also removes a crop made on a straightened page" in text


def test_a_raw_folder_without_the_flag_is_not_straightened(tmp_path, out, monkeypatch) -> None:
    spy = Angles(monkeypatch)
    assert run(raw_of(tmp_path)[0], out) == 0
    assert spy.angles == [None, None]


def test_a_raw_folder_with_the_flag_is_straightened_where_it_can_be(
    tmp_path, out, monkeypatch
) -> None:
    spy = Angles(monkeypatch)
    assert run(raw_of(tmp_path)[0], out, "--deskew") == 0
    assert spy.angles[0] is not None
    assert abs(spy.angles[0] - -41) <= 1
    assert spy.angles[1] is None


def store(raw: tuple[Path, tuple[Path, ...]], out: Path, *, crop: bool = False) -> bytes:
    folder, pages = raw
    settings = store_settings(out, duplex=False)
    draft = set_deskew(analysed(folder, pages, settings), 1, 55)
    save_draft(set_crop(set_deskew(draft, 2, 6), 2, CROP) if crop else draft, settings)
    return (folder / REVIEW_FILE).read_bytes()


@pytest.mark.parametrize(
    ("extra", "first"), [([], 55), (["--deskew"], 55), (["--no-deskew"], None)]
)
def test_a_version_6_raw_folder_keeps_its_angles_until_the_flag_says_otherwise(
    tmp_path, out, monkeypatch, extra, first
) -> None:
    raw = raw_of(tmp_path)
    before = store(raw, out)
    assert json.loads(before)["version"] == 6
    spy = Angles(monkeypatch)
    assert run(raw[0], out, *extra) == 0
    assert spy.angles[0] == first
    assert (raw[0] / REVIEW_FILE).read_bytes() == before  # the command never saves


def test_no_deskew_also_removes_a_crop_made_on_a_straightened_page(
    tmp_path, out, monkeypatch, capsys
) -> None:
    raw = raw_of(tmp_path)
    store(raw, out, crop=True)
    assert read_review(raw[0], raw[1]).draft.edits[2].crop == CROP
    spy = Angles(monkeypatch)
    assert run(raw[0], out, "--no-deskew") == 0
    assert spy.seen == [(None, None), (None, None)]
    assert run(raw[0], out, "--no-deskew", "--dry-run") == 0
    assert "crop removed" in capsys.readouterr().out


def dry_run(capsys, source, out: Path, *extra: str) -> list[str]:
    assert run(source, out, "--dry-run", *extra) == 0
    return capsys.readouterr().out.splitlines()


def test_the_dry_run_says_which_pages_would_turn_and_which_would_not(tmp_path, out, capsys) -> None:
    lines = dry_run(capsys, raw_of(tmp_path)[0], out, "--deskew")
    first, second = (next(line for line in lines if line.startswith(n)) for n in ("1 ", "2 "))
    assert "deskew -4.1°" in first or "deskew -4.0°" in first or "deskew -4.2°" in first
    assert "deskew skipped (" in second
    assert not any("deskew" in line for line in dry_run(capsys, raw_of(tmp_path / "plain")[0], out))


def test_a_dry_run_shows_a_stored_angle_without_the_flag(tmp_path, out, capsys) -> None:
    raw = raw_of(tmp_path)
    store(raw, out)
    lines = dry_run(capsys, raw[0], out)
    assert "deskew 5.5°" in next(line for line in lines if line.startswith("1 "))


def test_loose_pages_with_edits_are_straightened(tmp_path, out, monkeypatch) -> None:
    pages = pages_in(tmp_path / "loose")
    spy = Angles(monkeypatch)
    assert run(pages, out, "--deskew", "--rotate", "2:90") == 0
    assert abs(spy.angles[0] - -41) <= 1


def test_loose_pages_take_the_shortcut_through_build(tmp_path, out, monkeypatch) -> None:
    pages = pages_in(tmp_path / "loose")
    spy = Angles(monkeypatch)
    assert run(pages, out, "--deskew") == 0
    assert abs(spy.angles[0] - -41) <= 1
    spy.seen.clear()
    assert run(pages, out) == 0
    assert spy.seen == []  # carried bytes are reused: nothing is read again


def test_the_scan_session_gets_the_setting(tmp_path, doc_transport, monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def session(request, **hooks):
        seen["deskew"] = request.settings.deskew
        raise KeyboardInterrupt

    monkeypatch.setattr(cmd_doc, "run_document_session", session)
    assert doc_scan(tmp_path, "--deskew") == 130  # the stand-in ends as an interrupt
    assert seen == {"deskew": True}


def test_the_recovery_hint_repeats_the_flag(tmp_path, doc_transport, capsys, fixed_stamp) -> None:
    root = tmp_path / "my scans"
    root.mkdir()
    jam_after(doc_transport, 2)
    assert doc_scan(root, "--deskew") == 1
    command = printed_command(capsys.readouterr().err)
    assert command == expected(root, 2, "--dpi", "300", "--deskew", "--ocr", "off")
    assert shlex.split(command)[0] == "ffscan"


def blank_second(folder: Path) -> tuple[Path, tuple[Path, ...]]:
    raw = raw_of(folder)
    write_png(raw[0] / "page-0002.png", np.full((787, 590), 240, np.uint8), dpi=DPI)
    return raw


def row(lines: list[str], number: int) -> str:
    return next(line for line in lines if line.startswith(f"{number} "))


def test_pages_brought_back_are_measured_and_pages_dropped_are_not(tmp_path, out, capsys) -> None:
    raw = blank_second(tmp_path)
    kept = dry_run(capsys, raw[0], out, "--deskew", "--keep", "2")
    assert "deskew skipped (little_ink)" in row(kept, 2)
    dropped = dry_run(capsys, raw[0], out, "--deskew", "--drop", "1")
    assert "deskew" not in row(dropped, 1)
    assert "left out" in row(dropped, 1)


def test_a_stored_angle_on_a_page_too_large_to_straighten_is_said_to_be_skipped(
    tmp_path, out, capsys, monkeypatch
) -> None:
    raw = raw_of(tmp_path)
    store(raw, out)
    monkeypatch.setattr(cleanup, "MAX_WORK_PIXELS", 1000)
    lines = dry_run(capsys, raw[0], out)
    assert "deskew skipped (too_large)" in row(lines, 1)
    assert "deskew 5.5" not in row(lines, 1)


@pytest.mark.parametrize("failure", [UnsupportedPageError("x"), ValueError("x")])
def test_a_page_that_cannot_be_read_again_is_a_usage_error(
    tmp_path, out, monkeypatch, capsys, failure
) -> None:
    def refuse(*args, **kwargs):
        raise failure

    monkeypatch.setattr(cmd_doc, "estimate_deskew", refuse)
    assert run(raw_of(tmp_path)[0], out, "--deskew") == EXIT_USAGE
    assert "Traceback" not in capsys.readouterr().err
