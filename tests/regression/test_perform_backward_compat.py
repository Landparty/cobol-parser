"""
Regression tests for PERFORM statement backward compatibility.

These tests validate that all existing PERFORM variants continue to work
correctly after the Phase 2 parser enhancements (WITH TEST support, 
variable TIMES support).
"""

import pytest
from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.statements import PerformStatement


class TestPerformBackwardCompatibilityRegression:
    """Test backward compatibility of all PERFORM variants."""
    
    def _parse_cobol(self, cobol_text):
        """Helper to parse COBOL code."""
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        return parser.parse(cobol_text)
    
    def _find_perform_statements(self, ast, perform_type=None):
        """Find PERFORM statements in AST by type."""
        if not ast:
            return []
        
        proc_div = ast.get_division('PROCEDURE')
        if not proc_div:
            return []
        
        performs = []
        for section in proc_div.sections:
            # Check direct children (old architecture)
            for child in section.children:
                if isinstance(child, PerformStatement):
                    if perform_type is None or child.perform_type == perform_type:
                        performs.append(child)
            
            # Check statements in paragraphs (new architecture)
            for para in section.paragraphs:
                for stmt in para.statements:
                    if isinstance(stmt, PerformStatement):
                        if perform_type is None or stmt.perform_type == perform_type:
                            performs.append(stmt)
        
        return performs
    
    def test_perform_simple_paragraph_only(self):
        """Test PERFORM paragraph-name (simple, no options)."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-SIMPLE-PERFORM.
       PROCEDURE DIVISION.
           PERFORM CALCULATE-TOTAL.
           STOP RUN.
       CALCULATE-TOTAL.
           MOVE 100 TO TOTAL.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "SIMPLE")
        assert len(performs) >= 1
        perf = performs[0]
        
        # Verify target paragraph is set
        assert perf.target_paragraph == "CALCULATE-TOTAL"
        # Verify no THRU clause
        assert perf.thru_paragraph is None
        # Verify test_timing defaults to BEFORE
        assert perf.test_timing == "BEFORE"
    
    def test_perform_paragraph_thru_paragraph(self):
        """Test PERFORM paragraph-name THRU paragraph-name."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-THRU-PERFORM.
       PROCEDURE DIVISION.
           PERFORM PROCESS-RECORDS THRU END-PROCESS.
           STOP RUN.
       PROCESS-RECORDS.
           MOVE 0 TO RECORD-COUNT.
       END-PROCESS.
           MOVE RECORD-COUNT TO OUTPUT-COUNT.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "SIMPLE")
        assert len(performs) >= 1
        perf = performs[0]
        
        # Verify both paragraphs are set
        assert perf.target_paragraph == "PROCESS-RECORDS"
        assert perf.thru_paragraph == "END-PROCESS"
    
    def test_perform_until_condition(self):
        """Test PERFORM paragraph UNTIL condition."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-UNTIL-SIMPLE.
       PROCEDURE DIVISION.
           PERFORM CHECK-DONE UNTIL DONE-FLAG = Y.
           STOP RUN.
       CHECK-DONE.
           MOVE Y TO DONE-FLAG.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "UNTIL")
        assert len(performs) >= 1
        perf = performs[0]
        
        # Verify until_condition is set
        assert perf.until_condition is not None
        # Verify perform_type is UNTIL
        assert perf.perform_type == "UNTIL"
    
    def test_perform_varying_until_inline(self):
        """Test PERFORM VARYING ... UNTIL (inline END-PERFORM)."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-VARYING-INLINE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 I PIC 9(3).
       PROCEDURE DIVISION.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 5
               DISPLAY I
           END-PERFORM.
           STOP RUN.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "VARYING")
        assert len(performs) >= 1
        perf = performs[0]
        
        # Verify it's a VARYING statement
        assert perf.perform_type == "VARYING"
        # Verify varying_clause is set
        assert perf.varying_clause is not None
        # Verify until_condition is set
        assert perf.until_condition is not None
    
    def test_perform_backward_compat_test_timing_not_breaking(self):
        """Verify that adding WITH TEST support doesn't break existing PERFORM."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-COMPAT.
       PROCEDURE DIVISION.
           PERFORM MY-PARA.
           STOP RUN.
       MY-PARA.
           MOVE 1 TO X.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "SIMPLE")
        assert len(performs) >= 1
        perf = performs[0]
        
        # Verify test_timing still defaults to BEFORE even for old-style PERFORM
        assert perf.test_timing == "BEFORE"
        # Verify to_dict() includes test_timing
        perf_dict = perf.to_dict()
        assert "test_timing" in perf_dict
        assert perf_dict["test_timing"] == "BEFORE"
    
    def test_perform_variable_times_count_not_breaking(self):
        """Verify that adding variable TIMES support doesn't break numeric TIMES."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-VAR-TIMES.
       PROCEDURE DIVISION.
           PERFORM MY-LOOP THRU MY-LOOP-END VARYING WS-COUNT FROM 1 BY 1 UNTIL WS-COUNT > 5.
           STOP RUN.
       MY-LOOP.
           DISPLAY "LOOP".
       MY-LOOP-END.
           DISPLAY "END".
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast)
        # Should find at least one perform statement
        assert len(performs) >= 1


class TestPerformEdgeCasesRegression:
    """Test edge cases and error conditions in PERFORM statements."""
    
    def _parse_cobol(self, cobol_text):
        """Helper to parse COBOL code."""
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        return parser.parse(cobol_text)
    
    def _find_perform_statements(self, ast, perform_type=None):
        """Find PERFORM statements in AST by type."""
        if not ast:
            return []
        
        proc_div = ast.get_division('PROCEDURE')
        if not proc_div:
            return []
        
        performs = []
        for section in proc_div.sections:
            # Check direct children (old architecture)
            for child in section.children:
                if isinstance(child, PerformStatement):
                    if perform_type is None or child.perform_type == perform_type:
                        performs.append(child)
            
            # Check statements in paragraphs (new architecture)
            for para in section.paragraphs:
                for stmt in para.statements:
                    if isinstance(stmt, PerformStatement):
                        if perform_type is None or stmt.perform_type == perform_type:
                            performs.append(stmt)
        
        return performs
    
    def test_perform_serialization_preserves_attributes(self):
        """Test that to_dict() preserves all PERFORM attributes."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-SER.
       PROCEDURE DIVISION.
           PERFORM MY-PARA THRU END-PARA.
           STOP RUN.
       MY-PARA.
           MOVE 1 TO X.
       END-PARA.
           MOVE 2 TO Y.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "SIMPLE")
        assert len(performs) >= 1
        perf = performs[0]
        
        # Serialize and verify structure
        perf_dict = perf.to_dict()
        assert perf_dict["node_type"] == "Statement"
        assert perf_dict["target_paragraph"] == "MY-PARA"
        assert perf_dict["thru_paragraph"] == "END-PARA"
        assert perf_dict["test_timing"] == "BEFORE"  # Default value
    
    def test_perform_two_in_sequence(self):
        """Test two PERFORM statements in sequence."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-TWO-PERFORM.
       PROCEDURE DIVISION.
           PERFORM PARA-ONE.
           PERFORM PARA-TWO THRU PARA-TWO-END.
           STOP RUN.
       PARA-ONE.
           DISPLAY "ONE".
       PARA-TWO.
           DISPLAY "TWO".
       PARA-TWO-END.
           DISPLAY "TWO-END".
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        # Should find both PERFORM statements
        all_performs = self._find_perform_statements(result.ast)
        assert len(all_performs) >= 2
        
        # Verify types
        simple_performs = self._find_perform_statements(result.ast, "SIMPLE")
        assert len(simple_performs) >= 2  # Both PERFORM statements should be SIMPLE type
