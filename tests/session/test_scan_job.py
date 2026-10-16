"""What the scan requests ask scanimage for: photos exactly as before, documents in colour."""

import dataclasses
from pathlib import Path

import pytest

from fastfoto_linux.documents import ColourMode, DocumentSettings, OcrMode
from fastfoto_linux.scanner import MAX_LENGTH_MM, Mode, ScanTarget, Source, build_argv
from fastfoto_linux.session import DOCUMENT_DPI, DocumentScanRequest, RawPolicy
from tests.cli.fakes import DEVICE
from tests.documents.helpers import text_scene
from tests.process_helpers import plain_sheet
from tests.session.conftest import STAMP, make_request, run
from tests.session.doc_session_helpers import make_doc_request, run_doc

PHOTO_ARGV = (
    "scanimage",
    "-d",
    DEVICE,
    "--source",
    "ADF Duplex",
    "--mode",
    "Color",
    "--resolution",
    "300",
    "-y",
    "393.7",
    "--adf-skew=yes",
    "--format=png",
)


def test_a_photo_scan_asks_scanimage_for_exactly_what_it_always_did(out, transport) -> None:
    """A regression pin: the argv of a photo scan must not change when documents arrive."""
    transport.sheets = [plain_sheet()]
    run(make_request(out), transport)
    (job,) = transport.jobs
    assert build_argv(job) == (*PHOTO_ARGV, f"--batch={job.output_dir}/page-%04d.png")


def test_a_photo_request_defaults_to_colour_and_the_scanners_full_length(out) -> None:
    request = make_request(out)
    assert request.mode is Mode.COLOR
    assert request.max_length_mm == MAX_LENGTH_MM


def test_a_photo_request_hands_its_mode_and_length_to_the_job(out, transport) -> None:
    transport.sheets = [plain_sheet()]
    request = dataclasses.replace(make_request(out), mode=Mode.GRAY, max_length_mm=297.0)
    run(request, transport)
    (job,) = transport.jobs
    assert job.mode is Mode.GRAY
    assert job.max_length_mm == 297.0
    assert build_argv(job)[5:7] == ("--mode", "Gray")
    assert build_argv(job)[9:11] == ("-y", "297")


@pytest.mark.parametrize("dpi", DOCUMENT_DPI)
@pytest.mark.parametrize("duplex", [True, False], ids=["duplex", "simplex"])
def test_a_document_scan_is_colour_full_length_deskewed_at_the_asked_resolution(
    out, doc_transport, dpi, duplex
) -> None:
    doc_transport.scenes = [text_scene(1)]
    run_doc(make_doc_request(out, dpi=dpi, duplex=duplex), doc_transport)
    (job,) = doc_transport.jobs
    source = "ADF Duplex" if duplex else "ADF Front"
    assert build_argv(job) == (
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
    assert job.source is (Source.DUPLEX if duplex else Source.FRONT)


@pytest.mark.parametrize("colour", list(ColourMode))
def test_the_scan_is_in_colour_whatever_the_pdf_will_be(out, doc_transport, colour) -> None:
    doc_transport.scenes = [text_scene(1)]
    run_doc(make_doc_request(out, colour=colour), doc_transport)
    assert doc_transport.jobs[0].mode is Mode.COLOR


def test_a_document_request_hands_its_mode_and_length_to_the_job(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1)]
    request = dataclasses.replace(make_doc_request(out), mode=Mode.GRAY, max_length_mm=297.0)
    run_doc(request, doc_transport)
    assert (doc_transport.jobs[0].mode, doc_transport.jobs[0].max_length_mm) == (Mode.GRAY, 297.0)


def test_the_raw_pages_are_scanned_into_a_folder_of_the_output_folder(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1)]
    run_doc(make_doc_request(out), doc_transport)
    assert doc_transport.jobs[0].output_dir.parent == out


def test_kept_raw_pages_are_scanned_straight_into_dot_raw(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1)]
    run_doc(make_doc_request(out, policy=RawPolicy.KEEP), doc_transport)
    assert doc_transport.jobs[0].output_dir == out / ".raw" / STAMP


def test_the_document_resolutions_are_200_300_and_600() -> None:
    assert DOCUMENT_DPI == (200, 300, 600)


@pytest.mark.parametrize("dpi", [50, 100, 150, 240, 400, 1200])
def test_a_document_request_refuses_another_resolution(out: Path, dpi: int) -> None:
    with pytest.raises(ValueError, match="200"):
        DocumentScanRequest(
            target=ScanTarget(device=DEVICE),
            settings=DocumentSettings(output_root=out, ocr=OcrMode.OFF),
            dpi=dpi,
        )


def test_a_document_request_defaults_to_300_dpi_both_sides_and_the_automatic_raw_policy(
    out: Path,
) -> None:
    request = DocumentScanRequest(
        target=ScanTarget(device=DEVICE), settings=DocumentSettings(output_root=out)
    )
    assert (request.dpi, request.duplex, request.raw_policy) == (300, True, RawPolicy.AUTO)
    assert (request.mode, request.max_length_mm) == (Mode.COLOR, MAX_LENGTH_MM)
    assert request.raw_root == out


def test_a_document_request_is_frozen(out: Path) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        make_doc_request(out).dpi = 600  # type: ignore[misc]


def test_the_raw_pages_of_a_document_may_live_elsewhere(out: Path, tmp_path: Path) -> None:
    other = tmp_path / "elsewhere"
    assert make_doc_request(out, raw_parent=other).raw_root == other
