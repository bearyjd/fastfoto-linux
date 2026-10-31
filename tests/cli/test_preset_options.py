"""``--preset`` of ``ffscan scan``, ``process`` and ``doc``: exact names, the quality conflict."""

import contextlib
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest

from fastfoto_linux.cli import cmd_doc, main
from fastfoto_linux.cli.app import build_parser
from fastfoto_linux.cli.doc_options import build_settings as doc_build_settings
from fastfoto_linux.documents import DocumentSettings, OcrMode
from fastfoto_linux.output.presets import ExportPreset
from fastfoto_linux.pipeline.process import ProcessSettings
from tests.cli.fakes import write_dummy_page

DOC_PROCESS = ["doc", "process", "x.png", "--out", "o"]
DOC_SCAN = ["doc", "scan", "--out", "o"]
BAD_NAMES = ["Small", "SMALL", " small", "small ", "", "none", "high_quality", "png"]


@pytest.fixture
def photo_main(tmp_path, out, spy):
    def run(*extra: str) -> int:
        page = write_dummy_page(tmp_path / "raw", "page-1.png")
        return main(["process", str(page), "--out", str(out), *extra])

    return run


def test_a_preset_reaches_the_process_settings(photo_main, spy) -> None:
    assert photo_main("--preset", "small") == 0

    settings: ProcessSettings = spy[-1][1]
    assert settings.preset is ExportPreset.SMALL
    assert settings.quality == 95


@pytest.mark.parametrize("preset", list(ExportPreset))
def test_every_name_is_accepted(photo_main, spy, preset: ExportPreset) -> None:
    assert photo_main("--preset", preset.value) == 0
    assert spy[-1][1].preset is preset


def test_no_flag_means_no_preset_and_quality_95(photo_main, spy) -> None:
    assert photo_main() == 0
    assert spy[-1][1].preset is None
    assert spy[-1][1].quality == 95


def test_quality_alone_still_works(photo_main, spy) -> None:
    assert photo_main("--quality", "90") == 0
    assert spy[-1][1].quality == 90
    assert spy[-1][1].preset is None


@pytest.mark.parametrize("bad", BAD_NAMES)
def test_a_name_that_is_not_exact_is_a_usage_error(photo_main, spy, capsys, bad: str) -> None:
    calls = len(spy)

    assert photo_main("--preset", bad) == 2
    assert len(spy) == calls
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize("quality", ["95", "90", "80"])
@pytest.mark.parametrize("preset", ["small", "lossless", "high-quality"])
def test_preset_and_quality_together_are_a_usage_error(
    photo_main, spy, capsys, preset: str, quality: str
) -> None:
    calls = len(spy)

    assert photo_main("--preset", preset, "--quality", quality) == 2
    assert len(spy) == calls
    assert "--quality" in capsys.readouterr().err


def test_the_help_names_the_tradeoffs(capsys) -> None:
    with contextlib.suppress(SystemExit):
        main(["process", "--help"])
    text = capsys.readouterr().out
    assert "--preset" in text
    assert "high-quality" in text


def test_doc_presets_reach_the_document_settings() -> None:
    parse = build_parser().parse_args
    for base in (DOC_PROCESS, DOC_SCAN):
        assert doc_build_settings(parse(base)).preset is None
        assert doc_build_settings(parse([*base, "--preset", "small"])).preset is ExportPreset.SMALL


@pytest.mark.parametrize("bad", BAD_NAMES)
def test_doc_names_must_be_exact(bad: str, capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        build_parser().parse_args([*DOC_PROCESS, "--preset", bad])
    assert caught.value.code == 2
    assert "Traceback" not in capsys.readouterr().err


def test_the_recovery_command_keeps_the_preset(tmp_path: Path) -> None:
    for preset, expected in ((None, False), (ExportPreset.LOSSLESS, True)):
        settings = DocumentSettings(output_root=tmp_path, ocr=OcrMode.OFF, preset=preset)
        request = SimpleNamespace(settings=settings, dpi=300)
        words = shlex.split(cmd_doc.process_command([tmp_path / "a.png"], request, tmp_path))  # type: ignore[arg-type]
        assert ("--preset" in words) is expected
        if expected:
            assert words[words.index("--preset") + 1] == "lossless"
