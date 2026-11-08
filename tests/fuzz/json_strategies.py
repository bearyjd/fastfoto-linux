"""Hostile-JSON strategies shared by the sidecar fuzz tests."""

import json
from typing import Any

from hypothesis import strategies as st

# A recognisable string that a refusal must never repeat back: it stands for a path or a name
# taken from the file.
LEAK_MARKER = "LEAK-MARKER-/etc/passwd"

_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**70), max_value=2**70),
    st.floats(allow_nan=False, allow_infinity=False),
    st.sampled_from([0, 1, -1, 2**31, 2**63, 1e308, -0.0, 0.5, "", LEAK_MARKER, "../x", "a/b"]),
    st.text(max_size=20),
)
json_values = st.recursive(
    _scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=8), children, max_size=4),
    ),
    max_leaves=12,
)


def _paths(value: Any, prefix: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """Every key path into ``value``, parents before children."""
    found: list[tuple[Any, ...]] = [prefix] if prefix else []
    if isinstance(value, dict):
        for key, child in value.items():
            found += _paths(child, (*prefix, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found += _paths(child, (*prefix, index))
    return found


def _replaced(root: Any, path: tuple[Any, ...], replacement: Any, *, delete: bool) -> Any:
    """A deep copy of ``root`` with the value at ``path`` replaced (or removed)."""
    if not path:
        return replacement
    copy = json.loads(json.dumps(root))
    parent = copy
    for step in path[:-1]:
        parent = parent[step]
    if delete and isinstance(parent, dict):
        del parent[path[-1]]
    else:
        parent[path[-1]] = replacement
    return copy


@st.composite
def mutations(draw: st.DrawFn, document: Any, *, rounds: int = 3) -> Any:
    """``document`` with up to ``rounds`` leaves or branches replaced, added or removed."""
    result = document
    for _ in range(draw(st.integers(min_value=1, max_value=rounds))):
        paths = _paths(result)
        if not paths:
            break
        path = draw(st.sampled_from(paths))
        result = _replaced(result, path, draw(json_values), delete=draw(st.booleans()))
    return result
