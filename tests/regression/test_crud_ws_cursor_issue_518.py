"""Regression tests for issue #518: a cursor DECLAREd in WORKING-STORAGE.

The DB2 precompiler accepts ``EXEC SQL DECLARE c CURSOR FOR SELECT ...``
in the DATA DIVISION, and many shops put it there. The CRUD matrix read
only ``get_all_statements()`` (PROCEDURE DIVISION), so the cursor's table
was missing from the matrix -- and from MCP ``program_brief``'s
``sql_tables`` -- and a FETCH from it marked nothing.
"""

from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.analysis.crud_matrix import CRUDMatrixGenerator
from cobolparser.config import ProjectConfig
from cobolparser.mcp.tools import CobolTools
from cobolparser.mcp.workspace import Workspace

_WS_CURSOR = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. WSCURS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL DECLARE C1 CURSOR FOR
               SELECT A FROM WSTAB WHERE B = 1
           END-EXEC.
           EXEC SQL DECLARE C2 CURSOR FOR
               SELECT A FROM UPTAB FOR UPDATE OF A
           END-EXEC.
       01 WS-A PIC X(10).
       PROCEDURE DIVISION.
           EXEC SQL OPEN C1 END-EXEC.
           EXEC SQL FETCH C1 INTO :WS-A END-EXEC.
           EXEC SQL UPDATE UPTAB SET A = 1 WHERE CURRENT OF C2 END-EXEC.
           STOP RUN.
"""

_NESTED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTER.
       PROCEDURE DIVISION.
           STOP RUN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL DECLARE C9 CURSOR FOR SELECT A FROM INTAB END-EXEC.
       PROCEDURE DIVISION.
           EXEC SQL OPEN C9 END-EXEC.
           GOBACK.
       END PROGRAM INNER.
       END PROGRAM OUTER.
"""


def _tables(source: str, unit: int | None = None) -> dict[str, tuple[str, list[str]]]:
    result = parse_cobol(source)
    assert result.errors == []
    ast = result.ast if unit is None else result.ast.contained_programs[unit]
    matrix = CRUDMatrixGenerator().analyze(ast)
    return {
        e.table_name: (e.crud.as_string(), list(e.cursors))
        for e in matrix.table_entries
    }


def test_working_storage_cursor_reaches_the_matrix():
    tables = _tables(_WS_CURSOR)
    assert tables["WSTAB"] == ("-R--", ["C1"])


def test_for_update_cursor_with_where_current_of():
    tables = _tables(_WS_CURSOR)
    assert tables["UPTAB"] == ("-RU-", ["C2"])


def test_same_as_a_procedure_division_cursor():
    moved = _WS_CURSOR.replace(
        """           EXEC SQL DECLARE C1 CURSOR FOR
               SELECT A FROM WSTAB WHERE B = 1
           END-EXEC.
""",
        "",
    ).replace(
        "           EXEC SQL OPEN C1 END-EXEC.\n",
        "           EXEC SQL DECLARE C1 CURSOR FOR\n"
        "               SELECT A FROM WSTAB WHERE B = 1\n"
        "           END-EXEC.\n"
        "           EXEC SQL OPEN C1 END-EXEC.\n",
    )
    assert _tables(moved)["WSTAB"] == _tables(_WS_CURSOR)["WSTAB"]


def test_a_contained_programs_cursor_stays_its_own():
    assert _tables(_NESTED) == {}
    assert _tables(_NESTED, unit=0) == {"INTAB": ("-R--", ["C9"])}


def test_mcp_program_brief_lists_the_table(tmp_path: Path):
    (tmp_path / "WSCURS.cbl").write_text(_WS_CURSOR)
    tools = CobolTools(Workspace(tmp_path, ProjectConfig()))
    answer = tools.program_brief("WSCURS.cbl")["answer"]
    assert {"name": "WSTAB", "access": "-R--", "cursors": ["C1"]} in answer[
        "sql_tables"
    ]
