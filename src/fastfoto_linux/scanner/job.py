"""Describe a scanimage batch job and turn it into argv and environment."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from fastfoto_linux.scanner.errors import InvalidShimPathError

SUPPORTED_DPI = (50, 75, 100, 150, 200, 240, 300, 360, 400, 600)
MAX_LENGTH_MM = 393.7
DEFAULT_RESOLUTION_DPI = 600
DEFAULT_FILE_PREFIX = "page"

_FILE_PREFIX = re.compile(r"[A-Za-z0-9_-]+")
_LD_PRELOAD_SEPARATORS = re.compile(r"[\s:]")
_SANE_CONFIG_DIR_ENV = "SANE_CONFIG_DIR"
# scanimage's error texts are matched in English and its -y value needs a decimal point.
_LOCALE_ENV = "LC_ALL"
_LOCALE_VALUE = "C"
_LANGUAGE_ENV = "LANGUAGE"  # glibc lets it override the locale's messages, so it must go


class Source(StrEnum):
    """Document feeder mode, spelled exactly as the epsonds backend expects."""

    FRONT = "ADF Front"
    DUPLEX = "ADF Duplex"


class Mode(StrEnum):
    LINEART = "Lineart"
    GRAY = "Gray"
    COLOR = "Color"


@dataclass(frozen=True)
class ScanJob:
    """One ``scanimage --batch`` run; validated on construction."""

    device: str
    output_dir: Path
    source: Source = Source.DUPLEX
    mode: Mode = Mode.COLOR
    resolution: int = DEFAULT_RESOLUTION_DPI
    deskew: bool = True
    max_length_mm: float = MAX_LENGTH_MM
    file_prefix: str = DEFAULT_FILE_PREFIX

    def __post_init__(self) -> None:
        if not self.device.strip() or self.device.startswith("-"):
            raise ValueError(f"device must be a SANE device name, got {self.device!r}")
        if not isinstance(self.output_dir, Path):
            raise TypeError(f"output_dir must be a Path, got {type(self.output_dir).__name__}")
        Source(self.source)
        Mode(self.mode)
        if not isinstance(self.resolution, int) or self.resolution not in SUPPORTED_DPI:
            raise ValueError(f"resolution {self.resolution!r} not in {SUPPORTED_DPI}")
        if not (math.isfinite(self.max_length_mm) and 0 < self.max_length_mm <= MAX_LENGTH_MM):
            raise ValueError(
                f"max_length_mm must be in (0, {MAX_LENGTH_MM}], got {self.max_length_mm!r}"
            )
        if _FILE_PREFIX.fullmatch(self.file_prefix) is None:
            raise ValueError(f"file_prefix must match [A-Za-z0-9_-]+, got {self.file_prefix!r}")

    def page_path(self, number: int) -> Path:
        """File scanimage writes page ``number`` to (the ``--batch`` pattern, filled in)."""
        return self.output_dir / f"{self.file_prefix}-{number:04d}.png"


def batch_pattern(job: ScanJob) -> str:
    """The ``--batch`` printf pattern; a literal ``%`` in the directory must be doubled."""
    directory = str(job.output_dir).replace("%", "%%")
    return f"{directory}/{job.file_prefix}-%04d.png"


def build_argv(job: ScanJob, scanimage: str = "scanimage") -> tuple[str, ...]:
    """Full command line for ``job``. No shell is involved, so no quoting is needed."""
    return (
        scanimage,
        "-d",
        job.device,
        "--source",
        str(job.source),
        "--mode",
        str(job.mode),
        "--resolution",
        str(job.resolution),
        "-y",
        format(job.max_length_mm, "g"),
        f"--adf-skew={'yes' if job.deskew else 'no'}",
        "--format=png",
        f"--batch={batch_pattern(job)}",
    )


def validate_shim_path(shim: Path) -> Path:
    """Return ``shim`` if it can be named in ``LD_PRELOAD``, whose entries split on ``:``/space."""
    if _LD_PRELOAD_SEPARATORS.search(str(shim)):
        raise InvalidShimPathError(
            f"shim path cannot be used in LD_PRELOAD (whitespace or ':' separate entries); "
            f"move the library to a path without them: {str(shim)!r}"
        )
    return shim


def build_env(
    base_env: Mapping[str, str],
    *,
    shim: Path | None = None,
    sane_config_dir: Path | None = None,
) -> dict[str, str]:
    """A new environment for scanimage; ``base_env`` is never modified.

    ``shim`` is prepended to ``LD_PRELOAD``. ``sane_config_dir`` becomes ``SANE_CONFIG_DIR``
    (no trailing colon, so SANE does not also search the system config directory); when it is
    None any inherited ``SANE_CONFIG_DIR`` is removed, so a USB scan never silently uses a
    stale network config. ``LC_ALL=C`` is set and ``LANGUAGE`` dropped, so that scanimage's error
    texts come in English (they are matched as such) and a number is written with a decimal point.
    """
    env = dict(base_env)
    env[_LOCALE_ENV] = _LOCALE_VALUE
    env.pop(_LANGUAGE_ENV, None)
    if shim is not None:
        env["LD_PRELOAD"] = _with_preloaded(env.get("LD_PRELOAD", ""), validate_shim_path(shim))
    if sane_config_dir is None:
        env.pop(_SANE_CONFIG_DIR_ENV, None)
    else:
        env[_SANE_CONFIG_DIR_ENV] = str(sane_config_dir)
    return env


def _with_preloaded(existing: str, shim: Path) -> str:
    libraries = existing.split()
    if str(shim) in libraries:
        return existing
    return " ".join([str(shim), *libraries])
