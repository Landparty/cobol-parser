"""Regression tests for issue #341: dialect and CRUD-matrix gaps.

``EXEC SQL TRUNCATE TABLE t`` parsed as ``UNKNOWN``, so the CRUD matrix
   gave the table no D (delete) mark.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.crud_matrix import CRUDMatrixGenerator
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.sql_statements import ExecSQLStatement, SQLStatementType

_LOC = SourceLocation(1, 1)


class TestTruncateTable:
    @pytest.mark.parametrize(
        ("sql", "table"),
        [
            ("TRUNCATE TABLE T15 IMMEDIATE", "T15"),
            ("TRUNCATE SCH.T16 REUSE STORAGE", "SCH.T16"),
        ],
    )
    def test_sql_type_and_table(self, sql, table):
        stmt = ExecSQLStatement(_LOC)
        stmt.set_sql_text(sql)
        assert stmt.sql_type == SQLStatementType.TRUNCATE
        assert stmt.tables == [table]

    def test_crud_matrix_marks_truncated_table_deleted(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRUNC.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL TRUNCATE TABLE T15 IMMEDIATE END-EXEC
           STOP RUN.
"""
        result = parse_cobol(source)
        assert result.ast is not None
        matrix = CRUDMatrixGenerator().analyze(result.ast)
        crud = {e.table_name: e.crud.as_string() for e in matrix.table_entries}
        assert crud == {"T15": "---D"}
