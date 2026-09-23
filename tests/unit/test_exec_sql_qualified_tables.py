"""Regression tests: schema-qualified DB2 table names in EXEC SQL.

``INSERT INTO BANK.REGULATORY_RPT`` used to report *two* tables, ``BANK`` and
``BANK.REGULATORY_RPT``: ``collect_exec_sql_text`` rebuilt the text as
``BANK. REGULATORY_RPT`` (a space after the qualifier period), and the
FROM/INTO/UPDATE/JOIN regexes stopped at the first ``.``. Every program that
touched a qualified table also appeared to use a table named after its schema.
"""

import pytest

from cobolparser import parse_cobol


def _sql_statements(source):
    result = parse_cobol(source, filename="t.cbl")
    assert result.ast is not None, result.errors
    return [s for s in result.ast.get_all_statements() if hasattr(s, "tables")]


def _program(*sql_blocks):
    # Fixed format: source past column 72 is ignored, so long SQL is passed as
    # a tuple of lines.
    def lines(sql):
        return "\n".join(
            f"               {line}"
            for line in ([sql] if isinstance(sql, str) else sql)
        )

    body = "\n".join(
        f"           EXEC SQL\n{lines(sql)}\n           END-EXEC." for sql in sql_blocks
    )
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. QUALTEST.\n"
        "       PROCEDURE DIVISION.\n"
        f"{body}\n"
        "           GOBACK.\n"
    )


@pytest.mark.parametrize(
    ("sql", "table"),
    [
        ("INSERT INTO BANK.REGULATORY_RPT (A) VALUES (:HV-A)", "BANK.REGULATORY_RPT"),
        ("SELECT X INTO :HV-X FROM SYSIBM.SYSDUMMY1", "SYSIBM.SYSDUMMY1"),
        ("UPDATE BANK.ACCOUNT SET A = 1 WHERE B = 2", "BANK.ACCOUNT"),
        ("DELETE FROM BANK.LOAN WHERE A = :HV-A", "BANK.LOAN"),
        ("SELECT A INTO :HV-A FROM LOC1.BANK.ACCOUNT", "LOC1.BANK.ACCOUNT"),
    ],
)
def test_qualified_table_is_reported_once(sql, table):
    (stmt,) = _sql_statements(_program(sql))
    assert stmt.tables == [table]


def test_join_reports_both_qualified_tables_and_no_schema():
    (stmt,) = _sql_statements(
        _program(
            (
                "SELECT A.X INTO :HV-X FROM BANK.ACCOUNT A",
                "JOIN BANK.CUSTOMER C ON A.CIF = C.CIF",
            )
        )
    )
    assert sorted(stmt.tables) == ["BANK.ACCOUNT", "BANK.CUSTOMER"]


def test_sql_text_keeps_qualified_names_intact():
    (stmt,) = _sql_statements(
        _program("SELECT C.X, 1.5 INTO :HV-X FROM SYSIBM.SYSDUMMY1 C")
    )
    assert "SYSIBM.SYSDUMMY1" in stmt.sql_text
    assert "C.X" in stmt.sql_text
    assert "1.5" in stmt.sql_text


def test_space_after_a_period_in_the_source_is_preserved():
    (stmt,) = _sql_statements(_program("SELECT T. X INTO :HV-X FROM T"))
    assert "T. X" in stmt.sql_text
