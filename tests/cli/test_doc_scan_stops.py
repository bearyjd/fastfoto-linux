"""``ffscan doc scan`` when something goes wrong: the exit code, what is said, what is kept."""

import os
import signal
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.documents import build
from fastfoto_linux.scanner import (
    NoDocumentsError,
    ScanCancelledError,
    ScanError,
    ScannerDisconnectedError,
    ScannerInUseError,
    ScannerNotFoundError,
    ScannerStuckError,
    ShimMissingError,
)
from fastfoto_linux.scanner import precheck as precheck_module
from tests import _fake_ocrmypdf as fake
from tests.cli.doc_scan_helpers import doc_scan, kept, kept_pages, visible
from tests.documents.helpers import blank_scene, text_scene

pytestmark = pytest.mark.usefixtures("no_real_ocr", "fixed_stamp")

WAITING_LINE = "Waiting for the scanner to answer…"
THREE = ["page-0001.png", "page-0002.png", "page-0003.png"]


def three_pages(transport):
    transport.scenes = [text_scene(1), text_scene(2), text_scene(3)]
    return transport


def no_pdf(out: Path) -> bool:
    return not [p for p in out.iterdir() if p.suffix == ".pdf"]


# --- the scanner cannot be used ---------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        ScannerNotFoundError("no FF-680W found on USB and no network host given"),
        ShimMissingError("the gap shim is missing"),
    ],
    ids=["not-found", "no-shim"],
)
def test_a_scanner_that_cannot_be_found_or_used_is_exit_3_and_leaves_nothing(
    out, doc_transport, capsys, error
) -> None:
    doc_transport.resolve_error = error
    assert doc_scan(out) == 3
    assert str(error) in capsys.readouterr().err
    assert doc_transport.jobs == []
    assert visible(out) == []
    assert not (out / ".raw").exists()


@pytest.fixture
def check_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(precheck_module.SKIP_ENV_VAR, raising=False)


def install_check(
    monkeypatch: pytest.MonkeyPatch, error: BaseException | None = None, *, slow: bool = False
):
    calls: list[tuple[str, dict[str, Any]]] = []

    def check(device: str, **options: Any) -> None:
        calls.append((device, options))
        if slow and options.get("on_slow") is not None:
            options["on_slow"]()
        if error is not None:
            raise error

    monkeypatch.setattr("fastfoto_linux.session.documents.check_scanner", check)
    return calls


@pytest.mark.parametrize(
    "error",
    [ScannerStuckError(), ScannerInUseError(), ScannerDisconnectedError()],
    ids=["stuck", "in-use", "disconnected"],
)
@pytest.mark.usefixtures("check_enabled")
def test_a_scanner_that_fails_its_check_is_exit_3_in_one_line_and_nothing_is_scanned(
    out, doc_transport, monkeypatch, capsys, error
) -> None:
    install_check(monkeypatch, error)
    assert doc_scan(out) == 3
    err = capsys.readouterr().err
    assert str(error) in err
    assert len(err.strip().splitlines()) == 1
    assert doc_transport.jobs == []
    assert visible(out) == []
    assert not (out / ".raw").exists()


@pytest.mark.usefixtures("check_enabled")
def test_the_scanner_is_checked_with_its_device_before_the_scan(
    out, doc_transport, monkeypatch
) -> None:
    calls = install_check(monkeypatch)
    doc_transport.scenes = [text_scene(1)]
    assert doc_scan(out) == 0
    assert [device for device, _ in calls] == ["epsonds:libusb:001:004"]


@pytest.mark.usefixtures("check_enabled")
def test_a_check_that_waits_for_the_scanner_says_so_once(
    out, doc_transport, monkeypatch, capsys
) -> None:
    install_check(monkeypatch, slow=True)
    doc_transport.scenes = [text_scene(1)]
    assert doc_scan(out) == 0
    assert capsys.readouterr().err.splitlines().count(WAITING_LINE) == 1


@pytest.mark.usefixtures("check_enabled")
def test_a_quick_check_says_nothing_about_waiting(out, doc_transport, monkeypatch, capsys) -> None:
    install_check(monkeypatch)
    doc_transport.scenes = [text_scene(1)]
    assert doc_scan(out) == 0
    assert WAITING_LINE not in capsys.readouterr().err


@pytest.mark.usefixtures("check_enabled")
def test_ctrl_c_during_the_check_is_exit_130(out, doc_transport, monkeypatch, capsys) -> None:
    install_check(monkeypatch, KeyboardInterrupt())
    assert doc_scan(out) == 130
    assert "interrupted" in capsys.readouterr().err
    assert doc_transport.jobs == []


def test_the_environment_switches_the_check_off(out, doc_transport, monkeypatch) -> None:
    calls = install_check(monkeypatch)
    monkeypatch.setenv(precheck_module.SKIP_ENV_VAR, "1")
    doc_transport.scenes = [text_scene(1)]
    assert doc_scan(out) == 0
    assert calls == []


# --- the feeder, the stack and the pages ---------------------------------------------------------


def test_an_empty_feeder_is_exit_4_and_leaves_nothing_behind(out, doc_transport, capsys) -> None:
    doc_transport.failure = lambda pages: NoDocumentsError("the document feeder is empty")
    assert doc_scan(out) == 4
    assert "feeder is empty" in capsys.readouterr().err
    assert visible(out) == []
    assert not (out / ".raw").exists()


def test_a_scanner_error_part_way_is_exit_1_with_no_pdf_and_says_how_to_make_one(
    out, doc_transport, capsys
) -> None:
    three_pages(doc_transport)
    doc_transport.pages_before_failure = 2
    doc_transport.failure = lambda pages: ScanError("paper jam", returncode=1, pages=pages)
    assert doc_scan(out, "--discard-raw") == 1
    assert no_pdf(out)  # a PDF with the tail of the stack missing is worse than none
    err = capsys.readouterr().err
    assert "paper jam" in err
    assert f"raw pages kept in {kept(out)}" in err
    assert "ffscan doc process" in err
    assert kept_pages(out) == THREE


def test_a_scanner_error_before_any_page_is_exit_1_and_leaves_nothing(
    out, doc_transport, capsys
) -> None:
    doc_transport.failure = lambda pages: ScanError("could not start scanimage", pages=pages)
    assert doc_scan(out) == 1
    assert "could not start scanimage" in capsys.readouterr().err
    assert visible(out) == []
    assert not (out / ".raw").exists()


@pytest.mark.parametrize("policy", [[], ["--discard-raw"]], ids=["auto", "discard"])
def test_pages_that_are_all_blank_are_exit_1_with_no_pdf_the_hint_and_the_pages_kept(
    out, doc_transport, capsys, policy
) -> None:
    doc_transport.scenes = [blank_scene(1), blank_scene(2)]
    assert doc_scan(out, *policy) == 1
    err = capsys.readouterr().err
    assert "all 2 pages look blank" in err
    assert "--keep-blank" in err
    assert f"raw pages kept in {kept(out)}" in err
    assert no_pdf(out)
    assert kept_pages(out) == THREE[:2]


def test_keep_blank_makes_a_pdf_of_pages_that_are_all_blank(out, doc_transport) -> None:
    doc_transport.scenes = [blank_scene(1), blank_scene(2)]
    assert doc_scan(out, "--keep-blank") == 0
    assert visible(out) == ["Document_0001.pdf"]


def test_an_unusable_page_is_exit_1_naming_the_page_with_no_pdf_and_the_pages_kept(
    out, doc_transport, capsys
) -> None:
    three_pages(doc_transport)
    doc_transport.corrupt_page = 2
    assert doc_scan(out) == 1
    err = capsys.readouterr().err
    assert "page-0002.png" in err
    assert f"raw pages kept in {kept(out)}" in err
    assert no_pdf(out)
    assert kept_pages(out) == THREE


# --- stopped by the user ------------------------------------------------------------------------


def test_ctrl_c_during_the_scan_is_exit_130_and_keeps_the_pages(out, doc_transport, capsys) -> None:
    three_pages(doc_transport)
    doc_transport.failure = lambda pages: KeyboardInterrupt()
    assert doc_scan(out, "--discard-raw") == 130
    err = capsys.readouterr().err
    assert "interrupted" in err
    assert f"raw pages kept in {kept(out)}" in err
    assert kept_pages(out) == THREE
    assert no_pdf(out)


def test_a_cancel_reported_by_the_runner_is_exit_130_too(out, doc_transport, capsys) -> None:
    three_pages(doc_transport)
    doc_transport.pages_before_failure = 1
    doc_transport.failure = lambda pages: ScanCancelledError("scan cancelled", pages=pages)
    assert doc_scan(out) == 130
    assert "interrupted" in capsys.readouterr().err
    assert no_pdf(out)


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM], ids=["sigint", "sigterm"])
def test_a_signal_while_the_pdf_is_made_is_exit_130_with_nothing_published(
    out, doc_transport, monkeypatch, capsys, signum
) -> None:
    three_pages(doc_transport)
    real_trim = build.trim_page
    seen: list[int] = []

    def trim_then_signal(page):
        seen.append(1)
        if len(seen) == 2:
            signal.raise_signal(signum)
        return real_trim(page)

    monkeypatch.setattr(build, "trim_page", trim_then_signal)
    assert doc_scan(out, "--discard-raw") == 130
    err = capsys.readouterr().err
    assert "interrupted" in err
    assert f"raw pages kept in {kept(out)}" in err
    assert kept_pages(out) == THREE
    assert no_pdf(out)
    assert len(seen) == 2


def test_ctrl_c_during_ocr_is_exit_130_with_nothing_published_and_nothing_left_running(
    out, doc_transport, monkeypatch, capsys
) -> None:
    record = out.parent / "record.json"
    fake.put_on_path(out.parent / "bin", monkeypatch)
    fake.configure(monkeypatch, mode="hang", record_to=str(record), child=True)
    three_pages(doc_transport)
    fake.when_started(record, lambda: os.kill(os.getpid(), signal.SIGINT))
    assert doc_scan(out, "--ocr", "on", "--discard-raw") == 130
    err = capsys.readouterr().err
    assert "interrupted" in err
    assert f"raw pages kept in {kept(out)}" in err
    seen = fake.read_record(record)
    assert fake.wait_until_gone(seen["pid"])
    assert fake.wait_until_gone(seen["child"])
    assert no_pdf(out)
    assert kept_pages(out) == THREE
