"""A lossless (PNG) master is a normal editing source; PNG names still title correctly."""

from dataclasses import replace

from fastfoto_linux.gui.photoeditside import eligibility
from fastfoto_linux.gui.photos import PhotoItem


def test_a_retained_png_original_is_eligible(out):
    png = out / "Album_0001.png"
    png.write_bytes(b"x")
    item = PhotoItem(out, 1, png, out / "Album_0001_a.png", None)
    assert eligibility(item) == ""
    upper = out / "Album_0002.PNG"
    upper.write_bytes(b"x")
    assert eligibility(replace(item, original=upper)) == ""


def test_a_missing_png_original_gets_the_neutral_missing_reason(out):
    item = PhotoItem(out, 1, out / "Album_0001.png", out / "Album_0001_a.png", None)
    reason = eligibility(item)
    assert "original is missing" in reason and "JPEG" not in reason
    assert str(out) not in reason


def test_the_not_kept_reason_is_format_neutral(out):
    reason = eligibility(PhotoItem(out, 1, None, out / "Album_0001_a.png", None))
    assert "original" in reason and "JPEG" not in reason


def test_png_names_still_give_the_title_and_front(out):
    item = PhotoItem(out, 1, out / "A_0001.png", out / "A_0001_a.png", out / "A_0001_b.png")
    assert item.title == "A_0001" and item.front == out / "A_0001.png"
    only_enhanced = PhotoItem(out, 1, None, out / "A_0001_a.png", None)
    assert only_enhanced.title == "A_0001"
    back = PhotoItem(out, 1, None, None, out / "A_0001_b.png", unprocessed_reason="no crop")
    assert back.title == "A_0001"
