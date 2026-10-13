from importlib.metadata import version

import fastfoto_linux


def test_version_matches_installed_distribution_metadata() -> None:
    assert fastfoto_linux.__version__ == version("fastfoto-linux")
