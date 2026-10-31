"""A lossless (PNG) master cannot be edited: the reason is a fixed, path-free sentence."""

from dataclasses import replace

from fastfoto_linux.gui.photoeditside import eligibility
from fastfoto_linux.gui.photos import PhotoItem

PNG_REASON = "Photo edits need a JPEG original; this photo was saved as a lossless PNG."


def test_a_png_original_is_not_eligible_and_names_no_path(out):
    png = out / "Album_0001.png"
    png.write_bytes(b"x")
    item = PhotoItem(out, 1, png, out / "Album_0001_a.png", None)
    assert eligibility(item) == PNG_REASON
    assert str(out) not in eligibility(item)
    assert eligibility(replace(item, original=out / "Album_0001.PNG")) == PNG_REASON


def test_png_names_still_give_the_title_and_front(out):
    item = PhotoItem(out, 1, out / "A_0001.png", out / "A_0001_a.png", out / "A_0001_b.png")
    assert item.title == "A_0001" and item.front == out / "A_0001.png"
    only_enhanced = PhotoItem(out, 1, None, out / "A_0001_a.png", None)
    assert only_enhanced.title == "A_0001"
    back = PhotoItem(out, 1, None, None, out / "A_0001_b.png", unprocessed_reason="no crop")
    assert back.title == "A_0001"
