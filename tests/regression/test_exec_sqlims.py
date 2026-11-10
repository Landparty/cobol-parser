"""``EXEC SQLIMS ... END-EXEC`` (the IMS SQL interface) is an EXEC SQL block.

It used to match no EXEC parser: the block was dropped with a warning and an
inner ``OPEN cursor`` was parsed as a file OPEN statement (open-source corpus
finding, proleap ``ExecSqlIms.cbl``).
"""

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.sql_statements import ExecSQLStatement

SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQLIMS INCLUDE SQLIMSCA END-EXEC.
       01 A PIC X.
       PROCEDURE DIVISION.
           EXEC SQLIMS
             DECLARE C1 CURSOR FOR S1
           END-EXEC.
           EXEC SQLIMS OPEN C1 END-EXEC.
           EXEC
             SQLIMS FETCH C1 INTO :A
           END-EXEC
           EXEC SQL CLOSE C2 END-EXEC
           DISPLAY A
           STOP RUN.
"""


def _parse():
    result = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(SRC)
    assert result.ast is not None
    assert not result.errors and not result.warnings, (
        result.errors,
        result.warnings,
    )
    return result


def test_sqlims_blocks_parse_as_exec_sql():
    stmts = _parse().ast.get_all_statements()
    assert [type(s).__name__ for s in stmts] == [
        "DeclareCursorStatement",
        "ExecSQLStatement",
        "FetchStatement",
        "ExecSQLStatement",
        "DisplayStatement",
        "StopStatement",
    ]
    assert not _parse().ast.find_all_by_type("IOOpenStatement")


def test_interface_is_recorded():
    stmts = [
        s for s in _parse().ast.get_all_statements() if isinstance(s, ExecSQLStatement)
    ]
    assert [s.get_metadata("interface") for s in stmts] == [
        "SQLIMS",
        "SQLIMS",
        "SQLIMS",
        None,
    ]
    assert stmts[1].sql_type == "OPEN"
    assert stmts[2].into_variables == ["A"]


def test_sqlims_include_in_data_division():
    data = _parse().ast.get_division("DATA")
    blocks = data.find_all_by_type("ExecSQLStatement") + data.find_all_by_type(
        "IncludeStatement"
    )
    assert any(b.get_metadata("interface") == "SQLIMS" for b in blocks)
    assert [i.name for i in data.find_all_by_type("CobolDataItem")] == ["A"]
