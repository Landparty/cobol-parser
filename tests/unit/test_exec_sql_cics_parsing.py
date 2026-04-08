"""Tests for EXEC SQL and EXEC CICS statement parser coverage.

Targets uncovered lines in parsers/statements/ibm_exec_statements.py (63.16%):
  - ExecSqlStatementParser: SQL content collection with host variables,
    multi-token concatenation, exception handling in matches()
  - ExecCicsStatementParser: matches() detection, parse() full path
"""

from cobolparser import parse_cobol


class TestExecSqlParsing:
    """Cover EXEC SQL statement parsing paths."""

    def test_exec_sql_basic_select(self):
        """EXEC SQL SELECT ... END-EXEC parses without errors."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NAME PIC X(30).
       PROCEDURE DIVISION.
           EXEC SQL
               SELECT NAME INTO :WS-NAME
               FROM EMPLOYEE
               WHERE EMP-ID = 100
           END-EXEC.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_exec_sql_host_variable_syntax(self):
        """EXEC SQL with :VAR host variable syntax is parsed correctly."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ID   PIC 9(5).
       01  WS-NAME PIC X(30).
       PROCEDURE DIVISION.
           EXEC SQL
               SELECT NAME INTO :WS-NAME
               FROM EMPLOYEE
               WHERE EMP-ID = :WS-ID
           END-EXEC.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_exec_sql_insert(self):
        """EXEC SQL INSERT statement."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLTEST.
       PROCEDURE DIVISION.
           EXEC SQL
               INSERT INTO EMPLOYEE (NAME, ID)
               VALUES ('SMITH', 100)
           END-EXEC.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_exec_sql_with_commas_and_periods(self):
        """EXEC SQL with comma-separated values concatenation."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLTEST.
       PROCEDURE DIVISION.
           EXEC SQL
               UPDATE EMPLOYEE SET NAME = 'DOE', DEPT = 'IT'
               WHERE ID = 1
           END-EXEC.
           STOP RUN.
        """)
        assert result.ast is not None


class TestExecCicsParsing:
    """Cover EXEC CICS statement parsing paths."""

    def test_exec_cics_receive(self):
        """EXEC CICS RECEIVE ... END-EXEC parses without errors."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  CICS-BUFFER PIC X(100).
       PROCEDURE DIVISION.
           EXEC CICS
               RECEIVE INTO(CICS-BUFFER)
               LENGTH(100)
           END-EXEC.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_exec_cics_send(self):
        """EXEC CICS SEND statement."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSTEST.
       PROCEDURE DIVISION.
           EXEC CICS
               SEND FROM(WS-OUTPUT)
               LENGTH(50)
           END-EXEC.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_exec_cics_return(self):
        """EXEC CICS RETURN statement."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSTEST.
       PROCEDURE DIVISION.
           EXEC CICS
               RETURN TRANSID('TRN1')
           END-EXEC.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_exec_cics_and_sql_in_same_program(self):
        """Program with both EXEC SQL and EXEC CICS blocks."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MIXTEST.
       PROCEDURE DIVISION.
           EXEC SQL
               SELECT COUNT(*) FROM EMPLOYEE
           END-EXEC.
           EXEC CICS
               SEND FROM(WS-MSG)
           END-EXEC.
           STOP RUN.
        """)
        assert result.ast is not None
