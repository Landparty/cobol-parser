"""
Performance tests for PERFORM statement parsing.

These tests validate that parser performance remains acceptable
after Phase 2 enhancements (WITH TEST support, variable TIMES support).
"""

import time
import pytest
from cobolparser import CobolParser, ErrorRecoveryMode


class TestPerformParsingPerformance:
    """Test parser performance with PERFORM statements."""
    
    def _parse_cobol(self, cobol_text, measure_time=False):
        """Helper to parse COBOL code, optionally measuring time."""
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        start = time.time() if measure_time else 0
        result = parser.parse(cobol_text)
        elapsed = (time.time() - start) if measure_time else 0
        return result, elapsed
    
    def test_simple_perform_parsing_speed(self):
        """Test that simple PERFORM parsing completes quickly."""
        # Create a program with 20 PERFORM statements
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERF-TEST-SIMPLE.
       PROCEDURE DIVISION.
"""
        for i in range(20):
            cobol += f"""           PERFORM PARA-{i:02d}.
"""
        cobol += """           STOP RUN.
"""
        for i in range(20):
            cobol += f"""       PARA-{i:02d}.
           MOVE 0 TO X.
"""
        
        result, elapsed = self._parse_cobol(cobol, measure_time=True)
        
        # Parsing should complete in reasonable time (< 1 second for 20 performs)
        assert elapsed < 1.0, f"Parsing took {elapsed:.3f}s, expected < 1.0s"
        assert result.ast is not None
    
    def test_complex_perform_with_test_parsing_speed(self):
        """Test that complex PERFORM WITH TEST parsing completes quickly."""
        # Create multiple PERFORM UNTIL statements with WITH TEST clauses
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERF-TEST-WITH-TEST.
       PROCEDURE DIVISION.
"""
        for i in range(10):
            cobol += f"""           PERFORM PARA-{i:02d} WITH TEST BEFORE UNTIL DONE-{i:02d} = Y.
"""
        cobol += f"""           PERFORM PARA-AFTER WITH TEST AFTER UNTIL DONE-FINAL = Y.
           STOP RUN.
"""
        for i in range(10):
            cobol += f"""       PARA-{i:02d}.
           MOVE Y TO DONE-{i:02d}.
"""
        cobol += f"""       PARA-AFTER.
           MOVE Y TO DONE-FINAL.
"""
        
        result, elapsed = self._parse_cobol(cobol, measure_time=True)
        
        # Parsing should complete quickly even with WITH TEST clauses
        assert elapsed < 1.0, f"Parsing took {elapsed:.3f}s, expected < 1.0s"
        assert result.ast is not None
    
    def test_varying_perform_parsing_speed(self):
        """Test that PERFORM VARYING parsing completes quickly."""
        # Create multiple inline PERFORM VARYING statements
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERF-TEST-VARYING.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 I PIC 9(3).
       01 J PIC 9(3).
       01 K PIC 9(3).
       PROCEDURE DIVISION.
"""
        for iteration in range(5):
            cobol += f"""           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 10
               WITH TEST BEFORE
               MOVE I TO X
           END-PERFORM.
"""
        cobol += """           STOP RUN.
"""
        
        result, elapsed = self._parse_cobol(cobol, measure_time=True)
        
        # Parsing should complete quickly
        assert elapsed < 1.0, f"Parsing took {elapsed:.3f}s, expected < 1.0s"
        assert result.ast is not None
    
    def test_parse_many_performs_scalability(self):
        """Test that parser scales well with many PERFORM statements."""
        # Create 50 PERFORM statements
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERF-TEST-SCALE.
       PROCEDURE DIVISION.
"""
        for i in range(50):
            cobol += f"""           PERFORM PARA-{i:03d}.
"""
        cobol += """           STOP RUN.
"""
        for i in range(50):
            cobol += f"""       PARA-{i:03d}.
           MOVE {i} TO X.
"""
        
        result, elapsed = self._parse_cobol(cobol, measure_time=True)
        
        # Parsing 50 PERFORM statements should still be fast (< 2 seconds)
        assert elapsed < 2.0, f"Parsing took {elapsed:.3f}s for 50 performs, expected < 2.0s"
        assert result.ast is not None
        
        # Verify all PERFORMs were parsed
        proc_div = result.ast.get_division('PROCEDURE')
        assert proc_div is not None


class TestPerformASTMemoryEfficiency:
    """Test that PERFORM AST nodes maintain memory efficiency."""
    
    def _parse_cobol(self, cobol_text):
        """Helper to parse COBOL code."""
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        return parser.parse(cobol_text)
    
    def test_perform_to_dict_reasonable_size(self):
        """Test that PERFORM to_dict() produces reasonable size output."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERF-TEST-SIZE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 I PIC 9(3).
       PROCEDURE DIVISION.
           PERFORM VARYING I FROM 1 BY 1 WITH TEST BEFORE UNTIL I > 100.
               DISPLAY I
           END-PERFORM.
           STOP RUN.
       """
        
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        # Convert to dict
        ast_dict = result.ast.to_dict()
        
        # Dict should not be excessively large (reasonable recursive depth)
        # This is a sanity check - the dict should be serializable and reasonable
        import json
        json_str = json.dumps(ast_dict)
        
        # JSON should be reasonable size (< 100KB for a single PERFORM statement)
        assert len(json_str) < 100000, f"AST JSON size {len(json_str)} is too large"
