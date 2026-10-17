"""Regression tests for issue #538: EXEC CICS file control in the CRUD matrix.

Every CICS program reaches its VSAM data through ``EXEC CICS READ / WRITE /
REWRITE / DELETE / STARTBR / READNEXT / READPREV FILE(...)``. The CRUD
matrix looked only at native COBOL I/O and EXEC SQL, so such a program had
no file rows and MCP ``program_brief`` answered ``files: []`` with no
caveat.
"""

from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.crud_matrix import CRUDMatrixGenerator
from cobolparser.config import ProjectConfig
from cobolparser.mcp.tools import CobolTools
from cobolparser.mcp.workspace import Workspace

_ENTERPRISE = Path(__file__).parent.parent / "samples" / "enterprise"

_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ID PIC X(8).
       01 WS-FNAME PIC X(8) VALUE 'CUSTF'.
       PROCEDURE DIVISION.
"""


def _matrix(body: str):
    result = parse_cobol(_HEADER + body + "           GOBACK.\n")
    assert result.errors == []
    return CRUDMatrixGenerator().analyze(result.ast)


def _files(body: str) -> dict[str, str]:
    return {e.file_name: e.crud.as_string() for e in _matrix(body).file_entries}


def test_cicslink_sample_reads_and_updates_custmst():
    source = (_ENTERPRISE / "CICSLINK.cbl").read_text()
    matrix = CRUDMatrixGenerator().analyze(parse_cobol(source).ast)
    assert {e.file_name: e.crud.as_string() for e in matrix.file_entries} == {
        "CUSTMST": "-RU-"
    }
    assert matrix.caveats == []


@pytest.mark.parametrize(
    "command, crud",
    [
        ("READ FILE('CUSTF') INTO(WS-ID) RIDFLD(WS-ID)", "-R--"),
        ("STARTBR FILE('CUSTF') RIDFLD(WS-ID)", "-R--"),
        ("READNEXT FILE('CUSTF') INTO(WS-ID) RIDFLD(WS-ID)", "-R--"),
        ("READPREV FILE('CUSTF') INTO(WS-ID) RIDFLD(WS-ID)", "-R--"),
        ("WRITE FILE('CUSTF') FROM(WS-ID) RIDFLD(WS-ID)", "C---"),
        ("WRITE DATASET('CUSTF') FROM(WS-ID) RIDFLD(WS-ID)", "C---"),
        ("REWRITE FILE('CUSTF') FROM(WS-ID)", "--U-"),
        ("DELETE FILE('CUSTF') RIDFLD(WS-ID)", "---D"),
    ],
)
def test_each_file_command_marks_its_flag(command, crud):
    body = f"           EXEC CICS {command}\n           END-EXEC.\n"
    assert _files(body) == {"CUSTF": crud}


def test_commands_without_a_file_add_no_row():
    body = (
        "           EXEC CICS WRITEQ TS QUEUE('Q') FROM(WS-ID) END-EXEC.\n"
        "           EXEC CICS DELETEQ TS QUEUE('Q') END-EXEC.\n"
        "           EXEC CICS WRITE OPERATOR TEXT(WS-ID) END-EXEC.\n"
        "           EXEC CICS ENDBR FILE('CUSTF') END-EXEC.\n"
    )
    matrix = _matrix(body)
    assert matrix.file_entries == []
    assert matrix.caveats == []


def test_a_file_named_through_a_data_item_is_a_caveat():
    matrix = _matrix(
        "           EXEC CICS DELETE FILE(WS-FNAME) RIDFLD(WS-ID) END-EXEC.\n"
    )
    assert matrix.file_entries == []
    assert len(matrix.caveats) == 1
    assert "FILE(WS-FNAME)" in matrix.caveats[0]
    assert matrix.to_dict()["caveats"] == matrix.caveats


def test_mcp_program_brief_lists_cics_files_and_the_caveat(tmp_path: Path):
    (tmp_path / "CICSF.cbl").write_text(
        _HEADER
        + "           EXEC CICS READ FILE('CUSTF') INTO(WS-ID) RIDFLD(WS-ID)\n"
        + "           END-EXEC.\n"
        + "           EXEC CICS WRITE FILE(WS-FNAME) FROM(WS-ID) RIDFLD(WS-ID)\n"
        + "           END-EXEC.\n"
        + "           GOBACK.\n"
    )
    result = CobolTools(Workspace(tmp_path, ProjectConfig())).program_brief("CICSF.cbl")
    assert {"name": "CUSTF", "access": "-R--"} in result["answer"]["files"]
    assert any(
        c["kind"] == "incomplete-analysis" and "FILE(WS-FNAME)" in c["detail"]
        for c in result["caveats"]
    )
