"""Test doubles for scanning documents: scenes in, PNG pages out, the scanner never started."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.cli import cmd_doc
from fastfoto_linux.scanner import ScanJob, ScanResult, ScanTarget
from tests.cli.fakes import DEVICE
from tests.doc_synth import Scene, write_png


@dataclass
class DocTransport:
    """Stands in for ``resolve_target`` and ``run_scan``; records every call.

    ``scenes`` are written as the scanned pages ``page-0001.png`` ..., each with the resolution
    of its scene (none when ``dpi_in_file`` is False, like a scanimage that writes none).
    ``failure`` builds the exception raised once the pages are on disk; it is given the pages
    ``pages_before_failure`` says the scanner had finished. ``corrupt_page`` (1-based) is
    overwritten with bytes that are no PNG; ``truncate_page`` is cut to its first half (a page
    the scanner was writing when it stopped).
    """

    scenes: Sequence[Scene] = ()
    dpi_in_file: bool = True
    pages_before_failure: int = 0
    failure: Callable[[tuple[Path, ...]], BaseException] | None = None
    resolve_error: Exception | None = None
    corrupt_page: int | None = None
    truncate_page: int | None = None
    resolve_calls: list[dict[str, Any]] = field(default_factory=list)
    config_dir_existed: list[bool] = field(default_factory=list)
    jobs: list[ScanJob] = field(default_factory=list)
    envs: list[Mapping[str, str]] = field(default_factory=list)

    def resolve_target(self, **kwargs: Any) -> ScanTarget:
        self.resolve_calls.append(kwargs)
        config_dir = kwargs.get("config_dir")
        if config_dir is not None:
            self.config_dir_existed.append(Path(config_dir).is_dir())
        if self.resolve_error is not None:
            raise self.resolve_error
        return ScanTarget(device=DEVICE)

    def run_scan(self, job: ScanJob, *, env: Mapping[str, str], **kwargs: Any) -> ScanResult:
        self.jobs.append(job)
        self.envs.append(env)
        job.output_dir.mkdir(parents=True, exist_ok=True)
        pages = [
            write_png(
                job.page_path(number),
                scene.image,
                dpi=scene.dpi if self.dpi_in_file else None,
            )
            for number, scene in enumerate(self.scenes, start=1)
        ]
        if self.corrupt_page is not None:
            pages[self.corrupt_page - 1].write_bytes(b"not a png")
        if self.truncate_page is not None:
            cut = pages[self.truncate_page - 1]
            cut.write_bytes(cut.read_bytes()[: cut.stat().st_size // 2])
        on_progress = kwargs.get("on_progress")
        for number in range(1, len(pages) + 1):
            if on_progress is not None:
                on_progress(number)
        if self.failure is not None:
            raise self.failure(tuple(pages[: self.pages_before_failure]))
        return ScanResult(pages=tuple(pages))

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cmd_doc, "resolve_target", self.resolve_target)
        monkeypatch.setattr(cmd_doc, "run_scan", self.run_scan)
