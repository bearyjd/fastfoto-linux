import multiprocessing
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from functools import partial
from pathlib import Path

import pytest
from PIL import Image

from fastfoto_linux.output import writer
from tests import _output_workers as workers
from tests._output_helpers import make_root, names

DC = "{http://purl.org/dc/elements/1.1/}"
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"


def notes_of(path: Path) -> str | None:
    with Image.open(path) as image:
        root = ET.fromstring(image.info["xmp"])
    item = root.find(f".//{DC}description/{RDF}Alt/{RDF}li")
    return None if item is None else item.text


def assert_every_photo_is_whole(folder: Path, results: Iterable[tuple[int, int]]) -> None:
    """One file per photo, unique indexes, and each file really holds its own photo."""
    results = sorted(results)
    indexes = [index for _, index in results]
    assert len(set(indexes)) == len(indexes)
    assert len(names(folder)) == len(results)
    for photo, index in results:
        suffix = "_a" if workers.is_enhanced_only(photo) else ""
        path = folder / f"{workers.ALBUM}_{index:04d}{suffix}.jpg"
        assert path.exists(), f"photo {photo} is missing at index {index}"
        assert notes_of(path) == f"photo-{photo}"


def test_threads_mixing_original_only_and_enhanced_only_photos_never_cross_wire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_root(tmp_path)
    photos = range(12)
    real = writer.next_index

    def slow(directory: Path, prefix: str) -> int:
        index = real(directory, prefix)
        time.sleep(workers.NUMBERING_DELAY_S)
        return index

    monkeypatch.setattr(writer, "next_index", slow)

    with ThreadPoolExecutor(max_workers=len(photos)) as pool:
        results = list(pool.map(lambda photo: workers.write_numbered(str(root), photo), photos))

    assert_every_photo_is_whole(root / workers.ALBUM, results)


def test_processes_mixing_original_only_and_enhanced_only_photos_never_cross_wire(
    tmp_path: Path,
) -> None:
    root = make_root(tmp_path)
    photos = range(8)
    context = multiprocessing.get_context("spawn")

    with ProcessPoolExecutor(max_workers=4, mp_context=context) as pool:
        results = list(
            pool.map(partial(workers.write_numbered, str(root), slow=True), photos, timeout=30)
        )

    assert_every_photo_is_whole(root / workers.ALBUM, results)
