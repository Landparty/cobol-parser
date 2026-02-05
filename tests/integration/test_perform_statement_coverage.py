"""
Integration tests for PERFORM statement coverage enhancements.

Tests the following enhancements:
- PERFORM UNTIL standalone support
- WITH TEST BEFORE/AFTER support
- Variable TIMES support
- Combinations with VARYING
"""

import pytest
from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.statements import PerformStatement


class TestPerformStatementIntegration:
    """Integration tests for PERFORM statement enhancements."""
    
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
        # Traverse sections and find PerformStatement children
        for section in proc_div.sections:
            # Check if it's a CobolParagraph (no explicit sections) or CobolSection
            if hasattr(section, 'paragraphs'):
                # It's a CobolSection - has paragraphs
                for para in section.paragraphs:
                    for stmt in para.statements:
                        if isinstance(stmt, PerformStatement):
                            if perform_type is None or stmt.perform_type == perform_type:
                                performs.append(stmt)
                # Also check direct children (old architecture)
                for child in section.children:
                    if isinstance(child, PerformStatement):
                        if perform_type is None or child.perform_type == perform_type:
                            performs.append(child)
            else:
                # It's a CobolParagraph (no explicit sections case)
                for stmt in section.statements:
                    if isinstance(stmt, PerformStatement):
                        if perform_type is None or stmt.perform_type == perform_type:
                            performs.append(stmt)
        
        return performs
    
    def test_perform_until_simple(self):
        """Test PERFORM UNTIL with default test timing."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-UNTIL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-EOF PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           PERFORM READ-RECORD UNTIL WS-EOF = "Y".
           STOP RUN.
       READ-RECORD.
           MOVE 'Y' TO WS-EOF.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "UNTIL")
        assert len(performs) >= 1
        assert performs[0].until_condition is not None
        assert performs[0].test_timing == "BEFORE"
    
    def test_perform_until_with_test_before(self):
        """Test PERFORM UNTIL WITH TEST BEFORE."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-BEFORE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-EOF PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           PERFORM READ-RECORD WITH TEST BEFORE UNTIL WS-EOF = "Y".
           STOP RUN.
       READ-RECORD.
           MOVE 'Y' TO WS-EOF.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "UNTIL")
        assert len(performs) >= 1
        assert performs[0].test_timing == "BEFORE"
    
    def test_perform_until_with_test_after(self):
        """Test PERFORM UNTIL WITH TEST AFTER."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-AFTER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-EOF PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           PERFORM READ-RECORD WITH TEST AFTER UNTIL WS-EOF = "Y".
           STOP RUN.
       READ-RECORD.
           MOVE 'Y' TO WS-EOF.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "UNTIL")
        assert len(performs) >= 1
        assert performs[0].test_timing == "AFTER"
    
    def test_perform_times_variable(self):
        """Test PERFORM TIMES with variable instead of literal."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-TIMES-VAR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-COUNT PIC 9(3) VALUE 10.
       PROCEDURE DIVISION.
           PERFORM PROCESS-RECORD WS-COUNT TIMES.
           STOP RUN.
       PROCESS-RECORD.
           MOVE 0 TO WS-COUNT.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "TIMES")
        assert len(performs) >= 1
        # Variable name should be preserved, not converted to int
        assert performs[0].times_count == "WS-COUNT"
    
    def test_perform_varying_with_test_before(self):
        """Test PERFORM VARYING WITH TEST BEFORE."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-VAR-BEFORE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 I PIC 9(3).
       PROCEDURE DIVISION.
           PERFORM VARYING I FROM 1 BY 1
               WITH TEST BEFORE
               UNTIL I > 10
               MOVE I TO WS-COUNT
           END-PERFORM.
           STOP RUN.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "VARYING")
        assert len(performs) >= 1
        assert performs[0].test_timing == "BEFORE"
    
    def test_perform_varying_with_test_after(self):
        """Test PERFORM VARYING WITH TEST AFTER."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-VAR-AFTER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 I PIC 9(3).
       PROCEDURE DIVISION.
           PERFORM VARYING I FROM 1 BY 1
               WITH TEST AFTER
               UNTIL I > 10
               MOVE I TO WS-COUNT
           END-PERFORM.
           STOP RUN.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "VARYING")
        assert len(performs) >= 1
        assert performs[0].test_timing == "AFTER"
    
    def test_perform_to_dict_test_timing(self):
        """Test that to_dict() includes test_timing field."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-DICT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-EOF PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           PERFORM READ-RECORD WITH TEST AFTER UNTIL WS-EOF = "Y".
           STOP RUN.
       READ-RECORD.
           MOVE 'Y' TO WS-EOF.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "UNTIL")
        assert len(performs) >= 1
        
        perform_dict = performs[0].to_dict()
        assert "test_timing" in perform_dict
        assert perform_dict["test_timing"] == "AFTER"
    
    def test_perform_to_dict_variable_times(self):
        """Test that to_dict() preserves variable times_count."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-TIMES-DICT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-COUNT PIC 9(3) VALUE 10.
       PROCEDURE DIVISION.
           PERFORM PROCESS-RECORD WS-COUNT TIMES.
           STOP RUN.
       PROCESS-RECORD.
           MOVE 0 TO WS-COUNT.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "TIMES")
        assert len(performs) >= 1
        
        perform_dict = performs[0].to_dict()
        assert "times_count" in perform_dict
        assert perform_dict["times_count"] == "WS-COUNT"


class TestPerformBackwardCompatibility:
    """Ensure existing PERFORM variants still work correctly."""
    
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
            if hasattr(section, 'children'):
                for child in section.children:
                    if isinstance(child, PerformStatement):
                        if perform_type is None or child.perform_type == perform_type:
                            performs.append(child)
            
            # Check statements in paragraphs (new architecture)
            # Handle both CobolSection (has .paragraphs) and CobolParagraph (has .statements directly)
            if hasattr(section, 'paragraphs'):
                for para in section.paragraphs:
                    for stmt in para.statements:
                        if isinstance(stmt, PerformStatement):
                            if perform_type is None or stmt.perform_type == perform_type:
                                performs.append(stmt)
            elif hasattr(section, 'statements'):
                # If section is a CobolParagraph, statements are directly on it
                for stmt in section.statements:
                    if isinstance(stmt, PerformStatement):
                        if perform_type is None or stmt.perform_type == perform_type:
                            performs.append(stmt)
        
        return performs
    
    def test_backward_compat_simple(self):
        """Ensure SIMPLE PERFORM still works."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-SIMPLE.
       PROCEDURE DIVISION.
           PERFORM CALC-TOTAL.
           STOP RUN.
       CALC-TOTAL.
           MOVE 0 TO WS-TOTAL.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "SIMPLE")
        assert len(performs) >= 1
    
    def test_backward_compat_times_numeric(self):
        """Ensure numeric TIMES still works."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-TIMES.
       PROCEDURE DIVISION.
           PERFORM INIT-ARRAY 100 TIMES.
           STOP RUN.
       INIT-ARRAY.
           MOVE 0 TO WS-ITEM.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "TIMES")
        assert len(performs) >= 1
    
    def test_backward_compat_varying(self):
        """Ensure VARYING still works."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-VARYING.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 I PIC 9(3).
       PROCEDURE DIVISION.
           PERFORM VARYING I FROM 1 BY 1
               UNTIL I > 10
               MOVE I TO WS-COUNT
           END-PERFORM.
           STOP RUN.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        
        performs = self._find_perform_statements(result.ast, "VARYING")
        assert len(performs) >= 1
