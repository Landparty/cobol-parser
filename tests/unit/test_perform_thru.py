"""Unit tests for PERFORM THRU statement parsing."""

import pytest
from cobolparser.parser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode


class TestPerformThru:
    """Test PERFORM THRU statement parsing."""
    
    def test_simple_perform_thru(self):
        """Test basic PERFORM paragraph THRU paragraph."""
        source = """
            IDENTIFICATION DIVISION.
            PROGRAM-ID. TEST-THRU.
            PROCEDURE DIVISION.
            MAIN-PARA.
                PERFORM PARA-START THRU PARA-END.
                STOP RUN.
            PARA-START.
                DISPLAY 'Start'.
            PARA-MIDDLE.
                DISPLAY 'Middle'.
            PARA-END.
                DISPLAY 'End'.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)
        
        assert result is not None
        assert result.success, f"Parse failed: {result.errors}"
        assert result.ast is not None
        
        # Get procedure division
        proc_div = result.ast.get_division("PROCEDURE")
        assert proc_div is not None
        
        # Find the MAIN-PARA section
        main_para = next((s for s in proc_div.sections if s.section_name == "MAIN-PARA"), None)
        assert main_para is not None, "MAIN-PARA should exist"
        
        # Find the PERFORM statement
        perform_stmts = [c for c in main_para.children if hasattr(c, 'target_paragraph')]
        assert len(perform_stmts) > 0, "Should have at least one PERFORM statement"
        
        perform_stmt = perform_stmts[0]
        assert perform_stmt.target_paragraph == "PARA-START"
        assert perform_stmt.thru_paragraph == "PARA-END"
        
        print(f"✅ PERFORM THRU captured: {perform_stmt.target_paragraph} THRU {perform_stmt.thru_paragraph}")
    
    def test_perform_thru_with_times(self):
        """Test PERFORM paragraph THRU paragraph n TIMES."""
        source = """
            IDENTIFICATION DIVISION.
            PROGRAM-ID. TEST-THRU-TIMES.
            PROCEDURE DIVISION.
            MAIN-PARA.
                PERFORM PARA-A THRU PARA-B 5 TIMES.
                STOP RUN.
            PARA-A.
                DISPLAY 'A'.
            PARA-B.
                DISPLAY 'B'.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)
        
        assert result is not None
        assert result.success, f"Parse failed: {result.errors}"
        assert result.ast is not None
        
        # Get procedure division
        proc_div = result.ast.get_division("PROCEDURE")
        assert proc_div is not None
        
        # Find the PERFORM statement
        main_para = next((s for s in proc_div.sections if s.section_name == "MAIN-PARA"), None)
        assert main_para is not None
        
        perform_stmts = [c for c in main_para.children if hasattr(c, 'target_paragraph')]
        assert len(perform_stmts) > 0
        
        perform_stmt = perform_stmts[0]
        assert perform_stmt.target_paragraph == "PARA-A"
        assert perform_stmt.thru_paragraph == "PARA-B"
        assert perform_stmt.times_count == 5
        assert perform_stmt.perform_type == "TIMES"
        
        print(f"✅ PERFORM THRU TIMES captured: {perform_stmt.target_paragraph} THRU {perform_stmt.thru_paragraph} {perform_stmt.times_count} TIMES")
    
    def test_perform_thru_to_dict(self):
        """Test that to_dict() includes thru_paragraph."""
        source = """
            IDENTIFICATION DIVISION.
            PROGRAM-ID. TEST-DICT.
            PROCEDURE DIVISION.
            MAIN-PARA.
                PERFORM PARA-X THRU PARA-Y.
                STOP RUN.
            PARA-X.
                DISPLAY 'X'.
            PARA-Y.
                DISPLAY 'Y'.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)
        
        assert result.success
        
        # Get the PERFORM statement
        proc_div = result.ast.get_division("PROCEDURE")
        main_para = next((s for s in proc_div.sections if s.section_name == "MAIN-PARA"), None)
        perform_stmts = [c for c in main_para.children if hasattr(c, 'target_paragraph')]
        perform_stmt = perform_stmts[0]
        
        # Convert to dict
        stmt_dict = perform_stmt.to_dict()
        
        assert "target_paragraph" in stmt_dict
        assert "thru_paragraph" in stmt_dict
        assert stmt_dict["target_paragraph"] == "PARA-X"
        assert stmt_dict["thru_paragraph"] == "PARA-Y"
        
        print(f"✅ to_dict() includes thru_paragraph: {stmt_dict['thru_paragraph']}")
    
    def test_perform_without_thru(self):
        """Test that regular PERFORM without THRU still works."""
        source = """
            IDENTIFICATION DIVISION.
            PROGRAM-ID. TEST-NO-THRU.
            PROCEDURE DIVISION.
            MAIN-PARA.
                PERFORM PARA-SINGLE.
                STOP RUN.
            PARA-SINGLE.
                DISPLAY 'Single'.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)
        
        assert result.success
        
        # Get the PERFORM statement
        proc_div = result.ast.get_division("PROCEDURE")
        main_para = next((s for s in proc_div.sections if s.section_name == "MAIN-PARA"), None)
        perform_stmts = [c for c in main_para.children if hasattr(c, 'target_paragraph')]
        perform_stmt = perform_stmts[0]
        
        assert perform_stmt.target_paragraph == "PARA-SINGLE"
        assert perform_stmt.thru_paragraph is None
        
        print(f"✅ PERFORM without THRU works: thru_paragraph is None")
    
    def test_perform_thru_with_nested_calls(self):
        """Test that CALL statements within PERFORM THRU paragraphs are captured."""
        source = """
            IDENTIFICATION DIVISION.
            PROGRAM-ID. TEST-NESTED-CALLS.
            PROCEDURE DIVISION.
            MAIN-PARA.
                PERFORM PARA-START THRU PARA-END.
                STOP RUN.
            PARA-START.
                CALL 'SUBPROG1'.
            PARA-MIDDLE.
                CALL 'SUBPROG2'.
            PARA-END.
                CALL 'SUBPROG3'.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)
        
        assert result.success
        
        # Get procedure division
        proc_div = result.ast.get_division("PROCEDURE")
        
        # Verify PERFORM THRU is captured
        main_para = next((s for s in proc_div.sections if s.section_name == "MAIN-PARA"), None)
        perform_stmts = [c for c in main_para.children if hasattr(c, 'target_paragraph')]
        perform_stmt = perform_stmts[0]
        
        assert perform_stmt.target_paragraph == "PARA-START"
        assert perform_stmt.thru_paragraph == "PARA-END"
        
        # Verify CALL statements are captured in paragraphs
        para_start = next((s for s in proc_div.sections if s.section_name == "PARA-START"), None)
        para_middle = next((s for s in proc_div.sections if s.section_name == "PARA-MIDDLE"), None)
        para_end = next((s for s in proc_div.sections if s.section_name == "PARA-END"), None)
        
        assert para_start is not None
        assert para_middle is not None
        assert para_end is not None
        
        # Check for CALL statements
        start_calls = [c for c in para_start.children if hasattr(c, 'called_program')]
        middle_calls = [c for c in para_middle.children if hasattr(c, 'called_program')]
        end_calls = [c for c in para_end.children if hasattr(c, 'called_program')]
        
        assert len(start_calls) == 1
        assert len(middle_calls) == 1
        assert len(end_calls) == 1
        
        print(f"✅ PERFORM THRU with nested CALL statements: all captured")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
