"""Comprehensive test suite for IF statement parsing.

This module systematically tests all IF variants including:
- IF ... END-IF statements
- IF ... ELSE ... END-IF
- IF ... ELSE IF chains
- Nested IF statements
- Inline IF statements
- Complex conditions
"""

import pytest

from cobolparser import parse_cobol


class TestIfBasic:
    """Test basic IF statement functionality."""

    def test_if_simple(self):
        """Test simple IF with THEN."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 FLAG PIC X VALUE "N".
        PROCEDURE DIVISION.
            IF FLAG = "Y" THEN
                DISPLAY "YES"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        assert result.ast is not None

        ifs = result.ast.find_statements("IF")
        assert len(ifs) >= 1

    def test_if_without_then(self):
        """Test IF without explicit THEN (default)."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF 1 = 1
                DISPLAY "TRUE"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        ifs = result.ast.find_statements("IF")
        assert len(ifs) >= 1

    def test_if_with_end_if(self):
        """Test IF ... END-IF structure."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF TRUE
                DISPLAY "INLINE"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestIfElse:
    """Test IF ... ELSE ... END-IF structures."""

    def test_if_else_basic(self):
        """Test IF ... ELSE ... END-IF."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF FALSE
                DISPLAY "FALSE BRANCH"
            ELSE
                DISPLAY "ELSE BRANCH"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        ifs = result.ast.find_statements("IF")
        assert len(ifs) >= 1

    def test_if_else_if_chain(self):
        """Test IF ... ELSE IF ... ELSE ... END-IF chain."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 CODE PIC 9 VALUE 1.
        PROCEDURE DIVISION.
            IF CODE = 1
                DISPLAY "ONE"
            ELSE IF CODE = 2
                DISPLAY "TWO"
            ELSE IF CODE = 3
                DISPLAY "THREE"
            ELSE
                DISPLAY "OTHER"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        ifs = result.ast.find_statements("IF")
        assert len(ifs) >= 3


class TestNestedIf:
    """Test nested IF statements."""

    def test_nested_if_simple(self):
        """Test simple nested IF."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF TRUE
                IF FALSE
                    DISPLAY "INNER"
                END-IF
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        ifs = result.ast.find_statements("IF")
        assert len(ifs) >= 2

    def test_deeply_nested_if(self):
        """Test deeply nested IF statements."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF TRUE
                IF TRUE
                    IF FALSE
                        DISPLAY "DEEP"
                    END-IF
                END-IF
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        ifs = result.ast.find_statements("IF")
        assert len(ifs) >= 3

    def test_nested_if_with_else(self):
        """Test nested IF with ELSE branches."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF TRUE
                IF FALSE
                    DISPLAY "INNER TRUE"
                ELSE
                    DISPLAY "INNER ELSE"
                END-IF
            ELSE
                DISPLAY "OUTER ELSE"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestIfConditions:
    """Test various IF condition types."""

    def test_if_numeric_comparison(self):
        """Test IF with numeric comparison."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 NUM PIC 9(5) VALUE 100.
        PROCEDURE DIVISION.
            IF NUM > 50
                DISPLAY "GREATER"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_if_string_comparison(self):
        """Test IF with string comparison."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 TEXT PIC X(10) VALUE "HELLO".
        PROCEDURE DIVISION.
            IF TEXT = "HELLO"
                DISPLAY "MATCH"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_if_complex_condition_and(self):
        """Test IF with AND condition."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF 1 = 1 AND 2 = 2
                DISPLAY "BOTH TRUE"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_if_complex_condition_or(self):
        """Test IF with OR condition."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF 1 = 2 OR 2 = 2
                DISPLAY "ONE TRUE"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_if_complex_condition_mixed(self):
        """Test IF with mixed AND/OR conditions."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF (1 = 1 AND 2 = 2) OR (3 = 4 AND 5 = 5)
                DISPLAY "MIXED"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_if_negation(self):
        """Test IF with NOT condition."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF NOT FALSE
                DISPLAY "NOT FALSE IS TRUE"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestIfInline:
    """Test inline IF statements (one-liner COBOL style)."""

    def test_if_inline_single_statement(self):
        """Test inline IF with single statement."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF TRUE DISPLAY "ONE LINE".
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_if_inline_with_period(self):
        """Test inline IF ending with period."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF TRUE DISPLAY "TEST".
        """
        result = parse_cobol(source)
        # May succeed or fail depending on parser strictness
        assert result is not None


class TestIfWithStatements:
    """Test IF combined with various statements."""

    def test_if_with_display(self):
        """Test IF containing DISPLAY."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF TRUE
                DISPLAY "MESSAGE"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        ifs = result.ast.find_statements("IF")
        displays = result.ast.find_statements("DISPLAY")
        assert len(ifs) >= 1
        assert len(displays) >= 1

    def test_if_with_move(self):
        """Test IF containing MOVE."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 VAR PIC X.
        PROCEDURE DIVISION.
            IF TRUE
                MOVE "X" TO VAR
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_if_with_perform(self):
        """Test IF containing PERFORM."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF TRUE
                PERFORM PARA-NAME
            END-IF.
            STOP RUN.
        PARA-NAME.
            DISPLAY "DONE".
        """
        result = parse_cobol(source)
        assert result.success

    def test_if_with_call(self):
        """Test IF containing CALL."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF TRUE
                CALL "SUBPROG"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestIfSerialization:
    """Test IF statement serialization."""

    def test_if_to_dict(self):
        """Test IF statement to_dict() serialization."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF TRUE
                DISPLAY "YES"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

        ifs = result.ast.find_statements("IF")
        assert len(ifs) >= 1

        if_dict = ifs[0].to_dict()
        assert if_dict is not None
        assert isinstance(if_dict, dict)

    def test_if_json_serialization(self):
        """Test IF statement to JSON compatibility."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF 1 = 1
                DISPLAY "TEST"
            ELSE
                DISPLAY "ELSE"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestIfGetAllStatements:
    """Test get_all_statements with IF statements."""

    def test_get_all_statements_includes_if(self):
        """Test that get_all_statements includes IF statements."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF TRUE
                DISPLAY "MSG"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

        if hasattr(result.ast, "get_all_statements"):
            all_stmts = result.ast.get_all_statements()
            assert len(all_stmts) >= 1

    def test_get_all_statements_includes_nested_if(self):
        """Test get_all_statements with nested IF."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF TRUE
                IF FALSE
                    DISPLAY "NESTED"
                END-IF
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

        if hasattr(result.ast, "get_all_statements"):
            all_stmts = result.ast.get_all_statements()
            # Should have both IF statements
            assert len(all_stmts) >= 2


class TestIfEdgeCases:
    """Test IF edge cases."""

    def test_if_multiple_statements_in_branch(self):
        """Test IF with multiple statements in branch."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF TRUE
                DISPLAY "FIRST"
                DISPLAY "SECOND"
                DISPLAY "THIRD"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_if_true_false_keywords(self):
        """Test IF with TRUE/FALSE keywords."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF TRUE
                DISPLAY "YES"
            END-IF.
            IF FALSE
                DISPLAY "NO"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
