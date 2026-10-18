"""Review opt-in and retries travel through the existing worker without writing a PDF."""

from fastfoto_linux.gui.docform import DocumentForm
from fastfoto_linux.gui.doctools import DocumentTools
from fastfoto_linux.gui.worker import Worker
from tests.gui.doc_helpers import DocRecordingSink, cancelled_document
from tests.gui.review_helpers import draft
from tests.gui.test_worker_documents import finish, found


def test_review_scan_request_and_kept_retry_analyse_instead_of_writing(out):
    requests, opened = [], []
    sink = DocRecordingSink()

    def session(request, **kwargs):
        requests.append(request)
        return cancelled_document(out, 3)

    def opener(*args, **kwargs):
        opened.append((args, kwargs))
        return draft(out)

    worker = Worker(
        sink, discover=found, documents=DocumentTools(session=session, open_review=opener)
    )
    worker.scan_documents(
        DocumentForm(searchable=False), str(out), ocr_available=False, review=True
    )
    finish(sink, worker)
    assert requests[0].review
    kept = sink.value("finished")
    sink.finished.clear()
    sink.events.clear()
    worker.process_kept(kept)
    finish(sink, worker)
    result = sink.value("finished")
    assert opened[0][1]["thumbs"] == out / "thumbs"
    assert result.draft == draft(out)
    assert result.document is None


def test_disabled_review_keeps_the_existing_scan_contract(out):
    requests = []
    sink = DocRecordingSink()

    def session(request, **kwargs):
        requests.append(request)
        return cancelled_document(out, 3)

    worker = Worker(sink, discover=found, documents=DocumentTools(session=session))
    worker.scan_documents(DocumentForm(searchable=False), str(out), ocr_available=False)
    finish(sink, worker)
    assert not requests[0].review
