"""Publishing the PDF: numbered like photos, never overwriting, cleaned names."""

from pathlib import Path

import pytest

from fastfoto_linux.documents.publish import publish_pdf
from fastfoto_linux.output.errors import InvalidPrefixError, OutputRootMissingError
from fastfoto_linux.output.naming import next_index, pdf_path

PDF = b"%PDF-1.4 first"
OTHER = b"%PDF-1.4 second"


def test_the_pdf_is_written_as_name_and_a_four_digit_number(tmp_path: Path) -> None:
    path = publish_pdf(PDF, tmp_path, "Document")
    assert path == tmp_path / "Document_0001.pdf"
    assert path.read_bytes() == PDF


def test_each_call_takes_the_next_number_and_leaves_earlier_files_alone(tmp_path: Path) -> None:
    first = publish_pdf(PDF, tmp_path, "Document")
    second = publish_pdf(OTHER, tmp_path, "Document")
    assert (first.name, second.name) == ("Document_0001.pdf", "Document_0002.pdf")
    assert (first.read_bytes(), second.read_bytes()) == (PDF, OTHER)


def test_numbering_is_shared_with_photos_of_the_same_name(tmp_path: Path) -> None:
    for name in ("Document_0007.jpg", "Document_0003_a.jpg", "Other_0099.jpg"):
        (tmp_path / name).write_bytes(b"x")
    assert publish_pdf(PDF, tmp_path, "Document").name == "Document_0008.pdf"


def test_the_name_is_cleaned_like_an_album_name(tmp_path: Path) -> None:
    path = publish_pdf(PDF, tmp_path, "My/Taxes\\2025 ")
    assert path.parent == tmp_path
    assert path.name == "My Taxes 2025_0001.pdf"


def test_a_name_cannot_climb_out_of_the_folder(tmp_path: Path) -> None:
    folder = tmp_path / "out"
    folder.mkdir()
    path = publish_pdf(PDF, folder, "../../escape")
    assert path.parent == folder
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out"]


@pytest.mark.parametrize("name", ["", "..", "///", " . "])
def test_a_name_with_nothing_usable_is_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(InvalidPrefixError):
        publish_pdf(PDF, tmp_path, name)
    assert list(tmp_path.iterdir()) == []


def test_a_number_taken_in_the_meantime_is_skipped_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    taken = tmp_path / "Document_0001.pdf"
    taken.write_bytes(OTHER)
    calls = []

    def stale(directory: Path, prefix: str) -> int:
        calls.append(prefix)
        return 1  # a writer that did not take the lock got number 1 first

    monkeypatch.setattr("fastfoto_linux.documents.publish.next_index", stale)
    path = publish_pdf(PDF, tmp_path, "Document")
    assert path.name == "Document_0002.pdf"
    assert taken.read_bytes() == OTHER
    assert len(calls) >= 2


def test_a_missing_folder_is_an_error_not_a_new_folder(tmp_path: Path) -> None:
    with pytest.raises(OutputRootMissingError):
        publish_pdf(PDF, tmp_path / "gone", "Document")
    assert list(tmp_path.iterdir()) == []


def test_no_staging_file_is_left_behind(tmp_path: Path) -> None:
    publish_pdf(PDF, tmp_path, "Document")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_the_pdf_path_helper_numbers_like_a_photo(tmp_path: Path) -> None:
    assert pdf_path(tmp_path, "Document", 3) == tmp_path / "Document_0003.pdf"
    assert pdf_path(tmp_path, "Document", 12345) == tmp_path / "Document_12345.pdf"
    (tmp_path / "Document_0004.pdf").write_bytes(b"x")
    assert next_index(tmp_path, "Document") == 5


@pytest.mark.parametrize("index", [0, -1, 10**9])
def test_the_pdf_path_helper_refuses_numbers_it_cannot_write(tmp_path: Path, index: int) -> None:
    with pytest.raises(ValueError, match="index"):
        pdf_path(tmp_path, "Document", index)
