import pytest

from fastfoto_linux.pipeline.print_sizes import is_common_print_size

INCH = 25.4


@pytest.mark.parametrize(
    ("w_in", "h_in"),
    [
        (3, 5),
        (3.5, 5),
        (4, 5),
        (4, 6),
        (4, 6.5),
        (5, 7),
        (5, 8),
        (6, 8),
        (8, 10),
        (8, 12),
        (4, 4),
        (5, 5),
        (3, 3),
    ],
)
def test_common_prints_and_squares_are_plausible_either_way_up(w_in: float, h_in: float) -> None:
    assert is_common_print_size(w_in * INCH, h_in * INCH)
    assert is_common_print_size(h_in * INCH, w_in * INCH)


@pytest.mark.parametrize(
    ("w_mm", "h_mm"),
    [(180.5, 128.5), (165.0, 103.0), (250, 90), (300, 100), (148, 210), (210, 148)],
)
def test_measured_real_sizes_and_panoramas_are_plausible(w_mm: float, h_mm: float) -> None:
    assert is_common_print_size(w_mm, h_mm)


def test_tolerance_is_five_millimetres_per_side() -> None:
    assert is_common_print_size(127 + 4.9, 177.8 - 4.9)
    assert not is_common_print_size(127 + 5.5, 177.8)
    assert not is_common_print_size(127, 177.8 + 5.5)


@pytest.mark.parametrize(
    ("w_mm", "h_mm"),
    [(178, 83), (172, 120), (180, 59), (200, 100), (120, 60), (150, 30)],
)
def test_sizes_left_after_a_cropped_away_edge_are_implausible(w_mm: float, h_mm: float) -> None:
    assert not is_common_print_size(w_mm, h_mm)
    assert not is_common_print_size(h_mm, w_mm)


def test_a_short_wide_strip_is_not_a_panorama() -> None:
    assert not is_common_print_size(200, 70)  # aspect 2.9 but only 200 mm long


@pytest.mark.parametrize("side_mm", [26, 33, 40, 69])
def test_small_squares_are_stamps_not_prints(side_mm: float) -> None:
    assert not is_common_print_size(side_mm, side_mm)


def test_squares_from_70_mm_are_plausible() -> None:
    assert is_common_print_size(71, 71)
    assert is_common_print_size(120, 123)
