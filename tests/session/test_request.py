"""``ScanRequest``: validated and frozen, with the raw pages' home defaulting to the album root."""

import dataclasses
from pathlib import Path

import pytest

from fastfoto_linux.scanner import SUPPORTED_DPI, ScanTarget
from fastfoto_linux.session import RawPolicy, ScanRequest
from tests.cli.fakes import DEVICE
from tests.process_helpers import settings_for
from tests.session.conftest import DPI, make_request


def test_the_raw_policies_are_keep_auto_and_discard() -> None:
    assert [policy.value for policy in RawPolicy] == ["keep", "auto", "discard"]


def test_a_request_is_frozen(out: Path) -> None:
    request = make_request(out)
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.dpi = 600


def test_the_raw_pages_default_to_the_output_folder(out: Path) -> None:
    request = make_request(out)
    assert request.raw_parent is None
    assert request.raw_policy is RawPolicy.AUTO
    assert request.raw_root == out


def test_a_raw_parent_replaces_the_output_folder_as_the_raw_root(out: Path, tmp_path: Path) -> None:
    other = tmp_path / "elsewhere"
    assert make_request(out, raw_parent=other).raw_root == other


@pytest.mark.parametrize("duplex", [True, False])
def test_the_scan_source_must_agree_with_the_processing_pairs(out: Path, duplex: bool) -> None:
    with pytest.raises(ValueError, match="duplex"):
        ScanRequest(
            target=ScanTarget(device=DEVICE),
            dpi=DPI,
            duplex=duplex,
            settings=settings_for(out, duplex=not duplex),
        )


@pytest.mark.parametrize("dpi", [0, 299, 1200])
def test_an_unsupported_resolution_is_refused_before_anything_is_scanned(
    out: Path, dpi: int
) -> None:
    assert dpi not in SUPPORTED_DPI
    with pytest.raises(ValueError, match="dpi"):
        ScanRequest(
            target=ScanTarget(device=DEVICE),
            dpi=dpi,
            duplex=True,
            settings=settings_for(out),
        )
