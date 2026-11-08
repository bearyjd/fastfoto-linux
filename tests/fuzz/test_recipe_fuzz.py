"""Fuzz the photo recipe sidecar (schema versions 1 to 6).

Property: whatever the bytes are, ``parse_recipe`` returns a recipe or raises ``PhotoEditError``
(never another exception), the message is fixed text that repeats nothing of the input, and a
recipe that loads dumps to bytes that load to the same recipe.
"""

import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fastfoto_linux.photo_edits import (
    PhotoEditError,
    PhotoEditRecipe,
    PhotoSource,
    parse_recipe,
    recipe_bytes,
)
from fastfoto_linux.photo_edits.model import MAX_RECIPE_BYTES, RECIPE_VERSIONS
from tests.fuzz.json_strategies import LEAK_MARKER, json_values, mutations
from tests.photo_edits.helpers import eye, source_at


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> PhotoSource:
    return source_at(tmp_path_factory.mktemp("fuzz-recipe"))


@pytest.fixture(scope="module")
def valid_payloads(source: PhotoSource) -> list[dict[str, Any]]:
    """One valid recipe object per schema version, each with an eye correction."""
    payloads = []
    for version, algorithm in sorted(RECIPE_VERSIONS.items()):
        recipe = PhotoEditRecipe(
            source, (eye(),), schema_version=version, algorithm_version=algorithm
        )
        payloads.append(json.loads(recipe_bytes(recipe)))
    return payloads


def _assert_refused_cleanly(error: PhotoEditError, source: PhotoSource) -> None:
    message = str(error)
    assert message, "a refusal carries a message"
    assert LEAK_MARKER not in message
    assert str(source.path.parent) not in message
    assert len(message) < 200


def _check(data: bytes, source: PhotoSource) -> None:
    try:
        recipe = parse_recipe(data, source)
    except PhotoEditError as error:
        _assert_refused_cleanly(error, source)
        return
    dumped = recipe_bytes(recipe)
    assert recipe_bytes(parse_recipe(dumped, source)) == dumped


def test_every_schema_version_round_trips(
    source: PhotoSource, valid_payloads: list[dict[str, Any]]
) -> None:
    assert [p["schema_version"] for p in valid_payloads] == sorted(RECIPE_VERSIONS)
    for payload in valid_payloads:
        data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        assert recipe_bytes(parse_recipe(data, source)) == data


@given(data=st.binary(max_size=300))
def test_arbitrary_bytes_never_crash(data: bytes, source: PhotoSource) -> None:
    _check(data, source)


@given(value=json_values)
def test_arbitrary_json_never_crashes(value: Any, source: PhotoSource) -> None:
    _check(json.dumps(value).encode(), source)


@given(data=st.data())
def test_mutated_recipes_load_or_are_refused_with_a_typed_error(
    data: st.DataObject, source: PhotoSource, valid_payloads: list[dict[str, Any]]
) -> None:
    base = data.draw(st.sampled_from(valid_payloads))
    mutated = data.draw(mutations(base))
    _check(json.dumps(mutated).encode(), source)


@given(data=st.data())
def test_flipped_bytes_of_a_valid_recipe_never_crash(
    data: st.DataObject, source: PhotoSource, valid_payloads: list[dict[str, Any]]
) -> None:
    raw = bytearray(json.dumps(data.draw(st.sampled_from(valid_payloads))).encode())
    for _ in range(data.draw(st.integers(1, 4))):
        raw[data.draw(st.integers(0, len(raw) - 1))] = data.draw(st.integers(0, 255))
    _check(bytes(raw), source)


# The C JSON scanner raises RecursionError somewhere past 10 000 levels (3.13); 400 000 levels
# are still under every size cap here (2 MB, 8 MB, 1 MiB).
@given(depth=st.sampled_from([1_000, 20_000, 400_000]))
def test_deep_nesting_is_refused_not_a_recursion_crash(depth: int, source: PhotoSource) -> None:
    with pytest.raises(PhotoEditError):
        parse_recipe(b"[" * depth + b"]" * depth, source)


def test_size_cap_is_enforced_before_parsing(
    source: PhotoSource, valid_payloads: list[dict[str, Any]]
) -> None:
    valid = json.dumps(valid_payloads[-1], sort_keys=True, separators=(",", ":")).encode()
    assert recipe_bytes(parse_recipe(valid, source)) == valid
    with pytest.raises(PhotoEditError, match="byte limit"):
        parse_recipe(valid + b" " * (MAX_RECIPE_BYTES + 1 - len(valid)), source)
    with pytest.raises(PhotoEditError, match="byte limit"):
        parse_recipe(b"", source)


@given(data=st.data())
def test_a_repeated_field_is_refused_wherever_it_is_spliced_in(
    data: st.DataObject, source: PhotoSource, valid_payloads: list[dict[str, Any]]
) -> None:
    payload = data.draw(st.sampled_from(valid_payloads))
    key = data.draw(st.sampled_from(sorted(payload)))
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    repeated = "{" + json.dumps(key) + ":" + json.dumps(data.draw(json_values)) + "," + text[1:]
    with pytest.raises(PhotoEditError):
        parse_recipe(repeated.encode(), source)


def test_leak_marker_is_actually_reachable(
    source: PhotoSource, valid_payloads: list[dict[str, Any]]
) -> None:
    """Self-check of the fuzz oracle: the marker is a string the parser reads and refuses."""
    payload = json.loads(json.dumps(valid_payloads[-1]))
    payload["source"]["name"] = LEAK_MARKER
    with pytest.raises(PhotoEditError) as excinfo:
        parse_recipe(json.dumps(payload).encode(), source)
    _assert_refused_cleanly(excinfo.value, source)
