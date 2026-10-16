"""``ffscan doc scan`` when the session itself refuses the settings: the exit codes stay."""

import pytest

from fastfoto_linux.cli import cmd_doc
from fastfoto_linux.cli.errors import CliError
from fastfoto_linux.documents import DocumentSettingsError, OcrMissingError
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
