"""Fuzz the document ``review.json`` sidecar (format versions 1 to 6).

Property: any bytes either decode to a draft whose page references (partners, edit keys, order,
splits, part-name keys) all lie within the folder's page range, or raise ``ReviewFormatError``
with a short message that repeats nothing of the input. A sidecar that decodes encodes back to
one that decodes to the same draft.
"""

import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fastfoto_linux.documents.draft_edit import set_document_cleanup, set_document_despeckle
from fastfoto_linux.documents.draft_json import (
    MAX_PAGES,
    READ_VERSIONS,
    ReviewFormatError,
    StoredReview,
    decode_review,
    encode_review,
)
from fastfoto_linux.documents.modes import CleanupPolicy
from tests.documents.test_cleanup_sidecar import NAMES, plain
from tests.documents.test_crop_sidecar import cropped
from tests.documents.test_deskew_sidecar import straight
from tests.fuzz.json_strategies import LEAK_MARKER, json_values, mutations

ANALYSIS = 3
MESSAGE_LIMIT = 200


def _bases() -> list[bytes]:
    drafts = [
        plain(),
        set_document_cleanup(plain(), CleanupPolicy.LIGHT),
        cropped(),
        set_document_despeckle(cropped(), True),
        straight(),
    ]
    return [encode_review(draft, None, ANALYSIS) for draft in drafts]


BASES = _bases()


def _assert_in_range(stored: StoredReview, count: int) -> None:
    draft = stored.draft
    pages = range(1, count + 1)
    assert [page.number for page in draft.pages] == list(pages)
    assert [page.name for page in draft.pages] == NAMES
    assert all(page.partner is None or page.partner in pages for page in draft.pages)
    assert all(page.partner != page.number for page in draft.pages)
    assert not draft.order or sorted(draft.order) == list(pages)  # a permutation, or unset
    assert set(draft.edits) <= set(pages)
    assert set(draft.order) <= set(pages)
    assert draft.splits <= set(pages)
    assert set(draft.part_names) <= set(pages)


def _check(data: bytes, names: list[str] = NAMES) -> None:
    try:
        stored = decode_review(data, names)
    except ReviewFormatError as error:
        message = str(error)
        assert message
        assert LEAK_MARKER not in message
        assert len(message) < MESSAGE_LIMIT
        return
    _assert_in_range(stored, len(names))
    again = decode_review(encode_review(stored.draft, None, stored.analysis_version), names)
    assert again.draft == stored.draft


def test_the_bases_cover_every_format_version() -> None:
    versions = {json.loads(base)["version"] for base in BASES}
    assert versions == {2, 3, 4, 5, 6}
    assert versions <= set(READ_VERSIONS)
    for base in BASES:
        assert decode_review(base, NAMES).draft is not None


@given(data=st.binary(max_size=300))
def test_arbitrary_bytes_never_crash(data: bytes) -> None:
    _check(data)


@given(value=json_values)
def test_arbitrary_json_never_crashes(value: Any) -> None:
    _check(json.dumps(value).encode())


@given(data=st.data())
def test_mutated_sidecars_decode_in_range_or_are_refused(data: st.DataObject) -> None:
    base = json.loads(data.draw(st.sampled_from(BASES)))
    _check(json.dumps(data.draw(mutations(base))).encode())


@given(data=st.data())
def test_flipped_bytes_of_a_valid_sidecar_never_crash(data: st.DataObject) -> None:
    raw = bytearray(data.draw(st.sampled_from(BASES)))
    for _ in range(data.draw(st.integers(1, 4))):
        raw[data.draw(st.integers(0, len(raw) - 1))] = data.draw(st.integers(0, 255))
    _check(bytes(raw))


# The C JSON scanner raises RecursionError somewhere past 10 000 levels (3.13); 400 000 levels
# are still under every size cap here (2 MB, 8 MB, 1 MiB).
@given(depth=st.sampled_from([1_000, 20_000, 400_000]))
def test_deep_nesting_is_refused(depth: int) -> None:
    with pytest.raises(ReviewFormatError):
        decode_review(b"[" * depth + b"]" * depth, NAMES)


@given(names=st.lists(st.text(max_size=12), max_size=5))
def test_any_page_names_decode_or_are_refused(names: list[str]) -> None:
    _check(BASES[0], names)


def test_page_count_bounds() -> None:
    with pytest.raises(ReviewFormatError):
        decode_review(BASES[0], [])
    with pytest.raises(ReviewFormatError):
        decode_review(BASES[0], ["p"] * (MAX_PAGES + 1))


def test_an_out_of_range_reference_is_refused_not_clamped() -> None:
    data = json.loads(BASES[0])
    for field, bad in (("order", [1, 2, 9]), ("splits", [0]), ("edits", {"9": {}})):
        with pytest.raises(ReviewFormatError):
            decode_review(json.dumps(replace_key(data, field, bad)).encode(), NAMES)


def replace_key(data: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    return {**data, key: value}
