"""Pick how to reach the scanner: USB with the gap shim, or the network."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.scanner.usb import DEFAULT_SYSFS_ROOT

_PACKAGE_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ScanTarget:
    device: str
    shim: Path | None = None
    sane_config_dir: Path | None = None


def default_shim_candidates(
    env: Mapping[str, str], *, repo_root: Path = _PACKAGE_REPO_ROOT
) -> tuple[Path, ...]:
    raise NotImplementedError


def resolve_target(
    *,
    sysfs_root: Path = DEFAULT_SYSFS_ROOT,
    shim_candidates: Sequence[Path],
    net_host: str | None = None,
    config_dir: Path | None = None,
) -> ScanTarget:
    raise NotImplementedError
