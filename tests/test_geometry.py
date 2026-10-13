import pytest

from fastfoto_linux.pipeline.geometry import mm_to_px, px_to_mm


def test_mm_to_px_one_inch_is_dpi_pixels() -> None:
    assert mm_to_px(25.4, 600) == 600
    assert mm_to_px(25.4, 75) == 75


def test_mm_to_px_rounds_to_nearest_pixel() -> None:
    assert mm_to_px(3, 75) == 9  # 8.86
    assert mm_to_px(0.1, 75) == 0
    assert mm_to_px(0, 300) == 0


def test_px_to_mm_inverts_mm_to_px_within_half_a_pixel() -> None:
    for dpi in (75, 150, 300, 600):
        assert px_to_mm(mm_to_px(180.5, dpi), dpi) == pytest.approx(180.5, abs=25.4 / dpi / 2)


def test_px_to_mm_known_value() -> None:
    assert px_to_mm(600, 600) == pytest.approx(25.4)


@pytest.mark.parametrize("dpi", [0, -300])
def test_non_positive_dpi_is_rejected(dpi: int) -> None:
    with pytest.raises(ValueError, match="dpi"):
        mm_to_px(10, dpi)
    with pytest.raises(ValueError, match="dpi"):
        px_to_mm(10, dpi)
