"""Schema 5 baseline pinned before detail: the literal fixture and its render bytes."""

import hashlib
import json
import shutil
from pathlib import Path
from threading import Event

from fastfoto_linux.photo_edits import (
    open_edit,
    recipe_bytes,
    render,
    update_geometry,
)
from fastfoto_linux.photo_edits import recipe as codec

FIXTURES = Path(__file__).parent / "fixtures"
V5_SIDECAR_SHA256 = "ba91315bc011214e"
V5_FIXTURE_RENDER_SHA256 = "f11eb6aa634095b34d38efcbef03fa3aa524ab1d2d852178d5a3efda0798fd1b"


def test_literal_v5_fixture_is_canonical_and_pinned() -> None:
    raw = (FIXTURES / "legacy-v5.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest().startswith(V5_SIDECAR_SHA256)
    payload = json.loads(raw)
    assert codec.json_bytes(payload) == raw
    assert (payload["schema_version"], payload["algorithm_version"]) == (5, "photo-color-v1")
    assert payload["geometry"] == {
        "crop": [1, 1, 9, 6],
        "quarter_turns": 1,
        "straighten_tenths": 30,
    }
    assert payload["tone"]["saturation"] == 60
    assert payload["white_balance"] == {"temperature": 30, "tint": -20}
    assert len(payload["eyes"]) == 1
    assert "detail" not in payload


def test_literal_v5_fixture_reopens_and_renders_to_the_pinned_bytes(tmp_path: Path) -> None:
    for name in ("legacy-v3.jpg", "legacy-v5.json"):
        shutil.copyfile(FIXTURES / name, tmp_path / name)
    shutil.copyfile(FIXTURES / "legacy-v3.jpg", tmp_path / "legacy_edit-0001.jpg")
    source, recipe = open_edit(tmp_path / "legacy-v5.json")
    payload = json.loads((tmp_path / "legacy-v5.json").read_bytes())
    expected = {key: value for key, value in payload.items() if key != "output"}
    assert recipe_bytes(recipe) == codec.json_bytes(expected)
    assert update_geometry(recipe, recipe.geometry) is recipe
    result = render(source, recipe, cancel=Event())
    assert hashlib.sha256(result.tobytes()).hexdigest() == V5_FIXTURE_RENDER_SHA256
