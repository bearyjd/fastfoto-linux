"""Photo jobs share the worker lock with scan/discovery and never start a second lane."""

import inspect
from dataclasses import replace
from threading import Event

import pytest

from fastfoto_linux.gui.photoeditjobs import PhotoEditRequest
from fastfoto_linux.gui.worker import Worker, WorkerBusyError
from tests.gui.helpers import RecordingSink
from tests.gui.photoedit_helpers import fake_tools, source


class PhotoSink(RecordingSink):
    def on_photo_edit_result(self, result):
        self._add("photo_edit", result)
        self.finished.set()


def test_worker_editor_job_serializes_and_releases_busy_before_callback(out):
    assert "photo_edits" in inspect.signature(Worker).parameters
    src = source(out)
    entered, release = Event(), Event()
    calls = []
    tools = fake_tools(src, calls)

    def load(*args, **kwargs):
        entered.set()
        assert release.wait(5), "synthetic load was not released"
        return src

    sink = PhotoSink()
    worker = Worker(sink, photo_edits=replace(tools, load=load), photo_cache_dir=out / "cache")
    worker.photo_edit_job(PhotoEditRequest("open", 3, path=src.path))
    try:
        assert entered.wait(5)
        assert worker.busy
        with pytest.raises(WorkerBusyError):
            worker.check()
        with pytest.raises(WorkerBusyError):
            worker.photo_edit_job(PhotoEditRequest("open", 4, path=src.path))
    finally:
        release.set()
        worker.join(5)
    assert sink.finished.wait(5)
    assert not worker.busy
    assert sink.value("photo_edit").generation == 3
    assert sink.names == ["photo_edit"]
