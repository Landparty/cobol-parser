"""
Integration tests for copybook expansion.

Tests cover end-to-end workflows with real COBOL programs,
verifying that expansion works correctly with the existing parser.
"""

from pathlib import Path

import pytest

# Import modules under test
from cobolparser.preprocess import (
    CircularReferenceError,
    expand_copybooks,
    parse_cobol_with_expansion,
)

pytestmark = pytest.mark.integration


class TestBasicExpansion:
    """Integration tests for basic copybook expansion (US1)."""

    def test_basic_expansion_with_real_cobol(self):
        """Test basic expansion with real COBOL program (T040)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        # Read the real test program
        program_path = (
            Path(__file__).parent.parent
            / "samples"
            / "copybook_programs"
            / "basic_copy.cbl"
        )
        with open(program_path) as f:
            source = f.read()

        # Expand copybooks
        result = expand_copybooks(source, [str(samples_dir)])

        # Verify expansion occurred
        assert "COPY EMPLOYEE" not in result.expanded_source
        assert "COPY CUSTOMER" not in result.expanded_source
        assert "EMPLOYEE-RECORD" in result.expanded_source
        assert "CUSTOMER-RECORD" in result.expanded_source
        assert len(result.included_copybooks) == 2

    def test_expansion_preserves_cobol_structure(self):
        """Test that divisions, sections, paragraphs remain intact (T041)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY EMPLOYEE.
       01 MY-VAR PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "Hello".
           STOP RUN."""

        result = expand_copybooks(source, [str(samples_dir)])

        # Verify COBOL structure is preserved
        assert "IDENTIFICATION DIVISION" in result.expanded_source
        assert "PROGRAM-ID. TESTPROG" in result.expanded_source
        assert "DATA DIVISION" in result.expanded_source
        assert "WORKING-STORAGE SECTION" in result.expanded_source
        assert "PROCEDURE DIVISION" in result.expanded_source
        assert "MAIN-PARA" in result.expanded_source
        assert "MY-VAR" in result.expanded_source
        assert "EMPLOYEE-RECORD" in result.expanded_source

    def test_expanded_program_parses(self):
        """Test parse_cobol_with_expansion() end-to-end (T042)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY EMPLOYEE.
       PROCEDURE DIVISION.
           DISPLAY "Test".
           STOP RUN."""

        # Parse with expansion
        result = parse_cobol_with_expansion(source, "test.cbl", [str(samples_dir)])

        # Should return a ParseResult
        assert result is not None
        assert hasattr(result, "ast") or hasattr(result, "program")
        # The expanded source should have been parsed successfully


class TestNestedExpansion:
    """Integration tests for nested copybook resolution (US2)."""

    def test_real_nested_structure(self):
        """Test real nested copybook hierarchy (T056)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTED-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY LEVEL1.
       PROCEDURE DIVISION.
           STOP RUN."""

        result = expand_copybooks(source, [str(samples_dir)])

        # Verify all 3 levels expanded
        assert "LEVEL1-FIELD" in result.expanded_source
        assert "LEVEL2-FIELD" in result.expanded_source
        assert "LEVEL3-FIELD" in result.expanded_source
        assert result.max_depth_reached == 3
        assert len(result.included_copybooks) == 3

        # Verify no COPY statements remain
        assert "COPY LEVEL1" not in result.expanded_source
        assert "COPY LEVEL2" not in result.expanded_source
        assert "COPY LEVEL3" not in result.expanded_source

    def test_nested_programs_parse_correctly(self):
        """Test expanded nested program passes parser validation (T057)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTED-PARSE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY LEVEL1.
       PROCEDURE DIVISION.
           DISPLAY "Test".
           STOP RUN."""

        # Parse with expansion
        result = parse_cobol_with_expansion(source, "nested.cbl", [str(samples_dir)])

        # Should parse successfully
        assert result is not None
        # The nested structure should have been fully expanded and parsed


class TestCircularDetection:
    """Integration tests for circular reference detection (US3)."""

    def test_real_circular_copybook_structure(self):
        """Test circular dependency detection and reporting (T068)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CIRCULAR-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY CIRCULARA.
       PROCEDURE DIVISION.
           STOP RUN."""

        # Should raise CircularReferenceError
        with pytest.raises(CircularReferenceError) as exc_info:
            expand_copybooks(source, [str(samples_dir)])

        # Verify error message includes the circular chain
        error_msg = str(exc_info.value)
        assert "CIRCULARA" in error_msg
        assert "CIRCULARB" in error_msg
        # Should show it's circular (appears multiple times or uses arrow notation)
        assert error_msg.count("CIRCULAR") >= 2 or "→" in error_msg or "->" in error_msg


class TestSourceLocationIntegration:
    """Integration tests for source location preservation (US4)."""

    def test_error_tracing_with_source_locations(self):
        """Test error message references original copybook (T079)."""
        pytest.skip("Implementation pending - Phase 6")

    def test_source_location_map_serialization(self):
        """Test JSON export includes source location information (T080)."""
        pytest.skip("Implementation pending - Phase 6")


class TestProcedureDivisionCopybooks:
    """Integration tests for COPY statements in PROCEDURE DIVISION."""

    def test_procedure_copybook_expansion_and_parsing(self):
        """Test COPY in PROCEDURE DIVISION expands and statements appear in AST."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROC-COPY-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS PIC X(20).
       01 WS-COUNTER PIC 9(4) VALUE ZERO.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "Before copybook".
           COPY STANDARD-PROCEDURES.
           DISPLAY "After copybook".
           STOP RUN."""

        # Parse with expansion
        result = parse_cobol_with_expansion(source, "proc_test.cbl", [str(samples_dir)])

        # Verify parsing succeeded
        assert result is not None
        assert result.success, f"Parsing failed: {result.errors}"
        assert result.ast is not None

        # Verify PROCEDURE DIVISION exists in AST
        proc_div = result.ast.get_division("PROCEDURE")
        assert proc_div is not None, "PROCEDURE DIVISION not found in AST"

        # Get all statements from procedure division using the AST method
        all_statements = result.ast.get_all_statements()

        # Verify we have statements
        assert len(all_statements) > 0, "No statements found in PROCEDURE DIVISION"

        # Check for statement types from copybook (MOVE, DISPLAY, PERFORM)
        statement_types = [
            stmt.statement_type
            for stmt in all_statements
            if hasattr(stmt, "statement_type")
        ]

        # At minimum, we should have DISPLAY statements (before, from copybook, after)
        display_count = statement_types.count("DISPLAY")
        assert (
            display_count >= 2
        ), f"Expected at least 2 DISPLAY statements, found {display_count}"

        # Verify MOVE statement from copybook appears
        has_move = "MOVE" in statement_types
        assert (
            has_move
        ), f"Expected MOVE statement from copybook. Found types: {statement_types}"

    def test_multiple_procedure_copybooks(self):
        """Test multiple COPY statements in PROCEDURE DIVISION."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTI-PROC-COPY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS PIC X(20).
       01 WS-COUNTER PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           COPY STANDARD-PROCEDURES.
           COPY HELPER-ROUTINES.
           STOP RUN."""

        result = parse_cobol_with_expansion(
            source, "multi_proc.cbl", [str(samples_dir)]
        )

        # Verify parsing succeeded
        assert result is not None
        assert result.success, f"Parsing failed: {result.errors}"
        assert result.ast is not None

        # Verify AST has statements from both copybooks
        all_statements = result.ast.get_all_statements()
        statement_types = [
            stmt.statement_type
            for stmt in all_statements
            if hasattr(stmt, "statement_type")
        ]

        # Should have MOVE statements from both copybooks
        move_count = statement_types.count("MOVE")
        assert (
            move_count >= 2
        ), f"Expected at least 2 MOVE statements from copybooks, found {move_count}"

    def test_procedure_copybook_with_data_copybook(self):
        """Test COPY in both DATA and PROCEDURE divisions."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. MIXED-COPY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY EMPLOYEE.
       01 WS-STATUS PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           COPY STANDARD-PROCEDURES.
           STOP RUN."""

        result = parse_cobol_with_expansion(source, "mixed.cbl", [str(samples_dir)])

        # Verify parsing succeeded
        assert result is not None
        assert result.success, f"Parsing failed: {result.errors}"
        assert result.ast is not None

        # Verify DATA DIVISION has data items from EMPLOYEE copybook
        data_div = result.ast.get_division("DATA")
        assert data_div is not None

        # Verify PROCEDURE DIVISION exists
        proc_div = result.ast.get_division("PROCEDURE")
        assert proc_div is not None


class TestCopyReplacingIntegration:
    """Integration tests for COPY REPLACING (Phase 7)."""

    def test_replacing_text_substitution(self):
        """Test text replacement occurs after copybook insertion (T088)."""
        pytest.skip("Implementation pending - Phase 7")

    def test_parse_cobol_with_expansion_end_to_end(self):
        """Test real COBOL with copybooks expands and parses (T093)."""
        pytest.skip("Implementation pending - Phase 7")
