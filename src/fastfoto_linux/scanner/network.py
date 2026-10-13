"""Network (LAN) access to the FF-680W through a private SANE config directory."""

import ipaddress
import re
from pathlib import Path

from fastfoto_linux.scanner.errors import InvalidConfigDirError, InvalidHostError

MAX_HOSTNAME_LENGTH = 253
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOSTNAME = re.compile(rf"{_LABEL}(?:\.{_LABEL})*")
_DLL_CONF = "epsonds\n"
# epsonds.c reads "net autodiscovery..." as the discovery directive, not as a host name.
_DISCOVERY_DIRECTIVE = "autodiscovery"
_IPV6_UNSUPPORTED = (
    "IPv6 is not supported by the epsonds network transport; use an IPv4 address or hostname"
)


def validate_host(host: str) -> str:
    """Return ``host`` unchanged if it is a plain IPv4 address or hostname.

    Everything else is refused: the host is written into a SANE config file, so whitespace,
    newlines or ``#`` could add or comment out config lines. IPv6 is refused because SANE's
    generic TCP helper (``sanei_tcp_open``) only speaks IPv4. Numeric hosts that are not clean
    dotted-quad addresses (``010.0.0.1``) are refused because the C resolver reads leading
    zeros as octal.
    """
    address = _parse_ip(host)
    if isinstance(address, ipaddress.IPv6Address):
        raise InvalidHostError(f"{_IPV6_UNSUPPORTED}: {host!r}")
    if address is not None:
        return host
    if host.lower().startswith(_DISCOVERY_DIRECTIVE):
        raise InvalidHostError(
            f"host names starting with {_DISCOVERY_DIRECTIVE!r} are read by epsonds as a "
            f"discovery directive: {host!r}"
        )
    if len(host) > MAX_HOSTNAME_LENGTH or _HOSTNAME.fullmatch(host) is None:
        raise InvalidHostError(f"not a valid IPv4 address or hostname: {host!r}")
    if host.rsplit(".", 1)[-1].isdigit():
        raise InvalidHostError(
            f"numeric host that is not a valid IPv4 address (leading zeros are ambiguous): {host!r}"
        )
    return host


def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def validate_config_dir(config_dir: Path) -> Path:
    """Return ``config_dir`` if it can be used as ``SANE_CONFIG_DIR`` (a colon-separated list)."""
    if ":" in str(config_dir):
        raise InvalidConfigDirError(
            f"SANE_CONFIG_DIR is colon-separated, so the config directory cannot contain ':': "
            f"{str(config_dir)!r}"
        )
    return config_dir


def write_sane_net_config(config_dir: Path, host: str) -> Path:
    """Write a private SANE config dir that enables only epsonds, pointed at ``host``.

    Returns ``config_dir``, ready to be used as ``SANE_CONFIG_DIR``. The directory should be
    one only this user can write to, e.g. from ``tempfile.mkdtemp()`` or under
    ``$XDG_RUNTIME_DIR``; a predictable shared path such as ``/tmp/sane`` would let another user
    pre-create it and redirect the scanner.
    """
    validate_host(host)
    validate_config_dir(config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "dll.conf").write_text(_DLL_CONF)
    (config_dir / "epsonds.conf").write_text(f"net {host}\n")
    return config_dir


def sane_net_device_name(host: str) -> str:
    """SANE device name of the scanner at ``host``."""
    return f"epsonds:net:{validate_host(host)}"
