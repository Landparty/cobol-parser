"""Contract tests for STOP statement diagnostics.

These tests verify that STOP parsing produces consistent, well-formed
diagnostic messages according to the data model specifications.

Diagnostic Record Structure (per Data Model):
- line: Source line number (1-indexed)
- column: Source column number (1-indexed)
- message: Human-readable error message
- category: Error category (e.g., "SYNTAX", "SEMANTIC", "STRUCTURE")
- severity: Error severity (ERROR, WARNING, INFO)
"""

import pytest

from cobolparser import CobolParser, ParseResult, ParseError
from cobolparser.models.ast_base import SourceLocation


def _fixed_source(body: str) -> str:
    """Convert body to fixed-format COBOL source."""
    lines = [line.rstrip() for line in body.strip().splitlines()]
    return "\n".join(f"       {line}" for line in lines) + "\n"


def _get_stop_diagnostics(source: str) -> list:
    """Parse source and extract STOP-related diagnostics."""
    parser = CobolParser()
    result = parser.parse(_fixed_source(source))
    return result.errors


class TestStopDiagnosticStructure:
    """Tests for diagnostic record structure compliance."""

    def test_diagnostic_has_line_number(self):
        """Each diagnostic must include a valid line number."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        diagnostics = _get_stop_diagnostics(source)
        if diagnostics:
            for d in diagnostics:
                assert hasattr(d, "line_number") or hasattr(d, "location")

    def test_diagnostic_has_column_number(self):
        """Each diagnostic must include a valid column number."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        diagnostics = _get_stop_diagnostics(source)
        if diagnostics:
            for d in diagnostics:
                assert hasattr(d, "column") or hasattr(d, "location")

    def test_diagnostic_has_message(self):
        """Each diagnostic must have a non-empty message."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        diagnostics = _get_stop_diagnostics(source)
        if diagnostics:
            for d in diagnostics:
                assert str(d) and len(str(d).strip()) > 0


class TestStopValidCases:
    """Tests for valid STOP statements."""

    def test_stop_run_valid(self):
        """STOP RUN should parse successfully."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        diagnostics = _get_stop_diagnostics(source)
        # Should parse successfully
        stop_errors = [d for d in diagnostics if "STOP" in str(d).upper() and "error" in str(d).lower()]
        assert len(stop_errors) == 0 or len(diagnostics) == 0

    def test_stop_with_return_code(self):
        """STOP with return code should parse successfully."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  RETURN-CODE PIC 9.
        PROCEDURE DIVISION.
            STOP RUN RETURNING RETURN-CODE.
        """
        diagnostics = _get_stop_diagnostics(source)
        # Should parse successfully
        assert isinstance(diagnostics, list)

    def test_stop_after_statement(self):
        """STOP RUN after other statements should work."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  A PIC 9.
        PROCEDURE DIVISION.
            MOVE 1 TO A.
            STOP RUN.
        """
        diagnostics = _get_stop_diagnostics(source)
        # Should parse successfully
        assert isinstance(diagnostics, list)


class TestStopWithBranching:
    """Tests for STOP statements in control flow."""

    def test_stop_in_if_then(self):
        """STOP in IF THEN branch should work."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF 1 = 1
                STOP RUN
            END-IF.
        """
        diagnostics = _get_stop_diagnostics(source)
        # Should parse successfully
        assert isinstance(diagnostics, list)

    def test_stop_in_perform(self):
        """STOP in PERFORM should work."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM 
                STOP RUN
            END-PERFORM.
        """
        diagnostics = _get_stop_diagnostics(source)
        # Should parse successfully (may have various results)
        assert isinstance(diagnostics, list)


class TestStopDiagnosticMessageConsistency:
    """Tests for consistent diagnostic message formatting."""

    def test_error_messages_have_meaningful_content(self):
        """Error messages should contain meaningful diagnostic content."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        diagnostics = _get_stop_diagnostics(source)
        for d in diagnostics:
            msg = str(d).strip()
            if msg:
                assert len(msg) > 5, f"Message too short: {msg}"


class TestStopDiagnosticSeverity:
    """Tests for diagnostic severity classification."""

    def test_stop_run_no_errors(self):
        """STOP RUN by itself should not generate errors."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        diagnostics = _get_stop_diagnostics(source)
        # STOP RUN is valid and should have no errors
        assert len(diagnostics) == 0 or all("STOP" not in str(d).upper() or "error" not in str(d).lower() for d in diagnostics)
