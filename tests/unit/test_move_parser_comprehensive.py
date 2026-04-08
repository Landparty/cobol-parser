"""Comprehensive test suite for MOVE statement parsing.

This module systematically tests MOVE statement variants including:
- Simple MOVE (variable to variable)
- MOVE with literals
- MOVE CORRESPONDING (nested structure moving)
- Multiple targets (MOVE x TO a b c)
- MOVE with data conversion
- MOVE with picture clause interactions
"""

import pytest

from cobolparser import parse_cobol


class TestMoveBasic:
    """Test basic MOVE statement functionality."""

    def test_move_simple(self):
        """Test simple MOVE variable to variable."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 SOURCE PIC X(10).
        01 TARGET PIC X(10).
        PROCEDURE DIVISION.
            MOVE SOURCE TO TARGET.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        assert result.ast is not None

        moves = result.ast.find_statements("MOVE")
        assert len(moves) >= 1

    def test_move_literal_to_variable(self):
        """Test MOVE literal value to variable."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 VAR PIC X(20).
        PROCEDURE DIVISION.
            MOVE "HELLO" TO VAR.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        moves = result.ast.find_statements("MOVE")
        assert len(moves) >= 1

    def test_move_numeric_literal(self):
        """Test MOVE numeric literal."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 NUM PIC 9(5).
        PROCEDURE DIVISION.
            MOVE 12345 TO NUM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_move_figurative_constant(self):
        """Test MOVE with figurative constants (ZERO, SPACE, etc)."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 VAR PIC X(10).
        PROCEDURE DIVISION.
            MOVE ZERO TO VAR.
            MOVE SPACE TO VAR.
            MOVE LOW-VALUE TO VAR.
            MOVE HIGH-VALUE TO VAR.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestMoveMultipleTargets:
    """Test MOVE with multiple target variables."""

    def test_move_to_one_target(self):
        """Test MOVE to single target."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 A PIC X.
        PROCEDURE DIVISION.
            MOVE "X" TO A.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_move_to_multiple_targets(self):
        """Test MOVE with multiple targets."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 A PIC X.
        01 B PIC X.
        01 C PIC X.
        PROCEDURE DIVISION.
            MOVE "X" TO A B C.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        moves = result.ast.find_statements("MOVE")
        assert len(moves) >= 1

    def test_move_multiple_targets_grouped(self):
        """Test MOVE to multiple targets with grouping."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 GRP.
           05 A PIC X.
           05 B PIC X.
        01 C PIC X.
        PROCEDURE DIVISION.
            MOVE "Y" TO GRP C.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestMoveCorresponding:
    """Test MOVE CORRESPONDING (structure-to-structure)."""

    def test_move_corresponding_simple(self):
        """Test MOVE CORRESPONDING with matched fields."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 REC-1.
           05 NAME PIC X(20).
           05 AGE PIC 9(3).
        01 REC-2.
           05 NAME PIC X(20).
           05 AGE PIC 9(3).
        PROCEDURE DIVISION.
            MOVE CORRESPONDING REC-1 TO REC-2.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        moves = result.ast.find_statements("MOVE")
        assert len(moves) >= 1

    def test_move_corresponding_partial_match(self):
        """Test MOVE CORRESPONDING with partial field match."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 SOURCE-REC.
           05 ID PIC 9(5).
           05 NAME PIC X(20).
           05 SALARY PIC 9(7).
        01 TARGET-REC.
           05 ID PIC 9(5).
           05 NAME PIC X(30).
        PROCEDURE DIVISION.
            MOVE CORRESPONDING SOURCE-REC TO TARGET-REC.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestMoveDataConversion:
    """Test MOVE with data type conversions."""

    def test_move_numeric_to_string(self):
        """Test MOVE numeric to alphanumeric."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 NUM PIC 999 VALUE 123.
        01 STR PIC X(10).
        PROCEDURE DIVISION.
            MOVE NUM TO STR.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_move_string_to_numeric(self):
        """Test MOVE alphanumeric to numeric."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 STR PIC X(10) VALUE "456".
        01 NUM PIC 999.
        PROCEDURE DIVISION.
            MOVE STR TO NUM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_move_between_picture_clauses(self):
        """Test MOVE with different picture clause lengths."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 SHORT PIC X(5).
        01 LONG PIC X(20).
        01 NUM1 PIC 99.
        01 NUM2 PIC 9(5).
        PROCEDURE DIVISION.
            MOVE SHORT TO LONG.
            MOVE NUM1 TO NUM2.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestMovePictureClauseInteraction:
    """Test MOVE interactions with picture clause."""

    def test_move_with_signed_numeric(self):
        """Test MOVE with signed numeric."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 SIGNED PIC S9(5) VALUE -100.
        01 UNSIGNED PIC 9(5).
        PROCEDURE DIVISION.
            MOVE SIGNED TO UNSIGNED.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_move_with_decimal(self):
        """Test MOVE with decimal numbers."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 DEC1 PIC 9(5)V9(2) VALUE 123.45.
        01 DEC2 PIC 9(7)V9(3).
        PROCEDURE DIVISION.
            MOVE DEC1 TO DEC2.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_move_with_comp_usage(self):
        """Test MOVE to/from COMP (binary) variables."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 DISPLAY-VAR PIC 9(5).
        01 COMP-VAR PIC 9(5) COMP.
        PROCEDURE DIVISION.
            MOVE DISPLAY-VAR TO COMP-VAR.
            MOVE COMP-VAR TO DISPLAY-VAR.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestMoveSerialization:
    """Test MOVE statement serialization."""

    def test_move_to_dict(self):
        """Test MOVE statement to_dict() serialization."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 A PIC X.
        01 B PIC X.
        PROCEDURE DIVISION.
            MOVE A TO B.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

        moves = result.ast.find_statements("MOVE")
        assert len(moves) >= 1

        move_dict = moves[0].to_dict()
        assert move_dict is not None
        assert isinstance(move_dict, dict)


class TestMoveEdgeCases:
    """Test MOVE edge cases."""

    def test_move_self_to_self(self):
        """Test MOVE variable to itself (edge case)."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 VAR PIC X(10).
        PROCEDURE DIVISION.
            MOVE VAR TO VAR.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_move_with_perform(self):
        """Test MOVE inside PERFORM loop."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 COUNTER PIC 9(4).
        01 RESULT PIC 9(4).
        PROCEDURE DIVISION.
            PERFORM 5 TIMES
                MOVE COUNTER TO RESULT
                ADD 1 TO COUNTER
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_move_inside_if(self):
        """Test MOVE inside IF statement."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 FLAG PIC X VALUE "N".
        01 VAL PIC 9.
        PROCEDURE DIVISION.
            IF FLAG = "Y"
                MOVE 1 TO VAL
            ELSE
                MOVE 0 TO VAL
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_multiple_moves_in_sequence(self):
        """Test multiple consecutive MOVE statements."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 A PIC X.
        01 B PIC X.
        01 C PIC X.
        PROCEDURE DIVISION.
            MOVE "1" TO A.
            MOVE A TO B.
            MOVE B TO C.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        moves = result.ast.find_statements("MOVE")
        assert len(moves) >= 3


class TestMoveGetAllStatements:
    """Test get_all_statements with MOVE."""

    def test_get_all_statements_includes_moves(self):
        """Test that get_all_statements includes MOVE statements."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 A PIC X.
        01 B PIC X.
        PROCEDURE DIVISION.
            MOVE A TO B.
            DISPLAY B.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

        if hasattr(result.ast, "get_all_statements"):
            all_stmts = result.ast.get_all_statements()
            move_stmts = [
                s
                for s in all_stmts
                if hasattr(s, "statement_type") and s.statement_type == "MOVE"
            ]
            assert len(move_stmts) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
