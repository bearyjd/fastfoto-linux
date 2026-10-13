from pathlib import Path

import pytest

from fastfoto_linux.scanner.errors import InvalidConfigDirError, InvalidHostError, ScannerError
from fastfoto_linux.scanner.network import (
    sane_net_device_name,
    validate_host,
    write_sane_net_config,
)

GOOD_HOSTS = [
    "scanner.local",
    "10.0.0.5",
    "192.0.2.7",
    "Scanner-1",
    "a",
    "ff680w.example.org",
    "autodiscover.local",
    "my-autodiscovery.local",
]
BAD_HOSTS = [
    "",
    " ",
    "a b",
    " scanner.local",
    "scanner.local ",
    "scanner.local\n",
    "x\nnet evil",
    "x\r\nnet evil",
    "tab\there",
    "#",
    "host#comment",
    "host;rm",
    "[::1]",
    "fe80::1",
    "2001:db8::1",
    "::1",
    "fe80::1%eth0",
    "autodiscovery",
    "AutoDiscovery.local",
    "autodiscovery-host",
    "010.0.0.1",
    "10.0.0.05",
    "256.1.1.1",
    "1.2.3.4.5",
    "123",
    "-leading-hyphen.example",
    "trailing-hyphen-.example",
    "double..dot",
    ".leading-dot",
    "under_score.example",
    "bad/host",
    "a" * 64 + ".example",
    "a." * 130 + "b",
]


@pytest.mark.parametrize("host", GOOD_HOSTS)
def test_validate_host_accepts_hostnames_and_ip_addresses(host: str) -> None:
    assert validate_host(host) == host


@pytest.mark.parametrize("host", BAD_HOSTS)
def test_validate_host_rejects_anything_that_could_inject_config(host: str) -> None:
    with pytest.raises(InvalidHostError):
        validate_host(host)


def test_ipv6_is_refused_with_a_clear_reason() -> None:
    with pytest.raises(InvalidHostError, match="IPv6 is not supported by the epsonds network"):
        validate_host("fe80::1")
    with pytest.raises(InvalidHostError, match="use an IPv4 address or hostname"):
        validate_host("2001:db8::1")


@pytest.mark.parametrize("host", ["autodiscovery", "AUTODISCOVERY.example", "autodiscovery-1"])
def test_names_that_epsonds_reads_as_the_discovery_directive_are_refused(host: str) -> None:
    with pytest.raises(InvalidHostError, match="autodiscovery"):
        validate_host(host)


@pytest.mark.parametrize("host", ["010.0.0.1", "10.0.0.05", "256.1.1.1"])
def test_numeric_hosts_that_are_not_clean_ipv4_addresses_are_refused(host: str) -> None:
    with pytest.raises(InvalidHostError, match="IPv4"):
        validate_host(host)


def test_invalid_host_error_is_both_a_scanner_error_and_a_value_error() -> None:
    assert issubclass(InvalidHostError, ScannerError)
    assert issubclass(InvalidHostError, ValueError)


def test_write_sane_net_config_writes_exactly_dll_and_epsonds_conf(tmp_path: Path) -> None:
    config_dir = tmp_path / "sane"

    returned = write_sane_net_config(config_dir, "scanner.local")

    assert returned == config_dir
    assert (config_dir / "dll.conf").read_text() == "epsonds\n"
    assert (config_dir / "epsonds.conf").read_text() == "net scanner.local\n"
    assert sorted(p.name for p in config_dir.iterdir()) == ["dll.conf", "epsonds.conf"]


def test_write_sane_net_config_creates_missing_parent_directories(tmp_path: Path) -> None:
    config_dir = tmp_path / "a" / "b" / "sane"

    write_sane_net_config(config_dir, "10.0.0.5")

    assert (config_dir / "epsonds.conf").read_text() == "net 10.0.0.5\n"


def test_write_sane_net_config_replaces_an_older_host(tmp_path: Path) -> None:
    write_sane_net_config(tmp_path, "old.local")

    write_sane_net_config(tmp_path, "new.local")

    assert (tmp_path / "epsonds.conf").read_text() == "net new.local\n"


def test_write_sane_net_config_rejects_bad_host_without_touching_disk(tmp_path: Path) -> None:
    config_dir = tmp_path / "sane"

    with pytest.raises(InvalidHostError):
        write_sane_net_config(config_dir, "x\nnet evil")

    assert not config_dir.exists()


def test_sane_net_device_name_prefixes_the_epsonds_net_backend() -> None:
    assert sane_net_device_name("scanner.local") == "epsonds:net:scanner.local"
    assert sane_net_device_name("10.0.0.5") == "epsonds:net:10.0.0.5"


def test_sane_net_device_name_validates_the_host() -> None:
    with pytest.raises(InvalidHostError):
        sane_net_device_name("a b")


def test_config_dir_containing_a_colon_is_refused_because_sane_splits_on_colons(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "a:b"

    with pytest.raises(InvalidConfigDirError, match="SANE_CONFIG_DIR"):
        write_sane_net_config(config_dir, "scanner.local")

    assert not config_dir.exists()


def test_invalid_config_dir_error_is_a_scanner_error_and_a_value_error() -> None:
    assert issubclass(InvalidConfigDirError, ScannerError)
    assert issubclass(InvalidConfigDirError, ValueError)
