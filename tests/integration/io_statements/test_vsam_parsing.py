"""Integration tests for VSAM KSDS file I/O statement parsing.

Tests verify that READ, WRITE, REWRITE, DELETE, START, OPEN, and CLOSE
statements parse correctly for VSAM indexed file programs.
"""

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.models.statements import (
    IOCloseStatement,
    IODeleteStatement,
    IOOpenStatement,
    IOReadStatement,
    IORewriteStatement,
    IOStartStatement,
)

pytestmark = pytest.mark.integration


VSAM_KSDS_PROGRAM = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VSAM-TEST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUSTOMER-FILE
               ASSIGN TO "CUSTFILE"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS CUST-ID
               ALTERNATE RECORD KEY IS CUST-NAME
               FILE STATUS IS WS-FILE-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD CUSTOMER-FILE.
       01 CUSTOMER-RECORD.
          05 CUST-ID      PIC X(10).
          05 CUST-NAME    PIC X(30).
          05 CUST-BALANCE PIC 9(10)V99.
       WORKING-STORAGE SECTION.
       01 WS-FILE-STATUS  PIC XX.
       01 WS-SEARCH-KEY   PIC X(10).
       01 WS-EOF-FLAG     PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN I-O CUSTOMER-FILE.
           MOVE 'CUST001' TO CUST-ID.
           READ CUSTOMER-FILE KEY IS CUST-ID
               INVALID KEY
                   DISPLAY 'NOT FOUND'
               NOT INVALID KEY
                   DISPLAY 'FOUND'
           END-READ.
           MOVE 'CUST001' TO WS-SEARCH-KEY.
           START CUSTOMER-FILE KEY IS GREATER THAN CUST-ID
               INVALID KEY
                   DISPLAY 'START FAILED'
           END-START.
           READ CUSTOMER-FILE NEXT
               AT END
                   MOVE 'Y' TO WS-EOF-FLAG
           END-READ.
           MOVE 'UPDATE' TO CUST-NAME.
           REWRITE CUSTOMER-RECORD
               INVALID KEY
                   DISPLAY 'REWRITE FAILED'
           END-REWRITE.
           DELETE CUSTOMER-FILE RECORD
               INVALID KEY
                   DISPLAY 'DELETE FAILED'
           END-DELETE.
           CLOSE CUSTOMER-FILE.
           STOP RUN.
"""


def _get_stmts_of_type(result, cls):
    """Return all statements of a given class from the parsed result."""
    all_stmts = result.ast.get_all_statements()
    return [s for s in all_stmts if isinstance(s, cls)]


class TestVsamKsdsParsing:
    """Test parsing of a complete VSAM KSDS program."""

    def test_vsam_program_parses_without_errors(self):
        """Full VSAM KSDS program parses with no errors."""
        result = parse_cobol(VSAM_KSDS_PROGRAM)
        assert result.ast is not None
        assert result.errors == [], f"Unexpected errors: {result.errors}"

    def test_vsam_program_contains_open_statement(self):
        """OPEN I-O statement is present in the AST."""
        result = parse_cobol(VSAM_KSDS_PROGRAM)
        assert result.ast is not None
        open_stmts = _get_stmts_of_type(result, IOOpenStatement)
        assert len(open_stmts) >= 1, "Expected at least one IOOpenStatement"
        open_stmt = open_stmts[0]
        assert open_stmt.open_mode is not None

    def test_vsam_program_contains_read_statement(self):
        """READ with KEY IS clause is present in the AST."""
        result = parse_cobol(VSAM_KSDS_PROGRAM)
        assert result.ast is not None
        read_stmts = _get_stmts_of_type(result, IOReadStatement)
        assert len(read_stmts) >= 1, "Expected at least one IOReadStatement"
        # First READ has KEY IS
        keyed_reads = [s for s in read_stmts if s.key_name is not None]
        assert len(keyed_reads) >= 1, "Expected READ with KEY IS clause"
        assert keyed_reads[0].file_name is not None

    def test_vsam_program_contains_read_next(self):
        """READ NEXT statement is present in the AST."""
        result = parse_cobol(VSAM_KSDS_PROGRAM)
        assert result.ast is not None
        read_stmts = _get_stmts_of_type(result, IOReadStatement)
        next_reads = [s for s in read_stmts if s.access_mode == "NEXT"]
        assert len(next_reads) >= 1, "Expected READ NEXT statement"

    def test_vsam_program_contains_start_statement(self):
        """START with KEY condition is present in the AST."""
        result = parse_cobol(VSAM_KSDS_PROGRAM)
        assert result.ast is not None
        start_stmts = _get_stmts_of_type(result, IOStartStatement)
        assert len(start_stmts) >= 1, "Expected at least one IOStartStatement"
        start_stmt = start_stmts[0]
        assert start_stmt.file_name is not None

    def test_vsam_program_contains_rewrite_statement(self):
        """REWRITE with INVALID KEY clause is present in the AST."""
        result = parse_cobol(VSAM_KSDS_PROGRAM)
        assert result.ast is not None
        rewrite_stmts = _get_stmts_of_type(result, IORewriteStatement)
        assert len(rewrite_stmts) >= 1, "Expected at least one IORewriteStatement"
        rewrite_stmt = rewrite_stmts[0]
        assert rewrite_stmt.record_name is not None

    def test_vsam_program_contains_delete_statement(self):
        """DELETE with INVALID KEY clause is present in the AST."""
        result = parse_cobol(VSAM_KSDS_PROGRAM)
        assert result.ast is not None
        delete_stmts = _get_stmts_of_type(result, IODeleteStatement)
        assert len(delete_stmts) >= 1, "Expected at least one IODeleteStatement"
        delete_stmt = delete_stmts[0]
        assert delete_stmt.file_name is not None

    def test_vsam_program_contains_close_statement(self):
        """CLOSE statement is present in the AST."""
        result = parse_cobol(VSAM_KSDS_PROGRAM)
        assert result.ast is not None
        close_stmts = _get_stmts_of_type(result, IOCloseStatement)
        assert len(close_stmts) >= 1, "Expected at least one IOCloseStatement"
        close_stmt = close_stmts[0]
        assert len(close_stmt.file_names) >= 1


class TestReadStatementClauses:
    """Test individual READ clause variations."""

    def test_read_with_key_is(self):
        """READ with KEY IS clause sets key_name."""
        code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           READ MYFILE KEY IS MY-KEY.
           STOP RUN.
        """
        result = parse_cobol(code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        stmts = _get_stmts_of_type(result, IOReadStatement)
        assert len(stmts) >= 1
        assert stmts[0].key_name == "MY-KEY"

    def test_read_next_record(self):
        """READ NEXT sets access_mode to NEXT."""
        code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           READ SEQFILE NEXT.
           STOP RUN.
        """
        result = parse_cobol(code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        stmts = _get_stmts_of_type(result, IOReadStatement)
        assert len(stmts) >= 1
        assert stmts[0].access_mode == "NEXT"

    def test_read_into(self):
        """READ INTO clause sets into_target."""
        code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           READ MYFILE INTO WS-RECORD.
           STOP RUN.
        """
        result = parse_cobol(code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        stmts = _get_stmts_of_type(result, IOReadStatement)
        assert len(stmts) >= 1
        assert stmts[0].into_target == "WS-RECORD"

    def test_read_file_name(self):
        """READ sets file_name correctly."""
        code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           READ CUSTOMER-FILE.
           STOP RUN.
        """
        result = parse_cobol(code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        stmts = _get_stmts_of_type(result, IOReadStatement)
        assert len(stmts) >= 1
        assert stmts[0].file_name == "CUSTOMER-FILE"


class TestOpenStatementModes:
    """Test OPEN mode parsing."""

    def test_open_input(self):
        """OPEN INPUT sets open_mode to INPUT."""
        code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           OPEN INPUT MYFILE.
           STOP RUN.
        """
        result = parse_cobol(code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        stmts = _get_stmts_of_type(result, IOOpenStatement)
        assert len(stmts) >= 1
        assert stmts[0].open_mode == "INPUT"
        assert "MYFILE" in stmts[0].file_names

    def test_open_output(self):
        """OPEN OUTPUT sets open_mode to OUTPUT."""
        code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           OPEN OUTPUT OUTFILE.
           STOP RUN.
        """
        result = parse_cobol(code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        stmts = _get_stmts_of_type(result, IOOpenStatement)
        assert len(stmts) >= 1
        assert stmts[0].open_mode == "OUTPUT"

    def test_open_extend(self):
        """OPEN EXTEND sets open_mode to EXTEND."""
        code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           OPEN EXTEND LOGFILE.
           STOP RUN.
        """
        result = parse_cobol(code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        stmts = _get_stmts_of_type(result, IOOpenStatement)
        assert len(stmts) >= 1
        assert stmts[0].open_mode == "EXTEND"


class TestCloseStatement:
    """Test CLOSE statement parsing."""

    def test_close_single_file(self):
        """CLOSE with single file sets file_names."""
        code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           CLOSE MYFILE.
           STOP RUN.
        """
        result = parse_cobol(code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        stmts = _get_stmts_of_type(result, IOCloseStatement)
        assert len(stmts) >= 1
        assert "MYFILE" in stmts[0].file_names

    def test_close_multiple_files(self):
        """CLOSE with multiple files sets all file_names."""
        code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           CLOSE FILE1 FILE2 FILE3.
           STOP RUN.
        """
        result = parse_cobol(code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        stmts = _get_stmts_of_type(result, IOCloseStatement)
        assert len(stmts) >= 1
        assert len(stmts[0].file_names) == 3


class TestDeleteStatement:
    """Test DELETE statement parsing."""

    def test_delete_file_record(self):
        """DELETE file RECORD sets file_name."""
        code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           DELETE CUSTOMER-FILE RECORD.
           STOP RUN.
        """
        result = parse_cobol(code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        stmts = _get_stmts_of_type(result, IODeleteStatement)
        assert len(stmts) >= 1
        assert stmts[0].file_name == "CUSTOMER-FILE"


class TestRewriteStatement:
    """Test REWRITE statement parsing."""

    def test_rewrite_record(self):
        """REWRITE record-name sets record_name."""
        code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           REWRITE CUSTOMER-RECORD.
           STOP RUN.
        """
        result = parse_cobol(code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        stmts = _get_stmts_of_type(result, IORewriteStatement)
        assert len(stmts) >= 1
        assert stmts[0].record_name == "CUSTOMER-RECORD"


class TestStartStatement:
    """Test START statement parsing."""

    def test_start_file_name(self):
        """START sets file_name correctly."""
        code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           START CUSTOMER-FILE KEY IS GREATER THAN CUST-ID.
           STOP RUN.
        """
        result = parse_cobol(code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        stmts = _get_stmts_of_type(result, IOStartStatement)
        assert len(stmts) >= 1
        assert stmts[0].file_name == "CUSTOMER-FILE"
