"""
Contract tests for dynamic CALL statement analysis feature.

These tests validate the API contract for tracking possible values in
dynamic CALL statements (calls using variables instead of literals).
"""

import pytest
from cobolparser import parse_cobol, ErrorRecoveryMode
from cobolparser.analysis import DynamicCallAnalyzer
from cobolparser.models.statements import CallStatement


class TestDynamicCallAPIContract:
    """Test the API contract for dynamic CALL statements."""
    
    def test_call_statement_has_is_dynamic_property(self):
        """Verify CallStatement has is_dynamic property."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
        MAIN-PARA.
            CALL "STATIC-PROGRAM".
            STOP RUN.
        '''
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        
        assert result.success, f"Errors: {result.errors}"
        calls = result.ast.find_statements("CALL")
        assert len(calls) > 0, "Should find at least one CALL statement"
        
        call = calls[0]
        assert hasattr(call, 'is_dynamic'), "CallStatement must have is_dynamic property"
        assert isinstance(call.is_dynamic, bool), "is_dynamic must be boolean"
    
    def test_call_statement_has_possible_values_property(self):
        """Verify CallStatement has possible_values property."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "STATIC-PROGRAM".
        '''
        result = parse_cobol(cobol_source)
        
        assert result.success
        calls = result.ast.find_statements("CALL")
        assert len(calls) > 0
        
        call = calls[0]
        assert hasattr(call, 'possible_values'), "CallStatement must have possible_values property"
        assert isinstance(call.possible_values, list), "possible_values must be a list"
    
    def test_static_call_is_not_dynamic(self):
        """Verify static CALL (with literal) has is_dynamic=False."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "STATIC-PROGRAM".
        '''
        result = parse_cobol(cobol_source)
        
        assert result.success
        calls = result.ast.find_statements("CALL")
        assert len(calls) > 0
        
        call = calls[0]
        assert call.is_dynamic == False, "Static CALL should have is_dynamic=False"
        assert call.possible_values == [], "Static CALL should have empty possible_values"
    
    def test_dynamic_call_is_detected(self):
        """Verify dynamic CALL (with variable) has is_dynamic=True."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-PROGRAM-NAME PIC X(20) VALUE "SUBPROG".
        PROCEDURE DIVISION.
            CALL WS-PROGRAM-NAME.
        '''
        result = parse_cobol(cobol_source)
        
        assert result.success
        calls = result.ast.find_statements("CALL")
        assert len(calls) > 0
        
        call = calls[0]
        assert call.is_dynamic == True, "Dynamic CALL should have is_dynamic=True"
        assert call.called_program == "WS-PROGRAM-NAME"
    
    def test_call_statement_to_dict_includes_dynamic_fields(self):
        """Verify CallStatement.to_dict() includes is_dynamic and possible_values."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-PROGRAM PIC X(10) VALUE "PROG1".
        PROCEDURE DIVISION.
            CALL WS-PROGRAM.
        '''
        result = parse_cobol(cobol_source)
        
        assert result.success
        calls = result.ast.find_statements("CALL")
        assert len(calls) > 0
        
        call_dict = calls[0].to_dict()
        assert "is_dynamic" in call_dict, "to_dict() must include is_dynamic"
        assert "possible_values" in call_dict, "to_dict() must include possible_values"
        assert isinstance(call_dict["is_dynamic"], bool)
        assert isinstance(call_dict["possible_values"], list)
    
    def test_dynamic_call_analyzer_exists(self):
        """Verify DynamicCallAnalyzer class is available."""
        analyzer = DynamicCallAnalyzer()
        assert analyzer is not None
        assert hasattr(analyzer, 'analyze'), "Analyzer must have analyze method"
    
    def test_dynamic_call_analyzer_has_analyze_method(self):
        """Verify DynamicCallAnalyzer.analyze() accepts AST."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "PROG".
        '''
        result = parse_cobol(cobol_source)
        
        analyzer = DynamicCallAnalyzer()
        # Should not raise exception
        analyzer.analyze(result.ast)
    
    def test_analyzer_populates_possible_values(self):
        """Verify analyzer populates possible_values for dynamic CALL."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-PROGRAM PIC X(10) VALUE "PROG1".
        PROCEDURE DIVISION.
            CALL WS-PROGRAM.
        '''
        result = parse_cobol(cobol_source)
        
        # Before analysis
        calls = result.ast.find_statements("CALL")
        assert len(calls) > 0
        call = calls[0]
        assert call.is_dynamic == True
        
        # After analysis
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(result.ast)
        
        # Verify possible_values is populated
        assert len(call.possible_values) > 0, "Analyzer should populate possible_values"
        assert "PROG1" in call.possible_values
    
    def test_call_statement_immutable_possible_values(self):
        """Verify possible_values property returns a copy (immutable)."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-PROG PIC X(5) VALUE "PROG1".
        PROCEDURE DIVISION.
            CALL WS-PROG.
        '''
        result = parse_cobol(cobol_source)
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(result.ast)
        
        calls = result.ast.find_statements("CALL")
        call = calls[0]
        
        # Get possible values
        values1 = call.possible_values
        values2 = call.possible_values
        
        # Modify values1
        values1.append("MODIFIED")
        
        # Verify values2 is not affected (copy was returned)
        assert "MODIFIED" not in values2, "possible_values should return a copy"
        assert "MODIFIED" not in call.possible_values


class TestDynamicCallValueTracking:
    """Test value tracking capabilities."""
    
    def test_tracks_initial_value_from_working_storage(self):
        """Verify analyzer tracks VALUE clause from data definition."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-PROG PIC X(10) VALUE "INITIAL-PROG".
        PROCEDURE DIVISION.
            CALL WS-PROG.
        '''
        result = parse_cobol(cobol_source)
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(result.ast)
        
        calls = result.ast.find_statements("CALL")
        call = calls[0]
        
        assert call.is_dynamic
        assert "INITIAL-PROG" in call.possible_values
    
    def test_tracks_move_statement_values(self):
        """Verify analyzer tracks MOVE statements."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-PROG PIC X(10).
        PROCEDURE DIVISION.
            MOVE "PROGRAM-A" TO WS-PROG.
            CALL WS-PROG.
        '''
        result = parse_cobol(cobol_source)
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(result.ast)
        
        calls = result.ast.find_statements("CALL")
        call = calls[0]
        
        assert call.is_dynamic
        assert "PROGRAM-A" in call.possible_values
    
    def test_tracks_multiple_move_values(self):
        """Verify analyzer tracks multiple MOVE statements to same variable."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-PROG PIC X(10).
        PROCEDURE DIVISION.
            MOVE "PROG-A" TO WS-PROG.
            MOVE "PROG-B" TO WS-PROG.
            MOVE "PROG-C" TO WS-PROG.
            CALL WS-PROG.
        '''
        result = parse_cobol(cobol_source)
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(result.ast)
        
        calls = result.ast.find_statements("CALL")
        call = calls[0]
        
        assert call.is_dynamic
        # All three values should be tracked
        assert "PROG-A" in call.possible_values
        assert "PROG-B" in call.possible_values
        assert "PROG-C" in call.possible_values
        assert len(call.possible_values) == 3
    
    def test_combines_initial_value_and_move_values(self):
        """Verify analyzer combines VALUE clause with MOVE statements."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-PROG PIC X(10) VALUE "INITIAL".
        PROCEDURE DIVISION.
            MOVE "RUNTIME" TO WS-PROG.
            CALL WS-PROG.
        '''
        result = parse_cobol(cobol_source)
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(result.ast)
        
        calls = result.ast.find_statements("CALL")
        call = calls[0]
        
        assert call.is_dynamic
        assert "INITIAL" in call.possible_values
        assert "RUNTIME" in call.possible_values
        assert len(call.possible_values) == 2


class TestDynamicCallAnalyzerMethods:
    """Test DynamicCallAnalyzer utility methods."""
    
    def test_get_variable_values_method(self):
        """Verify analyzer.get_variable_values() returns tracked values."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-VAR PIC X(10) VALUE "VALUE1".
        PROCEDURE DIVISION.
            MOVE "VALUE2" TO WS-VAR.
        '''
        result = parse_cobol(cobol_source)
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(result.ast)
        
        values = analyzer.get_variable_values("WS-VAR")
        assert "VALUE1" in values
        assert "VALUE2" in values
    
    def test_get_all_tracked_variables_method(self):
        """Verify analyzer.get_all_tracked_variables() returns variable names."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-VAR1 PIC X(5) VALUE "TEST".
        01  WS-VAR2 PIC X(5) VALUE "TEST".
        PROCEDURE DIVISION.
            MOVE "A" TO WS-VAR1.
            MOVE "B" TO WS-VAR2.
        '''
        result = parse_cobol(cobol_source)
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(result.ast)
        
        variables = analyzer.get_all_tracked_variables()
        assert "WS-VAR1" in variables
        assert "WS-VAR2" in variables
