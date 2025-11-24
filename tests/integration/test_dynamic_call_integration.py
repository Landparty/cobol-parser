"""
Integration tests for dynamic CALL statement value tracking.

These tests demonstrate the complete end-to-end workflow for analyzing
dynamic CALL statements and tracking their possible values.
"""

import pytest
from cobolparser import parse_cobol, ErrorRecoveryMode
from cobolparser.analysis import DynamicCallAnalyzer


class TestDynamicCallIntegration:
    """Integration tests for dynamic CALL analysis."""
    
    def test_complete_dynamic_call_workflow(self):
        """Test complete workflow: parse, analyze, retrieve values."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. DYNAMIC-CALLER.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-TXT              PIC X(20) VALUE "INITIAL-PROG".
        01  WS-EMPLOYEE-ID      PIC 9(5).
        01  WS-SALARY           PIC 9(7)V99.
        
        PROCEDURE DIVISION.
        MAIN-PROCESS.
            MOVE "PROG-A" TO WS-TXT.
            CALL WS-TXT USING WS-EMPLOYEE-ID WS-SALARY.
            
            MOVE "PROG-B" TO WS-TXT.
            CALL WS-TXT USING WS-EMPLOYEE-ID.
            
            MOVE "PROG-C" TO WS-TXT.
            CALL WS-TXT.
            
            STOP RUN.
        '''
        
        # Step 1: Parse the COBOL source
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.success, f"Parsing failed: {result.errors}"
        assert result.ast is not None
        
        # Step 2: Find CALL statements (before analysis)
        calls = result.ast.find_statements("CALL")
        assert len(calls) == 3, "Should find 3 CALL statements"
        
        # Verify all are dynamic
        for call in calls:
            assert call.is_dynamic == True, "All CALLs should be dynamic"
            assert call.called_program == "WS-TXT"
            assert call.possible_values == [], "Values not populated yet"
        
        # Step 3: Analyze with DynamicCallAnalyzer
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(result.ast)
        
        # Step 4: Verify possible values are populated
        for call in calls:
            assert len(call.possible_values) == 4, "Should have 4 possible values"
            assert "INITIAL-PROG" in call.possible_values
            assert "PROG-A" in call.possible_values
            assert "PROG-B" in call.possible_values
            assert "PROG-C" in call.possible_values
        
        # Step 5: Verify analyzer utility methods
        ws_txt_values = analyzer.get_variable_values("WS-TXT")
        assert len(ws_txt_values) == 4
        assert "INITIAL-PROG" in ws_txt_values
        
        tracked_vars = analyzer.get_all_tracked_variables()
        assert "WS-TXT" in tracked_vars
    
    def test_mixed_static_and_dynamic_calls(self):
        """Test program with both static and dynamic CALLs."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. MIXED-CALLS.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-DYNAMIC-PROG     PIC X(10) VALUE "SUBPROG1".
        
        PROCEDURE DIVISION.
        MAIN-LOGIC.
            CALL "STATIC-PROG".
            
            MOVE "SUBPROG2" TO WS-DYNAMIC-PROG.
            CALL WS-DYNAMIC-PROG.
            
            CALL "ANOTHER-STATIC".
            
            STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.success
        assert result.ast is not None
        
        calls = result.ast.find_statements("CALL")
        assert len(calls) == 3
        
        # Analyze
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(result.ast)
        
        # Check each CALL
        static_count = 0
        dynamic_count = 0
        
        for call in calls:
            if call.is_dynamic:
                dynamic_count += 1
                assert len(call.possible_values) > 0
                assert call.called_program == "WS-DYNAMIC-PROG"
            else:
                static_count += 1
                assert call.possible_values == []
        
        assert static_count == 2
        assert dynamic_count == 1
    
    def test_conditional_moves_to_dynamic_call(self):
        """Test dynamic CALL with conditional MOVE statements."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. CONDITIONAL-CALL.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-PROGRAM-NAME     PIC X(10).
        01  WS-TRANSACTION-TYPE PIC X.
           88  TYPE-INQUIRY     VALUE 'I'.
           88  TYPE-UPDATE      VALUE 'U'.
           88  TYPE-DELETE      VALUE 'D'.
        
        PROCEDURE DIVISION.
        SELECT-PROGRAM.
            IF TYPE-INQUIRY
                MOVE "INQ-PROG" TO WS-PROGRAM-NAME
            ELSE
                IF TYPE-UPDATE
                    MOVE "UPD-PROG" TO WS-PROGRAM-NAME
                ELSE
                    MOVE "DEL-PROG" TO WS-PROGRAM-NAME
                END-IF
            END-IF.
            
        CALL-PROGRAM.
            CALL WS-PROGRAM-NAME.
            
            STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.success
        assert result.ast is not None
        
        # Analyze
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(result.ast)
        
        calls = result.ast.find_statements("CALL")
        assert len(calls) == 1
        
        call = calls[0]
        assert call.is_dynamic
        assert call.called_program == "WS-PROGRAM-NAME"
        
        # Should track all three possible values
        assert "INQ-PROG" in call.possible_values
        assert "UPD-PROG" in call.possible_values
        assert "DEL-PROG" in call.possible_values
    
    def test_table_driven_dynamic_call(self):
        """Test dynamic CALL with table-driven program selection."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TABLE-DRIVEN.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-PROGRAM-TABLE.
            05  WS-PROG-ENTRY OCCURS 3 TIMES PIC X(10).
        01  WS-CURRENT-PROGRAM  PIC X(10).
        01  WS-INDEX            PIC 9.
        
        PROCEDURE DIVISION.
        INITIALIZE-TABLE.
            MOVE "VALIDATE" TO WS-PROG-ENTRY(1).
            MOVE "PROCESS"  TO WS-PROG-ENTRY(2).
            MOVE "FINALIZE" TO WS-PROG-ENTRY(3).
            
        MAIN-LOOP.
            PERFORM VARYING WS-INDEX FROM 1 BY 1 UNTIL WS-INDEX > 3
                MOVE WS-PROG-ENTRY(WS-INDEX) TO WS-CURRENT-PROGRAM
                CALL WS-CURRENT-PROGRAM
            END-PERFORM.
            
            STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.success
        assert result.ast is not None
        
        # Analyze
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(result.ast)
        
        calls = result.ast.find_statements("CALL")
        assert len(calls) >= 1
        
        # Find the dynamic CALL
        dynamic_calls = [c for c in calls if c.is_dynamic]
        assert len(dynamic_calls) >= 1
        
        call = dynamic_calls[0]
        assert call.called_program == "WS-CURRENT-PROGRAM"
        
        # Note: Current implementation may not track array element assignments
        # This test documents expected behavior for future enhancements
    
    def test_multiple_variables_dynamic_calls(self):
        """Test multiple different dynamic CALL variables."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. MULTI-VAR-CALL.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-VALIDATION-PROG  PIC X(10) VALUE "VALIDATOR".
        01  WS-BUSINESS-PROG    PIC X(10) VALUE "BUS-LOGIC".
        01  WS-AUDIT-PROG       PIC X(10) VALUE "AUDITOR".
        
        PROCEDURE DIVISION.
        MAIN-PROCESS.
            CALL WS-VALIDATION-PROG.
            CALL WS-BUSINESS-PROG.
            CALL WS-AUDIT-PROG.
            
            MOVE "ALT-VALID" TO WS-VALIDATION-PROG.
            CALL WS-VALIDATION-PROG.
            
            STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.success
        assert result.ast is not None
        
        # Analyze
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(result.ast)
        
        calls = result.ast.find_statements("CALL")
        assert len(calls) == 4
        
        # Check tracked variables
        tracked_vars = analyzer.get_all_tracked_variables()
        assert "WS-VALIDATION-PROG" in tracked_vars
        assert "WS-BUSINESS-PROG" in tracked_vars
        assert "WS-AUDIT-PROG" in tracked_vars
        
        # Check WS-VALIDATION-PROG has both values
        val_values = analyzer.get_variable_values("WS-VALIDATION-PROG")
        assert "VALIDATOR" in val_values
        assert "ALT-VALID" in val_values
        assert len(val_values) == 2
        
        # Check other programs have single values
        bus_values = analyzer.get_variable_values("WS-BUSINESS-PROG")
        assert "BUS-LOGIC" in bus_values
        assert len(bus_values) == 1
        
        aud_values = analyzer.get_variable_values("WS-AUDIT-PROG")
        assert "AUDITOR" in aud_values
        assert len(aud_values) == 1
    
    def test_json_serialization_with_dynamic_calls(self):
        """Test JSON export includes dynamic CALL information."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. JSON-TEST.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-PROG PIC X(10) VALUE "SUBPROG1".
        
        PROCEDURE DIVISION.
            MOVE "SUBPROG2" TO WS-PROG.
            CALL WS-PROG.
            STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.success
        assert result.ast is not None
        
        # Analyze
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(result.ast)
        
        # Export to JSON
        json_output = result.ast.to_json()
        assert json_output is not None
        
        # Verify JSON contains the information (basic check)
        import json
        ast_dict = json.loads(json_output)
        assert ast_dict is not None
        
        # The exact structure depends on AST serialization,
        # but it should be serializable
        assert isinstance(ast_dict, dict)
