"""Despeckle has its own version constant: raising FORMAT_VERSION must not change v5 bytes."""

import json
from dataclasses import replace

import pytest

from fastfoto_linux.documents import draft_json, sidecar_versions
from fastfoto_linux.documents.draft_json import decode_review, encode_review
from tests.documents.test_cleanup_sidecar import NAMES, plain

_PAGE = (
    '{{"name":"page-0{n}.png","size":1,"mtime_ns":1,"dpi":100,"trim":[0,0,0,0],'
    '"band_bottom":false,"blank":false,"partner":null,"flags":[],"marks":[],"detail":[],'
    '"colour":null}}'
)
PINNED_V5 = (
    '{"version":5,"analysis_version":3,"duplex":false,"keep_blank":false,"pages":['
    + ",".join(_PAGE.format(n=n) for n in (1, 2, 3))
    + '],"edits":{"1":{"include":true,"turns":1,"colour":"grey","cleanup":null,"crop":null},'
    '"3":{"include":null,"turns":2,"colour":null,"cleanup":null,"crop":null}},'
    '"order":[2,1,3],"splits":[2],"part_names":{"1":"Synthetic"},'
    '"cleanup":"off","despeckle":true}'
).encode()


@pytest.fixture
def future_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """A later FORMAT_VERSION, as if a newer feature raised it."""
    monkeypatch.setattr(sidecar_versions, "FORMAT_VERSION", 6)
    monkeypatch.setattr(draft_json, "FORMAT_VERSION", 6, raising=False)


def test_the_despeckle_version_is_five() -> None:
    assert sidecar_versions.DESPECKLE_VERSION == 5


def test_a_despeckle_draft_is_written_as_the_pinned_v5_bytes(future_format: None) -> None:
    assert encode_review(replace(plain(), despeckle=True), None, 3) == PINNED_V5


def test_the_pinned_v5_file_still_reads(future_format: None) -> None:
    stored = decode_review(PINNED_V5, NAMES)
    assert stored.draft.despeckle is True
    assert json.loads(PINNED_V5)["version"] == 5
