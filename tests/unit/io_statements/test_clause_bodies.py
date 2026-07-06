"""
Unit tests for IO statement conditional-clause bodies.

Verifies that the statements inside AT END / NOT AT END / INVALID KEY /
NOT INVALID KEY clauses are parsed into real AST nodes (not discarded),
attached to the owning IO statement, reachable via tree traversal, and
carry correct source locations.
"""

import pytest

from cobolparser import parse_cobol


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
       01  WS-AMT    PIC 9(5).
       PROCEDURE DIVISION.
{procedure_stmts}
           STOP RUN.
    """


def _only_io_stmt(result, verb: str):
    assert result.ast is not None
    stmts = result.ast.find_statements(verb)
    assert len(stmts) >= 1
    return stmts[0]


@pytest.mark.io
class TestReadClauseBodies:
    """AT END / NOT AT END / INVALID KEY bodies on READ."""

    def test_at_end_call_body_is_parsed(self) -> None:
        """The original repro: an inner CALL must not vanish from the AST."""
        result = parse_cobol(
            _prog(
                "           READ SEQ-FILE\n"
                '               AT END CALL "EOFH" USING WS-AMT\n'
                "           END-READ."
            )
        )
        stmt = _only_io_stmt(result, "READ")
        assert stmt.at_end_clause, "AT END body was discarded"
        call = stmt.at_end_clause[0]
        assert call.statement_type == "CALL"
        assert call.called_program == "EOFH"
        assert [p.name for p in call.using_parameters] == ["WS-AMT"]

    def test_at_end_body_reachable_via_traversal(self) -> None:
        """Clause statements must be children so find_all_by_type sees them."""
        result = parse_cobol(
            _prog(
                "           READ SEQ-FILE\n"
                '               AT END CALL "EOFH" USING WS-AMT\n'
                "           END-READ."
            )
        )
        assert result.ast is not None
        calls = result.ast.find_all_by_type("CallStatement")
        assert len(calls) == 1
        assert calls[0].called_program == "EOFH"

    def test_at_end_and_not_at_end_bodies(self) -> None:
        result = parse_cobol(
            _prog(
                "           READ SEQ-FILE\n"
                "               AT END MOVE 'Y' TO WS-BUF\n"
                "               NOT AT END DISPLAY 'GOT REC'\n"
                "           END-READ."
            )
        )
        stmt = _only_io_stmt(result, "READ")
        assert len(stmt.at_end_clause) == 1
        assert stmt.at_end_clause[0].statement_type == "MOVE"
        assert stmt.at_end_clause[0].targets == ["WS-BUF"]
        assert len(stmt.not_at_end_clause) == 1
        assert stmt.not_at_end_clause[0].statement_type == "DISPLAY"

    def test_at_end_multiple_statements(self) -> None:
        result = parse_cobol(
            _prog(
                "           READ SEQ-FILE\n"
                "               AT END\n"
                "                   DISPLAY 'EOF'\n"
                "                   MOVE 'Y' TO WS-BUF\n"
                "           END-READ."
            )
        )
        stmt = _only_io_stmt(result, "READ")
        assert [s.statement_type for s in stmt.at_end_clause] == ["DISPLAY", "MOVE"]

    def test_invalid_key_and_not_invalid_key_bodies(self) -> None:
        result = parse_cobol(
            _prog(
                "           READ IDX-FILE\n"
                "               INVALID KEY DISPLAY 'NOT FOUND'\n"
                "               NOT INVALID KEY DISPLAY 'FOUND'\n"
                "           END-READ."
            )
        )
        stmt = _only_io_stmt(result, "READ")
        assert len(stmt.invalid_key_clause) == 1
        assert stmt.invalid_key_clause[0].statement_type == "DISPLAY"
        assert len(stmt.not_invalid_key_clause) == 1
        assert stmt.not_invalid_key_clause[0].statement_type == "DISPLAY"

    def test_clause_body_source_location(self) -> None:
        """Nested statements carry the location of their own verb token."""
        result = parse_cobol(
            _prog(
                "           READ SEQ-FILE\n"
                '               AT END CALL "EOFH" USING WS-AMT\n'
                "           END-READ."
            )
        )
        stmt = _only_io_stmt(result, "READ")
        call = stmt.at_end_clause[0]
        assert call.location.line > stmt.location.line

    def test_clause_body_serialized_in_to_dict(self) -> None:
        result = parse_cobol(
            _prog(
                "           READ SEQ-FILE\n"
                '               AT END CALL "EOFH" USING WS-AMT\n'
                "           END-READ."
            )
        )
        stmt = _only_io_stmt(result, "READ")
        d = stmt.to_dict()
        assert len(d["at_end_clause"]) == 1
        assert d["at_end_clause"][0]["called_program"] == "EOFH"

    def test_period_terminated_clause_does_not_capture_siblings(self) -> None:
        """A period ends the READ scope; following statements are siblings."""
        result = parse_cobol(
            _prog(
                "           READ SEQ-FILE\n"
                "               AT END MOVE 'Y' TO WS-BUF.\n"
                "           DISPLAY 'AFTER'."
            )
        )
        stmt = _only_io_stmt(result, "READ")
        assert [s.statement_type for s in stmt.at_end_clause] == ["MOVE"]
        assert result.ast is not None
        displays = result.ast.find_statements("DISPLAY")
        assert len(displays) == 1

    def test_end_read_terminated_clause_does_not_capture_siblings(self) -> None:
        result = parse_cobol(
            _prog(
                "           READ SEQ-FILE\n"
                "               AT END MOVE 'Y' TO WS-BUF\n"
                "           END-READ.\n"
                "           DISPLAY 'AFTER'."
            )
        )
        stmt = _only_io_stmt(result, "READ")
        assert [s.statement_type for s in stmt.at_end_clause] == ["MOVE"]
        # END-READ must not leak into the MOVE targets
        assert stmt.at_end_clause[0].targets == ["WS-BUF"]
        assert result.ast is not None
        displays = result.ast.find_statements("DISPLAY")
        assert len(displays) == 1


@pytest.mark.io
class TestWriteClauseBodies:
    """INVALID KEY / NOT INVALID KEY bodies on WRITE."""

    def test_invalid_key_body(self) -> None:
        result = parse_cobol(
            _prog(
                "           WRITE IDX-REC\n"
                "               INVALID KEY DISPLAY 'DUP KEY'\n"
                "           END-WRITE."
            )
        )
        stmt = _only_io_stmt(result, "WRITE")
        assert len(stmt.invalid_key_clause) == 1
        assert stmt.invalid_key_clause[0].statement_type == "DISPLAY"

    def test_not_invalid_key_body(self) -> None:
        result = parse_cobol(
            _prog(
                "           WRITE IDX-REC\n"
                "               INVALID KEY MOVE 'E' TO WS-BUF\n"
                "               NOT INVALID KEY DISPLAY 'WROTE'\n"
                "           END-WRITE."
            )
        )
        stmt = _only_io_stmt(result, "WRITE")
        assert len(stmt.invalid_key_clause) == 1
        assert stmt.invalid_key_clause[0].statement_type == "MOVE"
        assert len(stmt.not_invalid_key_clause) == 1
        assert stmt.not_invalid_key_clause[0].statement_type == "DISPLAY"

    def test_invalid_key_call_body_traversal(self) -> None:
        result = parse_cobol(
            _prog(
                "           WRITE IDX-REC\n"
                '               INVALID KEY CALL "ERRH" USING WS-AMT\n'
                "           END-WRITE."
            )
        )
        assert result.ast is not None
        calls = result.ast.find_all_by_type("CallStatement")
        assert len(calls) == 1
        assert calls[0].called_program == "ERRH"
        stmt = _only_io_stmt(result, "WRITE")
        assert stmt.invalid_key_clause and stmt.invalid_key_clause[0] is calls[0]


@pytest.mark.io
class TestRewriteDeleteStartClauseBodies:
    """INVALID KEY bodies on REWRITE, DELETE, and START."""

    def test_rewrite_invalid_key_body(self) -> None:
        result = parse_cobol(
            _prog(
                "           REWRITE IDX-REC\n"
                "               INVALID KEY DISPLAY 'REWRITE FAIL'\n"
                "               NOT INVALID KEY DISPLAY 'REWROTE'\n"
                "           END-REWRITE."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_all_by_type("IORewriteStatement")
        assert len(stmts) == 1
        stmt = stmts[0]
        assert len(stmt.invalid_key_clause) == 1
        assert stmt.invalid_key_clause[0].statement_type == "DISPLAY"
        assert len(stmt.not_invalid_key_clause) == 1

    def test_delete_invalid_key_body(self) -> None:
        result = parse_cobol(
            _prog(
                "           DELETE IDX-FILE\n"
                '               INVALID KEY CALL "DELH" USING WS-AMT\n'
                "           END-DELETE."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_all_by_type("IODeleteStatement")
        assert len(stmts) == 1
        stmt = stmts[0]
        assert len(stmt.invalid_key_clause) == 1
        call = stmt.invalid_key_clause[0]
        assert call.statement_type == "CALL"
        assert call.called_program == "DELH"

    def test_start_invalid_key_body(self) -> None:
        result = parse_cobol(
            _prog(
                "           START IDX-FILE KEY IS EQUAL TO IDX-KEY\n"
                "               INVALID KEY DISPLAY 'NO MATCH'\n"
                "           END-START."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_all_by_type("IOStartStatement")
        assert len(stmts) == 1
        stmt = stmts[0]
        assert len(stmt.invalid_key_clause) == 1
        assert stmt.invalid_key_clause[0].statement_type == "DISPLAY"
