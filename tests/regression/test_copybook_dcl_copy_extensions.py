"""COPY and EXEC SQL INCLUDE find ``.copy`` and ``.dcl`` members.

CardDemo keeps its DCLGEN members as ``dcl/DCLTRTYP.dcl``; with that folder
on the copybook path, ``EXEC SQL INCLUDE DCLTRTYP`` still did not resolve,
because the default extension list stopped at ``.cpy/.cbl/.cob``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.parser import parse_cobol_with_expansion
from cobolparser.preprocess.models import CopybookSearchPath
from cobolparser.preprocess.path_resolver import find_copybook_file

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXTS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE DCLTAB END-EXEC.
       COPY CUSTREC.
       PROCEDURE DIVISION.
           MOVE 1 TO TAB-ID.
           MOVE 2 TO CUST-ID.
           GOBACK.
"""


@pytest.mark.parametrize("suffix", [".dcl", ".DCL", ".copy", ".COPY"])
def test_find_copybook_file_tries_the_suffix(tmp_path: Path, suffix: str) -> None:
    member = tmp_path / f"CUSTREC{suffix}"
    member.write_text("       01 CUST-ID PIC 9.\n")
    found = find_copybook_file("CUSTREC", CopybookSearchPath([str(tmp_path)]))
    assert Path(found).name == member.name


def test_cpy_still_wins_over_the_new_suffixes(tmp_path: Path) -> None:
    (tmp_path / "CUSTREC.dcl").write_text("       01 OTHER PIC 9.\n")
    (tmp_path / "CUSTREC.cpy").write_text("       01 CUST-ID PIC 9.\n")
    found = find_copybook_file("CUSTREC", CopybookSearchPath([str(tmp_path)]))
    assert Path(found).name == "CUSTREC.cpy"


def test_include_and_copy_expand_from_dcl_and_copy_files(tmp_path: Path) -> None:
    (tmp_path / "DCLTAB.dcl").write_text(
        "       01 DCLTAB.\n           10 TAB-ID PIC 9.\n"
    )
    (tmp_path / "CUSTREC.copy").write_text("       01 CUST-ID PIC 9.\n")
    result = parse_cobol_with_expansion(
        PROGRAM, filename="exts.cbl", copybook_paths=[str(tmp_path)]
    )
    assert result.success, result.errors
    names = {i.name for i in result.ast.find_all_by_type("CobolDataItem")}
    assert {"TAB-ID", "CUST-ID"} <= names
