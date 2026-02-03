"""Test suite for basic CALL statement parsing (T015).

Tests FR-001 and FR-002: Basic CALL statements with literal and variable program names.
Covers both static and dynamic CALL variations.
"""

import pytest
from cobolparser import parse_cobol


class TestCallBasicParsing:
    """Test basic CALL statement parsing (US-1, FR-001, FR-002)."""

    def test_call_with_literal_program_name(self):
        """Test static CALL with literal program name (FR-001)."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "SUBPROGRAM".
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        
        calls = result.ast.find_statements("CALL")
        assert len(calls) >= 1
        
        call_stmt = calls[0]
        assert call_stmt.called_program == "SUBPROGRAM"
        assert call_stmt.is_dynamic is False

    def test_call_with_variable_program_name(self):
        """Test dynamic CALL with variable program name (FR-002)."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-PROGRAM PIC X(20).
        PROCEDURE DIVISION.
            CALL WS-PROGRAM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        
        calls = result.ast.find_statements("CALL")
        assert len(calls) >= 1
        
        call_stmt = calls[0]
        assert call_stmt.called_program == "WS-PROGRAM"
        assert call_stmt.is_dynamic is True

    def test_call_with_no_parameters(self):
        """Test CALL with no USING clause (FR-001, FR-002)."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "WORKER".
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        
        calls = result.ast.find_statements("CALL")
        assert len(calls) >= 1
        
        call_stmt = calls[0]
        assert len(call_stmt.using_parameters) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
