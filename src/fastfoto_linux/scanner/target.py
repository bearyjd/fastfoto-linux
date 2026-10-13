"""Pick how to reach the scanner: USB with the gap shim, or the network."""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.scanner.errors import ScannerNotFoundError, ShimMissingError
from fastfoto_linux.scanner.job import build_env, validate_shim_path
from fastfoto_linux.scanner.network import (
    sane_net_device_name,
    validate_config_dir,
    validate_host,
    write_sane_net_config,
)
from fastfoto_linux.scanner.usb import DEFAULT_SYSFS_ROOT, find_usb_scanners

logger = logging.getLogger(__name__)

SHIM_ENV_VAR = "FF680W_SHIM"
SHIM_FILENAME = "ff680w_usb_gap.so"
SHIM_BUILD_COMMAND = "make -C tools/usb-gap-shim"
_PACKAGE_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ScanTarget:
    """How to address the scanner: SANE device name plus the environment it needs."""

    device: str
    shim: Path | None = None
    sane_config_dir: Path | None = None

    def env(self, base_env: Mapping[str, str]) -> dict[str, str]:
        """A new environment for scanimage: shim preloaded and/or private SANE config set."""
        return build_env(base_env, shim=self.shim, sane_config_dir=self.sane_config_dir)


def default_shim_candidates(
    env: Mapping[str, str], *, repo_root: Path = _PACKAGE_REPO_ROOT
) -> tuple[Path, ...]:
    """Where to look for the USB gap shim, best first.

    ``$FF680W_SHIM`` (a leading ``~`` or ``~/`` is expanded from ``$HOME``; ``~user`` is not),
    then ``~/.local/lib/fastfoto-linux/``, then the in-repo build (only listed when it exists,
    so an installed package does not point at some unrelated directory).
    """
    home = env.get("HOME")
    candidates: list[Path] = []
    if env.get(SHIM_ENV_VAR):
        raw = env[SHIM_ENV_VAR]
        expand = home and (raw == "~" or raw.startswith("~/"))
        candidates.append(Path(home + raw[1:] if expand else raw))
    if home:
        candidates.append(Path(home) / ".local" / "lib" / "fastfoto-linux" / SHIM_FILENAME)
    in_repo = repo_root / "tools" / "usb-gap-shim" / SHIM_FILENAME
    if in_repo.is_file():
        candidates.append(in_repo)
    return tuple(candidates)


def resolve_target(
    *,
    sysfs_root: Path = DEFAULT_SYSFS_ROOT,
    shim_candidates: Sequence[Path],
    net_host: str | None = None,
    config_dir: Path | None = None,
) -> ScanTarget:
    """USB (needs the shim) if the scanner is plugged in, else the network host.

    ``config_dir`` is where the private SANE config for a network target is written; it is
    required whenever ``net_host`` is given, must not contain ``:``, and should be a directory
    only this user can write to (``tempfile.mkdtemp()`` or under ``$XDG_RUNTIME_DIR``).
    """
    if net_host is not None:
        validate_host(net_host)
        if config_dir is None:
            raise ValueError("config_dir is required when net_host is given")
        validate_config_dir(config_dir)
    scanners = find_usb_scanners(sysfs_root)
    if scanners:
        if len(scanners) > 1:
            logger.warning("%d FF-680W scanners on USB; using the first", len(scanners))
        shim = _first_existing(shim_candidates)
        if shim is not None:
            return ScanTarget(
                device=scanners[0].sane_usb_device_name(), shim=validate_shim_path(shim)
            )
        if net_host is None:
            raise ShimMissingError(_shim_missing_message(shim_candidates))
        logger.warning("FF-680W found on USB but the gap shim is missing; using the network")
    if net_host is None or config_dir is None:
        raise ScannerNotFoundError("no FF-680W found on USB and no network host given")
    return ScanTarget(
        device=sane_net_device_name(net_host),
        sane_config_dir=write_sane_net_config(config_dir, net_host),
    )


def _first_existing(candidates: Sequence[Path]) -> Path | None:
    return next((path.resolve() for path in candidates if path.is_file()), None)


def _shim_missing_message(candidates: Sequence[Path]) -> str:
    searched = ", ".join(str(path) for path in candidates) or "no candidate paths"
    return (
        f"FF-680W found on USB but {SHIM_FILENAME} is missing (searched: {searched}). "
        f"Build it with `{SHIM_BUILD_COMMAND}` or set ${SHIM_ENV_VAR}; USB I/O fails without it."
    )
