"""``--despeckle`` of ``ffscan doc``: the option, a raw folder's stored value, the dry run and
the recovery hint. Every run here has OCR off."""

import shlex
from pathlib import Path
from typing import Any

import pypdf
import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.cli.app import build_parser
from fastfoto_linux.cli.doc_options import build_settings
from fastfoto_linux.documents import write
from fastfoto_linux.documents.draft_edit import set_document_despeckle
from fastfoto_linux.documents.draft_store import REVIEW_FILE, save_draft
from tests.cli.doc_cleanup_helpers import OCR_OFF, raw_folder_of, shaded_pages
from tests.cli.doc_scan_helpers import doc_scan
from tests.cli.test_doc_scan_recovery import expected, jam_after, printed_command
from tests.documents.store_helpers import analysed, store_settings

pytestmark = pytest.mark.usefixtures("no_real_ocr")

PROCESS = ["doc", "process", "x.png", "--out", "o"]
SCAN = ["doc", "scan", "--out", "o"]


@pytest.fixture
def out(tmp_path: Path) -> Path:
    path = tmp_path / "out"
    path.mkdir()
    return path


def settings_of(argv: list[str]):
    return build_settings(build_parser().parse_args(argv))


def test_the_default_is_none_and_not_given_is_off() -> None:
    parse = build_parser().parse_args
    assert parse(PROCESS).despeckle is None
    assert parse([*PROCESS, "--despeckle"]).despeckle is True
    assert parse([*PROCESS, "--no-despeckle"]).despeckle is False
    for base in (PROCESS, SCAN):
        assert settings_of(base).despeckle is False
        assert settings_of([*base, "--despeckle"]).despeckle is True
        assert settings_of([*base, "--no-despeckle"]).despeckle is False


def test_the_help_says_what_it_does(capsys) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["doc", "process", "--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert "--despeckle" in text
    assert "remove small isolated specks from black and white pages" in text


class Spy:
    """The ``despeckle`` argument of each ``write.encode_page`` call."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.flags: list[Any] = []
        original = write.encode_page

        def spy(*args: Any, **kwargs: Any) -> Any:
            self.flags.append(kwargs.get("despeckle"))
            return original(*args, **kwargs)

        monkeypatch.setattr(write, "encode_page", spy)


def process(folder: Path, out: Path, monkeypatch: pytest.MonkeyPatch, *extra: str) -> list[Any]:
    spy = Spy(monkeypatch)
    argv = ["doc", "process", str(folder), "--out", str(out), *OCR_OFF, "--colour", "bw", *extra]
    assert main(argv) == 0
    return spy.flags


def store(raw: tuple[Path, tuple[Path, ...]], out: Path, flag: bool) -> None:
    folder, pages = raw
    settings = store_settings(out, duplex=False)
    save_draft(set_document_despeckle(analysed(folder, pages, settings), flag), settings)


@pytest.mark.parametrize(
    ("extra", "expected_flag"),
    [([], False), (["--despeckle"], True), (["--no-despeckle"], False)],
)
def test_without_a_sidecar_the_flag_is_the_setting(
    tmp_path, out, monkeypatch, extra, expected_flag
) -> None:
    raw = raw_folder_of(tmp_path, count=2)
    assert process(raw[0], out, monkeypatch, *extra) == [expected_flag] * 2


@pytest.mark.parametrize(
    ("extra", "expected_flag"),
    [([], True), (["--despeckle"], True), (["--no-despeckle"], False)],
)
def test_a_version_5_raw_folder_keeps_its_value_until_the_flag_says_otherwise(
    tmp_path, out, monkeypatch, extra, expected_flag
) -> None:
    raw = raw_folder_of(tmp_path, count=2)
    store(raw, out, True)
    sidecar = raw[0] / REVIEW_FILE
    before = (sidecar.read_bytes(), sidecar.stat().st_mtime_ns)
    assert process(raw[0], out, monkeypatch, *extra) == [expected_flag] * 2
    assert (sidecar.read_bytes(), sidecar.stat().st_mtime_ns) == before


def test_no_flag_on_a_raw_folder_without_despeckle_stays_off(tmp_path, out, monkeypatch) -> None:
    raw = raw_folder_of(tmp_path, count=2)
    store(raw, out, False)
    assert process(raw[0], out, monkeypatch) == [False, False]


def test_the_pdf_without_the_flag_is_the_pdf_with_no_despeckle(tmp_path, out) -> None:
    pages = shaded_pages(tmp_path / "raw")
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    args = ["doc", "process", str(pages[0]), *OCR_OFF, "--colour", "bw", "--out"]
    assert main([*args, str(one)]) == 0
    assert main([*args, str(two), "--no-despeckle"]) == 0
    images = [
        pypdf.PdfReader(folder / "Document_0001.pdf").pages[0].images[0].data
        for folder in (one, two)
    ]
    assert images[0] == images[1]


def dry_run(capsys, out: Path, source: list[Path], *extra: str) -> str:
    argv = ["doc", "process", *map(str, source), "--out", str(out), *OCR_OFF, "--dry-run", *extra]
    assert main(argv) == 0
    return capsys.readouterr().out


def test_the_dry_run_shows_despeckle_on_black_and_white_rows_only(tmp_path, out, capsys) -> None:
    pages = shaded_pages(tmp_path / "raw")
    text = dry_run(capsys, out, pages, "--despeckle", "--colour", "bw")
    assert text.count("despeckle") == 1
    assert "; despeckle" in text
    assert "despeckle" not in dry_run(capsys, out, pages, "--despeckle", "--colour", "grey")
    assert "despeckle" not in dry_run(capsys, out, pages, "--colour", "bw")


def test_the_recovery_hint_repeats_the_flag(tmp_path, doc_transport, capsys, fixed_stamp) -> None:
    root = tmp_path / "my scans"
    root.mkdir()
    jam_after(doc_transport, 2)
    assert doc_scan(root, "--despeckle") == 1
    command = printed_command(capsys.readouterr().err)
    assert command == expected(root, 2, "--dpi", "300", "--despeckle", "--ocr", "off")
    assert shlex.split(command)[0] == "ffscan"
