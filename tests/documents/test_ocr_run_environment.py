"""How ``run_ocr`` starts ocrmypdf: as a module of the running interpreter or as a program, with
the programs it needs on PATH, and with a rasterizer that is never Ghostscript."""

import os
import sys
import textwrap
from pathlib import Path

import pytest

from fastfoto_linux.documents import ocr_tools
from fastfoto_linux.documents.ocr import OcrStatus, run_ocr
from tests import _fake_ocrmypdf as fake
from tests.documents.ocr_helpers import PLAIN, SHORT_GRACE_S, TIMEOUT_S, run_fake

MODULE_MAIN = textwrap.dedent(
    """\
    import json, os, sys

    argv = sys.argv[1:]
    open(os.environ["FAKE_MODULE_RECORD"], "w").write(json.dumps({"argv": argv}))
    open(argv[-1], "wb").write(open(argv[-2], "rb").read())
    """
)


@pytest.fixture
def staging(tmp_path: Path) -> Path:
    folder = tmp_path / "staging"
    folder.mkdir()
    return folder


@pytest.fixture
def fake_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return fake.put_on_path(tmp_path / "bin", monkeypatch)


@pytest.fixture
def module_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in ``ocrmypdf`` package that comes first on the interpreter's import path."""
    package = tmp_path / "modules" / "ocrmypdf"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text(MODULE_MAIN, encoding="utf-8")
    record = tmp_path / "module-record.json"
    monkeypatch.setenv("PYTHONPATH", str(package.parent))
    monkeypatch.setenv("FAKE_MODULE_RECORD", str(record))
    return record


def test_the_rasterizer_is_pdfium_so_that_ghostscript_is_never_used(
    fake_on_path: Path, staging: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record.json"
    run_fake(fake_on_path, monkeypatch, staging_parent=staging, record_to=str(record))
    argv = fake.read_record(record)["argv"]
    assert argv[argv.index("--rasterizer") + 1] == "pypdfium"
    assert argv[argv.index("--output-type") + 1] == "pdf"  # as before: no PDF/A, no Ghostscript


def test_ocrmypdf_runs_with_the_brew_folder_and_the_interpreters_folder_on_path(
    fake_on_path: Path, staging: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    brew_bin = tmp_path / "linuxbrew" / "bin"
    brew_bin.mkdir(parents=True)
    monkeypatch.setattr(ocr_tools, "BREW_BIN", brew_bin)
    monkeypatch.setenv("PATH", f"{fake_on_path.parent}{os.pathsep}/usr/bin")
    record = tmp_path / "record.json"
    run_fake(fake_on_path, monkeypatch, staging_parent=staging, record_to=str(record))
    folders = fake.read_record(record)["path"].split(os.pathsep)
    assert folders == [
        str(brew_bin),
        str(Path(sys.executable).parent),
        str(fake_on_path.parent),
        "/usr/bin",
    ]


def test_the_interpreter_is_run_with_dash_m_when_it_has_the_module(
    staging: Path, module_record: Path
) -> None:
    outcome = run_ocr(
        PLAIN,
        executable=sys.executable,
        langs="eng+deu",
        page_count=2,
        staging_parent=staging,
        timeout_s=TIMEOUT_S,
        grace_s=SHORT_GRACE_S,
    )
    assert outcome.status is OcrStatus.DONE, outcome.detail
    argv = fake.read_record(module_record)["argv"]
    assert argv[:-2] == [
        *["--output-type", "pdf", "--rotate-pages", "-l", "eng+deu"],
        *["--rasterizer", "pypdfium"],
    ]


def test_a_program_is_run_as_it_is_not_with_dash_m(
    fake_on_path: Path, staging: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record.json"
    run_fake(fake_on_path, monkeypatch, staging_parent=staging, record_to=str(record))
    assert "-m" not in fake.read_record(record)["argv"]
