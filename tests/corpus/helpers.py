"""Builders for corpus tests: plain bytes, never image files."""

import hashlib
import json
from pathlib import Path

from fastfoto_linux.evaluation.redeye_split import derived_split

SEED = "0123456789abcdef0123456789abcdef"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def raw_item(name: str = "a", data: bytes = b"alpha", **over: object) -> dict:
    """One valid raw item; its split is the derived one unless ``split`` is overridden."""
    item: dict = {
        "id": f"item-{name}",
        "path": f"{name}.bin",
        "sha256": sha(data),
        "kind": "photo",
        "source": "synthetic test bytes",
        "licence": "CC0-1.0",
        "consent_scope": "private-eval",
        "annotations": {},
    }
    item.update(over)
    item.setdefault("split", derived_split(SEED, item.get("group"), item["sha256"]))
    return item


def document(items: list[dict], seed: str = SEED) -> dict:
    return {"format": "fastfoto-corpus", "version": 1, "split_seed": seed, "items": items}


def encode(doc: object) -> bytes:
    return json.dumps(doc).encode()


def manifest_bytes(*items: dict) -> bytes:
    return encode(document(list(items)))


def write_corpus(root: Path, files: dict[str, bytes]) -> Path:
    """Write ``files`` (relative path -> bytes) and a MANIFEST.json naming them."""
    items = []
    for number, (rel, data) in enumerate(files.items()):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        items.append(raw_item(f"f{number}", data, path=rel))
    manifest = root / "MANIFEST.json"
    manifest.write_bytes(encode(document(items)))
    return manifest
