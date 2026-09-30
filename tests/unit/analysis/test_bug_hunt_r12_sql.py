"""Bug hunt round 12: SQL / DB2 handling.

Each test reproduces one defect through the public API and pins the fix.
"""

from __future__ import annotations

from cobolparser import CRUDMatrixGenerator, DclgenChecker, IOLogger, parse_cobol
from cobolparser.analysis import HostVariableResolver
from cobolparser.analysis.sql_cics_lint import (
    KIND_NO_SQLCODE_CHECK,
    KIND_SELECT_WITHOUT_INTO,
    SqlCicsAnalyzer,
)
from cobolparser.analysis.xref import ROLE_REFERENCE, ROLE_WRITE, XrefAnalyzer
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.sql_statements import (
    DeclareTableStatement,
    ExecSQLStatement,
    db2_type_to_cobol_pic,
    db2_type_to_cobol_usage,
    parse_exec_sql,
)


def _program(ws: str, proc: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. R12SQL.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{ws}\n"
        "       PROCEDURE DIVISION.\n"
        f"{proc}\n"
        "           GOBACK.\n"
    )


def _parse(ws: str, proc: str):  # type: ignore[no-untyped-def]
    result = parse_cobol(_program(ws, proc))
    assert not result.errors, result.errors
    return result.ast


def _sql(text: str) -> ExecSQLStatement:
    return parse_exec_sql(text, SourceLocation(1, 1))


def _columns(ast):  # type: ignore[no-untyped-def]
    return {
        column.name: column
        for stmt in ast.get_all_statements()
        if isinstance(stmt, DeclareTableStatement)
        for column in stmt.columns
    }


def _crud(ast) -> dict[str, str]:  # type: ignore[no-untyped-def]
    matrix = CRUDMatrixGenerator().analyze(ast)
    rows = matrix.to_csv().splitlines()[1:]
    return {row.split(",")[2]: row.split(",")[7] for row in rows if row}


# ---------------------------------------------------------------------------
# DB2 FLOAT precision
# ---------------------------------------------------------------------------


def test_bare_float_is_double_precision() -> None:
    assert db2_type_to_cobol_usage("FLOAT") == "COMP-2"
    assert db2_type_to_cobol_usage("FLOAT", 21) == "COMP-1"
    assert db2_type_to_cobol_usage("FLOAT", 22) == "COMP-2"
    assert db2_type_to_cobol_usage("REAL") == "COMP-1"
    assert db2_type_to_cobol_pic("FLOAT", precision=10) == "COMP-1"


def test_declare_table_float_precision_decides_usage() -> None:
    ast = _parse(
        "       01 FA COMP-2.\n       01 FB COMP-1.\n       01 FC COMP-2.",
        "           EXEC SQL DECLARE T1 TABLE\n"
        "             ( FA FLOAT NOT NULL,\n"
        "               FB FLOAT(21) NOT NULL,\n"
        "               FC FLOAT(53) NOT NULL ) END-EXEC.\n"
        "           EXEC SQL SELECT FA, FB, FC INTO :FA, :FB, :FC\n"
        "             FROM T1 END-EXEC.",
    )
    columns = _columns(ast)
    assert columns["FA"].cobol_usage == "COMP-2"
    assert columns["FB"].cobol_usage == "COMP-1"
    assert columns["FC"].cobol_usage == "COMP-2"
    report = DclgenChecker().check(ast)
    assert sorted(report.checked) == ["FA", "FB", "FC"]
    assert report.violations == []


# ---------------------------------------------------------------------------
# DB2 TIMESTAMP(p) / bare DECIMAL
# ---------------------------------------------------------------------------


def test_timestamp_precision_is_not_a_length() -> None:
    ast = _parse(
        "       01 TS-A PIC X(26).\n       01 TS-B PIC X(26).",
        "           EXEC SQL DECLARE T1 TABLE\n"
        "             ( TS_A TIMESTAMP(6) NOT NULL,\n"
        "               TS_B TIMESTAMP(12) NOT NULL ) END-EXEC.\n"
        "           EXEC SQL SELECT TS_A, TS_B INTO :TS-A, :TS-B\n"
        "             FROM T1 END-EXEC.",
    )
    columns = _columns(ast)
    assert columns["TS_A"].length == 26
    assert columns["TS_B"].cobol_picture == "X(32)"
    report = DclgenChecker().check(ast)
    # TS-A matches exactly; TS-B is 6 characters short and truncates.
    assert [(v.host_variable, v.kind, v.severity) for v in report.violations] == [
        ("TS-B", "length", "error")
    ]


def test_bare_decimal_is_decimal_5_0() -> None:
    assert db2_type_to_cobol_pic("DECIMAL") == "S9(5)"
    ast = _parse(
        "       01 AMT PIC S9(5) COMP-3.",
        "           EXEC SQL DECLARE T1 TABLE\n"
        "             ( AMT DECIMAL NOT NULL ) END-EXEC.\n"
        "           EXEC SQL SELECT AMT INTO :AMT FROM T1 END-EXEC.",
    )
    report = DclgenChecker().check(ast)
    assert report.checked == ["AMT"]
    assert report.violations == []


# ---------------------------------------------------------------------------
# Table extraction: data-change-table-references, DELETE without FROM, ...
# ---------------------------------------------------------------------------


def test_final_table_records_the_inserted_table() -> None:
    stmt = _sql("SELECT ID INTO :W-ID FROM FINAL TABLE (INSERT INTO T8 (A) VALUES (1))")
    assert stmt.tables == ["T8"]
    assert stmt.data_change_tables == [("INSERT", "T8")]
    old = _sql("SELECT C1 FROM OLD TABLE (DELETE FROM S.T9 WHERE A = 1)")
    assert "OLD" not in old.tables and "S.T9" in old.tables
    assert old.data_change_tables == [("DELETE", "S.T9")]
    # The nested INSERT's own source table is still read.
    cursor = _sql(
        "DECLARE C1 CURSOR FOR SELECT C1 FROM FINAL TABLE "
        "(INSERT INTO T5 SELECT * FROM T6)"
    )
    assert sorted(cursor.tables) == ["T5", "T6"]


def test_delete_without_from_records_its_target_first() -> None:
    assert _sql("DELETE T11 WHERE A = 1").tables == ["T11"]
    stmt = _sql("DELETE T11 WHERE A IN (SELECT A FROM T2)")
    assert stmt.tables == ["T11", "T2"]


def test_crud_matrix_for_final_table_and_delete_without_from() -> None:
    ast = _parse(
        "       01 W-ID PIC S9(9) COMP.",
        "           EXEC SQL SELECT ID INTO :W-ID\n"
        "             FROM FINAL TABLE (INSERT INTO T8 (A) VALUES (1))\n"
        "           END-EXEC.\n"
        "           EXEC SQL DELETE T11 WHERE A IN\n"
        "             (SELECT A FROM T2) END-EXEC.",
    )
    crud = _crud(ast)
    assert "FINAL" not in crud
    assert "C" in crud["T8"]
    assert crud["T11"] == "---D"
    assert crud["T2"] == "-R--"


def test_scroll_cursor_name_is_read() -> None:
    stmt = _sql(
        "DECLARE C2 SENSITIVE STATIC SCROLL CURSOR WITH HOLD FOR " "SELECT A FROM T1"
    )
    assert stmt.cursor_name == "C2"
    assert _sql("DECLARE C3 NO SCROLL CURSOR FOR SELECT A FROM T1").cursor_name == (
        "C3"
    )


def test_scroll_cursor_fetch_reaches_crud_matrix() -> None:
    ast = _parse(
        "       01 W-A PIC X(8).",
        "           EXEC SQL DECLARE C2 INSENSITIVE SCROLL CURSOR FOR\n"
        "             SELECT A FROM T1 END-EXEC.\n"
        "           EXEC SQL FETCH C2 INTO :W-A END-EXEC.",
    )
    matrix = CRUDMatrixGenerator().analyze(ast)
    [entry] = [e for e in matrix.table_entries if e.table_name == "T1"]
    assert entry.cursors == ["C2"]


def test_cursor_cte_name_is_not_a_table() -> None:
    stmt = _sql("DECLARE C1 CURSOR FOR WITH X AS (SELECT A FROM T1) SELECT A FROM X")
    assert stmt.tables == ["T1"]


def test_table_function_and_lateral_are_not_tables() -> None:
    assert _sql("SELECT A INTO :X FROM TABLE(F(1)) AS Q").tables == []
    assert _sql("SELECT A INTO :X FROM LATERAL (SELECT B FROM T9) AS Q").tables == [
        "T9"
    ]


def test_bracketed_sql_comment_is_dropped() -> None:
    ast = _parse(
        "       01 WS-X PIC X(8).",
        "           EXEC SQL SELECT A INTO :WS-X\n"
        "             FROM T4 /* :CMT FROM T5 */ END-EXEC.\n"
        "           EXEC SQL SELECT A INTO :WS-X FROM T6 /* multi\n"
        "             line :CMT2 */ WHERE B = 1 END-EXEC.",
    )
    stmts = [s for s in ast.get_all_statements() if isinstance(s, ExecSQLStatement)]
    assert [s.tables for s in stmts] == [["T4"], ["T6"]]
    assert [s.host_variables for s in stmts] == [["WS-X"], ["WS-X"]]
    assert stmts[1].where_present


# ---------------------------------------------------------------------------
# io_logger: SET :hv = ... writes the host variable
# ---------------------------------------------------------------------------


def test_sql_set_assignment_target_is_output() -> None:
    ast = _parse(
        "       01 WS-X PIC X(26).\n       01 WS-Y PIC X(26).",
        "           EXEC SQL SET :WS-X = CURRENT TIMESTAMP END-EXEC.\n"
        "           EXEC SQL SET :WS-Y = :WS-X END-EXEC.",
    )
    ops = IOLogger().analyze(ast).sql_operations
    by_line = {}
    for op in ops:
        by_line.setdefault(op.line, []).append((op.direction, op.variables))
    assert sorted(by_line.values()) == [
        [("OUTPUT", ["WS-X"])],
        [("OUTPUT", ["WS-Y"]), ("INPUT", ["WS-X"])],
    ]


# ---------------------------------------------------------------------------
# host_var_resolver: :STRUCT.NAME binds to the NAME under STRUCT
# ---------------------------------------------------------------------------


def test_qualified_host_variable_binds_to_its_structure() -> None:
    ast = _parse(
        "       01 WS-OLD.\n"
        "          05 SALARY PIC X(10).\n"
        "       01 DCLEMP.\n"
        "          05 SALARY PIC S9(7)V99 COMP-3.",
        "           EXEC SQL SELECT SALARY INTO :DCLEMP.SALARY\n"
        "             FROM EMP END-EXEC.",
    )
    info = HostVariableResolver().resolve(ast).resolved["SALARY"]
    assert info.picture == "S9(7)V99"
    assert info.usage == "COMP-3"


# ---------------------------------------------------------------------------
# xref: an OF/IN qualifier of a receiving operand is not written
# ---------------------------------------------------------------------------


def test_xref_qualifier_of_receiving_operand_is_not_a_write() -> None:
    ast = _parse(
        "       01 WS-GRP.\n"
        "          05 WS-PROG PIC X(8).\n"
        "       01 WS-X PIC X(8).",
        "           MOVE WS-X TO WS-PROG OF WS-GRP\n"
        "           MOVE 'A' TO WS-PROG IN WS-GRP.",
    )
    report = XrefAnalyzer().analyze(ast)
    entries = {entry.name: entry for entry in report.entries}
    assert [r.role for r in entries["WS-PROG"].references] == [ROLE_WRITE] * 2
    assert [r.role for r in entries["WS-GRP"].references] == [ROLE_REFERENCE] * 2


# ---------------------------------------------------------------------------
# sql_cics_lint
# ---------------------------------------------------------------------------


def test_select_without_into_is_not_hidden_by_a_literal() -> None:
    ast = _parse(
        "       01 WS-X PIC X(8).",
        "           EXEC SQL SELECT A FROM T1 WHERE B = 'INTO :Z' END-EXEC\n"
        "           IF SQLCODE = 0 CONTINUE END-IF.",
    )
    report = SqlCicsAnalyzer().analyze(ast)
    assert [v.kind for v in report.violations] == [KIND_SELECT_WITHOUT_INTO]


def test_unknown_statement_label_is_its_first_word() -> None:
    ast = _parse(
        "       01 WS-X PIC X(8).",
        "           EXEC SQL SET :WS-X = CURRENT DATE END-EXEC.",
    )
    [violation] = SqlCicsAnalyzer().analyze(ast).violations
    assert violation.kind == KIND_NO_SQLCODE_CHECK
    assert violation.symbol == "SET"
