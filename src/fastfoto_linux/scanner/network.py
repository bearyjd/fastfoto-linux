"""Network (LAN) access to the FF-680W through a private SANE config directory."""

import ipaddress
import re
from pathlib import Path

from fastfoto_linux.scanner.errors import InvalidHostError

MAX_HOSTNAME_LENGTH = 253
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOSTNAME = re.compile(rf"{_LABEL}(?:\.{_LABEL})*")
_DLL_CONF = "epsonds\n"


def validate_host(host: str) -> str:
    """Return ``host`` unchanged if it is a plain IPv4/IPv6 address or hostname.

    Everything else is refused: the host is written into a SANE config file, so whitespace,
    newlines or ``#`` could add or comment out config lines.
    """
    if _is_ip_address(host) or (
        len(host) <= MAX_HOSTNAME_LENGTH and _HOSTNAME.fullmatch(host) is not None
    ):
        return host
    raise InvalidHostError(f"not a valid IPv4/IPv6 address or hostname: {host!r}")


def _is_ip_address(host: str) -> bool:
    if "%" in host:  # IPv6 zone ids are not plain addresses
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def write_sane_net_config(config_dir: Path, host: str) -> Path:
    """Write a private SANE config dir that enables only epsonds, pointed at ``host``.

    Returns ``config_dir``, ready to be used as ``SANE_CONFIG_DIR``.
    """
    validate_host(host)
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "dll.conf").write_text(_DLL_CONF)
    (config_dir / "epsonds.conf").write_text(f"net {host}\n")
    return config_dir


def sane_net_device_name(host: str) -> str:
    """SANE device name of the scanner at ``host``."""
    return f"epsonds:net:{validate_host(host)}"
