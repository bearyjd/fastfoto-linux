"""Detail in the render pipeline: bypass, effect, reconstruction, order and preview parity."""

from dataclasses import replace
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from fastfoto_linux.photo_edits import (
    PhotoDetail,
    PhotoEditRecipe,
    PhotoGeometry,
    PhotoTone,
    PhotoWhiteBalance,
    apply_geometry,
    color,
    detail,
    make_preview,
    render,
    update_detail,
    update_geometry,
    update_tone,
    update_white_balance,
)
from fastfoto_linux.photo_edits.render import _apply_tone, _eye_buffer, _preview_jpeg
from tests.photo_edits.detail_helpers import (
    Forbidden,
    NlmSpy,
    flat_source,
    noisy_source,
    reconstruct,
    reference_sharpen,
    step_source,
    ycc,
)
from tests.photo_edits.helpers import eye, source_at
from tests.photo_edits.straighten_helpers import TONE, straight_recipe

WB = PhotoWhiteBalance(30, -20)
CROP = (3, 2, 93, 62)


def _render(source, recipe):
    return render(source, recipe, cancel=Event())


def _recipes(tmp_path: Path):
    source = source_at(tmp_path)
    v2 = PhotoEditRecipe(source, (eye(),))
    v4 = straight_recipe(source, PhotoGeometry(1, (3, 4, 100, 70), 37), tone=TONE, eyes=(eye(),))
    v5 = update_white_balance(v4, WB)
    v6 = update_detail(update_detail(v5, PhotoDetail(5, 5, 5)), PhotoDetail())
    return source, v2, v4, v5, v6


def test_neutral_detail_never_touches_opencv_and_equals_schema_5(tmp_path: Path, monkeypatch):
    source, v2, v4, v5, v6 = _recipes(tmp_path)
    monkeypatch.setattr(detail, "cv2", Forbidden())
    for recipe in (v2, v4, v5, v6):
        assert _render(source, recipe).shape[2] == 3
    assert v6.schema_version == 6 and v6.detail == PhotoDetail()
    v5_again = replace(v6, schema_version=5, algorithm_version="photo-color-v1")
    assert np.array_equal(_render(source, v6), _render(source, v5_again))


def test_each_stage_skips_on_its_own(tmp_path: Path, monkeypatch) -> None:
    source = noisy_source(tmp_path)
    base = PhotoEditRecipe(source)
    luma_only = NlmSpy()
    monkeypatch.setattr(detail, "cv2", luma_only)
    _render(source, update_detail(base, PhotoDetail(60, 0, 0)))
    assert [call[0] for call in luma_only.calls] == [(64, 96)]
    chroma_only = NlmSpy()
    monkeypatch.setattr(detail, "cv2", chroma_only)
    _render(source, update_detail(base, PhotoDetail(0, 60, 0)))
    assert [call[0] for call in chroma_only.calls] == [(64, 96, 2)]
    sharpen_only = NlmSpy()
    monkeypatch.setattr(detail, "cv2", sharpen_only)
    _render(source, update_detail(base, PhotoDetail(0, 0, 60)))
    assert sharpen_only.calls == []


def test_luma_denoise_lowers_the_luma_noise(tmp_path: Path) -> None:
    source = noisy_source(tmp_path)
    out = _render(source, update_detail(PhotoEditRecipe(source), PhotoDetail(60, 0, 0)))
    assert ycc(out)[..., 0].std() < ycc(source.pixels)[..., 0].std()


def test_chroma_denoise_lowers_the_chroma_noise_and_keeps_the_mean_luma(tmp_path: Path) -> None:
    source = noisy_source(tmp_path)
    out = _render(source, update_detail(PhotoEditRecipe(source), PhotoDetail(0, 60, 0)))
    before, after = ycc(source.pixels).astype(float), ycc(out).astype(float)
    assert after[..., 1].std() < before[..., 1].std()
    assert after[..., 2].std() < before[..., 2].std()
    assert abs(after[..., 0].mean() - before[..., 0].mean()) < 1


@pytest.mark.parametrize(("luma", "chroma"), [(60, 0), (0, 60), (60, 40)])
def test_the_nlm_outputs_reconstruct_exactly(tmp_path: Path, monkeypatch, luma, chroma) -> None:
    source = noisy_source(tmp_path)
    spy = NlmSpy()
    monkeypatch.setattr(detail, "cv2", spy)
    out = _render(source, update_detail(PhotoEditRecipe(source), PhotoDetail(luma, chroma, 0)))
    by_shape = {shape: (h, result) for shape, h, result in spy.calls}
    luma_out = by_shape[(64, 96)][1] if luma else None
    chroma_out = by_shape[(64, 96, 2)][1] if chroma else None
    assert np.array_equal(out, reconstruct(source.pixels, luma_out, chroma_out))
    if luma:
        assert by_shape[(64, 96)][0] == pytest.approx(detail.H_LUMA_MAX * luma / 100)
    if chroma:
        assert by_shape[(64, 96, 2)][0] == pytest.approx(detail.H_CHROMA_MAX * chroma / 100)


@pytest.mark.parametrize("control", [(100, 100, 0), (0, 0, 100), (100, 100, 100)])
def test_a_flat_image_is_byte_unchanged(tmp_path: Path, control) -> None:
    source = flat_source(tmp_path)
    out = _render(source, update_detail(PhotoEditRecipe(source), PhotoDetail(*control)))
    assert np.array_equal(out, source.pixels)


def test_sharpen_overshoots_more_when_stronger_and_keeps_the_channel_differences(tmp_path):
    source = step_source(tmp_path)
    outs = {
        amount: _render(source, update_detail(PhotoEditRecipe(source), PhotoDetail(0, 0, amount)))
        for amount in (20, 80)
    }
    overshoot = {a: int(out[..., 1].max()) - 170 for a, out in outs.items()}
    assert overshoot[80] > overshoot[20] > 0
    for out in outs.values():
        assert int(out.min()) > 0 and int(out.max()) < 255
        for a, b in ((0, 1), (2, 1)):
            assert np.array_equal(
                out[..., a].astype(int) - out[..., b],
                source.pixels[..., a].astype(int) - source.pixels[..., b],
            )


def test_sharpen_matches_the_independent_reference(tmp_path: Path) -> None:
    source = noisy_source(tmp_path, dpi=600.0)
    out = _render(source, update_detail(PhotoEditRecipe(source), PhotoDetail(0, 0, 50)))
    assert np.array_equal(out, reference_sharpen(source.pixels, 50, 600.0))


def _full_recipe(source, geometry: PhotoGeometry) -> PhotoEditRecipe:
    recipe = straight_recipe(source, geometry, tone=TONE, eyes=(eye(),))
    recipe = update_white_balance(recipe, WB)
    return update_detail(recipe, PhotoDetail(40, 50, 60))


def _chain(source, recipe, *, denoise_first: bool, sharpen_last: bool) -> np.ndarray:
    cancel = Event()
    buffer = _eye_buffer(source, recipe, cancel)
    if denoise_first:
        detail.apply_denoise(buffer, recipe.detail, cancel)
    buffer = apply_geometry(buffer, recipe.geometry)
    if not denoise_first:
        detail.apply_denoise(buffer, recipe.detail, cancel)
    if not sharpen_last:
        detail.apply_sharpen(buffer, recipe.detail, source.effective_dpi, cancel)
    color.apply_white_balance(buffer, recipe.white_balance, cancel)
    _apply_tone(buffer, recipe.tone, cancel)
    if sharpen_last:
        detail.apply_sharpen(buffer, recipe.detail, source.effective_dpi, cancel)
    return buffer


def test_render_order_is_eyes_denoise_geometry_wb_tone_sharpen(tmp_path: Path) -> None:
    source = noisy_source(tmp_path)
    recipe = _full_recipe(source, PhotoGeometry(1, CROP))
    assert np.array_equal(
        _render(source, recipe), _chain(source, recipe, denoise_first=True, sharpen_last=True)
    )
    assert not np.array_equal(
        _render(source, recipe), _chain(source, recipe, denoise_first=True, sharpen_last=False)
    )


def test_denoise_after_an_angled_geometry_differs(tmp_path: Path) -> None:
    source = noisy_source(tmp_path, dpi=100.0)
    recipe = _full_recipe(source, PhotoGeometry(0, None, 37))
    assert np.array_equal(
        _render(source, recipe), _chain(source, recipe, denoise_first=True, sharpen_last=True)
    )
    assert not np.array_equal(
        _render(source, recipe), _chain(source, recipe, denoise_first=False, sharpen_last=True)
    )


def _preview(tmp_path: Path, source, recipe):
    preview = make_preview(
        source, recipe, cache_dir=tmp_path / "cache", generation=1, cancel=Event()
    )
    return preview.after.read_bytes(), preview.working.read_bytes()


def _blob(source, pixels) -> bytes:
    return _preview_jpeg(pixels, bounded=True, icc_profile=source.icc_profile)[0]


def _cases(source):
    base = PhotoEditRecipe(source)
    sharp = PhotoDetail(0, 0, 90)
    return {
        "crop": update_geometry(update_detail(base, sharp), PhotoGeometry(0, (10, 8, 80, 50))),
        "turn": update_geometry(update_detail(base, sharp), PhotoGeometry(1)),
        "angle": update_geometry(
            update_detail(base, PhotoDetail(30, 30, 90)), PhotoGeometry(0, None, 37)
        ),
        "wb": update_white_balance(base, WB),
    }


@pytest.mark.parametrize("name", ["crop", "turn", "angle", "wb"])
def test_the_after_preview_equals_the_export_and_working_is_the_neutral_render(
    tmp_path: Path, name: str
) -> None:
    source = noisy_source(tmp_path, dpi=100.0)
    recipe = _cases(source)[name]
    after, working = _preview(tmp_path, source, recipe)
    assert after == _blob(source, _render(source, recipe))
    neutral = replace(recipe, geometry=PhotoGeometry())
    assert working == _blob(source, _render(source, neutral))


def test_tone_changes_still_reach_the_preview(tmp_path: Path) -> None:
    source = noisy_source(tmp_path, dpi=100.0)
    recipe = update_tone(_cases(source)["crop"], PhotoTone(20, 10, 10, 100))
    after, _ = _preview(tmp_path, source, recipe)
    assert after == _blob(source, _render(source, recipe))
