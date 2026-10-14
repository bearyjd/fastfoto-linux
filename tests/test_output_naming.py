import logging
from pathlib import Path

import pytest

from fastfoto_linux.output.errors import InvalidAlbumError, InvalidPrefixError
from fastfoto_linux.output.naming import (
    DEFAULT_PREFIX,
    MAX_ALBUM_CHARS,
    MAX_COMPONENT_BYTES,
    MAX_INDEX,
    MAX_INDEX_DIGITS,
    MAX_PREFIX_BYTES,
    album_dir,
    default_prefix,
    next_index,
    photo_paths,
    sanitise_album,
    sanitise_prefix,
)

ADVERSARIAL_ALBUMS = [
    "../../etc",
    "/etc/passwd",
    "..\\..\\windows",
    "C:\\Users\\x",
    "....//....//x",
    "a/../../b",
    "nul\x00byte",
    "\u202eevil",
    "~root",
    ".hidden",
    "x\n\ty\r",
    "\U0001f600" * 300,
    "\u7956" * 300,
]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Grandma 1970s", "Grandma 1970s"),
        ("  Grandma   1970s  ", "Grandma 1970s"),
        ("Grandma/1970s", "Grandma 1970s"),
        ("a\\b", "a b"),
        ("../../etc", "etc"),
        ("/etc/passwd", "etc passwd"),
        ("..hidden", "hidden"),
        (".hidden.album.", "hidden.album"),
        ("tab\tnew\nline", "tab new line"),
        ("nul\x00byte", "nul byte"),
        ("bell\x07", "bell"),
        ("\u202eevil", "evil"),
        ("Cafe\u0301", "Caf\u00e9"),
        ("Caf\u00e9 \u7956\u6bcd", "Caf\u00e9 \u7956\u6bcd"),
        ("1983_June_lake-trip", "1983_June_lake-trip"),
    ],
)
def test_sanitise_album_table(raw: str, expected: str) -> None:
    assert sanitise_album(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", ".", "..", "...", " . . ", "/", "\\", "\x00", "\n"])
def test_sanitise_album_rejects_names_with_nothing_usable(raw: str) -> None:
    with pytest.raises(InvalidAlbumError):
        sanitise_album(raw)


@pytest.mark.parametrize("raw", ADVERSARIAL_ALBUMS)
def test_sanitise_album_always_yields_one_safe_path_component(raw: str) -> None:
    name = sanitise_album(raw)

    assert name
    assert Path(name).name == name
    assert not name.startswith(".")
    assert not any(ch in name for ch in "/\\\x00")
    assert name.isprintable()
    assert len(name) <= MAX_ALBUM_CHARS
    assert len(name.encode()) <= MAX_COMPONENT_BYTES


def test_sanitise_album_keeps_exactly_the_maximum_length() -> None:
    assert sanitise_album("a" * MAX_ALBUM_CHARS) == "a" * MAX_ALBUM_CHARS


def test_sanitise_album_truncates_to_the_character_limit() -> None:
    assert sanitise_album("a" * (MAX_ALBUM_CHARS + 30)) == "a" * MAX_ALBUM_CHARS


def test_sanitise_album_truncates_on_a_codepoint_boundary_to_the_byte_limit() -> None:
    name = sanitise_album("\U0001f600" * MAX_ALBUM_CHARS)

    assert name == "\U0001f600" * (MAX_COMPONENT_BYTES // 4)
    assert len(name.encode()) <= MAX_COMPONENT_BYTES


def test_sanitise_album_restrips_after_truncating() -> None:
    assert sanitise_album("a" * (MAX_ALBUM_CHARS - 1) + " .tail") == "a" * (MAX_ALBUM_CHARS - 1)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("FastFoto", "FastFoto"),
        ("1983_June_lake-trip", "1983_June_lake-trip"),
        ("a__b_-c", "a__b_-c"),
        ("_x_", "_x_"),
        ("Grandma 1970s", "Grandma 1970s"),
        ("  Grandma   1970s  ", "Grandma 1970s"),
        ("Mom & Dad (1970s)", "Mom & Dad (1970s)"),
        ("Smith, J. + Co. 'Trip' #2", "Smith, J. + Co. 'Trip' #2"),
        ("Caf\u00e9 \u7956\u6bcd", "Caf\u00e9 \u7956\u6bcd"),
        ("Cafe\u0301", "Caf\u00e9"),
        ("a/b\\c", "a b c"),
        ("../x", "x"),
        ("../../escape", "escape"),
        ("..hidden", "hidden"),
        ("nul\x00byte", "nul byte"),
        ("tab\tnew\nline", "tab new line"),
        ("\u202eevil", "evil"),
    ],
)
def test_sanitise_prefix_table(raw: str, expected: str) -> None:
    assert sanitise_prefix(raw) == expected


def test_sanitise_prefix_truncates_to_the_character_limit() -> None:
    assert sanitise_prefix("a" * 500) == "a" * MAX_ALBUM_CHARS


def test_sanitise_prefix_truncates_to_the_byte_limit_on_a_codepoint_boundary() -> None:
    stem = sanitise_prefix("\U0001f600" * MAX_ALBUM_CHARS)

    assert stem == "\U0001f600" * (MAX_PREFIX_BYTES // 4)
    assert len(stem.encode()) <= MAX_PREFIX_BYTES


def test_the_longest_prefix_still_makes_a_legal_file_name() -> None:
    stem = sanitise_prefix("\U0001f600" * MAX_ALBUM_CHARS)
    longest = f"{stem}_{'9' * MAX_INDEX_DIGITS}_a.jpg"
    staging = f".{longest}.deadbeef.tmp"

    assert len(longest.encode()) <= MAX_COMPONENT_BYTES
    assert len(staging.encode()) <= MAX_COMPONENT_BYTES


def test_the_name_length_reserve_matches_the_largest_index_exactly() -> None:
    suffix = f"_{'9' * MAX_INDEX_DIGITS}_a.jpg"
    staging_overhead = len(b".") + len(b".deadbeef.tmp")

    assert MAX_COMPONENT_BYTES - len(suffix) - staging_overhead == MAX_PREFIX_BYTES


@pytest.mark.parametrize(
    "raw", ["", "   ", ".", "..", "...", " . . ", "/", "\\", "\x00", "\n", "../..", "/../"]
)
def test_sanitise_prefix_rejects_names_with_nothing_usable(raw: str) -> None:
    with pytest.raises(InvalidPrefixError):
        sanitise_prefix(raw)


@pytest.mark.parametrize("raw", ADVERSARIAL_ALBUMS)
def test_sanitise_prefix_yields_one_safe_idempotent_component(raw: str) -> None:
    once = sanitise_prefix(raw)

    assert Path(once).name == once
    assert not once.startswith(".")
    assert not any(ch in once for ch in "/\\\x00")
    assert once.isprintable()
    assert len(once.encode()) <= MAX_PREFIX_BYTES
    assert sanitise_prefix(once) == once


@pytest.mark.parametrize(
    ("album", "expected"),
    [
        (None, DEFAULT_PREFIX),
        ("Grandma 1970s", "Grandma 1970s"),
        ("1983_June_lake-trip", "1983_June_lake-trip"),
        ("Mom & Dad (1970s)", "Mom & Dad (1970s)"),
        ("\u7956\u6bcd", "\u7956\u6bcd"),
        ("Caf\u00e9", "Caf\u00e9"),
        ("../../x", "x"),
    ],
)
def test_default_prefix_is_the_album_folder_name(album: str | None, expected: str) -> None:
    assert default_prefix(album) == expected


def test_default_prefix_still_rejects_an_unusable_album() -> None:
    with pytest.raises(InvalidAlbumError):
        default_prefix("..")


@pytest.mark.parametrize("album", ["1983_June_lake-trip", "Mom & Dad (1970s)", "Smith, J. + Co."])
def test_default_prefix_equals_the_sanitised_folder_name(album: str) -> None:
    folder = sanitise_album(album)

    assert default_prefix(album) == folder


def test_album_dir_without_album_is_the_resolved_root(tmp_path: Path) -> None:
    assert album_dir(tmp_path / "out" / ".." / "out", None) == (tmp_path / "out").resolve()


def test_album_dir_is_a_child_of_the_root_and_is_not_created(tmp_path: Path) -> None:
    root = tmp_path / "out"

    result = album_dir(root, "Grandma 1970s")

    assert result == root.resolve() / "Grandma 1970s"
    assert not root.exists()


@pytest.mark.parametrize("raw", ADVERSARIAL_ALBUMS)
def test_album_dir_never_leaves_the_root(tmp_path: Path, raw: str) -> None:
    root = (tmp_path / "out").resolve()

    result = album_dir(root, raw)

    assert result.parent == root


@pytest.mark.parametrize("raw", ["..", ".", "", "/", "\\"])
def test_album_dir_rejects_unusable_albums(tmp_path: Path, raw: str) -> None:
    with pytest.raises(InvalidAlbumError):
        album_dir(tmp_path, raw)


def test_album_dir_rejects_a_symlink_that_escapes_the_root(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (root / "Sneaky").symlink_to(outside, target_is_directory=True)

    with pytest.raises(InvalidAlbumError, match="outside"):
        album_dir(root, "Sneaky")


def test_album_dir_allows_a_symlink_that_stays_inside_the_root(tmp_path: Path) -> None:
    root = tmp_path / "out"
    (root / "real").mkdir(parents=True)
    (root / "Alias").symlink_to(root / "real", target_is_directory=True)

    assert album_dir(root, "Alias") == (root / "real").resolve()


def touch(directory: Path, *names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_bytes(b"x")


def test_next_index_is_one_for_a_missing_or_empty_folder(tmp_path: Path) -> None:
    assert next_index(tmp_path / "missing", "X") == 1
    touch(tmp_path / "empty")
    assert next_index(tmp_path / "empty", "X") == 1


def test_next_index_continues_after_the_highest_number(tmp_path: Path) -> None:
    touch(tmp_path, "X_0001.jpg", "X_0002_a.jpg", "X_0002_b.jpg")

    assert next_index(tmp_path, "X") == 3


def test_next_index_does_not_fill_gaps(tmp_path: Path) -> None:
    touch(tmp_path, "X_0001.jpg", "X_0005.jpg")

    assert next_index(tmp_path, "X") == 6


@pytest.mark.parametrize("name", ["X_0007_a.jpg", "X_0007_b.jpg", "X_0007.jpg"])
def test_next_index_continues_a_folder_holding_only_one_kind_of_file(
    tmp_path: Path, name: str
) -> None:
    touch(tmp_path, name)

    assert next_index(tmp_path, "X") == 8


def test_next_index_rolls_over_to_five_digits(tmp_path: Path) -> None:
    touch(tmp_path, "X_9999.jpg")

    assert next_index(tmp_path, "X") == 10000
    assert photo_paths(tmp_path, "X", 10000).original.name == "X_10000.jpg"


def test_next_index_reads_existing_five_digit_numbers(tmp_path: Path) -> None:
    touch(tmp_path, "X_10003_a.jpg", "X_0004.jpg")

    assert next_index(tmp_path, "X") == 10004


def test_next_index_counts_the_known_shapes_in_any_extension_and_letter_case(
    tmp_path: Path,
) -> None:
    touch(tmp_path, "X_0050.tif", "X_0060.JPG", "X_0065_c.png")

    assert next_index(tmp_path, "X") == 66


def test_next_index_ignores_names_that_only_start_like_a_numbered_file(tmp_path: Path) -> None:
    touch(tmp_path, "X_0070-copy.jpg", "X_0071 (1).jpg", "X_0072_ab.jpg", "X_0073", "X_0074.")

    assert next_index(tmp_path, "X") == 1


def test_next_index_does_not_mistake_a_number_inside_the_prefix_for_an_index(
    tmp_path: Path,
) -> None:
    touch(tmp_path, "Trip_2020_0003.jpg", "Trip_2020_0003_a.jpg")

    assert next_index(tmp_path, "Trip") == 1
    assert next_index(tmp_path, "Trip_2020") == 4


def test_next_index_ignores_camera_style_names_with_a_time_part(tmp_path: Path) -> None:
    touch(tmp_path, "IMG_20200101_123456.jpg")

    assert next_index(tmp_path, "IMG") == 1


def test_next_index_accepts_up_to_the_largest_usable_index(tmp_path: Path) -> None:
    touch(tmp_path, f"X_{MAX_INDEX - 1}.jpg", "X_1234567890.jpg")

    assert next_index(tmp_path, "X") == MAX_INDEX
    assert photo_paths(tmp_path, "X", MAX_INDEX).original.name == f"X_{MAX_INDEX}.jpg"


def test_next_index_ignores_a_stray_number_that_leaves_no_room_above_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    touch(tmp_path, f"X_{MAX_INDEX}.jpg", "X_0004.jpg")

    with caplog.at_level(logging.WARNING):
        assert next_index(tmp_path, "X") == 5

    assert any(f"X_{MAX_INDEX}.jpg" in record.getMessage() for record in caplog.records)


def test_next_index_skips_directories(tmp_path: Path) -> None:
    (tmp_path / "X_0099.jpg").mkdir()
    (tmp_path / "X_0098").mkdir()
    touch(tmp_path, "X_0005.jpg")

    assert next_index(tmp_path, "X") == 6


def test_next_index_ignores_case_when_matching_the_prefix(tmp_path: Path) -> None:
    touch(tmp_path, "beach_0005.jpg")

    assert next_index(tmp_path, "Beach") == 6
    assert next_index(tmp_path, "BEACH") == 6


def test_next_index_ignores_unicode_normalisation_when_matching_the_prefix(
    tmp_path: Path,
) -> None:
    touch(tmp_path, "Cafe\u0301_0003.jpg")

    assert next_index(tmp_path, "Caf\u00e9") == 4


def test_next_index_ignores_other_prefixes_and_malformed_names(tmp_path: Path) -> None:
    touch(
        tmp_path,
        "Y_0050.jpg",
        "XX_0060.jpg",
        "X_Y_0070.jpg",
        "X_12.jpg",
        "X_abcd.jpg",
        "notes.txt",
        ".X_0090.jpg.abcd.tmp",
    )

    assert next_index(tmp_path, "X") == 1


def test_next_index_treats_prefix_characters_literally(tmp_path: Path) -> None:
    touch(tmp_path, "a-b_0003.jpg", "aXb_0009.jpg")

    assert next_index(tmp_path, "a-b") == 4


def test_next_index_matches_a_prefix_with_punctuation_exactly(tmp_path: Path) -> None:
    touch(tmp_path, "Mom & Dad (1970s)_0012_a.jpg", "Mom & Dad (1970s)_0012_b.jpg")
    touch(tmp_path, "Mom & Dad X1970sX_0099.jpg", "Mom + Dad (1970s)_0050.jpg")

    assert next_index(tmp_path, "Mom & Dad (1970s)") == 13


def test_photo_paths_follow_the_fastfoto_convention(tmp_path: Path) -> None:
    paths = photo_paths(tmp_path, "Trip", 7)

    assert paths.original == tmp_path / "Trip_0007.jpg"
    assert paths.enhanced == tmp_path / "Trip_0007_a.jpg"
    assert paths.back == tmp_path / "Trip_0007_b.jpg"


@pytest.mark.parametrize("index", [0, -1])
def test_photo_paths_reject_non_positive_indexes(tmp_path: Path, index: int) -> None:
    with pytest.raises(ValueError, match="index"):
        photo_paths(tmp_path, "X", index)


def test_photo_paths_reject_indexes_wider_than_the_name_length_reserve(tmp_path: Path) -> None:
    assert photo_paths(tmp_path, "X", 10**MAX_INDEX_DIGITS - 1).original.name.startswith("X_9")
    with pytest.raises(ValueError, match="index"):
        photo_paths(tmp_path, "X", 10**MAX_INDEX_DIGITS)
