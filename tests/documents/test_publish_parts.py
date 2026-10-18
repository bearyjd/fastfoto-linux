"""``publish_pdfs``: several PDFs under one lock, each with its own next number, all or none."""

import threading
from pathlib import Path

import pytest

from fastfoto_linux.documents.publish import publish_pdf, publish_pdfs
from fastfoto_linux.output.errors import InvalidPrefixError, OutputRootMissingError
from fastfoto_linux.output.files import LOCK_NAME, locked_folder


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if not p.name.startswith("."))


def test_every_part_is_written_under_its_name_with_its_own_number(tmp_path: Path) -> None:
    (tmp_path / "Receipts_0004.pdf").write_bytes(b"old")
    paths = publish_pdfs([("Tax", b"1"), ("Receipts", b"2"), ("Tax", b"3")], tmp_path)
    assert [p.name for p in paths] == ["Tax_0001.pdf", "Receipts_0005.pdf", "Tax_0002.pdf"]
    assert [p.read_bytes() for p in paths] == [b"1", b"2", b"3"]


def test_a_name_is_cleaned_like_an_album_name(tmp_path: Path) -> None:
    (path,) = publish_pdfs([("My/Taxes\\2025 ", b"x")], tmp_path)
    assert path.name == "My Taxes 2025_0001.pdf"


def test_publish_pdf_is_the_one_part_case(tmp_path: Path) -> None:
    assert publish_pdf(b"x", tmp_path, "Doc") == tmp_path / "Doc_0001.pdf"
    assert publish_pdfs([("Doc", b"y")], tmp_path) == (tmp_path / "Doc_0002.pdf",)


def test_no_parts_write_nothing(tmp_path: Path) -> None:
    assert publish_pdfs([], tmp_path) == ()
    assert _names(tmp_path) == []


def test_a_name_with_nothing_usable_in_any_part_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(InvalidPrefixError):
        publish_pdfs([("Fine", b"1"), ("..", b"2")], tmp_path)
    assert _names(tmp_path) == []


def test_a_missing_folder_is_an_error_not_a_new_folder(tmp_path: Path) -> None:
    with pytest.raises(OutputRootMissingError):
        publish_pdfs([("Doc", b"1")], tmp_path / "gone")


def test_a_writer_that_ignores_the_lock_costs_the_numbers_it_took_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    taken = tmp_path / "Receipts_0001.pdf"
    taken.write_bytes(b"rival")
    monkeypatch.setattr("fastfoto_linux.documents.publish.next_index", lambda *_: 1)
    paths = publish_pdfs([("Tax", b"1"), ("Receipts", b"2")], tmp_path)
    assert [p.name for p in paths] == ["Tax_0001.pdf", "Receipts_0002.pdf"]
    assert taken.read_bytes() == b"rival"


def test_a_failure_part_way_leaves_none_of_the_parts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastfoto_linux.output import files  # noqa: PLC0415

    real = files._publish
    calls: list[None] = []

    def failing(entry: object) -> None:
        calls.append(None)
        if len(calls) == 2:
            raise OSError("disk full")
        real(entry)  # type: ignore[arg-type]

    monkeypatch.setattr(files, "_publish", failing)
    with pytest.raises(OSError, match="disk full"):
        publish_pdfs([("A", b"1"), ("B", b"2")], tmp_path)
    assert [p.name for p in tmp_path.iterdir() if p.name != LOCK_NAME] == []


def test_the_folder_lock_is_held_while_the_parts_are_numbered_and_written(tmp_path: Path) -> None:
    done = threading.Event()
    results: list[tuple[Path, ...]] = []

    def publish() -> None:
        results.append(publish_pdfs([("A", b"1"), ("A", b"2")], tmp_path))
        done.set()

    with locked_folder(tmp_path):  # a rival writer holds the lock
        worker = threading.Thread(target=publish)
        worker.start()
        assert not done.wait(0.3)
        assert _names(tmp_path) == []
    worker.join(timeout=10)
    assert done.is_set()
    assert [p.name for p in results[0]] == ["A_0001.pdf", "A_0002.pdf"]
