"""Discover local models and copy verified downloads into each OCR run's private folder.

The catalogue pins official Git blob identities. It is read from the installed package; neither
model names nor download locations are taken from user URLs. Discovery never opens the network.
"""

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.documents import ocr_tools
from fastfoto_linux.documents.errors import OcrCancelledError, OcrMissingError

CATALOG_PATH = Path(__file__).with_name("ocr_language_catalog.json")
MAX_MODEL_BYTES = 32 * 1024 * 1024
DISCOVERY_TIMEOUT_S = 5.0
MAX_DISCOVERY_BYTES = 64 * 1024
PRIVATE_DIRECTORY_MODE = 0o700
_UNSAFE_WRITE_BITS = stat.S_IWGRP | stat.S_IWOTH
_CODE = re.compile(r"[a-z][a-z0-9_]*", re.ASCII)
_GIT_ID = re.compile(r"[0-9a-f]{40}", re.ASCII)
_ROOT = re.compile(r'^List of available languages in "(.+)" \([0-9]+\):$')


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    size: int
    installed: bool = False
    downloaded: bool = False


@dataclass(frozen=True)
class Inventory:
    languages: tuple[Language, ...]
    error: str = ""
    orientation: Language | None = None

    @property
    def installed(self) -> tuple[Language, ...]:
        return tuple(language for language in self.languages if language.installed)

    @property
    def available(self) -> tuple[Language, ...]:
        return tuple(language for language in self.languages if not language.installed)


@dataclass(frozen=True)
class _Model:
    code: str
    name: str
    size: int
    git_blob_sha1: str


@dataclass(frozen=True)
class _Catalog:
    revision: str
    languages: tuple[_Model, ...]
    auxiliaries: tuple[_Model, ...]

    @property
    def models(self) -> dict[str, _Model]:
        return {model.code: model for model in (*self.languages, *self.auxiliaries)}


def _catalog() -> _Catalog:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if not _GIT_ID.fullmatch(data["revision"]):
        raise ValueError("OCR catalogue revision is invalid")
    groups = []
    for group in ("languages", "auxiliaries"):
        models = tuple(_Model(**item) for item in data[group])
        for model in models:
            if (
                not _CODE.fullmatch(model.code)
                or not _GIT_ID.fullmatch(model.git_blob_sha1)
                or not 0 < model.size <= MAX_MODEL_BYTES
            ):
                raise ValueError("OCR catalogue model is invalid")
        groups.append(models)
    return _Catalog(data["revision"], *groups)


def _cancelled(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise OcrCancelledError("stopped while preparing OCR languages")


def _trusted_base(base: Path) -> Path:
    resolved = base.resolve()
    for parent in (*reversed(resolved.parents), resolved):
        try:
            info = parent.stat()
        except FileNotFoundError:
            continue
        readonly = bool(os.statvfs(parent).f_flag & os.ST_RDONLY)
        trusted_owner = info.st_uid in (0, os.getuid())
        shared_sticky = trusted_owner and info.st_mode & stat.S_ISVTX
        if not stat.S_ISDIR(info.st_mode) or (
            not readonly
            and (not trusted_owner or (info.st_mode & _UNSAFE_WRITE_BITS and not shared_sticky))
        ):
            raise OSError("OCR model cache needs a safe, trusted data directory")
    return resolved


def _cache_root(catalog: _Catalog, *, create: bool = False) -> Path:
    configured = Path(os.environ.get("XDG_DATA_HOME", ""))
    base = configured if configured.is_absolute() else Path.home() / ".local" / "share"
    base = _trusted_base(base)
    if create:
        base.mkdir(parents=True, exist_ok=True)
    current = base
    for part in ("fastfoto-linux", "tessdata", catalog.revision):
        current /= part
        if create:
            current.mkdir(mode=PRIVATE_DIRECTORY_MODE, exist_ok=True)
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & _UNSAFE_WRITE_BITS
        ):
            raise OSError("OCR model cache is not a safe, user-owned directory")
    return current


def _verified_bytes(path: Path, model: _Model) -> bytes | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            info = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & _UNSAFE_WRITE_BITS
                or info.st_size != model.size
            ):
                return None
            data = source.read(model.size + 1)
    except OSError:
        return None
    return data if _matches(data, model) else None


def _matches(data: bytes, model: _Model) -> bool:
    if len(data) != model.size:
        return False
    try:
        digest = hashlib.sha1(f"blob {model.size}\0".encode() + data).hexdigest()
    except ValueError as error:
        raise OSError(
            "OCR model integrity verification unavailable: Git SHA1 is disabled"
        ) from error
    return digest == model.git_blob_sha1


def _system_models(
    cancel: threading.Event | None = None, env: dict[str, str] | None = None
) -> tuple[dict[str, Path], tuple[Path, ...], str]:
    _cancelled(cancel)
    executable = ocr_tools.find_tesseract()
    if executable is None:
        return {}, (), "Tesseract is not installed; languages can be downloaded in advance"
    try:
        result = subprocess.run(
            [executable, "--list-langs"],
            capture_output=True,
            text=True,
            timeout=DISCOVERY_TIMEOUT_S,
            env=ocr_tools.ocr_environment() if env is None else env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}, (), "Tesseract languages could not be listed within the time limit"
    _cancelled(cancel)
    text = result.stdout
    if result.returncode or len(text) > MAX_DISCOVERY_BYTES:
        return {}, (), "Tesseract could not list its installed languages"
    lines = text.splitlines()
    match = _ROOT.fullmatch(lines[0]) if lines else None
    if match is None or not Path(match[1]).is_absolute():
        return {}, (), "Tesseract did not report its model directory"
    root = Path(match[1])
    models = {
        code: root / f"{code}.traineddata"
        for code in lines[1:]
        if _CODE.fullmatch(code) and (root / f"{code}.traineddata").is_file()
    }
    return models, (root,), ""


def discover_languages(*, cancel: threading.Event | None = None) -> Inventory:
    """List installed and downloadable models, without network access."""
    catalog = _catalog()
    installed, _, error = _system_models(cancel)
    try:
        root = _cache_root(catalog)
        downloaded = set()
        for model in catalog.models.values():
            _cancelled(cancel)
            if _verified_bytes(root / f"{model.code}.traineddata", model) is not None:
                downloaded.add(model.code)
    except OSError as problem:
        downloaded = set()
        error = str(problem)
    languages = tuple(
        Language(
            model.code,
            model.name,
            model.size,
            model.code in installed or model.code in downloaded,
            model.code in downloaded,
        )
        for model in catalog.languages
    )
    known = catalog.models.keys()
    custom = tuple(Language(code, code, 0, True) for code in sorted(installed.keys() - known))
    osd = catalog.models.get("osd")
    orientation = (
        Language(
            osd.code,
            osd.name,
            osd.size,
            "osd" in installed or "osd" in downloaded,
            "osd" in downloaded,
        )
        if osd is not None
        else None
    )
    return Inventory(languages + custom, error, orientation)


def _codes(langs: str) -> tuple[str, ...]:
    codes = tuple(langs.split("+"))
    if not all(_CODE.fullmatch(code) for code in codes):
        raise ValueError("Use OCR language codes such as eng or eng+spa")
    return codes


def _missing(codes: tuple[str, ...]) -> OcrMissingError:
    return OcrMissingError(
        f"OCR language models missing: {', '.join(codes)}. "
        "Download selected languages in the language picker before scanning."
    )


def require_languages(langs: str) -> None:
    """Fail before feeding pages when selected OCR models or orientation data are absent."""
    codes = (*_codes(langs), "osd")
    inventory = discover_languages()
    installed = {language.code for language in inventory.installed}
    if inventory.orientation is not None and inventory.orientation.installed:
        installed.add("osd")
    missing = tuple(dict.fromkeys(code for code in codes if code not in installed))
    if missing:
        raise _missing(missing)


def _managed_selection(codes: tuple[str, ...], catalog: _Catalog) -> tuple[dict[str, bytes], bool]:
    root = _cache_root(catalog)
    models = catalog.models
    selected = {}
    corrupt = False
    for code in codes:
        model = models.get(code)
        path = root / f"{code}.traineddata"
        if model is None:
            continue
        data = _verified_bytes(path, model)
        if data is not None:
            selected[code] = data
        elif path.exists() or path.is_symlink():
            corrupt = True
    return selected, corrupt


def _copy_configs(roots: tuple[Path, ...], overlay: Path) -> None:
    for root in roots:
        for name in ("configs", "tessconfigs"):
            source = root / name
            if source.is_dir():
                shutil.copytree(source, overlay / name, dirs_exist_ok=True)


def prepare_tessdata(langs: str, folder: Path, env: dict[str, str]) -> dict[str, str]:
    """Build an isolated overlay only when a selected model comes from verified app storage.

    Managed files are copied from the exact bytes that were verified, so changing the cache
    afterwards cannot change a running OCR job. Installed models retain their distribution's
    orientation data and configuration files. The caller's environment is never modified.
    """
    codes = (*_codes(langs), "osd")
    catalog = _catalog()
    try:
        managed, corrupt = _managed_selection(codes, catalog)
    except OSError as error:
        raise OcrMissingError(str(error)) from error
    if not managed and not corrupt:
        return dict(env)
    installed, roots, _ = _system_models(env=env)
    missing = tuple(code for code in codes if code not in managed and code not in installed)
    if missing:
        raise _missing(missing)
    overlay = folder / "tessdata"
    overlay.mkdir(mode=PRIVATE_DIRECTORY_MODE)
    for code in dict.fromkeys(codes):
        destination = overlay / f"{code}.traineddata"
        if code in managed:
            destination.write_bytes(managed[code])
        else:
            shutil.copyfile(installed[code], destination)
    _copy_configs(roots, overlay)
    return {**env, "TESSDATA_PREFIX": str(overlay)}
