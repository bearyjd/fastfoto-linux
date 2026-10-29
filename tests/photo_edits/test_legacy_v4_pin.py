"""Schema 4 baseline pinned before white balance: the literal fixture and its render bytes."""

import hashlib
import json
import shutil
from pathlib import Path
from threading import Event

from fastfoto_linux.photo_edits import (
    PhotoGeometry,
    open_edit,
    recipe_bytes,
    render,
    update_geometry,
)
from fastfoto_linux.photo_edits import recipe as codec
from tests.photo_edits.helpers import eye
from tests.photo_edits.straighten_helpers import TONE, sized_source, straight_recipe

FIXTURES = Path(__file__).parent / "fixtures"
V4_SIDECAR_SHA256 = "c7285cacf418ab08"
V4_FIXTURE_RENDER_SHA256 = "bd9ecaaf8d49a004a2cdd6f44973cb23e00dc1948de7a5b9a92d2cba7c13cda6"
V4_SYNTHETIC_RENDER_SHA256 = "4af5ab2c9c137553036f6cf37c2608c87d4f98afc2afd42a3f63ba6608ef20a7"


def test_literal_v4_fixture_is_canonical_and_pinned() -> None:
    raw = (FIXTURES / "legacy-v4.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest().startswith(V4_SIDECAR_SHA256)
    payload = json.loads(raw)
    assert codec.json_bytes(payload) == raw
    assert (payload["schema_version"], payload["algorithm_version"]) == (4, "photo-geometry-v2")
    assert payload["geometry"] == {
        "crop": [1, 1, 9, 6],
        "quarter_turns": 1,
        "straighten_tenths": 30,
    }
    assert payload["tone"]["saturation"] == 60
    assert len(payload["eyes"]) == 1
    assert "white_balance" not in payload


def test_literal_v4_fixture_reopens_and_renders_to_the_pinned_bytes(tmp_path: Path) -> None:
    for name in ("legacy-v3.jpg", "legacy-v4.json"):
        shutil.copyfile(FIXTURES / name, tmp_path / name)
    shutil.copyfile(FIXTURES / "legacy-v3.jpg", tmp_path / "legacy_edit-0001.jpg")
    source, recipe = open_edit(tmp_path / "legacy-v4.json")
    payload = json.loads((tmp_path / "legacy-v4.json").read_bytes())
    expected = {key: value for key, value in payload.items() if key != "output"}
    assert recipe_bytes(recipe) == codec.json_bytes(expected)
    assert update_geometry(recipe, recipe.geometry) is recipe
    result = render(source, recipe, cancel=Event())
    assert hashlib.sha256(result.tobytes()).hexdigest() == V4_FIXTURE_RENDER_SHA256


def test_synthetic_v4_render_is_pinned(tmp_path: Path) -> None:
    source = sized_source(tmp_path, 100, 160)
    geometry = PhotoGeometry(1, (10, 5, 120, 80), 37)
    recipe = straight_recipe(source, geometry, tone=TONE, eyes=(eye(),))
    assert recipe.schema_version == 4
    result = render(source, recipe, cancel=Event())
    assert hashlib.sha256(result.tobytes()).hexdigest() == V4_SYNTHETIC_RENDER_SHA256
