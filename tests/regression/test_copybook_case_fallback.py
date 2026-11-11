"""``COPY LGCMAREA`` finds ``lgcmarea.cpy`` on a case-sensitive filesystem.

IBM's sample repositories (cics-genapp, dbb, dbb-zappbuild) keep members in
lower case while the programs COPY them in upper case. Windows and macOS
resolved that; Linux and CI did not, so 36 corpus programs failed every
analyzer there and field-impact on GenApp reported 2 programs instead of 21.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.parser import parse_cobol_with_expansion
from cobolparser.preprocess import CopybookNotFoundError
from cobolparser.preprocess.models import CopybookSearchPath
from cobolparser.preprocess.path_resolver import PathResolver, find_copybook_file

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CASEFB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY LGCMAREA.
           EXEC SQL INCLUDE LGPOLICY END-EXEC.
       PROCEDURE DIVISION.
           MOVE 1 TO CA-NUM.
           MOVE 2 TO POL-NUM.
           GOBACK.
"""


def _sensitive(tmp_path: Path, **kw: object) -> CopybookSearchPath:
    return CopybookSearchPath(directories=[str(tmp_path)], case_sensitive=True, **kw)  # type: ignore[arg-type]


def test_a_lower_case_file_resolves_an_upper_case_member(tmp_path: Path) -> None:
    (tmp_path / "lgcmarea.cpy").write_text("       01 CA-NUM PIC 9.\n")
    found = PathResolver(_sensitive(tmp_path)).resolve("LGCMAREA")
    assert Path(found).name == "lgcmarea.cpy"


def test_mixed_case_resolves_too(tmp_path: Path) -> None:
    (tmp_path / "LgCmArea.Cpy").write_text("       01 CA-NUM PIC 9.\n")
    assert Path(find_copybook_file("lgcmarea", _sensitive(tmp_path))).name == (
        "LgCmArea.Cpy"
    )


def test_an_exact_match_still_wins(tmp_path: Path) -> None:
    (tmp_path / "lgcmarea.cpy").write_text("       01 A PIC 9.\n")
    (tmp_path / "LGCMAREA.cpy").write_text("       01 B PIC 9.\n")
    found = find_copybook_file("LGCMAREA", _sensitive(tmp_path))
    assert Path(found).name == "LGCMAREA.cpy"


def test_an_exact_name_in_a_later_directory_beats_a_case_variant(
    tmp_path: Path,
) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    (first / "lgcmarea.cpy").write_text("       01 A PIC 9.\n")
    (second / "LGCMAREA.cpy").write_text("       01 B PIC 9.\n")
    config = CopybookSearchPath(
        directories=[str(first), str(second)], case_sensitive=True
    )
    # second/ holds the exact name, so the exact probe across every
    # directory wins before the fallback runs.
    assert Path(find_copybook_file("LGCMAREA", config)).parent == second


def test_a_path_literal_is_never_folded(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "rec.cpy").write_text("       01 A PIC 9.\n")
    with pytest.raises(CopybookNotFoundError):
        find_copybook_file("sub/REC.cpy", _sensitive(tmp_path))


def test_case_fallback_false_keeps_strict_matching(tmp_path: Path) -> None:
    (tmp_path / "lgcmarea.cpy").write_text("       01 CA-NUM PIC 9.\n")
    with pytest.raises(CopybookNotFoundError) as caught:
        find_copybook_file("LGCMAREA", _sensitive(tmp_path, case_fallback=False))
    assert caught.value.case_variant_exists


def test_copy_and_include_expand_end_to_end(tmp_path: Path) -> None:
    (tmp_path / "lgcmarea.cpy").write_text("       01 CA-NUM PIC 9.\n")
    (tmp_path / "lgpolicy.cpy").write_text("       01 POL-NUM PIC 9.\n")
    result = parse_cobol_with_expansion(
        PROGRAM, filename="casefb.cbl", copybook_paths=[str(tmp_path)]
    )
    assert result.success, result.errors
    names = {i.name for i in result.ast.find_all_by_type("CobolDataItem")}
    assert {"CA-NUM", "POL-NUM"} <= names


def test_among_case_variants_the_earlier_directory_wins(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    (first / "lgcmarea.cpy").write_text("       01 A PIC 9.\n")
    (second / "Lgcmarea.cpy").write_text("       01 B PIC 9.\n")
    config = CopybookSearchPath(
        directories=[str(first), str(second)], case_sensitive=True
    )
    assert Path(find_copybook_file("LGCMAREA", config)).parent == first
