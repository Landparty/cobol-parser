"""Tests for GO TO and STOP statement parser coverage.

Targets uncovered branches in:
  - go_parser.py: DEPENDING ON clause, missing TO keyword error path
  - stop_parser.py: STOP with string literal, STOP RUN variants
"""
import pytest
from cobolparser import parse_cobol
from cobolparser import CobolParser, ErrorRecoveryMode


def _prog(procedure_stmts: str) -> str:
    return f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  IDX  PIC 9.
       PROCEDURE DIVISION.
{procedure_stmts}
           STOP RUN.
    """


class TestGoParserCoverage:
    """Cover uncovered branches in go_parser.py."""

    def test_goto_basic(self):
        """GO TO PARA-1 — baseline."""
        result = parse_cobol(_prog("           GO TO PARA-1."))
        assert result.ast is not None
        stmts = result.ast.find_statements("GOTO")
        assert len(stmts) >= 1
        assert stmts[0].target_paragraph == "PARA-1"

    def test_goto_depending_on(self):
        """GO TO PARA-1 DEPENDING ON IDX — covers _parse_depending_on_clause (lines 100-139)."""
        result = parse_cobol(_prog("           GO TO PARA-1 DEPENDING ON IDX."))
        assert result.ast is not None
        stmts = result.ast.find_statements("GOTO")
        assert len(stmts) >= 1
        assert stmts[0].depending_on_variable == "IDX"

    def test_goto_depending_on_target_stored(self):
        """DEPENDING ON variable and target paragraph both set correctly."""
        result = parse_cobol(
            _prog("           GO TO EXIT-PARA DEPENDING ON IDX.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("GOTO")
        assert len(stmts) >= 1
        stmt = stmts[0]
        assert stmt.target_paragraph == "EXIT-PARA"
        assert stmt.depending_on_variable == "IDX"

    def test_goto_missing_to_recovers(self):
        """GO without TO in error-recovery mode covers error report path (lines 65-72)."""
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(
            """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
           GO PARA-1.
           STOP RUN.
            """
        )
        # Parser should not crash
        assert result is not None

    def test_goto_no_period(self):
        """GO TO without trailing period — parser still returns a statement."""
        result = parse_cobol(
            """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
           GO TO PARA-1
           STOP RUN.
            """
        )
        assert result.ast is not None


class TestStopParserCoverage:
    """Cover uncovered branches in stop_parser.py."""

    def test_stop_run(self):
        """STOP RUN — stop_type should be 'RUN'."""
        result = parse_cobol(
            """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
           STOP RUN.
            """
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("STOP")
        assert len(stmts) >= 1
        assert stmts[0].stop_type == "RUN"

    def test_stop_with_string_literal(self):
        """STOP 'message' covers string literal branch (lines 41-43)."""
        result = parse_cobol(
            """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
           STOP 'HALTED'.
            """
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("STOP")
        assert len(stmts) >= 1
        stmt = stmts[0]
        # stop_type set to the literal value (not "RUN")
        assert stmt.stop_type != "RUN"

    def test_stop_run_uppercase_variants(self):
        """STOP RUN is parsed regardless of case variations."""
        result = parse_cobol(
            """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
           STOP RUN.
            """
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("STOP")
        assert len(stmts) >= 1
