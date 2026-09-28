"""Regression tests: FETCH cursor name / orientation for DB2 scroll and rowset forms.

The cursor used to be "the word after FETCH [NEXT] [FROM]", so
``FETCH NEXT ROWSET FROM C1`` named cursor ``ROWSET``, ``FETCH ABSOLUTE 5 FROM
C1`` named ``ABSOLUTE``, ``FETCH SENSITIVE ...`` named ``SENSITIVE`` and
``FETCH PRIOR FROM C1`` named none -- and the CRUD matrix, keyed by cursor,
lost the read. The orientation was a substring test, so ``FETCH C1 INTO
:WS-LAST-NAME`` was a FETCH LAST.
"""

import pytest

from cobolparser import CRUDMatrixGenerator, parse_cobol
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.sql_statements import FetchStatement, parse_exec_sql


@pytest.mark.parametrize(
    ("sql", "cursor", "direction", "rows"),
    [
        ("FETCH NEXT ROWSET FROM C1 FOR 10 ROWS INTO :WS-ARR", "C1", "NEXT", 10),
        ("FETCH PRIOR FROM C1 INTO :WS-A", "C1", "PRIOR", None),
        ("FETCH FIRST FROM C1 INTO :WS-A", "C1", "FIRST", None),
        ("FETCH ABSOLUTE -5 FROM C1 INTO :WS-A", "C1", "ABSOLUTE", None),
        ("FETCH RELATIVE :WS-N FROM C1 INTO :WS-A", "C1", "RELATIVE", None),
        ("FETCH SENSITIVE WITH CONTINUE NEXT FROM C1", "C1", "NEXT", None),
        ("FETCH ROWSET STARTING AT ABSOLUTE 3 FROM C1 FOR 5 ROWS", "C1", "ABSOLUTE", 5),
        ("FETCH C1 INTO :WS-LAST-NAME", "C1", "NEXT", None),
        ("FETCH C1 INTO :WS-PRIOR-KEY", "C1", "NEXT", None),
    ],
)
def test_cursor_orientation_and_rowset_size(sql, cursor, direction, rows):
    stmt = parse_exec_sql(sql, SourceLocation(1, 1))
    assert isinstance(stmt, FetchStatement)
    assert stmt.cursor_name == cursor
    assert stmt.fetch_direction == direction
    assert stmt.fetch_count == rows


def test_rowset_fetch_reads_the_cursor_table_in_the_crud_matrix():
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. ROWSETP.\n"
        "       PROCEDURE DIVISION.\n"
        "           EXEC SQL\n"
        "               DECLARE C1 CURSOR WITH ROWSET POSITIONING FOR\n"
        "               SELECT A FROM T1\n"
        "           END-EXEC.\n"
        "           EXEC SQL\n"
        "               FETCH NEXT ROWSET FROM C1 FOR 10 ROWS\n"
        "               INTO :WS-ARR\n"
        "           END-EXEC.\n"
        "           GOBACK.\n"
    )
    result = parse_cobol(source, filename="t.cbl")
    assert result.ast is not None, result.errors
    (fetch,) = [
        s for s in result.ast.get_all_statements() if isinstance(s, FetchStatement)
    ]
    assert fetch.cursor_name == "C1"
    matrix = CRUDMatrixGenerator().analyze(result.ast)
    (entry,) = [e for e in matrix.table_entries if e.table_name == "T1"]
    assert entry.crud.read
    assert entry.cursors == ["C1"]
