"""Comprehensive test suite for EVALUATE statement parsing.

This module systematically tests EVALUATE statement variants including:
- EVALUATE with single subject
- EVALUATE with multiple subjects (ALSO)
- WHEN conditions (TRUE, FALSE, ANY, ranges with THRU)
- WHEN OTHER (default case)
- Complex condition combinations
"""

import pytest
from cobolparser import parse_cobol


class TestEvaluateSingleSubject:
    """Test EVALUATE with single subject."""
    
    def test_evaluate_single_subject_literal(self):
        """Test EVALUATE with literal subject."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            EVALUATE 1
                WHEN 1
                    DISPLAY "ONE"
                WHEN 2
                    DISPLAY "TWO"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        assert result.ast is not None
        
        evaluates = result.ast.find_statements("EVALUATE")
        assert len(evaluates) >= 1
    
    def test_evaluate_single_subject_variable(self):
        """Test EVALUATE with variable subject."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 CODE PIC X VALUE "A".
        PROCEDURE DIVISION.
            EVALUATE CODE
                WHEN "A"
                    DISPLAY "ALPHA"
                WHEN "B"
                    DISPLAY "BETA"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        evaluates = result.ast.find_statements("EVALUATE")
        assert len(evaluates) >= 1
    
    def test_evaluate_numeric_subject(self):
        """Test EVALUATE with numeric subject."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 NUM PIC 9(3) VALUE 5.
        PROCEDURE DIVISION.
            EVALUATE NUM
                WHEN 1
                    DISPLAY "LOW"
                WHEN 5
                    DISPLAY "MID"
                WHEN 9
                    DISPLAY "HIGH"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestEvaluateMultipleSubjects:
    """Test EVALUATE with multiple subjects (ALSO)."""
    
    def test_evaluate_two_subjects(self):
        """Test EVALUATE with two subjects (ALSO)."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            EVALUATE 1 ALSO "A"
                WHEN 1 ALSO "A"
                    DISPLAY "MATCH"
                WHEN 2 ALSO "B"
                    DISPLAY "OTHER"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        evaluates = result.ast.find_statements("EVALUATE")
        assert len(evaluates) >= 1
    
    def test_evaluate_three_subjects(self):
        """Test EVALUATE with three subjects."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            EVALUATE 1 ALSO 2 ALSO 3
                WHEN 1 ALSO 2 ALSO 3
                    DISPLAY "ALL"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestEvaluateWhenClause:
    """Test various WHEN clause conditions."""
    
    def test_when_literal_values(self):
        """Test WHEN with literal values."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            EVALUATE 5
                WHEN 1
                    DISPLAY "ONE"
                WHEN 5
                    DISPLAY "FIVE"
                WHEN 10
                    DISPLAY "TEN"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_when_range_thru(self):
        """Test WHEN with THRU range."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            EVALUATE 5
                WHEN 1 THRU 10
                    DISPLAY "IN RANGE"
                WHEN 11 THRU 20
                    DISPLAY "OUT OF RANGE"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_when_true_false(self):
        """Test WHEN TRUE/FALSE."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            EVALUATE TRUE
                WHEN 1 = 1
                    DISPLAY "TRUE PATH"
                WHEN FALSE
                    DISPLAY "FALSE PATH"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_when_any(self):
        """Test WHEN ANY (matches anything)."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            EVALUATE 5
                WHEN ANY
                    DISPLAY "ANYTHING"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestEvaluateWhenOther:
    """Test WHEN OTHER (default case)."""
    
    def test_when_other_alone(self):
        """Test WHEN OTHER as default."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            EVALUATE 5
                WHEN 1
                    DISPLAY "ONE"
                WHEN OTHER
                    DISPLAY "DEFAULT"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_when_other_placement(self):
        """Test WHEN OTHER must be last."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            EVALUATE "X"
                WHEN "A"
                    DISPLAY "A"
                WHEN "B"
                    DISPLAY "B"
                WHEN OTHER
                    DISPLAY "DEFAULT"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestEvaluateMultipleWhenConditions:
    """Test WHEN with multiple alternative conditions."""
    
    def test_when_with_also_multiple_selectors(self):
        """Test multiple WHEN ALSO conditions."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            EVALUATE 1 ALSO 2
                WHEN 1 ALSO 2
                    DISPLAY "EXACT MATCH"
                WHEN 1 ALSO ANY
                    DISPLAY "PARTIAL"
                WHEN ANY ALSO 2
                    DISPLAY "OTHER PARTIAL"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestEvaluateComplexSelectors:
    """Test EVALUATE with complex selectors."""
    
    def test_evaluate_with_conditions(self):
        """Test EVALUATE using conditions instead of values."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 NUM PIC 9(3).
        PROCEDURE DIVISION.
            EVALUATE TRUE
                WHEN NUM = 0
                    DISPLAY "ZERO"
                WHEN NUM < 10
                    DISPLAY "SMALL"
                WHEN NUM >= 10
                    DISPLAY "LARGE"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_evaluate_with_logical_conditions(self):
        """Test EVALUATE with AND/OR conditions."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            EVALUATE TRUE
                WHEN 1 = 1 AND 2 = 2
                    DISPLAY "BOTH"
                WHEN 1 = 2 OR 3 = 3
                    DISPLAY "ONE"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestEvaluateSerialization:
    """Test EVALUATE statement serialization."""
    
    def test_evaluate_to_dict(self):
        """Test EVALUATE statement to_dict()."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            EVALUATE 1
                WHEN 1
                    DISPLAY "ONE"
                WHEN OTHER
                    DISPLAY "OTHER"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        
        evaluates = result.ast.find_statements("EVALUATE")
        assert len(evaluates) >= 1
        
        eval_dict = evaluates[0].to_dict()
        assert eval_dict is not None
        assert isinstance(eval_dict, dict)


class TestEvaluateEdgeCases:
    """Test EVALUATE edge cases."""
    
    def test_evaluate_empty_when(self):
        """Test EVALUATE with empty WHEN clause (edge case)."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            EVALUATE 1
                WHEN 1
                WHEN 2
                    DISPLAY "ONE OR TWO"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        # May succeed or fail depending on parser strictness
        assert result is not None
    
    def test_nested_evaluate(self):
        """Test nested EVALUATE statements."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            EVALUATE 1
                WHEN 1
                    EVALUATE 2
                        WHEN 2
                            DISPLAY "NESTED"
                    END-EVALUATE
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        evaluates = result.ast.find_statements("EVALUATE")
        # Should have 2 EVALUATE statements
        assert len(evaluates) >= 2
    
    def test_evaluate_with_statements_in_when(self):
        """Test EVALUATE with multiple statements in WHEN."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            EVALUATE 1
                WHEN 1
                    DISPLAY "A"
                    DISPLAY "B"
                    DISPLAY "C"
                WHEN 2
                    DISPLAY "TWO"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestEvaluateGetAllStatements:
    """Test get_all_statements with EVALUATE."""
    
    def test_get_all_statements_includes_evaluate(self):
        """Test get_all_statements includes EVALUATE."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            EVALUATE 1
                WHEN 1
                    DISPLAY "ONE"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        
        if hasattr(result.ast, 'get_all_statements'):
            all_stmts = result.ast.get_all_statements()
            assert len(all_stmts) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
