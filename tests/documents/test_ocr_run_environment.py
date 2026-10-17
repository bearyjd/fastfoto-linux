"""How ``run_ocr`` starts ocrmypdf: as a module of the running interpreter or as a program, with
the programs it needs on PATH, and with a rasterizer that is never Ghostscript."""

import importlib.metadata
import os
import sys
import textwrap
from pathlib import Path

import pytest

from fastfoto_linux.documents import ocr_tools, ocr_version
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


def test_ocrmypdf_runs_with_the_path_it_was_given_then_the_interpreters_folder_then_brews(
    fake_on_path: Path, staging: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The order of detection, so that Homebrew's folder never shadows /usr/bin."""
    brew_bin = tmp_path / "linuxbrew" / "bin"
    brew_bin.mkdir(parents=True)
    brew_bin.chmod(0o755)
    monkeypatch.setattr(ocr_tools, "BREW_BIN", brew_bin)
    monkeypatch.setenv("PATH", f"{fake_on_path.parent}{os.pathsep}/usr/bin")
    record = tmp_path / "record.json"
    run_fake(fake_on_path, monkeypatch, staging_parent=staging, record_to=str(record))
    folders = fake.read_record(record)["path"].split(os.pathsep)
    assert folders == [
        str(fake_on_path.parent),
        "/usr/bin",
        str(Path(sys.executable).parent),
        str(brew_bin),
    ]


def test_the_interpreter_is_run_with_dash_m_when_it_has_the_module(
    staging: Path, module_record: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ocr_version, "metadata_version", lambda name: "17.13.0")
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


def test_the_module_is_never_taken_from_the_folder_ffscan_runs_in(
    staging: Path, module_record: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``python -m`` puts the current folder first on the import path: a folder that holds an
    ``ocrmypdf`` package of its own must not get its code run."""
    shadow = tmp_path / "elsewhere" / "ocrmypdf"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text("", encoding="utf-8")
    (shadow / "__main__.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    monkeypatch.chdir(shadow.parent)
    outcome = run_ocr(
        PLAIN,
        executable=sys.executable,
        langs="eng",
        page_count=2,
        staging_parent=staging,
        timeout_s=TIMEOUT_S,
        grace_s=SHORT_GRACE_S,
    )
    assert outcome.status is OcrStatus.DONE, outcome.detail
    assert module_record.is_file()


def test_a_program_is_run_as_it_is_not_with_dash_m(
    fake_on_path: Path, staging: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record.json"
    run_fake(fake_on_path, monkeypatch, staging_parent=staging, record_to=str(record))
    assert "-m" not in fake.read_record(record)["argv"]


# ---- the rasterizer option only for the versions that know it -------------------------------


def run_module(staging: Path, langs: str = "eng") -> OcrStatus:
    outcome = run_ocr(
        PLAIN,
        executable=sys.executable,
        langs=langs,
        page_count=2,
        staging_parent=staging,
        timeout_s=TIMEOUT_S,
        grace_s=SHORT_GRACE_S,
    )
    return outcome.status


@pytest.mark.parametrize(
    ("version", "passed"),
    [("17.13.0", True), ("17.0.0", True), ("16.4.3", False), ("15.0.0", False)],
)
def test_a_program_is_given_the_rasterizer_only_from_version_17(
    fake_on_path: Path,
    staging: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
    passed: bool,
) -> None:
    record = staging.parent / "record.json"
    outcome = run_fake(
        fake_on_path, monkeypatch, staging_parent=staging, record_to=str(record), version=version
    )
    assert outcome.status is OcrStatus.DONE, outcome.detail  # the fake exits 2 on an unknown flag
    assert ("--rasterizer" in fake.read_record(record)["argv"]) is passed


def test_a_program_that_does_not_say_its_version_is_not_given_the_rasterizer(
    fake_on_path: Path, staging: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record.json"
    outcome = run_fake(
        fake_on_path,
        monkeypatch,
        staging_parent=staging,
        record_to=str(record),
        version="16.4.3",
        version_text="unreadable",
    )
    assert outcome.status is OcrStatus.DONE, outcome.detail
    assert "--rasterizer" not in fake.read_record(record)["argv"]


def test_the_other_options_are_the_same_for_every_version(
    fake_on_path: Path, staging: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record.json"
    run_fake(
        fake_on_path,
        monkeypatch,
        langs="eng+deu",
        staging_parent=staging,
        record_to=str(record),
        version="16.4.3",
    )
    assert fake.read_record(record)["argv"][:-2] == [
        *["--output-type", "pdf", "--rotate-pages", "-l", "eng+deu"],
    ]


@pytest.mark.parametrize(
    ("version", "passed"), [("17.13.0", True), ("16.4.3", False), (None, False)]
)
def test_the_module_is_given_the_rasterizer_by_the_version_it_is_installed_as(
    staging: Path,
    module_record: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str | None,
    passed: bool,
) -> None:
    def installed(name: str) -> str:
        if version is None:
            raise importlib.metadata.PackageNotFoundError(name)
        return version

    monkeypatch.setattr(ocr_version, "metadata_version", installed)
    assert run_module(staging) is OcrStatus.DONE
    assert ("--rasterizer" in fake.read_record(module_record)["argv"]) is passed


def test_a_program_that_rejects_the_options_says_so_with_its_version(
    fake_on_path: Path, staging: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = run_fake(
        fake_on_path,
        monkeypatch,
        staging_parent=staging,
        version="17.13.0",
        reject=["--rotate-pages"],  # exit status 2, the way argparse says "unrecognized arguments"
    )
    assert outcome.status is OcrStatus.FAILED
    assert "status 2" in outcome.detail
    assert "did not accept the options" in outcome.detail
    assert "(version 17.13.0)" in outcome.detail
    assert outcome.detail.index("did not accept") < outcome.detail.index("could not read")
