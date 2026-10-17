"""``ffscan doc scan`` when the session itself refuses the settings: the exit codes stay."""

import pytest

from fastfoto_linux.cli import cmd_doc
from fastfoto_linux.cli.app import exit_code_for
from fastfoto_linux.cli.errors import CliError
from fastfoto_linux.documents import DocumentSettingsError, OcrMissingError
from fastfoto_linux.documents.errors import OutputFolderMissingError
from tests.cli.doc_scan_helpers import doc_scan

pytestmark = pytest.mark.usefixtures("no_real_ocr", "fixed_stamp")


def refusing(error: Exception):
    def run(request, **_):
        raise error

    return run


def test_settings_the_session_refuses_are_a_usage_error(
    out, doc_transport, monkeypatch, capsys
) -> None:
    error = DocumentSettingsError("the output folder is gone")
    monkeypatch.setattr(cmd_doc, "run_document_session", refusing(error))
    assert doc_scan(out) == 2
    assert "the output folder is gone" in capsys.readouterr().err


def test_a_missing_ocrmypdf_the_session_finds_is_exit_3(
    out, doc_transport, monkeypatch, capsys
) -> None:
    error = OcrMissingError("searchable text needs ocrmypdf, which is not installed")
    monkeypatch.setattr(cmd_doc, "run_document_session", refusing(error))
    assert doc_scan(out) == 3
    assert "needs ocrmypdf" in capsys.readouterr().err


def test_the_failures_a_user_can_act_on_become_one_line_errors() -> None:
    failure = cmd_doc.document_failure(DocumentSettingsError("bad name"))
    assert isinstance(failure, CliError)
    assert (failure.code, str(failure)) == (2, "bad name")


def test_a_folder_that_vanished_after_the_checks_is_exit_1_as_for_doc_process(
    out, doc_transport, monkeypatch, capsys
) -> None:
    error = OutputFolderMissingError("the output folder /out is not an existing folder")
    monkeypatch.setattr(cmd_doc, "run_document_session", refusing(error))
    assert doc_scan(out) == 1
    assert "is not an existing folder" in capsys.readouterr().err


def test_a_folder_removed_after_the_checks_scans_nothing_and_exits_1(
    out, doc_transport, monkeypatch, capsys
) -> None:
    prepare = cmd_doc.prepare_output_root

    def prepare_then_lose_the_folder(args):
        root = prepare(args)
        root.rmdir()  # empty: the checks have passed, and then the drive goes away
        return root

    monkeypatch.setattr(cmd_doc, "prepare_output_root", prepare_then_lose_the_folder)
    assert doc_scan(out) == 1
    assert "not an existing folder" in capsys.readouterr().err
    assert doc_transport.jobs == []


def test_only_the_missing_folder_changes_exit_code_the_other_settings_stay_usage_errors() -> None:
    gone = OutputFolderMissingError("the output folder /out is not an existing folder")
    assert exit_code_for(cmd_doc.document_failure(gone)) == 1
    assert exit_code_for(cmd_doc.document_failure(DocumentSettingsError("bad name"))) == 2
