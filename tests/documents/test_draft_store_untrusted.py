"""``review.json`` is untrusted input: whatever is wrong with it, it is ignored with a logged
warning and the folder is analysed afresh. Nothing in it can name a file outside the folder."""

import json
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.documents import draft_store as store
from fastfoto_linux.documents.draft_store import (
    MAX_REVIEW_BYTES,
    REVIEW_FILE,
    load_draft,
    open_draft,
    read_review,
    save_draft,
)
from tests.documents.store_helpers import (
    analysed,
    edited,
    put_sidecar,
    raw_folder,
    sidecar,
    store_settings,
)

Tamper = Callable[[dict[str, Any]], Any]


def _page(data: dict[str, Any], **changes: Any) -> dict[str, Any]:
    data["pages"][0].update(changes)
    return data


TAMPERINGS: dict[str, Tamper] = {
    "traversal name": lambda d: _page(d, name="../../../etc/passwd"),
    "absolute name": lambda d: _page(d, name="/etc/passwd"),
    "other page name": lambda d: _page(d, name="page-0099.png"),
    "name with a slash": lambda d: _page(d, name="sub/page-0001.png"),
    "huge size": lambda d: _page(d, size=10**30),
    "huge mtime": lambda d: _page(d, mtime_ns=2**80),
    "huge trim": lambda d: _page(d, trim=[10**12, 0, 0, 0]),
    "negative trim": lambda d: _page(d, trim=[-1, 0, 0, 0]),
    "huge dpi": lambda d: _page(d, dpi=10**9),
    "string size": lambda d: _page(d, size="12"),
    "bool size": lambda d: _page(d, size=True),
    "float size": lambda d: _page(d, size=1.5),
    "flags as a string": lambda d: _page(d, flags="few_marks"),
    "unknown flag": lambda d: _page(d, flags=["no_such_flag"]),
    "marks as a dict": lambda d: _page(d, marks={"a": 1}),
    "mark out of range": lambda d: _page(d, marks=[[0.1, 0.1, 1.5, 0.9]]),
    "mark with four strings": lambda d: _page(d, marks=[["a", "b", "c", "d"]]),
    "too many marks": lambda d: _page(d, marks=[[0.1, 0.1, 0.2, 0.2]] * 25),
    "blank as a string": lambda d: _page(d, blank="yes"),
    "partner is the page": lambda d: _page(d, partner=1),
    "partner out of range": lambda d: _page(d, partner=99),
    "detail with a path": lambda d: _page(d, detail=["../x"]),
    "pages null": lambda d: d.update(pages=None) or d,
    "one page short": lambda d: d.update(pages=d["pages"][:-1]) or d,
    "pages is a dict": lambda d: d.update(pages={}) or d,
    "turns 4": lambda d: d.update(edits={"1": {"include": None, "turns": 4}}) or d,
    "turns -1": lambda d: d.update(edits={"1": {"include": None, "turns": -1}}) or d,
    "turns as a string": lambda d: d.update(edits={"1": {"include": None, "turns": "1"}}) or d,
    "include as a string": lambda d: d.update(edits={"1": {"include": "yes", "turns": 0}}) or d,
    "edit of a page that is not there": lambda d: d.update(edits={"9": {"turns": 1}}) or d,
    "edit key is not a number": lambda d: d.update(edits={"x": {"turns": 1}}) or d,
    "order with a repeat": lambda d: d.update(order=[1, 1, 2, 3]) or d,
    "order too short": lambda d: d.update(order=[1, 2, 3]) or d,
    "order from zero": lambda d: d.update(order=[0, 1, 2, 3]) or d,
    "order of strings": lambda d: d.update(order=["1", "2", "3", "4"]) or d,
    "order as a number": lambda d: d.update(order=4) or d,
    "split out of range": lambda d: d.update(splits=[9]) or d,
    "split of bools": lambda d: d.update(splits=[True]) or d,
    "part name 0": lambda d: d.update(part_names={"0": "x"}) or d,
    "part name too far": lambda d: d.update(part_names={"9": "x"}) or d,
    "part name with a path": lambda d: d.update(part_names={"1": "../x"}) or d,
    "part name not a string": lambda d: d.update(part_names={"1": 5}) or d,
    "wrong version": lambda d: d.update(version=2) or d,
    "version as a string": lambda d: d.update(version="1") or d,
    "duplex as a number": lambda d: d.update(duplex=1) or d,
    "options with a bad colour": lambda d: d["options"].update(colour="neon") or d,
    "options with bad languages": lambda d: d["options"].update(langs="../../x") or d,
    "options with a bad name": lambda d: d["options"].update(name="a/b") or d,
    "a list at the top": lambda d: [d],
    "null at the top": lambda d: None,
    "a number at the top": lambda d: 7,
}

RAW_TEXTS = {
    "not json": b"{not json",
    "empty": b"",
    "binary": bytes(range(256)),
    "nan": b'{"version": 1, "pages": [{"marks": [[NaN, 0, 1, 1]]}]}',
    "deep nesting": b"[" * 200_000,
    "bad utf-8": b'{"version": 1, "x": "\xff\xfe"}',
}


@pytest.fixture
def saved(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    folder, pages = raw_folder(tmp_path)
    settings = store_settings(out)
    draft = analysed(folder, pages, settings)
    save_draft(edited(draft), settings)
    return folder, pages, settings, draft


def _ignored(folder, pages, settings, draft, caplog) -> None:
    caplog.set_level(logging.WARNING)
    assert read_review(folder, pages) is None
    assert load_draft(folder, pages, settings) is None
    opened = open_draft(folder, pages, settings)
    assert opened.pages == draft.pages  # analysed afresh
    assert not opened.has_edits
    assert [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize("name", list(TAMPERINGS))
def test_a_tampered_sidecar_is_ignored(saved, caplog, name) -> None:
    folder, pages, settings, draft = saved
    put_sidecar(folder, TAMPERINGS[name](sidecar(folder)))
    _ignored(folder, pages, settings, draft, caplog)


@pytest.mark.parametrize("name", list(RAW_TEXTS))
def test_text_that_is_not_a_sidecar_is_ignored(saved, caplog, name) -> None:
    folder, pages, settings, draft = saved
    (folder / REVIEW_FILE).write_bytes(RAW_TEXTS[name])
    _ignored(folder, pages, settings, draft, caplog)


def test_an_oversized_sidecar_is_ignored_unread(saved, caplog) -> None:
    folder, pages, settings, draft = saved
    valid = (folder / REVIEW_FILE).read_bytes()
    (folder / REVIEW_FILE).write_bytes(valid + b" " * (MAX_REVIEW_BYTES + 1 - len(valid)))
    _ignored(folder, pages, settings, draft, caplog)


def test_a_sidecar_that_is_a_link_is_ignored(saved, tmp_path, caplog) -> None:
    folder, pages, settings, draft = saved
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_bytes((folder / REVIEW_FILE).read_bytes())
    (folder / REVIEW_FILE).unlink()
    (folder / REVIEW_FILE).symlink_to(elsewhere)
    _ignored(folder, pages, settings, draft, caplog)


def test_a_sidecar_that_is_a_pipe_is_ignored_without_hanging(saved, caplog) -> None:
    folder, pages, settings, draft = saved
    (folder / REVIEW_FILE).unlink()
    os.mkfifo(folder / REVIEW_FILE)
    done: list[bool] = []

    def run() -> None:
        _ignored(folder, pages, settings, draft, caplog)
        done.append(True)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=20)
    assert done == [True]


def test_the_valid_sidecar_of_these_tests_is_accepted(saved) -> None:
    folder, pages, settings, _ = saved
    assert load_draft(folder, pages, settings) is not None
    assert json.loads((folder / REVIEW_FILE).read_text())["version"] == 1
    assert store.MAX_REVIEW_BYTES == MAX_REVIEW_BYTES
