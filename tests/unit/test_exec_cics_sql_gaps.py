"""Regression tests for two EXEC statement gaps:

1. ``EXEC CICS`` with the command verb on the line *after* ``EXEC CICS``
   (the idiomatic layout, and the example used in
   ``ExecCicsStatementParser``'s own docstring) used to leave
   ``cics_command`` as the stray newline token instead of the real verb,
   and misfiled the verb as a bogus ``options`` key.

2. ``collect_exec_sql_text`` rejoining a lexer-split two-character
   relational operator (``>=``, ``<=``, ``<>`` all lex as two single-char
   tokens) with a spurious inserted space, e.g. ``SALARY >= :WS-ID``
   reconstructing as ``SALARY > =:WS-ID``. This helper backs EXEC SQL,
   EXEC CICS, and EXEC IMS/DLI text collection, so all three are covered.
"""

from cobolparser import parse_cobol


def _first_statement_of_type(ast, type_name):
    """Depth-first search for the first AST node whose class name matches."""
    stack = [ast]
    while stack:
        node = stack.pop()
        if type(node).__name__ == type_name:
            return node
        stack.extend(getattr(node, "children", []))
    return None


class TestExecCicsCommandOnNextLine:
    """Bug 1: EXEC CICS command verb on the line after EXEC CICS."""

    def test_receive_command_on_next_line(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  CICS-BUFFER PIC X(80).
       PROCEDURE DIVISION.
           EXEC CICS
               RECEIVE INTO(CICS-BUFFER)
           END-EXEC.
           STOP RUN.
        """)
        assert result.success
        assert result.errors == []
        node = _first_statement_of_type(result.ast, "ExecCicsStatement")
        assert node is not None
        assert node.cics_command == "RECEIVE"
        assert node.options == {"INTO": "CICS-BUFFER"}
        # The verb must not be misfiled as a bogus options key.
        assert "RECEIVE" not in node.options

    def test_read_dataset_command_on_next_line(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC PIC X(80).
       01  WS-KEY PIC X(10).
       PROCEDURE DIVISION.
           EXEC CICS
               READ DATASET('FILEA') INTO(WS-REC) RIDFLD(WS-KEY)
           END-EXEC.
           STOP RUN.
        """)
        assert result.success
        assert result.errors == []
        node = _first_statement_of_type(result.ast, "ExecCicsStatement")
        assert node is not None
        assert node.cics_command == "READ"
        assert node.options == {
            "DATASET": "FILEA",
            "INTO": "WS-REC",
            "RIDFLD": "WS-KEY",
        }
        assert "READ" not in node.options

    def test_command_on_same_line_still_works(self):
        """Non-regression: the command-on-same-line layout keeps working."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSTEST.
       PROCEDURE DIVISION.
           EXEC CICS RETURN
           END-EXEC.
           STOP RUN.
        """)
        assert result.success
        node = _first_statement_of_type(result.ast, "ExecCicsStatement")
        assert node is not None
        assert node.cics_command == "RETURN"


class TestExecSqlSplitRelationalOperators:
    """Bug 2: >=, <=, <> reconstructed with a spurious inserted space."""

    def _sql_text(self, where_clause):
        result = parse_cobol(f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ID PIC 9(5).
       PROCEDURE DIVISION.
           EXEC SQL
               SELECT * FROM T WHERE SALARY {where_clause} :WS-ID
           END-EXEC.
           STOP RUN.
        """)
        assert result.success
        assert result.errors == []
        node = _first_statement_of_type(result.ast, "ExecSQLStatement")
        assert node is not None
        return node.sql_text

    def test_greater_or_equal(self):
        text = self._sql_text(">=")
        assert ">=:WS-ID" in text
        assert "> =" not in text

    def test_less_or_equal(self):
        text = self._sql_text("<=")
        assert "<=:WS-ID" in text
        assert "< =" not in text

    def test_not_equal(self):
        text = self._sql_text("<>")
        assert "<>:WS-ID" in text
        assert "< >" not in text

    def test_unrelated_greater_and_equal_not_fused(self):
        """A `>` and a later, unrelated `=` must not be joined together."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLTEST.
       PROCEDURE DIVISION.
           EXEC SQL
               SELECT * FROM T WHERE A > 5 AND B = 3
           END-EXEC.
           STOP RUN.
        """)
        assert result.success
        node = _first_statement_of_type(result.ast, "ExecSQLStatement")
        assert node is not None
        assert node.sql_text == "SELECT * FROM T WHERE A > 5 AND B = 3"


class TestExecImsDliSplitRelationalOperators:
    """Bug 2 also corrupts EXEC DLI SSA text, which shares the same helper."""

    def test_ssa_qualifier_greater_or_equal(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSTEST.
       PROCEDURE DIVISION.
           EXEC DLI
               GU SEGMENT(EMPLOYEE) WHERE(FIELDA >= VALUEA)
           END-EXEC.
           STOP RUN.
        """)
        assert result.success
        assert result.errors == []
        node = _first_statement_of_type(result.ast, "ExecImsStatement")
        assert node is not None
        assert node.ims_command == "GU"
        assert "FIELDA >= VALUEA" in node.ims_text
        assert "FIELDA > = VALUEA" not in node.ims_text
        assert "WHERE(FIELDA >= VALUEA)" in node.arguments
