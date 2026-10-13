"""Network (LAN) access to the FF-680W through a private SANE config directory."""

from pathlib import Path


def validate_host(host: str) -> str:
    raise NotImplementedError


def write_sane_net_config(config_dir: Path, host: str) -> Path:
    raise NotImplementedError


def sane_net_device_name(host: str) -> str:
    raise NotImplementedError
