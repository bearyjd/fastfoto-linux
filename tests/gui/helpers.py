"""Fakes shared by the GUI tests: a worker that records, a sink that records, results."""

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.output import WrittenFiles
from fastfoto_linux.pipeline.process import ProcessResult
from fastfoto_linux.session import RawReason, SessionResult, Stage

ALBUM = "Family Trips"


def written(directory: Path, index: int, *, enhanced: bool = True, back: bool = False):
    stem = directory / f"{ALBUM}_{index:04d}"
    return WrittenFiles(
        directory=directory,
        index=index,
        original=stem.with_suffix(".jpg"),
        enhanced=directory / f"{stem.name}_a.jpg" if enhanced else None,
        back=directory / f"{stem.name}_b.jpg" if back else None,
    )


def with_images(files: WrittenFiles) -> WrittenFiles:
    """Write a tiny JPEG at each path of ``files`` (QML warns about pictures it cannot open)."""
    files.directory.mkdir(parents=True, exist_ok=True)
    for path in files.paths:
        Image.new("RGB", (64, 48), (90, 120, 160)).save(path)
    return files


def clean_result(directory: Path, photos: int = 3) -> SessionResult:
    files = tuple(written(directory, number) for number in range(1, photos + 1))
    return SessionResult(process=ProcessResult(written=files), pages_scanned=photos * 2)


def cancelled_scan(raw_dir: Path, pages: int = 3) -> SessionResult:
    """What a cancel during the scan leaves: pages in the raw folder, nothing processed."""
    kept = tuple(raw_dir / f"page-{number:04d}.png" for number in range(1, pages + 1))
    return SessionResult(
        pages_scanned=pages,
        raw_dir=raw_dir,
        raw_reason=RawReason.CANCELLED,
        cancelled=True,
        kept_pages=kept,
    )


@dataclass
class FakeWorker:
    """Stands in for the Worker behind the controller: only records what it is asked."""

    calls: list[tuple[str, Any]] = field(default_factory=list)

    def check(self) -> None:
        self.calls.append(("check", None))

    def scan(self, form: ScanForm, *, checked: bool = False) -> None:
        self.calls.append(("scan", form))

    def process_kept(self, kept: SessionResult) -> None:
        self.calls.append(("process_kept", kept))

    def cancel(self) -> None:
        self.calls.append(("cancel", None))

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


class RecordingSink:
    """A WorkerSink that records every event with the thread it arrived on."""

    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []
        self.threads: list[int] = []
        self.finished = threading.Event()

    def _add(self, name: str, value: Any = None) -> None:
        self.events.append((name, value))
        self.threads.append(threading.get_ident())

    def on_scanner(self, error: Exception | None) -> None:
        self._add("scanner", error)
        self.finished.set()

    def on_stage(self, stage: Stage) -> None:
        self._add("stage", stage)

    def on_page(self, number: int) -> None:
        self._add("page", number)

    def on_photo(self, files: WrittenFiles) -> None:
        self._add("photo", files)

    def on_finished(self, result: SessionResult) -> None:
        self._add("finished", result)
        self.finished.set()

    def on_error(self, error: Exception) -> None:
        self._add("error", error)
        self.finished.set()

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.events]

    def value(self, name: str) -> Any:
        return next(value for event, value in self.events if event == name)


class ScriptedSession:
    """Stands in for run_session: plays one scan for the UI tests.

    It reports its pages and photos like the real session, and with ``hold`` it waits in the
    SCANNING stage until ``release`` is set or the cancel event is (then it returns the pages as
    kept, as a cancel during the scan does).
    """

    def __init__(
        self,
        out: Path,
        *,
        photos: int = 3,
        hold: bool = False,
        result: SessionResult | None = None,
    ) -> None:
        self.out = out
        self.photos = photos
        self.hold = hold
        self.result = result
        self.release = threading.Event()
        self.holding = threading.Event()
        self.requests: list[Any] = []

    def __call__(self, request: Any, **hooks: Any) -> SessionResult:
        self.requests.append(request)
        hooks["on_stage"](Stage.SCANNING)
        for number in range(1, self.photos * 2 + 1):
            hooks["on_page"](number)
        if self.hold:
            self.holding.set()
            cancel = hooks["cancel"]
            while not (self.release.is_set() or cancel.is_set()):
                cancel.wait(0.005)
            if cancel.is_set():
                return cancelled_scan(self.out / ".raw" / "stamp", self.photos * 2)
        hooks["on_stage"](Stage.PROCESSING)
        for index in range(1, self.photos + 1):
            hooks["on_photo"](with_images(written(self.out / ALBUM, index, back=index == 1)))
        hooks["on_stage"](Stage.DONE)
        return self.result or clean_result(self.out / ALBUM, self.photos)


def process_fake(out: Path, photos: int = 3):
    """A process_pages stand-in that writes ``photos`` photos (reporting each)."""

    def process(pages: Any, settings: Any, **hooks: Any) -> ProcessResult:
        files = tuple(with_images(written(out / ALBUM, index)) for index in range(1, photos + 1))
        for item in files:
            hooks["on_photo"](item)
        return ProcessResult(written=files)

    return process
