"""An XMP packet with its own Orientation would disagree with the Exif tag once that changes."""

from pathlib import Path

import pytest

from fastfoto_linux.cli.app import main
from fastfoto_linux.library.decide import decide_file
from fastfoto_linux.library.exif_errors import JpegExifError
from fastfoto_linux.library.jpeg_exif import set_orientation
from fastfoto_linux.library.plan import Action
from tests.face_images import load_astronaut
from tests.library.jpeg_helpers import make_jpeg, write_file
from tests.library.untrusted_helpers import sideways, with_xmp

REASON = "xmp-orientation"
ATTRIBUTE = (
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:Description tiff:Orientation="6"/></x:xmpmeta>'
)
ELEMENT = (
    b"<x:xmpmeta><rdf:Description><tiff:Orientation>1</tiff:Orientation>"
    b"</rdf:Description></x:xmpmeta>"
)
OTHER = b'<x:xmpmeta><rdf:Description dc:title="holiday" tiff:Make="TestCam"/></x:xmpmeta>'


@pytest.mark.parametrize("packet", [ATTRIBUTE, ELEMENT], ids=["attribute", "element"])
def test_a_photo_that_needs_a_turn_but_has_an_xmp_orientation_is_skipped(
    tmp_path: Path, packet: bytes
) -> None:
    write_file(tmp_path, "a.jpg", with_xmp(sideways(90), packet))
    row = decide_file(tmp_path, "a.jpg")
    assert (row.action, row.reason) == (Action.SKIP, REASON)


def test_an_xmp_packet_about_something_else_does_not_stop_the_turn(tmp_path: Path) -> None:
    write_file(tmp_path, "a.jpg", with_xmp(sideways(90), OTHER))
    assert decide_file(tmp_path, "a.jpg").action is Action.ROTATE


def test_the_edit_itself_refuses_a_file_with_an_xmp_orientation() -> None:
    data = with_xmp(make_jpeg(load_astronaut()), ATTRIBUTE)
    with pytest.raises(JpegExifError) as caught:
        set_orientation(data, 6)
    assert caught.value.reason == REASON


def test_the_summary_counts_them_under_their_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    library = tmp_path / "lib"
    write_file(library, "a.jpg", with_xmp(sideways(90), ATTRIBUTE))
    plan = tmp_path / "plan.csv"
    assert main(["library", "check", str(library), "--plan", str(plan), "--jobs", "1"]) == 0
    assert f"{REASON}: 1" in capsys.readouterr().out
