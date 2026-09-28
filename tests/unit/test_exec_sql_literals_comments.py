"""Regression tests: string literals and ``--`` comments inside EXEC SQL.

The lexer hands a string literal over without its quotes, and has no token for
an SQL line comment (``--`` arrives as two MINUS tokens). ``collect_exec_sql_text``
used to join both back as plain words, so the literal/comment scrubber in the
SQL model never saw either:

* ``WHERE B = 'X:FAKE'`` reported ``FAKE`` as a host variable, and
  ``WHERE C = 'FROM T9'`` reported ``T9`` as a table;
* ``-- keep :WS-C`` reported ``WS-C`` as a host variable.
"""

from cobolparser import parse_cobol


def _sql(*lines):
    body = "\n".join(f"               {line}" for line in lines)
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. LITTEST.\n"
        "       PROCEDURE DIVISION.\n"
        "           EXEC SQL\n"
        f"{body}\n"
        "           END-EXEC.\n"
        "           GOBACK.\n"
    )
    result = parse_cobol(source, filename="t.cbl")
    assert result.ast is not None, result.errors
    (stmt,) = [s for s in result.ast.get_all_statements() if hasattr(s, "tables")]
    return stmt


def test_colon_inside_a_literal_is_not_a_host_variable():
    stmt = _sql("SELECT A INTO :WS-A FROM T1", "WHERE B = 'X:FAKE'")
    assert stmt.host_variables == ["WS-A"]
    assert "'X:FAKE'" in stmt.sql_text


def test_from_inside_a_literal_is_not_a_table():
    stmt = _sql("SELECT A INTO :WS-A FROM T1", "WHERE C = 'FROM T9'")
    assert stmt.tables == ["T1"]


def test_embedded_quote_is_doubled_back():
    stmt = _sql("SELECT A INTO :WS-A FROM T1", "WHERE C = 'IT''S:X'")
    assert "'IT''S:X'" in stmt.sql_text
    assert stmt.host_variables == ["WS-A"]


def test_hex_literal_keeps_its_prefix():
    stmt = _sql("SELECT A INTO :WS-A FROM T1", "WHERE C = X'C1'")
    assert "X'C1'" in stmt.sql_text


def test_line_comment_is_dropped():
    stmt = _sql(
        "SELECT A INTO :WS-A FROM T1",
        "WHERE B = :WS-B -- keep :WS-C FROM T9",
        "AND D = 1",
    )
    assert stmt.host_variables == ["WS-A", "WS-B"]
    assert stmt.tables == ["T1"]
    assert "keep" not in stmt.sql_text
    # The line after the comment is still part of the statement.
    assert "AND D = 1" in stmt.sql_text


def test_subtraction_of_a_negative_is_not_a_comment():
    stmt = _sql("SELECT A - -1 INTO :WS-A FROM T1 WHERE B = :WS-B")
    assert stmt.host_variables == ["WS-A", "WS-B"]
    assert stmt.tables == ["T1"]
