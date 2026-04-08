"""Comprehensive test suite for PERFORM statement parsing.

This module systematically tests all PERFORM variants including:
- PERFORM UNTIL with test BEFORE/AFTER
- PERFORM TIMES with numeric/variable counts
- PERFORM VARYING with conditions
- PERFORM THRU (paragraph ranges)
- Nested PERFORM statements
- Error cases and edge conditions
"""

import pytest

from cobolparser import parse_cobol


class TestPerformUntilBasic:
    """Test basic PERFORM UNTIL functionality."""

    def test_perform_until_simple(self):
        """Test simple PERFORM UNTIL loop."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-COUNTER PIC 9(4) VALUE 0.
        PROCEDURE DIVISION.
            PERFORM UNTIL WS-COUNTER >= 10
                DISPLAY WS-COUNTER
                ADD 1 TO WS-COUNTER
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        assert result.ast is not None

        # Find the PERFORM statement
        performs = result.ast.find_statements("PERFORM")
        assert len(performs) >= 1

        perform = performs[0]
        assert hasattr(perform, "condition") or hasattr(perform, "until_condition")

    def test_perform_until_with_test_before(self):
        """Test PERFORM UNTIL WITH TEST BEFORE (default)."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM UNTIL TRUE
                DISPLAY "ONCE"
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        performs = result.ast.find_statements("PERFORM")
        assert len(performs) >= 1

    def test_perform_until_with_test_after(self):
        """Test PERFORM UNTIL WITH TEST AFTER."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM UNTIL WS-FLAG = 1 WITH TEST AFTER
                DISPLAY "LOOP"
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        performs = result.ast.find_statements("PERFORM")
        assert len(performs) >= 1


class TestPerformTimes:
    """Test PERFORM n TIMES functionality."""

    def test_perform_times_numeric_literal(self):
        """Test PERFORM ... TIMES with numeric literal."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM 5 TIMES
                DISPLAY "FIVE TIMES"
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        performs = result.ast.find_statements("PERFORM")
        assert len(performs) >= 1

    def test_perform_times_variable(self):
        """Test PERFORM ... TIMES with variable."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 LOOP-COUNT PIC 9(4) VALUE 3.
        PROCEDURE DIVISION.
            PERFORM LOOP-COUNT TIMES
                DISPLAY "VARIABLE TIMES"
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        performs = result.ast.find_statements("PERFORM")
        assert len(performs) >= 1

    def test_perform_times_to_dict(self):
        """Test PERFORM TIMES serialization to dictionary."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM 3 TIMES
                DISPLAY "TEST"
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        performs = result.ast.find_statements("PERFORM")
        assert len(performs) >= 1

        perform_dict = performs[0].to_dict()
        assert perform_dict is not None
        assert isinstance(perform_dict, dict)


class TestPerformVarying:
    """Test PERFORM VARYING (loop with index modification)."""

    def test_perform_varying_simple(self):
        """Test PERFORM VARYING with simple range."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 COUNTER PIC 9(4) VALUE 1.
        PROCEDURE DIVISION.
            PERFORM VARYING COUNTER FROM 1 BY 1
                UNTIL COUNTER > 10
                DISPLAY COUNTER
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        performs = result.ast.find_statements("PERFORM")
        assert len(performs) >= 1

    def test_perform_varying_with_test_before(self):
        """Test PERFORM VARYING WITH TEST BEFORE."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 I PIC 9(4) VALUE 1.
        PROCEDURE DIVISION.
            PERFORM VARYING I FROM 1 BY 1
                UNTIL I > 5
                WITH TEST BEFORE
                DISPLAY I
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        performs = result.ast.find_statements("PERFORM")
        assert len(performs) >= 1

    def test_perform_varying_with_test_after(self):
        """Test PERFORM VARYING WITH TEST AFTER."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 J PIC 9(4) VALUE 1.
        PROCEDURE DIVISION.
            PERFORM VARYING J FROM 1 BY 1
                UNTIL J > 3
                WITH TEST AFTER
                DISPLAY J
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        performs = result.ast.find_statements("PERFORM")
        assert len(performs) >= 1


class TestPerformThru:
    """Test PERFORM paragraph-name THRU paragraph-name."""

    def test_perform_thru_simple(self):
        """Test PERFORM paragraph THRU paragraph."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM PARA-1 THRU PARA-3.
            STOP RUN.
        PARA-1.
            DISPLAY "FIRST".
        PARA-2.
            DISPLAY "SECOND".
        PARA-3.
            DISPLAY "THIRD".
        """
        result = parse_cobol(source)
        assert result.success
        performs = result.ast.find_statements("PERFORM")
        # Should have one PERFORM THRU
        assert len(performs) >= 1
        assert any(p.thru_paragraph is not None for p in performs)

    def test_perform_thru_with_times(self):
        """Test PERFORM paragraph THRU paragraph n TIMES."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM PARA-A THRU PARA-B 2 TIMES.
            STOP RUN.
        PARA-A.
            DISPLAY "A".
        PARA-B.
            DISPLAY "B".
        """
        result = parse_cobol(source)
        assert result.success


class TestPerformNested:
    """Test nested PERFORM statements."""

    def test_nested_perform_until(self):
        """Test PERFORM UNTIL containing another PERFORM."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM UNTIL TRUE
                PERFORM 2 TIMES
                    DISPLAY "NESTED"
                END-PERFORM
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        performs = result.ast.find_statements("PERFORM")
        assert len(performs) >= 2

    def test_deeply_nested_perform(self):
        """Test deeply nested PERFORM statements."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM UNTIL FALSE
                PERFORM VARYING I FROM 1 BY 1 UNTIL I > 3
                    PERFORM 2 TIMES
                        DISPLAY "DEEP"
                    END-PERFORM
                END-PERFORM
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        performs = result.ast.find_statements("PERFORM")
        assert len(performs) >= 3


class TestPerformEdgeCases:
    """Test edge cases and error conditions."""

    def test_perform_without_end_perform(self):
        """Test PERFORM at paragraph level (without END-PERFORM)."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM DO-WORK.
            STOP RUN.
        DO-WORK.
            DISPLAY "WORK".
        """
        result = parse_cobol(source)
        assert result.success
        performs = result.ast.find_statements("PERFORM")
        assert len(performs) >= 1

    def test_perform_get_all_statements(self):
        """Test get_all_statements includes nested PERFORM statements."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM UNTIL FALSE
                DISPLAY "OUTER"
                PERFORM 1 TIMES
                    DISPLAY "INNER"
                END-PERFORM
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

        all_stmts = (
            result.ast.get_all_statements()
            if hasattr(result.ast, "get_all_statements")
            else []
        )
        assert len(all_stmts) >= 2  # At least the nested performs

    def test_perform_serialization(self):
        """Test PERFORM statement JSON serialization."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM 3 TIMES
                DISPLAY "SERIALIZE"
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

        performs = result.ast.find_statements("PERFORM")
        assert len(performs) >= 1

        # Should be able to serialize to dict
        perform_dict = performs[0].to_dict()
        assert perform_dict is not None


class TestPerformWithCallStatements:
    """Test PERFORM combined with CALL statements."""

    def test_perform_with_call_inside(self):
        """Test PERFORM containing CALL statement."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM 1 TIMES
                CALL "SUBPROGRAM"
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

        performs = result.ast.find_statements("PERFORM")
        calls = result.ast.find_statements("CALL")
        assert len(performs) >= 1
        assert len(calls) >= 1

    def test_perform_and_call_interaction(self):
        """Test interaction between PERFORM and CALL."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM PARA-WITH-CALL 3 TIMES.
            STOP RUN.
        PARA-WITH-CALL.
            CALL "WORKER".
        """
        result = parse_cobol(source)
        assert result.success


class TestPerformBackwardCompatibility:
    """Test backward compatibility with older PERFORM syntax."""

    def test_perform_simple_paragraph_only(self):
        """Test legacy PERFORM with just paragraph name."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM WORK-PARA.
            STOP RUN.
        WORK-PARA.
            DISPLAY "WORK".
        """
        result = parse_cobol(source)
        assert result.success
        performs = result.ast.find_statements("PERFORM")
        assert len(performs) >= 1

    def test_perform_inline_end_perform(self):
        """Test inline PERFORM with END-PERFORM."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM
                DISPLAY "INLINE"
            END-PERFORM.
        """
        result = parse_cobol(source)
        assert result.success


class TestPerformConditions:
    """Test various UNTIL condition types."""

    def test_perform_until_true_false(self):
        """Test PERFORM UNTIL TRUE/FALSE."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM UNTIL TRUE END-PERFORM.
            PERFORM UNTIL FALSE END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_perform_until_complex_condition(self):
        """Test PERFORM UNTIL with complex condition."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 A PIC 9 VALUE 0.
        01 B PIC 9 VALUE 0.
        PROCEDURE DIVISION.
            PERFORM UNTIL A = 1 AND B = 1 OR A = 2
                DISPLAY "CONDITION"
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
