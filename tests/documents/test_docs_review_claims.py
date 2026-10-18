"""What the README and the design note say about the review sidecar, the thumbnails, a raw folder
as the input and what is deleted is what the code does."""

from pathlib import Path

import pytest

from fastfoto_linux.cli import doc_edit_options
from fastfoto_linux.documents import draft_store, thumbs

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = {
    "README": (ROOT / "README.md").read_text(encoding="utf-8"),
    "design note": (ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8"),
}


def text_of(name: str) -> str:
    return " ".join(DOCUMENTS[name].split())


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_sidecar_and_the_thumbnails_are_described_with_their_names(name: str) -> None:
    text = text_of(name)
    assert f"`{draft_store.REVIEW_FILE}`" in text
    assert f"`{draft_store.THUMBS_DIR}/" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_limits_are_the_ones_in_the_code(name: str) -> None:
    text = text_of(name)
    assert f"{thumbs.THUMB_MAX_PX} px" in text
    assert f"{draft_store.MAX_REVIEW_BYTES // (1024 * 1024)} MiB" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_a_raw_folder_as_the_input_is_described(name: str) -> None:
    text = text_of(name)
    assert "ffscan doc process" in text
    assert "RAWDIR" in text
    assert "--fresh" in doc_edit_options.EDIT_OPTIONS
    assert "never writes" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_deletion_policy_is_described(name: str) -> None:
    text = text_of(name)
    assert "nothing is deleted automatically" in text
    assert "Delete the original pages" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_sidecar_is_called_untrusted_input(name: str) -> None:
    assert "untrusted" in text_of(name)
