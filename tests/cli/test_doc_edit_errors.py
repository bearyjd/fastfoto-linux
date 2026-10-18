"""``ffscan doc process`` edit options that cannot be used: exit 2, a clear line, no work done."""

from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.documents import analyse as analyse_module
from tests import _fake_ocrmypdf as fake
from tests.documents.helpers import blank_scene, text_scene, write_pages


@pytest.fixture(autouse=True)
def no_real_ocr(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    fake.no_ocr_on_path(tmp_path_factory.mktemp("no-ocr"), monkeypatch)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (["--drop", "5"], "page 5"),
        (["--drop", "0"], "page 0"),
        (["--keep", "9"], "page 9"),
        (["--split", "7"], "page 7"),
        (["--rotate", "6:90"], "page 6"),
        (["--drop", "2", "--keep", "2"], "both"),
        (["--drop", "2,2"], "twice"),
        (["--keep", "1,3,1"], "twice"),
        (["--split", "3,3"], "twice"),
        (["--rotate", "1:90,1:180"], "twice"),
        (["--rotate", "1:45"], "angle"),
        (["--rotate", "1:0"], "angle"),
        (["--rotate", "1:-90"], "angle"),
        (["--rotate", "1"], "--rotate"),
        (["--rotate", "x:90"], "--rotate"),
        (["--drop", "a"], "--drop"),
        (["--drop", ""], "--drop"),
        (["--order", "1,2,3"], "permutation"),
        (["--order", "1,2,2,3"], "permutation"),
        (["--order", "1,2,3,5"], "permutation"),
        (["--part-name", "2=Receipts"], "part 2"),
        (["--part-name", "0=Receipts"], "part 0"),
        (["--part-name", "Receipts"], "--part-name"),
        (["--part-name", "1=.."], "usable"),
        (["--part-name", "1=A,1=B"], "twice"),
    ],
)
def test_a_bad_edit_exits_2_and_writes_nothing(
    options: list[str], message: str, tmp_path: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pages = write_pages(tmp_path / "raw", [text_scene(n) for n in range(1, 5)])
    code = main(
        [
            "doc",
            "process",
            *map(str, pages),
            "--out",
            str(out),
            "--ocr",
            "off",
            "--simplex",
            *options,
        ]
    )
    assert code == 2
    assert message in capsys.readouterr().err
    assert [p.name for p in out.iterdir() if not p.name.startswith(".")] == []


def test_a_bad_edit_is_found_before_any_page_is_read(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pages = write_pages(tmp_path / "raw", [text_scene(1), text_scene(2)])
    reads: list[Path] = []
    real = analyse_module.load_page

    def spy(path: Path, **kwargs: object) -> object:
        reads.append(path)
        return real(path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(analyse_module, "load_page", spy)
    argv = ["doc", "process", *map(str, pages), "--out", str(out), "--ocr", "off", "--drop", "7"]
    assert main(argv) == 2
    assert reads == []


@pytest.mark.parametrize("options", [["--rotate", "1:90"], ["--keep", "2"]])
def test_turning_or_bringing_back_needs_the_pages_in_one_folder(
    options: list[str], tmp_path: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = write_pages(tmp_path / "a", [text_scene(1)])
    second = write_pages(tmp_path / "b", [blank_scene(2)])
    argv = ["doc", "process", *map(str, [*first, *second]), "--out", str(out), "--ocr", "off"]
    assert main([*argv, "--simplex", *options]) == 2
    assert "one folder" in capsys.readouterr().err
    assert [p.name for p in out.iterdir() if not p.name.startswith(".")] == []


def test_dropping_pages_from_several_folders_works(tmp_path: Path, out: Path) -> None:
    first = write_pages(tmp_path / "a", [text_scene(1)])
    second = write_pages(tmp_path / "b", [text_scene(2)])
    argv = ["doc", "process", *map(str, [*first, *second]), "--out", str(out), "--ocr", "off"]
    assert main([*argv, "--simplex", "--drop", "2"]) == 0
