"""COPY text-names fold to uppercase, as in Enterprise COBOL (issue #289).

``copy errorcd.`` used to fail with ``Copybook 'errorcd' not found ... Did
you mean: ERRORCD?`` on a case-sensitive filesystem, because the member was
looked up exactly as written. z/OS folds the text-name to uppercase, so the
uppercased member is now probed first and the name as written after it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import expand_copybooks
from cobolparser.preprocess.models import CopybookSearchPath
from cobolparser.preprocess.path_resolver import PathResolver, find_copybook_file

PROGRAM = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. T.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       copy errorcd.\n"
    "       PROCEDURE DIVISION.\n"
    "           STOP RUN.\n"
)


def _write(directory: Path, name: str, record: str) -> Path:
    directory.mkdir(exist_ok=True)
    path = directory / name
    path.write_text(f"       01  {record} PIC X(4).\n")
    return path


def _config(*dirs: Path) -> CopybookSearchPath:
    return CopybookSearchPath(directories=[str(d) for d in dirs], case_sensitive=True)


@pytest.mark.parametrize("member", ["errorcd", "ErrorCd", "ERRORCD"])
def test_any_spelling_finds_the_uppercase_member(tmp_path: Path, member: str) -> None:
    expected = str(_write(tmp_path / "copy", "ERRORCD.cpy", "ERR-CD"))
    config = _config(tmp_path / "copy")
    assert PathResolver(config).resolve(member) == expected
    assert find_copybook_file(member, config) == expected


def test_lowercase_copy_statement_expands(tmp_path: Path) -> None:
    _write(tmp_path / "copy", "ERRORCD.cpy", "ERR-CD")
    out = expand_copybooks(PROGRAM, copybook_paths=[str(tmp_path / "copy")])
    assert "ERR-CD" in out.expanded_source


def test_uppercase_member_wins_over_lowercase_file(tmp_path: Path) -> None:
    d = tmp_path / "copy"
    expected = str(_write(d, "ERRORCD.cpy", "UPPER-REC"))
    _write(d, "errorcd.cpy", "LOWER-REC")
    config = _config(d)
    assert PathResolver(config).resolve("errorcd") == expected
    assert find_copybook_file("errorcd", config) == expected


def test_lowercase_only_member_still_resolves(tmp_path: Path) -> None:
    expected = str(_write(tmp_path / "copy", "errorcd.cpy", "LOWER-REC"))
    config = _config(tmp_path / "copy")
    assert PathResolver(config).resolve("errorcd") == expected
    assert find_copybook_file("errorcd", config) == expected


def test_directory_order_still_decides_first(tmp_path: Path) -> None:
    # SYSLIB concatenation order outranks the case of the match: an
    # as-written member in the first directory beats an uppercase one later.
    first = tmp_path / "first"
    expected = str(_write(first, "errorcd.cpy", "FIRST-REC"))
    _write(tmp_path / "second", "ERRORCD.cpy", "SECOND-REC")
    config = _config(first, tmp_path / "second")
    assert PathResolver(config).resolve("errorcd") == expected
    assert find_copybook_file("errorcd", config) == expected


@pytest.mark.parametrize("library", ["mylib", "MYLIB"])
def test_library_name_folds_to_uppercase(tmp_path: Path, library: str) -> None:
    # A top-level ERRORCD.cpy must not shadow MYLIB/ERRORCD.cpy just
    # because the program spelled the library in lowercase.
    root = tmp_path / "copy"
    _write(root, "ERRORCD.cpy", "TOP-REC")
    lib = root / "MYLIB"
    lib.mkdir()
    expected = str(_write(lib, "ERRORCD.cpy", "LIB-REC"))
    config = _config(root)
    assert PathResolver(config).resolve("errorcd", library) == expected
    assert find_copybook_file("errorcd", config, library) == expected


def test_lowercase_library_directory_still_resolves(tmp_path: Path) -> None:
    root = tmp_path / "copy"
    lib = root / "mylib"
    lib.mkdir(parents=True)
    expected = str(_write(lib, "ERRORCD.cpy", "LIB-REC"))
    assert find_copybook_file("errorcd", _config(root), "mylib") == expected


def test_extension_order_decides_before_case(tmp_path: Path) -> None:
    # .cpy comes before .cbl in the configured order, whatever the case:
    # folding must not pull the program source FOO.cbl in over Foo.cpy.
    d = tmp_path / "copy"
    _write(d, "FOO.cbl", "PROG-REC")
    expected = str(_write(d, "Foo.cpy", "COPY-REC"))
    config = _config(d)
    assert PathResolver(config).resolve("Foo") == expected
    assert find_copybook_file("Foo", config) == expected


def test_extensionless_upper_member_does_not_shadow_cpy(tmp_path: Path) -> None:
    d = tmp_path / "copy"
    _write(d, "FOO", "BARE-REC")
    expected = str(_write(d, "foo.cpy", "COPY-REC"))
    config = _config(d)
    assert PathResolver(config).resolve("foo") == expected
    assert find_copybook_file("foo", config) == expected


def test_name_as_written_with_extension_is_tried_first(tmp_path: Path) -> None:
    # A literal text-name that already names a file is used as written.
    d = tmp_path / "copy"
    expected = str(_write(d, "mem.cpy", "LOWER-REC"))
    _write(d, "MEM.CPY", "UPPER-REC")
    config = _config(d)
    assert PathResolver(config).resolve("mem.cpy") == expected
    assert find_copybook_file("mem.cpy", config) == expected


def test_case_insensitive_search_unchanged(tmp_path: Path) -> None:
    d = tmp_path / "copy"
    _write(d, "Errorcd.cpy", "ERR-CD")
    config = CopybookSearchPath(directories=[str(d)], case_sensitive=False)
    for member in ("errorcd", "ERRORCD"):
        assert PathResolver(config).resolve(member).lower().endswith("errorcd.cpy")
        assert find_copybook_file(member, config).lower().endswith("errorcd.cpy")
