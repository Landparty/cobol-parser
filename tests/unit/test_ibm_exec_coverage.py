"""Tests for IBM EXEC SQL and EXEC CICS statement parser coverage.

Targets uncovered branches in ibm_exec_statements.py:
  - ExecCicsStatementParser.matches (lines 107-129)
  - ExecCicsStatementParser.parse body with CICS content loop (lines 136-168)
  - ExecSqlStatementParser.matches with IDENTIFIER-based EXEC token
  - Host-variable colon-prefix path in SQL content (lines 81-88)
"""

from cobolparser import parse_cobol


def _prog(procedure_stmts: str) -> str:
    return f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
{procedure_stmts}
           STOP RUN.
    """


class TestExecSqlCoverage:
    """Cover uncovered branches in ExecSqlStatementParser."""

    def test_exec_sql_basic(self):
        """EXEC SQL SELECT covers basic SQL parsing path."""
        result = parse_cobol(
            _prog(
                "           EXEC SQL\n"
                "               SELECT COUNT(*) FROM MYTABLE\n"
                "           END-EXEC."
            )
        )
        assert result.ast is not None

    def test_exec_sql_with_host_variable(self):
        """EXEC SQL with :VAR host variables covers colon-prefix path (lines 81-88)."""
        result = parse_cobol(
            _prog(
                "           EXEC SQL\n"
                "               INSERT INTO ORDERS (ID, NAME)\n"
                "               VALUES (:WS-ID, :WS-NAME)\n"
                "           END-EXEC."
            )
        )
        assert result.ast is not None

    def test_exec_sql_into_host_variable(self):
        """EXEC SQL SELECT INTO :VAR covers INTO with host variable."""
        result = parse_cobol(
            _prog(
                "           EXEC SQL\n"
                "               SELECT COUNT(*) INTO :WS-COUNT FROM MYTABLE\n"
                "           END-EXEC."
            )
        )
        assert result.ast is not None

    def test_exec_sql_update(self):
        """EXEC SQL UPDATE with WHERE clause."""
        result = parse_cobol(
            _prog(
                "           EXEC SQL\n"
                "               UPDATE EMPLOYEES SET SALARY = :WS-SAL\n"
                "               WHERE EMPNO = :WS-EMP\n"
                "           END-EXEC."
            )
        )
        assert result.ast is not None

    def test_exec_sql_freeform_identifier_exec(self):
        """EXEC parsed as IDENTIFIER token still matches SQL parser (lines 33-46)."""
        result = parse_cobol(
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TESTPROG.\n"
            "PROCEDURE DIVISION.\n"
            "    EXEC SQL SELECT 1 FROM DUAL END-EXEC.\n"
            "    STOP RUN.\n"
        )
        assert result.ast is not None


class TestExecCicsCoverage:
    """Cover uncovered branches in ExecCicsStatementParser."""

    def test_exec_cics_receive(self):
        """EXEC CICS RECEIVE covers CICS parser matches + parse body (lines 107-168)."""
        result = parse_cobol(
            _prog(
                "           EXEC CICS\n"
                "               RECEIVE INTO WS-BUF\n"
                "           END-EXEC."
            )
        )
        assert result.ast is not None

    def test_exec_cics_send(self):
        """EXEC CICS SEND TEXT covers content-loop iteration."""
        result = parse_cobol(
            _prog(
                "           EXEC CICS\n"
                "               SEND TEXT FROM WS-MSG LENGTH 80\n"
                "           END-EXEC."
            )
        )
        assert result.ast is not None

    def test_exec_cics_link(self):
        """EXEC CICS LINK PROGRAM covers another CICS command variant."""
        result = parse_cobol(
            _prog(
                "           EXEC CICS\n"
                "               LINK PROGRAM('SUBPROG') COMMAREA(WS-CA)\n"
                "           END-EXEC."
            )
        )
        assert result.ast is not None

    def test_exec_cics_return(self):
        """EXEC CICS RETURN covers minimal CICS block."""
        result = parse_cobol(
            _prog(
                "           EXEC CICS\n"
                "               RETURN\n"
                "           END-EXEC."
            )
        )
        assert result.ast is not None

    def test_exec_cics_multiple_in_program(self):
        """Multiple EXEC CICS blocks in one program."""
        result = parse_cobol(
            _prog(
                "           EXEC CICS RECEIVE INTO WS-BUF END-EXEC.\n"
                "           EXEC CICS RETURN END-EXEC."
            )
        )
        assert result.ast is not None
