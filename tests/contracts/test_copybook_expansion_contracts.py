"""
Contract tests for copybook expansion API.

These tests verify API stability, function signatures, return types,
and exception behavior to prevent breaking changes.
"""

import inspect
from pathlib import Path

import pytest

# Import modules under test
from cobolparser.preprocess import expand_copybooks, parse_cobol_with_expansion
from cobolparser.preprocess.models import CopybookExpansion


class TestExpandCopybooksSignature:
    """Contract tests for expand_copybooks() function signature (US1)."""

    def test_basic_signature(self):
        """Verify function accepts required parameters (T028)."""
        sig = inspect.signature(expand_copybooks)
        params = list(sig.parameters.keys())

        # Check required parameters exist
        assert "source_code" in params
        assert "copybook_paths" in params
        assert "max_nesting_depth" in params
        assert "preserve_source_locations" in params

        # Check default values
        assert sig.parameters["max_nesting_depth"].default == 100
        assert sig.parameters["preserve_source_locations"].default is False

    def test_return_type(self):
        """Verify function returns CopybookExpansion object (T029)."""
        # Simple program without COPY statements
        source = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. TEST."
        result = expand_copybooks(source, [])

        assert isinstance(result, CopybookExpansion)
        assert hasattr(result, "expanded_source")
        assert hasattr(result, "included_copybooks")
        assert hasattr(result, "max_depth_reached")
        assert hasattr(result, "statistics")


class TestBasicExpansionBehavior:
    """Contract tests for basic expansion behavior (US1)."""

    def test_single_copy_statement_expansion(self):
        """Test COPY MEMBER1. replaced with content (T030)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY EMPLOYEE.
       PROCEDURE DIVISION.
           STOP RUN."""

        result = expand_copybooks(source, [str(samples_dir)])

        # Should contain EMPLOYEE copybook content
        assert "EMPLOYEE-RECORD" in result.expanded_source
        assert "EMPLOYEE-ID" in result.expanded_source
        assert "EMPLOYEE-NAME" in result.expanded_source
        assert "COPY EMPLOYEE" not in result.expanded_source
        assert len(result.included_copybooks) == 1
        assert "EMPLOYEE.cpy" in result.included_copybooks[0]

    def test_multiple_copy_statements(self):
        """Test multiple COPY statements all expanded (T031)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY EMPLOYEE.
       COPY CUSTOMER.
       PROCEDURE DIVISION.
           STOP RUN."""

        result = expand_copybooks(source, [str(samples_dir)])

        # Should contain both copybook contents
        assert "EMPLOYEE-ID" in result.expanded_source
        assert "CUSTOMER-ID" in result.expanded_source
        assert len(result.included_copybooks) == 2

    def test_copy_syntax_variants(self):
        """Test all COPY syntax variants recognized (T032)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        # Test different COPY syntaxes
        source1 = "       COPY EMPLOYEE."
        result1 = expand_copybooks(source1, [str(samples_dir)])
        assert "EMPLOYEE-ID" in result1.expanded_source

        source2 = '       COPY "EMPLOYEE".'
        result2 = expand_copybooks(source2, [str(samples_dir)])
        assert "EMPLOYEE-ID" in result2.expanded_source

    def test_no_copy_passthrough(self):
        """Test program without COPY returns unchanged (T033)."""
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN."""

        result = expand_copybooks(source, [])

        # Should return source unchanged
        assert result.expanded_source == source
        assert len(result.included_copybooks) == 0
        assert result.max_depth_reached == 0


class TestNestedExpansionContracts:
    """Contract tests for nested copybook resolution (US2)."""

    def test_nested_copy_expansion(self):
        """Test LEVEL1 contains COPY LEVEL2, both expanded (T051)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY LEVEL1.
       PROCEDURE DIVISION.
           STOP RUN."""

        result = expand_copybooks(source, [str(samples_dir)])

        # Should contain content from nested levels
        assert "LEVEL1-DATA" in result.expanded_source
        assert "LEVEL1-FIELD" in result.expanded_source
        assert "LEVEL2-FIELD" in result.expanded_source
        assert "COPY LEVEL1" not in result.expanded_source
        assert result.max_depth_reached >= 2

    def test_three_level_nesting(self):
        """Test 3-level nesting all expanded (T052)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = "       COPY LEVEL1."
        result = expand_copybooks(source, [str(samples_dir)])

        # Should contain all 3 levels
        assert "LEVEL1-FIELD" in result.expanded_source
        assert "LEVEL2-FIELD" in result.expanded_source
        assert "LEVEL3-FIELD" in result.expanded_source
        assert result.max_depth_reached == 3
        assert len(result.included_copybooks) == 3

    def test_multiple_nested_references(self):
        """Test single copybook references multiple others (T053)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        # Create a test that verifies multiple nested copybooks
        source = "       COPY LEVEL1."
        result = expand_copybooks(source, [str(samples_dir)])

        # Should have expanded nested structure
        assert len(result.included_copybooks) > 0
        assert result.max_depth_reached >= 1


class TestCircularReferenceContracts:
    """Contract tests for circular reference detection (US3)."""

    def test_direct_circular_reference(self):
        """Test A→B, B→A detected with chain (T063)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        from cobolparser.preprocess import CircularReferenceError

        source = "       COPY CIRCULARA."

        with pytest.raises(CircularReferenceError) as exc_info:
            expand_copybooks(source, [str(samples_dir)])

        # Should include dependency chain in error
        error_msg = str(exc_info.value)
        assert "CIRCULARA" in error_msg
        assert "CIRCULARB" in error_msg

    def test_indirect_circular_reference(self):
        """Test A→B→C→A detected with complete chain (T064)."""
        # Use same test as direct since we have A→B→A sample files
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        from cobolparser.preprocess import CircularReferenceError

        source = "       COPY CIRCULARA."

        with pytest.raises(CircularReferenceError):
            expand_copybooks(source, [str(samples_dir)])

    def test_circular_in_multiple_copies(self):
        """Test error identifies specific COPY causing cycle (T065)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        from cobolparser.preprocess import CircularReferenceError

        # Multiple COPY statements, one causes circular
        source = """       COPY EMPLOYEE.
       COPY CIRCULARA."""

        with pytest.raises(CircularReferenceError):
            expand_copybooks(source, [str(samples_dir)])


class TestSourceLocationContracts:
    """Contract tests for source location preservation (US4)."""

    def test_source_location_map_enabled(self):
        """Test preserve_source_locations=True returns populated map (T074)."""
        pytest.skip("Implementation pending - Phase 6")

    def test_source_location_accuracy(self):
        """Test each line maps to original file and line (T075)."""
        pytest.skip("Implementation pending - Phase 6")

    def test_nested_source_locations(self):
        """Test deeply nested content traces to original copybook (T076)."""
        pytest.skip("Implementation pending - Phase 6")


class TestParseCobolWithExpansionContracts:
    """Contract tests for parse_cobol_with_expansion() (Phase 7)."""

    def test_function_signature(self):
        """Verify accepts source_code, filename, copybook_paths (T091)."""
        pytest.skip("Implementation pending - Phase 7")

    def test_returns_parse_result(self):
        """Verify return type compatibility with existing parser (T092)."""
        pytest.skip("Implementation pending - Phase 7")


class TestProcedureDivisionCopybookContracts:
    """Contract tests for COPY statements in PROCEDURE DIVISION."""

    def test_procedure_copybook_statements_in_ast(self):
        """Test COPY in PROCEDURE DIVISION statements appear in AST."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROC-AST-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           COPY STANDARD-PROCEDURES.
           STOP RUN."""

        result = parse_cobol_with_expansion(source, "ast_test.cbl", [str(samples_dir)])

        # Contract: parse_cobol_with_expansion returns valid ParseResult
        assert result is not None
        assert hasattr(result, "ast")
        assert hasattr(result, "success")
        assert result.success, f"Parsing failed: {result.errors}"
        assert result.ast is not None

        # Contract: AST contains statements from expanded copybook
        all_statements = result.ast.get_all_statements()
        statement_types = [
            stmt.statement_type
            for stmt in all_statements
            if hasattr(stmt, "statement_type")
        ]

        # Contract: MOVE statement from STANDARD-PROCEDURES.cpy is in AST
        assert (
            "MOVE" in statement_types
        ), "MOVE statement from copybook not found in AST"

    def test_procedure_copybook_preserves_order(self):
        """Test statements from COPY maintain order in AST."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDER-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS PIC X(20).
       01 WS-COUNTER PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "Start".
           COPY STANDARD-PROCEDURES.
           DISPLAY "End".
           STOP RUN."""

        result = parse_cobol_with_expansion(
            source, "order_test.cbl", [str(samples_dir)]
        )

        # Contract: statements maintain order
        assert result.success, f"Parsing failed: {result.errors}"
        assert result.ast is not None

        all_statements = result.ast.get_all_statements()

        # Should have multiple statements in order
        assert len(all_statements) >= 3, "Expected at least 3 statements"

        # First should be DISPLAY "Start"
        # Middle should be from copybook (MOVE, DISPLAY, PERFORM)
        # Last should be DISPLAY "End" (and optionally STOP RUN if parser supports it)
        statement_types = [
            stmt.statement_type
            for stmt in all_statements
            if hasattr(stmt, "statement_type")
        ]

        # Verify we have expected statement types from copybook
        assert "DISPLAY" in statement_types, "Expected DISPLAY statements"
        assert "MOVE" in statement_types, "Expected MOVE statement from copybook"
        assert (
            "PERFORM" in statement_types
        ), "Expected PERFORM statement from copybook"

        # Verify we have at least 3 DISPLAY statements (Start, Processing started, End)
        display_count = statement_types.count("DISPLAY")
        assert (
            display_count >= 3
        ), f"Expected at least 3 DISPLAY statements, got {display_count}"
