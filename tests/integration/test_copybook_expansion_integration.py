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


class TestNestedProcedureDivisionCopybooks:
    """Integration tests for nested COPY statements in PROCEDURE DIVISION.

    Verifies that copybooks containing executable statements AND nested
    COPY directives are fully expanded and all resulting statements are
    properly parsed into the AST.
    """

    def test_nested_procedure_copybook_expansion(self):
        """Test that nested COPY in PROCEDURE DIVISION is fully expanded."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTED-PROC-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS PIC X(20).
       01 WS-COUNTER PIC 9(4) VALUE ZERO.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "Before outer copybook".
           COPY PROC-NESTED-OUTER.
           DISPLAY "After outer copybook".
           STOP RUN."""

        result = expand_copybooks(source, [str(samples_dir)])

        # All COPY statements must be gone
        assert "COPY PROC-NESTED-OUTER" not in result.expanded_source
        assert "COPY PROC-NESTED-INNER" not in result.expanded_source

        # Content from both outer and inner copybooks must be present
        assert "OUTER-START" in result.expanded_source
        assert "Outer copybook start" in result.expanded_source
        assert "INNER-DONE" in result.expanded_source
        assert "Inner copybook executed" in result.expanded_source
        assert "Outer copybook end" in result.expanded_source

        # Both copybooks must appear in included list
        included_names = [
            Path(p).stem for p in result.included_copybooks
        ]
        assert "PROC-NESTED-OUTER" in included_names
        assert "PROC-NESTED-INNER" in included_names

        # Nesting depth must be at least 2
        assert result.max_depth_reached >= 2

    def test_nested_procedure_copybook_statements_parsed(self):
        """Test that statements from nested procedure copybooks appear in the AST.

        PROC-NESTED-OUTER.cpy contains:
          MOVE "OUTER-START" TO WS-STATUS.
          DISPLAY "Outer copybook start".
          COPY PROC-NESTED-INNER.        <-- nested
          DISPLAY "Outer copybook end".

        PROC-NESTED-INNER.cpy contains:
          MOVE "INNER-DONE" TO WS-STATUS.
          DISPLAY "Inner copybook executed".
          ADD 1 TO WS-COUNTER.

        After expansion we expect all these plus the main program's
        DISPLAY and STOP RUN to appear in the AST.
        """
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTED-PROC-PARSE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS PIC X(20).
       01 WS-COUNTER PIC 9(4) VALUE ZERO.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "Before outer copybook".
           COPY PROC-NESTED-OUTER.
           DISPLAY "After outer copybook".
           STOP RUN."""

        result = parse_cobol_with_expansion(
            source, "nested_proc.cbl", [str(samples_dir)]
        )

        assert result is not None
        assert result.success, f"Parsing failed: {result.errors}"
        assert result.ast is not None

        # Retrieve all statements from the AST
        all_statements = result.ast.get_all_statements()
        statement_types = [
            stmt.statement_type
            for stmt in all_statements
            if hasattr(stmt, "statement_type")
        ]

        # --- Verify statements from the main program ---
        # At least 5 DISPLAYs: main before, outer start, inner, outer end, main after
        display_count = statement_types.count("DISPLAY")
        assert display_count >= 5, (
            f"Expected at least 5 DISPLAY statements "
            f"(main×2 + outer×2 + inner×1), found {display_count}"
        )

        # --- Verify MOVE from outer copybook ---
        move_stmts = [
            stmt for stmt in all_statements
            if getattr(stmt, "statement_type", None) == "MOVE"
        ]
        assert len(move_stmts) >= 2, (
            f"Expected at least 2 MOVE statements "
            f"(outer + inner), found {len(move_stmts)}"
        )
        # Check specific MOVE sources if available
        move_sources = [
            getattr(stmt, "source", None) for stmt in move_stmts
        ]
        assert any(
            s and "OUTER-START" in s for s in move_sources
        ), f"MOVE from outer copybook not found. Sources: {move_sources}"
        assert any(
            s and "INNER-DONE" in s for s in move_sources
        ), f"MOVE from inner copybook not found. Sources: {move_sources}"

        # Check MOVE targets include WS-STATUS
        move_targets = [
            target
            for stmt in move_stmts
            for target in getattr(stmt, "targets", [])
        ]
        assert any(
            "WS-STATUS" in t for t in move_targets
        ), f"Expected WS-STATUS in MOVE targets. Targets: {move_targets}"

        # --- Verify ADD from inner copybook ---
        add_count = statement_types.count("ADD")
        assert add_count >= 1, (
            f"Expected at least 1 ADD statement from inner copybook, found {add_count}"
        )

        # --- Verify STOP RUN is still present ---
        assert "STOP" in statement_types, (
            f"STOP RUN missing from AST. Found types: {statement_types}"
        )

    def test_three_level_nested_procedure_copybook(self):
        """Test 3-level deep nested COPY in PROCEDURE DIVISION.

        PROC-DEEP-L1 → COPY PROC-DEEP-L2 → COPY PROC-DEEP-L3
        Each level contains DISPLAY and MOVE/ADD statements.
        """
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEEP-PROC-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS PIC X(20).
       01 WS-COUNTER PIC 9(4) VALUE ZERO.
       PROCEDURE DIVISION.
       MAIN-PARA.
           COPY PROC-DEEP-L1.
           STOP RUN."""

        # First verify expansion
        exp_result = expand_copybooks(source, [str(samples_dir)])
        assert "COPY PROC-DEEP" not in exp_result.expanded_source
        assert "Level 1 reached" in exp_result.expanded_source
        assert "Level 2 reached" in exp_result.expanded_source
        assert "Level 3 reached" in exp_result.expanded_source
        assert exp_result.max_depth_reached >= 3

        included_names = [
            Path(p).stem for p in exp_result.included_copybooks
        ]
        assert "PROC-DEEP-L1" in included_names
        assert "PROC-DEEP-L2" in included_names
        assert "PROC-DEEP-L3" in included_names

        # Now verify parsing
        result = parse_cobol_with_expansion(
            source, "deep_proc.cbl", [str(samples_dir)]
        )
        assert result is not None
        assert result.success, f"Parsing failed: {result.errors}"

        all_statements = result.ast.get_all_statements()
        statement_types = [
            stmt.statement_type
            for stmt in all_statements
            if hasattr(stmt, "statement_type")
        ]

        # DISPLAYs from all 3 levels
        display_count = statement_types.count("DISPLAY")
        assert display_count >= 3, (
            f"Expected at least 3 DISPLAY statements (one per level), "
            f"found {display_count}"
        )

        # MOVEs from L1 and L3
        move_stmts = [
            stmt for stmt in all_statements
            if getattr(stmt, "statement_type", None) == "MOVE"
        ]
        assert len(move_stmts) >= 2, (
            f"Expected at least 2 MOVE statements from L1 and L3, "
            f"found {len(move_stmts)}"
        )
        move_sources = [
            getattr(stmt, "source", None) for stmt in move_stmts
        ]
        assert any(
            s and "L1-COMPLETE" in s for s in move_sources
        ), f"MOVE from L1 not found. Sources: {move_sources}"
        assert any(
            s and "L3-COMPLETE" in s for s in move_sources
        ), f"MOVE from L3 not found. Sources: {move_sources}"

        # ADD from L2
        assert "ADD" in statement_types, (
            f"ADD statement from L2 not found. Types: {statement_types}"
        )

    def test_nested_procedure_copybook_with_data_copybook(self):
        """Test nested COPY in PROCEDURE DIVISION alongside DATA DIVISION COPY."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. MIXED-NESTED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY EMPLOYEE.
       01 WS-STATUS PIC X(20).
       01 WS-COUNTER PIC 9(4) VALUE ZERO.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "Start".
           COPY PROC-NESTED-OUTER.
           STOP RUN."""

        result = parse_cobol_with_expansion(
            source, "mixed_nested.cbl", [str(samples_dir)]
        )

        assert result is not None
        assert result.success, f"Parsing failed: {result.errors}"

        # Verify DATA DIVISION has the employee data items
        data_div = result.ast.get_division("DATA")
        assert data_div is not None

        # Verify PROCEDURE DIVISION has statements from nested copybooks
        proc_div = result.ast.get_division("PROCEDURE")
        assert proc_div is not None

        all_statements = result.ast.get_all_statements()
        statement_types = [
            stmt.statement_type
            for stmt in all_statements
            if hasattr(stmt, "statement_type")
        ]

        # Inner copybook's ADD must be present
        assert "ADD" in statement_types, (
            f"ADD from inner copybook not found. Types: {statement_types}"
        )
        # Both copybooks' MOVEs must be present
        move_count = statement_types.count("MOVE")
        assert move_count >= 2, (
            f"Expected at least 2 MOVE from nested copybooks, found {move_count}"
        )

    def test_procedure_copybook_preserves_statement_order(self):
        """Verify expanded copybook statements appear in correct order in AST."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDER-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS PIC X(20).
       01 WS-COUNTER PIC 9(4) VALUE ZERO.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "FIRST".
           COPY PROC-NESTED-OUTER.
           DISPLAY "LAST".
           STOP RUN."""

        result = parse_cobol_with_expansion(
            source, "order_test.cbl", [str(samples_dir)]
        )

        assert result is not None
        assert result.success, f"Parsing failed: {result.errors}"

        all_statements = result.ast.get_all_statements()

        # Extract DISPLAY items in order
        display_items = []
        for stmt in all_statements:
            if getattr(stmt, "statement_type", None) == "DISPLAY":
                items = getattr(stmt, "display_items", [])
                if items:
                    display_items.append(items[0])

        # Verify ordering: FIRST, then outer-start, then inner, then outer-end, then LAST
        assert len(display_items) >= 5, (
            f"Expected at least 5 DISPLAY items, got {len(display_items)}: {display_items}"
        )

        # Find positions of key markers
        first_idx = next(
            (i for i, d in enumerate(display_items) if "FIRST" in d), -1
        )
        outer_start_idx = next(
            (i for i, d in enumerate(display_items) if "Outer copybook start" in d), -1
        )
        inner_idx = next(
            (i for i, d in enumerate(display_items) if "Inner copybook executed" in d), -1
        )
        outer_end_idx = next(
            (i for i, d in enumerate(display_items) if "Outer copybook end" in d), -1
        )
        last_idx = next(
            (i for i, d in enumerate(display_items) if "LAST" in d), -1
        )

        assert first_idx != -1, f"FIRST not found in displays: {display_items}"
        assert outer_start_idx != -1, f"Outer start not found: {display_items}"
        assert inner_idx != -1, f"Inner not found: {display_items}"
        assert outer_end_idx != -1, f"Outer end not found: {display_items}"
        assert last_idx != -1, f"LAST not found: {display_items}"

        # Verify order
        assert first_idx < outer_start_idx < inner_idx < outer_end_idx < last_idx, (
            f"Statement order wrong. Indices: FIRST={first_idx}, "
            f"outer_start={outer_start_idx}, inner={inner_idx}, "
            f"outer_end={outer_end_idx}, LAST={last_idx}. "
            f"Display items: {display_items}"
        )


class TestCopyReplacingIntegration:
    """Integration tests for COPY REPLACING (Phase 7)."""

    def test_replacing_text_substitution(self):
        """Test text replacement occurs after copybook insertion (T088)."""
        pytest.skip("Implementation pending - Phase 7")

    def test_parse_cobol_with_expansion_end_to_end(self):
        """Test real COBOL with copybooks expands and parses (T093)."""
        pytest.skip("Implementation pending - Phase 7")
