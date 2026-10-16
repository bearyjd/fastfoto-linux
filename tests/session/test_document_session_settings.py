"""A document session refuses settings it cannot use before it touches the folder or the scanner."""

from typing import Any

import pytest

from fastfoto_linux.documents import (
    DocumentError,
    DocumentSettingsError,
    OcrMissingError,
    OcrMode,
)
from fastfoto_linux.session import RawPolicy, Stage
from tests.documents.helpers import text_scene
from tests.session.doc_session_helpers import make_doc_request, run_doc

pytestmark = pytest.mark.usefixtures("no_real_ocr")

BAD_SETTINGS = [  # (the settings, the error they are refused with, a word of its message)
    pytest.param(({"name": "///"}, DocumentSettingsError, "name"), id="name"),
    pytest.param(({"name": ""}, DocumentSettingsError, "name"), id="empty-name"),
    pytest.param(({"langs": "eng;rm"}, DocumentSettingsError, "language"), id="langs"),
    pytest.param(({"ocr": OcrMode.ON}, OcrMissingError, "ocrmypdf"), id="ocr-on-without-the-tool"),
]


class Calls:
    """What the session reached for: the scanner check and the stages."""

    def __init__(self) -> None:
        self.checks: list[str] = []
        self.stages: list[Stage] = []

    def precheck(self, device: str, **_: Any) -> None:
        self.checks.append(device)


def run_refused(request, doc_transport, calls: Calls, error: type[Exception], match: str) -> None:
    with pytest.raises(error, match=match):
        run_doc(request, doc_transport, precheck=calls.precheck, on_stage=calls.stages.append)
    assert doc_transport.jobs == []  # the scanner was never started
    assert calls.checks == []  # nor checked
    assert calls.stages == []


@pytest.mark.parametrize("bad", BAD_SETTINGS)
@pytest.mark.parametrize("policy", list(RawPolicy))
def test_a_bad_setting_starts_no_scan_and_makes_no_folder(out, doc_transport, bad, policy) -> None:
    settings, error, match = bad
    request = make_doc_request(out, policy=policy, **settings)
    run_refused(request, doc_transport, Calls(), error, match)
    assert list(out.iterdir()) == []  # no hidden folder, no .raw


@pytest.mark.parametrize("bad", BAD_SETTINGS)
def test_the_raw_folder_somewhere_else_is_not_made_either(
    out, tmp_path, doc_transport, bad
) -> None:
    settings, error, match = bad
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    request = make_doc_request(out, raw_parent=elsewhere, **settings)
    run_refused(request, doc_transport, Calls(), error, match)
    assert list(elsewhere.iterdir()) == []


def test_an_output_folder_that_is_missing_is_refused_before_anything_is_made(
    out, doc_transport
) -> None:
    gone = out / "gone"
    run_refused(make_doc_request(gone), doc_transport, Calls(), DocumentSettingsError, "gone")
    assert not gone.exists()
    assert list(out.iterdir()) == []


def test_an_output_folder_that_is_a_file_is_refused(out, doc_transport) -> None:
    file = out / "file.txt"
    file.write_text("not a folder")
    run_refused(make_doc_request(file), doc_transport, Calls(), DocumentSettingsError, "file.txt")
    assert list(out.iterdir()) == [file]


def test_the_error_is_one_a_front_end_can_show_as_it_is(out, doc_transport) -> None:
    request = make_doc_request(out, name="///")
    with pytest.raises(DocumentError) as raised:
        run_doc(request, doc_transport)
    assert "///" in str(raised.value)
    assert isinstance(raised.value, ValueError)


def test_good_settings_are_not_refused(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1)]
    result = run_doc(make_doc_request(out, name="Tax Return", langs="eng+deu"), doc_transport)
    assert result.ok
    assert len(doc_transport.jobs) == 1
