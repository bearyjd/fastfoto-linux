import fastfoto_linux


def test_version_is_exposed() -> None:
    assert fastfoto_linux.__version__ == "0.0.1"
