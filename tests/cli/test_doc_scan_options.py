"""``ffscan doc scan``: the command line, and what is refused before the scanner is touched."""

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.scanner import ScannerNotFoundError, build_argv
from tests.cli.doc_scan_helpers import HINT, doc_scan, kept, visible
from tests.cli.fakes import DEVICE, HOST
from tests.documents.helpers import text_scene

pytestmark = pytest.mark.usefixtures("no_real_ocr", "fixed_stamp")


def argv_of(job, source: str, dpi: int) -> tuple[str, ...]:
    return (
        "scanimage",
        "-d",
        DEVICE,
        "--source",
        source,
        "--mode",
        "Color",
        "--resolution",
        str(dpi),
        "-y",
        "393.7",
        "--adf-skew=yes",
        "--format=png",
        f"--batch={job.output_dir}/page-%04d.png",
    )


@pytest.mark.parametrize("dpi", [200, 300, 600])
@pytest.mark.parametrize("colour", ["colour", "grey", "bw"])
def test_scanimage_always_gets_colour_and_the_asked_resolution(
    out, doc_transport, colour, dpi
) -> None:
    doc_transport.scenes = [text_scene(1)]
    assert doc_scan(out, "--colour", colour, "--dpi", str(dpi)) == 0
    (job,) = doc_transport.jobs
    assert build_argv(job) == argv_of(job, "ADF Duplex", dpi)


def test_simplex_asks_for_the_front_only(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1)]
    assert doc_scan(out, "--simplex") == 0
    (job,) = doc_transport.jobs
    assert build_argv(job) == argv_of(job, "ADF Front", 300)


@pytest.mark.parametrize(
    ("option", "bad"),
    [
        ("--dpi", "150"),  # a photo resolution, but not a document one
        ("--dpi", "400"),
        ("--dpi", "1200"),
        ("--dpi", "fast"),
        ("--colour", "sepia"),
        ("--ocr", "sometimes"),
        ("--lang", "en g"),
        ("--lang", "eng+"),
        ("--net", "not a host"),
    ],
)
def test_a_bad_option_is_a_usage_error_and_the_scanner_is_never_touched(
    out, doc_transport, capsys, option, bad
) -> None:
    assert doc_scan(out, option, bad) == 2
    assert option in capsys.readouterr().err
    assert doc_transport.resolve_calls == []
    assert doc_transport.jobs == []
    assert visible(out) == []


def test_keep_raw_and_discard_raw_exclude_each_other(out, doc_transport, capsys) -> None:
    assert doc_scan(out, "--keep-raw", "--discard-raw") == 2
    assert "not allowed with" in capsys.readouterr().err
    assert doc_transport.jobs == []


def test_out_is_required(doc_transport, capsys) -> None:
    assert main(["doc", "scan"]) == 2
    assert "--out" in capsys.readouterr().err


def test_a_name_with_no_usable_characters_is_a_usage_error(out, doc_transport, capsys) -> None:
    assert doc_scan(out, "--name", "///") == 2
    assert "no usable characters" in capsys.readouterr().err
    assert doc_transport.resolve_calls == []


def test_a_missing_output_folder_is_a_usage_error_unless_mkdir_says_otherwise(
    tmp_path, doc_transport, capsys
) -> None:
    target = tmp_path / "fresh"
    assert doc_scan(target) == 2
    assert "--mkdir" in capsys.readouterr().err
    assert not target.exists()
    assert doc_transport.resolve_calls == []
    doc_transport.scenes = [text_scene(1)]
    assert doc_scan(target, "--mkdir") == 0
    assert visible(target) == ["Document_0001.pdf"]


def test_the_options_before_the_command_are_accepted_as_for_every_command(
    out, doc_transport
) -> None:
    doc_transport.scenes = [text_scene(1)]
    assert main(["-v", "doc", "scan", "--out", str(out), "--ocr", "off"]) == 0


# --- required searchable text ---------------------------------------------------------------


def test_required_ocr_without_ocrmypdf_is_exit_3_before_the_scanner_or_the_folder_is_touched(
    tmp_path, doc_transport, capsys
) -> None:
    target = tmp_path / "fresh"
    assert doc_scan(target, "--mkdir", "--ocr", "on") == 3
    assert not target.exists()  # not even the folder was made
    assert doc_transport.resolve_calls == []
    assert doc_transport.jobs == []
    err = capsys.readouterr().err
    assert HINT in err
    assert "Traceback" not in err


# --- the scanner address ----------------------------------------------------------------------


def test_without_net_the_target_is_looked_for_on_usb_only(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1)]
    assert doc_scan(out) == 0
    (call,) = doc_transport.resolve_calls
    assert call["net_host"] is None
    assert call["config_dir"] is None
    assert call["shim_candidates"] is not None


def test_net_gives_a_private_config_folder_that_is_gone_afterwards(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1)]
    assert doc_scan(out, "--net", HOST) == 0
    (call,) = doc_transport.resolve_calls
    assert call["net_host"] == HOST
    assert doc_transport.config_dir_existed == [True]
    assert not call["config_dir"].exists()


def test_the_private_config_folder_is_gone_after_a_scanner_that_is_not_found(
    out, doc_transport, capsys
) -> None:
    doc_transport.resolve_error = ScannerNotFoundError("no FF-680W found on USB")
    assert doc_scan(out, "--net", HOST) == 3
    assert not doc_transport.resolve_calls[0]["config_dir"].exists()
    assert "no FF-680W found" in capsys.readouterr().err


def test_a_kept_run_with_net_keeps_its_raw_pages_in_the_output_folder(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1)]
    assert doc_scan(out, "--net", HOST, "--keep-raw") == 0
    assert kept(out).is_dir()
