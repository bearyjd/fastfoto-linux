"""A sheet saved whole is still a failed sheet: the session keeps the raw pages."""

from fastfoto_linux.pipeline.sides import BackPolicy
from fastfoto_linux.session import RawPolicy, RawReason
from tests.cli.fakes import FakeTransport
from tests.process_helpers import page_name, plain_sheet, wide_sheet
from tests.session.conftest import STAMP, Events, kept_names, make_request, run


def test_the_whole_page_is_reported_as_a_photo_and_the_raw_pages_stay(out) -> None:
    events = Events()
    transport = FakeTransport(sheets=[plain_sheet(0), wide_sheet(1)])
    request = make_request(out, policy=RawPolicy.DISCARD, back_policy=BackPolicy.NEVER)
    session = run(request, transport, **events.callbacks())
    assert [files.index for files in events.photos] == [1, 2]
    assert events.photos[1].unprocessed_reason is not None
    assert session.ok is False
    assert session.raw_reason is RawReason.SHEETS_FAILED
    assert session.raw_dir == out / ".raw" / STAMP
    assert kept_names(session.raw_dir) == [page_name(n) for n in range(1, 5)]
