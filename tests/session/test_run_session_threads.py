"""``run_session`` on a worker thread: every callback runs there, never on the caller's thread."""

import threading

from fastfoto_linux.session import RawReason
from tests.process_helpers import plain_sheet
from tests.session.conftest import make_request, run

JOIN_TIMEOUT_S = 30.0
POLL_S = 0.05


def test_the_callbacks_run_on_the_worker_thread(out, transport) -> None:
    transport.sheets = [plain_sheet(0), plain_sheet(1)]
    threads: dict[str, set[int]] = {"page": set(), "photo": set(), "stage": set()}

    def note(kind: str):
        return lambda *args: threads[kind].add(threading.get_ident())

    results = []
    worker = threading.Thread(
        target=lambda: results.append(
            run(
                make_request(out),
                transport,
                on_page=note("page"),
                on_photo=note("photo"),
                on_stage=note("stage"),
            )
        )
    )
    worker.start()
    worker.join(timeout=JOIN_TIMEOUT_S)
    assert not worker.is_alive()
    assert worker.ident is not None
    assert worker.ident != threading.get_ident()
    assert threads == {kind: {worker.ident} for kind in threads}
    assert [session.ok for session in results] == [True]


def test_the_main_thread_can_cancel_a_session_running_on_a_worker(out, transport) -> None:
    transport.sheets = [plain_sheet(0), plain_sheet(1), plain_sheet(2)]
    cancel, first_photo = threading.Event(), threading.Event()

    def hold_the_first_photo(files) -> None:
        first_photo.set()
        assert cancel.wait(timeout=JOIN_TIMEOUT_S), "the main thread never pressed Cancel"

    results = []
    worker = threading.Thread(
        target=lambda: results.append(
            run(make_request(out), transport, on_photo=hold_the_first_photo, cancel=cancel)
        )
    )
    worker.start()
    while worker.is_alive() and not first_photo.wait(timeout=POLL_S):
        pass  # a worker that died has nothing to cancel: the asserts below say why
    cancel.set()
    worker.join(timeout=JOIN_TIMEOUT_S)
    assert not worker.is_alive()
    (session,) = results
    assert session.cancelled is True
    assert session.process is not None
    assert session.process.photos == 1
    assert session.raw_reason is RawReason.CANCELLED
