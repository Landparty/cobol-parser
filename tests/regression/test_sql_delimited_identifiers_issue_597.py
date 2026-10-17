"""Regression tests for issue #597: DB2 delimited identifiers in EXEC SQL.

In DB2 SQL under APOSTSQL (the default), ``"CUST"`` is a delimited identifier
-- a table, schema or column name -- not a string. The EXEC SQL text
collector re-delimited every literal with ``'``, and the literal scrubber
blanked both quote kinds, so ``FROM "PROD"."CUST"`` reached the table scans
as ``FROM  .`` and the statement reported no tables: the CRUD matrix (and
everything else reading ``ExecSQLStatement.tables``) silently lost the table.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.crud_matrix import CRUDMatrixGenerator
from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.models.sql_statements import (
    ExecSQLStatement,
    _strip_sql_literals_and_comments,
)


def _program(sql: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 X PIC X.\n"
        "       PROCEDURE DIVISION.\n"
        f"           EXEC SQL {sql}\n"
        "           END-EXEC.\n"
        "           STOP RUN.\n"
    )


def _parse(sql: str):
    result = parse_cobol(_program(sql))
    assert result.errors == []
    statements = [
        s for s in result.ast.get_all_statements() if isinstance(s, ExecSQLStatement)
    ]
    assert len(statements) == 1
    return result.ast, statements[0]


@pytest.mark.parametrize(
    "sql, tables, crud",
    [
        ('SELECT X INTO :X FROM "PROD"."CUST"', ["PROD.CUST"], "-R--"),
        ('UPDATE "CUST" SET X = 1', ["CUST"], "--U-"),
        ('INSERT INTO "HIST" (ID) VALUES (1)', ["HIST"], "C---"),
        ('DELETE FROM "CUST" WHERE ID = 1', ["CUST"], "---D"),
    ],
)
def test_delimited_table_names_reach_tables_and_crud(sql, tables, crud):
    ast, stmt = _parse(sql)
    assert stmt.tables == tables
    matrix = CRUDMatrixGenerator().analyze(ast)
    assert {e.table_name: e.crud.as_string() for e in matrix.table_entries} == {
        tables[0]: crud
    }


def test_delimited_and_undelimited_forms_agree():
    _, quoted = _parse('SELECT X INTO :X FROM "PROD"."CUST" C JOIN "ORD" O ON 1=1')
    _, plain = _parse("SELECT X INTO :X FROM PROD.CUST C JOIN ORD O ON 1=1")
    assert quoted.tables == plain.tables == ["PROD.CUST", "ORD"]


def test_sql_text_keeps_the_double_quote_delimiter():
    _, stmt = _parse('DELETE FROM "CUST" WHERE ID = 1')
    assert stmt.sql_text == 'DELETE FROM "CUST" WHERE ID = 1'


def test_apostrophe_string_literal_is_still_not_a_table():
    _, stmt = _parse("SELECT X INTO :X FROM T WHERE N = 'FROM T9'")
    assert stmt.tables == ["T"]


def test_scrubber_unquotes_identifiers_and_blanks_strings():
    scrubbed = _strip_sql_literals_and_comments(
        "SELECT \"A\"\"B\" FROM \"PROD\".\"CUST\" WHERE N = ':H' AND M = \"X Y\""
    )
    assert "PROD.CUST" in scrubbed
    assert ":H" not in scrubbed
    # Not identifier-shaped once unescaped: still blanked, never a name.
    assert "X Y" not in scrubbed
    assert 'A"B' not in scrubbed


def test_lexer_records_the_literal_delimiter():
    tokens = CobolLexer("       MOVE \"A\" TO B. MOVE 'C' TO D.\n").tokenize()
    literals = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
    assert [(t.value, t.quote) for t in literals] == [("A", '"'), ("C", "'")]
