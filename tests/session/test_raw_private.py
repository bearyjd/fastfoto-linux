"""The raw pages of a document are private (mode 0700); the photo ones are as they always were."""

import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from fastfoto_linux.session import RawPolicy
from fastfoto_linux.session.raw import create_raw_dir
from tests.documents.helpers import blank_scene, text_scene
from tests.process_helpers import plain_sheet
from tests.session.conftest import STAMP, make_request, run
from tests.session.doc_session_helpers import make_doc_request, run_doc

PRIVATE = 0o700


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture(params=[0o022, 0o000], ids=["umask-022", "umask-000"])
def umask(request: pytest.FixtureRequest) -> Iterator[int]:
    old = os.umask(request.param)
    yield request.param
    os.umask(old)


@pytest.mark.usefixtures("no_real_ocr")
def test_kept_document_pages_are_scanned_into_a_private_folder(out, doc_transport, umask) -> None:
    doc_transport.scenes = [text_scene(1)]
    run_doc(make_doc_request(out, policy=RawPolicy.KEEP), doc_transport)
    assert mode_of(out / ".raw" / STAMP) == PRIVATE


@pytest.mark.usefixtures("no_real_ocr")
def test_document_pages_kept_after_a_blank_page_are_private(out, doc_transport, umask) -> None:
    doc_transport.scenes = [text_scene(1), blank_scene(2)]
    result = run_doc(make_doc_request(out), doc_transport)
    assert result.raw_dir == out / ".raw" / STAMP
    assert mode_of(out / ".raw" / STAMP) == PRIVATE


def test_a_private_raw_folder_that_already_exists_is_made_private(out: Path) -> None:
    (out / ".raw" / STAMP).mkdir(parents=True, mode=0o755)
    old = os.umask(0o022)
    try:
        folder = create_raw_dir(out, keep=True, private=True)
    finally:
        os.umask(old)
    assert mode_of(folder) == PRIVATE


def test_a_kept_photo_folder_is_made_as_it_always_was(out, transport) -> None:
    transport.sheets = [plain_sheet()]
    old = os.umask(0o022)
    try:
        run(make_request(out, policy=RawPolicy.KEEP), transport)
    finally:
        os.umask(old)
    assert mode_of(out / ".raw" / STAMP) == 0o755


def test_a_raw_folder_is_not_private_unless_asked(out: Path) -> None:
    old = os.umask(0o022)
    try:
        folder = create_raw_dir(out, keep=True)
    finally:
        os.umask(old)
    assert mode_of(folder) == 0o755
