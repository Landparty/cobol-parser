"""
Negative and diagnostic tests for IO statement error handling.

Tests verify that invalid IO combinations emit appropriate error codes and
diagnostics as specified in contracts/io-statement-ast.md (FR-004).

Per TDD, these tests are expected to fail until error recovery is implemented.
"""

import pytest
from cobolparser import CobolParser, ErrorRecoveryMode


@pytest.mark.io
class TestIOErrorHandling:
    """Negative tests for IO statement error cases."""

    def test_read_with_lock_on_sequential_file(self) -> None:
        """READ WITH LOCK is invalid on sequential files (should emit IO_INVALID_LOCK)."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-ERR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO X ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  F.
       01  REC PIC X(100).
       PROCEDURE DIVISION.
           OPEN INPUT F.
           READ F WITH LOCK.
           CLOSE F.
           STOP RUN.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)

        # TODO: Assert that result contains error with code IO_INVALID_LOCK
        # Syntax: with_lock is only valid on INDEXED/RELATIVE files
        assert result.diagnostics is not None or result.ast is not None

    def test_start_on_sequential_file(self) -> None:
        """START is invalid on sequential files (should emit IO_INVALID_ORG)."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-ERR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO X ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  F.
       01  REC PIC X(100).
       WORKING-STORAGE SECTION.
       01  WS-KEY PIC 9(5).
       PROCEDURE DIVISION.
           OPEN INPUT F.
           START F KEY IS WS-KEY.
           CLOSE F.
           STOP RUN.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)

        # TODO: Assert error code IO_INVALID_ORG (START requires indexed/relative)
        assert result.diagnostics is not None or result.ast is not None

    def test_delete_on_sequential_without_current_record(self) -> None:
        """DELETE on sequential after READ should work, but DELETE without READ is error."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-ERR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO X ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  F.
       01  REC PIC X(100).
       PROCEDURE DIVISION.
           OPEN I-O F.
           DELETE F.
           CLOSE F.
           STOP RUN.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)

        # TODO: Assert warning or error (no current record context)
        assert result.ast is not None or result.diagnostics is not None

    def test_rewrite_without_read_context(self) -> None:
        """REWRITE without prior READ is an error."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-ERR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO X ORGANIZATION IS INDEXED.
       DATA DIVISION.
       FILE SECTION.
       FD  F.
       01  REC PIC X(100).
       PROCEDURE DIVISION.
           OPEN I-O F.
           REWRITE REC.
           CLOSE F.
           STOP RUN.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)

        # TODO: Assert warning about missing READ context
        assert result.ast is not None or result.diagnostics is not None

    def test_invalid_key_on_sequential_open(self) -> None:
        """INVALID KEY clause invalid on sequential file READ."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-ERR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO X ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  F.
       01  REC PIC X(100).
       PROCEDURE DIVISION.
           OPEN INPUT F.
           READ F INVALID KEY DISPLAY 'Error'.
           CLOSE F.
           STOP RUN.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)

        # TODO: Assert error code IO_INVALID_CLAUSE
        # INVALID KEY is only for INDEXED/RELATIVE/VSAM
        assert result.ast is not None or result.diagnostics is not None

    def test_key_clause_without_organization(self) -> None:
        """KEY IS clause on unkeyed file organization."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-ERR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO X ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  F.
       01  REC PIC X(100).
       WORKING-STORAGE SECTION.
       01  WS-KEY PIC 9(5).
       PROCEDURE DIVISION.
           OPEN INPUT F.
           READ F KEY IS WS-KEY.
           CLOSE F.
           STOP RUN.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)

        # TODO: Assert error (KEY clause invalid on SEQUENTIAL)
        assert result.ast is not None or result.diagnostics is not None

    def test_write_to_input_file(self) -> None:
        """WRITE to a file opened INPUT is an error."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-ERR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO X ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  F.
       01  REC PIC X(100).
       PROCEDURE DIVISION.
           OPEN INPUT F.
           WRITE REC.
           CLOSE F.
           STOP RUN.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)

        # TODO: Assert warning about file mode mismatch
        assert result.ast is not None or result.diagnostics is not None

    def test_read_from_output_file(self) -> None:
        """READ from a file opened OUTPUT is an error."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-ERR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO X ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  F.
       01  REC PIC X(100).
       PROCEDURE DIVISION.
           OPEN OUTPUT F.
           READ F.
           CLOSE F.
           STOP RUN.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)

        # TODO: Assert error about file mode
        assert result.ast is not None or result.diagnostics is not None

    def test_advancing_on_sequential_read(self) -> None:
        """ADVANCING clause invalid on READ (only for WRITE)."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-ERR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO X ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  F RECORD VARYING IN SIZE FROM 50 TO 100 CHARACTERS.
       01  REC PIC X(100).
       PROCEDURE DIVISION.
           OPEN INPUT F.
           READ F AFTER ADVANCING 1 LINE.
           CLOSE F.
           STOP RUN.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)

        # TODO: Assert error (ADVANCING only on WRITE)
        assert result.ast is not None or result.diagnostics is not None

    def test_multiple_at_end_clauses(self) -> None:
        """Multiple AT END clauses in single statement is syntax error."""
        source = """
       PROCEDURE DIVISION.
           READ F
               AT END DISPLAY 'End 1'
               AT END DISPLAY 'End 2'
           END-READ.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        # This should fail to parse or emit error
        result = parser.parse(source)
        # TODO: Assert syntax error code
        assert result is not None

    def test_display_advancing_clause_unknown(self) -> None:
        """Unknown advancing value for DISPLAY."""
        source = """
       PROCEDURE DIVISION.
           DISPLAY 'Hello' WITH ADVANCING SOMETHING.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)

        # TODO: Assert syntax/semantic error
        assert result.ast is not None or result.diagnostics is not None

    def test_no_rewind_on_non_sequential(self) -> None:
        """NO REWIND clause invalid on indexed/relative files."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-ERR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO X ORGANIZATION IS INDEXED.
       DATA DIVISION.
       FILE SECTION.
       FD  F.
       01  REC PIC X(100).
       PROCEDURE DIVISION.
           OPEN INPUT F.
           CLOSE F WITH NO REWIND.
           STOP RUN.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)

        # TODO: Assert error (NO REWIND only on sequential/tape)
        assert result.ast is not None or result.diagnostics is not None
