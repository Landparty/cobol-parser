"""
Unit tests for IO statement clause variations.

Tests cover all permutations of IO clauses including AT END, INVALID KEY,
ADVANCING, WITH LOCK, FROM, INTO, KEY IS, and their correct parsing via
full-program round-trips using parse_cobol().
"""

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode, parse_cobol


def _prog(procedure_stmts: str) -> str:
    return f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SEQ-FILE ASSIGN TO 'SEQ.DAT'
               ORGANIZATION IS SEQUENTIAL.
           SELECT IDX-FILE ASSIGN TO 'IDX.DAT'
               ORGANIZATION IS INDEXED
               RECORD KEY IS IDX-KEY.
       DATA DIVISION.
       FILE SECTION.
       FD  SEQ-FILE.
       01  SEQ-REC PIC X(80).
       FD  IDX-FILE.
       01  IDX-REC PIC X(80).
           05  IDX-KEY PIC 9(5).
       WORKING-STORAGE SECTION.
       01  WS-BUF    PIC X(80).
       01  WS-KEY    PIC 9(5).
       PROCEDURE DIVISION.
{procedure_stmts}
           STOP RUN.
    """


@pytest.mark.io
class TestIOClauseVariations:
    """Tests for all IO statement clause permutations via full parse round-trips."""

    # -------------------------------------------------------------------------
    # READ clause variations
    # -------------------------------------------------------------------------

    def test_read_at_end_clause(self) -> None:
        """READ with AT END clause populates at_end_clause on the AST node."""
        result = parse_cobol(
            _prog(
                "           READ SEQ-FILE\n"
                "               AT END DISPLAY 'DONE'\n"
                "           END-READ."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].at_end_clause is not None

    def test_read_not_at_end_clause(self) -> None:
        """READ with NOT AT END clause populates not_at_end_clause."""
        result = parse_cobol(
            _prog(
                "           READ SEQ-FILE\n"
                "               NOT AT END DISPLAY 'GOT REC'\n"
                "           END-READ."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].not_at_end_clause is not None

    def test_read_invalid_key_clause(self) -> None:
        """READ with INVALID KEY clause populates invalid_key_clause."""
        result = parse_cobol(
            _prog(
                "           READ IDX-FILE\n"
                "               INVALID KEY DISPLAY 'NOT FOUND'\n"
                "           END-READ."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].invalid_key_clause is not None

    def test_read_not_invalid_key_clause(self) -> None:
        """READ with NOT INVALID KEY clause populates not_invalid_key_clause."""
        result = parse_cobol(
            _prog(
                "           READ IDX-FILE\n"
                "               NOT INVALID KEY DISPLAY 'FOUND'\n"
                "           END-READ."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].not_invalid_key_clause is not None

    def test_read_combined_at_end_invalid_key(self) -> None:
        """READ with both AT END and NOT AT END populates both clauses."""
        result = parse_cobol(
            _prog(
                "           READ SEQ-FILE\n"
                "               AT END DISPLAY 'EOF'\n"
                "               NOT AT END DISPLAY 'REC'\n"
                "           END-READ."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].at_end_clause is not None
        assert stmts[0].not_at_end_clause is not None

    def test_read_with_lock(self) -> None:
        """READ IDX-FILE WITH LOCK sets with_lock on the AST node."""
        result = parse_cobol(
            _prog("           READ IDX-FILE WITH LOCK.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].with_lock is True

    def test_read_with_no_lock(self) -> None:
        """READ IDX-FILE WITH NO LOCK sets with_nowait on the AST node."""
        result = parse_cobol(
            _prog("           READ IDX-FILE WITH NO LOCK.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].with_nowait is True

    def test_read_key_clause(self) -> None:
        """READ IDX-FILE KEY IS WS-KEY captures key_name on the AST node."""
        result = parse_cobol(
            _prog("           READ IDX-FILE KEY IS WS-KEY.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].key_name == "WS-KEY"

    def test_read_into_clause(self) -> None:
        """READ SEQ-FILE INTO WS-BUF captures into_target on the AST node."""
        result = parse_cobol(
            _prog("           READ SEQ-FILE INTO WS-BUF.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].into_target == "WS-BUF"

    # -------------------------------------------------------------------------
    # WRITE clause variations
    # -------------------------------------------------------------------------

    def test_write_advancing_line(self) -> None:
        """WRITE AFTER ADVANCING n LINES sets advancing_mode to AFTER."""
        result = parse_cobol(
            _prog("           WRITE SEQ-REC AFTER ADVANCING 2 LINES.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("WRITE")
        assert len(stmts) >= 1
        assert stmts[0].advancing_mode == "AFTER"

    def test_write_advancing_page(self) -> None:
        """WRITE BEFORE ADVANCING PAGE sets advancing_mode to BEFORE."""
        result = parse_cobol(
            _prog("           WRITE SEQ-REC BEFORE ADVANCING PAGE.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("WRITE")
        assert len(stmts) >= 1
        assert stmts[0].advancing_mode == "BEFORE"

    def test_write_advancing_before(self) -> None:
        """WRITE BEFORE ADVANCING (no count) sets advancing_mode to BEFORE."""
        result = parse_cobol(
            _prog("           WRITE SEQ-REC BEFORE ADVANCING 1 LINES.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("WRITE")
        assert len(stmts) >= 1
        assert stmts[0].advancing_mode == "BEFORE"

    def test_write_advancing_after(self) -> None:
        """WRITE AFTER ADVANCING 1 LINES sets advancing_mode to AFTER."""
        result = parse_cobol(
            _prog("           WRITE SEQ-REC AFTER ADVANCING 1 LINES.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("WRITE")
        assert len(stmts) >= 1
        assert stmts[0].advancing_mode == "AFTER"

    def test_write_from_clause(self) -> None:
        """WRITE SEQ-REC FROM WS-BUF captures from_clause on the AST node."""
        result = parse_cobol(
            _prog("           WRITE SEQ-REC FROM WS-BUF.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("WRITE")
        assert len(stmts) >= 1
        assert stmts[0].from_clause == "WS-BUF"

    def test_write_from_and_advancing(self) -> None:
        """WRITE FROM + AFTER ADVANCING captures both attributes."""
        result = parse_cobol(
            _prog("           WRITE SEQ-REC FROM WS-BUF AFTER ADVANCING 1 LINES.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("WRITE")
        assert len(stmts) >= 1
        assert stmts[0].from_clause == "WS-BUF"
        assert stmts[0].advancing_mode == "AFTER"

    # -------------------------------------------------------------------------
    # START clause variations
    # -------------------------------------------------------------------------

    def test_start_key_equal(self) -> None:
        """START IDX-FILE KEY EQUAL TO WS-KEY parses without error."""
        result = parse_cobol(
            _prog("           START IDX-FILE KEY EQUAL TO WS-KEY.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("START_STATEMENT")
        assert len(stmts) >= 1
        assert stmts[0].file_name == "IDX-FILE"

    def test_start_key_not_less(self) -> None:
        """START IDX-FILE KEY NOT LESS THAN WS-KEY parses without error."""
        result = parse_cobol(
            _prog("           START IDX-FILE KEY NOT LESS THAN WS-KEY.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("START_STATEMENT")
        assert len(stmts) >= 1
        assert stmts[0].file_name == "IDX-FILE"

    # -------------------------------------------------------------------------
    # DELETE clause variations
    # -------------------------------------------------------------------------

    def test_delete_invalid_key(self) -> None:
        """DELETE IDX-FILE RECORD INVALID KEY captures invalid_key_clause."""
        result = parse_cobol(
            _prog(
                "           DELETE IDX-FILE RECORD\n"
                "               INVALID KEY DISPLAY 'ERR'\n"
                "           END-DELETE."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("DELETE_STATEMENT")
        assert len(stmts) >= 1
        assert stmts[0].invalid_key_clause is not None

    def test_delete_not_invalid_key(self) -> None:
        """DELETE IDX-FILE RECORD NOT INVALID KEY captures not_invalid_key_clause."""
        result = parse_cobol(
            _prog(
                "           DELETE IDX-FILE RECORD\n"
                "               NOT INVALID KEY DISPLAY 'OK'\n"
                "           END-DELETE."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("DELETE_STATEMENT")
        assert len(stmts) >= 1
        assert stmts[0].not_invalid_key_clause is not None

    # -------------------------------------------------------------------------
    # REWRITE clause variations
    # -------------------------------------------------------------------------

    def test_rewrite_invalid_key(self) -> None:
        """REWRITE IDX-REC INVALID KEY captures invalid_key_clause."""
        result = parse_cobol(
            _prog(
                "           REWRITE IDX-REC\n"
                "               INVALID KEY DISPLAY 'ERR'\n"
                "           END-REWRITE."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("REWRITE_STATEMENT")
        assert len(stmts) >= 1
        assert stmts[0].invalid_key_clause is not None

    def test_rewrite_from_clause(self) -> None:
        """REWRITE IDX-REC FROM WS-BUF parses without error and captures record_name."""
        result = parse_cobol(
            _prog("           REWRITE IDX-REC FROM WS-BUF.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("REWRITE_STATEMENT")
        assert len(stmts) >= 1
        assert stmts[0].record_name == "IDX-REC"

    # -------------------------------------------------------------------------
    # ACCEPT clause variations
    # -------------------------------------------------------------------------

    def test_accept_from_environment(self) -> None:
        """ACCEPT WS-BUF FROM ENVIRONMENT parses without error."""
        result = parse_cobol(
            _prog("           ACCEPT WS-BUF FROM ENVIRONMENT 'MYVAR'.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("ACCEPT")
        assert len(stmts) >= 1

    def test_accept_from_console(self) -> None:
        """ACCEPT WS-BUF FROM CONSOLE parses without error."""
        result = parse_cobol(
            _prog("           ACCEPT WS-BUF FROM CONSOLE.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("ACCEPT")
        assert len(stmts) >= 1

    # -------------------------------------------------------------------------
    # DISPLAY clause variations
    # -------------------------------------------------------------------------

    def test_display_upon_console(self) -> None:
        """DISPLAY 'Hello' UPON CONSOLE parses without error."""
        result = parse_cobol(
            _prog("           DISPLAY 'Hello' UPON CONSOLE.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("DISPLAY")
        assert len(stmts) >= 1

    def test_display_with_advancing(self) -> None:
        """DISPLAY 'Hello' WITH ADVANCING parses without error."""
        result = parse_cobol(
            _prog("           DISPLAY 'Hello' WITH ADVANCING.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("DISPLAY")
        assert len(stmts) >= 1

    def test_display_no_advancing(self) -> None:
        """DISPLAY 'Hello' NO ADVANCING parses without error."""
        result = parse_cobol(
            _prog("           DISPLAY 'Hello' NO ADVANCING.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("DISPLAY")
        assert len(stmts) >= 1

    # -------------------------------------------------------------------------
    # CLOSE clause variations
    # -------------------------------------------------------------------------

    def test_close_with_rewind(self) -> None:
        """CLOSE TAPE-FILE REEL sets reel option on the close statement."""
        result = parse_cobol(
            _prog("           CLOSE SEQ-FILE REEL.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("CLOSE")
        assert len(stmts) >= 1
        stmt = stmts[0]
        assert "SEQ-FILE" in stmt.file_names
        assert stmt.close_options["SEQ-FILE"]["reel"] is True

    def test_close_no_rewind(self) -> None:
        """CLOSE SEQ-FILE WITH NO REWIND sets no_rewind on the close statement."""
        result = parse_cobol(
            _prog("           CLOSE SEQ-FILE WITH NO REWIND.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("CLOSE")
        assert len(stmts) >= 1
        stmt = stmts[0]
        assert "SEQ-FILE" in stmt.file_names
        assert stmt.close_options["SEQ-FILE"]["no_rewind"] is True

    def test_close_with_lock(self) -> None:
        """CLOSE IDX-FILE WITH LOCK sets with_lock on the close statement."""
        result = parse_cobol(
            _prog("           CLOSE IDX-FILE WITH LOCK.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("CLOSE")
        assert len(stmts) >= 1
        stmt = stmts[0]
        assert "IDX-FILE" in stmt.file_names
        assert stmt.close_options["IDX-FILE"]["with_lock"] is True

    # -------------------------------------------------------------------------
    # OPEN clause variations
    # -------------------------------------------------------------------------

    def test_open_extend(self) -> None:
        """OPEN EXTEND SEQ-FILE sets open_mode to EXTEND."""
        result = parse_cobol(
            _prog("           OPEN EXTEND SEQ-FILE.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1
        assert stmts[0].open_mode == "EXTEND"

    def test_open_io_mode(self) -> None:
        """OPEN I-O IDX-FILE sets open_mode to I-O."""
        result = parse_cobol(
            _prog("           OPEN I-O IDX-FILE.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1
        assert stmts[0].open_mode == "I-O"

    def test_open_input_mode(self) -> None:
        """OPEN INPUT SEQ-FILE sets open_mode to INPUT."""
        result = parse_cobol(
            _prog("           OPEN INPUT SEQ-FILE.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1
        assert stmts[0].open_mode == "INPUT"

    def test_open_output_mode(self) -> None:
        """OPEN OUTPUT SEQ-FILE sets open_mode to OUTPUT."""
        result = parse_cobol(
            _prog("           OPEN OUTPUT SEQ-FILE.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1
        assert stmts[0].open_mode == "OUTPUT"

    def test_open_with_reposition(self) -> None:
        """OPEN I-O IDX-FILE WITH REPOSITION sets with_reposition on the statement."""
        result = parse_cobol(
            _prog("           OPEN I-O IDX-FILE WITH REPOSITION.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1
        assert stmts[0].with_reposition is True

    # -------------------------------------------------------------------------
    # UNLOCK clause variations
    # -------------------------------------------------------------------------

    def test_unlock_basic(self) -> None:
        """UNLOCK IDX-FILE sets file_name on the UNLOCK statement."""
        result = parse_cobol(
            _prog("           UNLOCK IDX-FILE.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("UNLOCK_STATEMENT")
        assert len(stmts) >= 1
        assert stmts[0].file_name == "IDX-FILE"

    def test_unlock_records(self) -> None:
        """UNLOCK IDX-FILE RECORDS sets record_scope."""
        result = parse_cobol(
            _prog("           UNLOCK IDX-FILE RECORDS.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("UNLOCK_STATEMENT")
        assert len(stmts) >= 1
        assert stmts[0].file_name == "IDX-FILE"
        assert stmts[0].record_scope == "RECORD"

    # -------------------------------------------------------------------------
    # READ access mode variations
    # -------------------------------------------------------------------------

    def test_read_next_record(self) -> None:
        """READ IDX-FILE NEXT sets access_mode to NEXT."""
        result = parse_cobol(
            _prog("           READ IDX-FILE NEXT.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].access_mode == "NEXT"

    def test_read_first_record(self) -> None:
        """READ IDX-FILE FIRST sets access_mode to FIRST."""
        result = parse_cobol(
            _prog("           READ IDX-FILE FIRST.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].access_mode == "FIRST"

    def test_read_last_record(self) -> None:
        """READ IDX-FILE LAST sets access_mode to LAST."""
        result = parse_cobol(
            _prog("           READ IDX-FILE LAST.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].access_mode == "LAST"

    def test_read_previous_record(self) -> None:
        """READ IDX-FILE PREVIOUS sets access_mode to PREVIOUS."""
        result = parse_cobol(
            _prog("           READ IDX-FILE PREVIOUS.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].access_mode == "PREVIOUS"

    # -------------------------------------------------------------------------
    # Error recovery — parser must not crash on malformed IO
    # -------------------------------------------------------------------------

    def test_error_recovery_on_invalid_io(self) -> None:
        """Parser in COLLECT_ALL mode must not crash on invalid IO statements."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           READ.
           WRITE.
           OPEN.
           STOP RUN.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)
        assert result is not None
