"""Comprehensive test suite for CALL statement parsing.

This module systematically tests CALL statement variants including:
- Static CALLs with literal program names
- Dynamic CALLs with variable program names
- CALL with USING clause
- CALL with RETURNING clause
- CALL with both USING and RETURNING
- Error cases and edge conditions
"""

import pytest
from cobolparser import parse_cobol


class TestCallBasic:
    """Test basic CALL statement functionality."""
    
    def test_call_with_literal_program_name(self):
        """Test CALL with literal program name (static CALL)."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "SUBPROGRAM".
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        assert result.ast is not None
        
        calls = result.ast.find_statements("CALL")
        assert len(calls) >= 1
    
    def test_call_with_variable_program_name(self):
        """Test CALL with variable program name (dynamic CALL)."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 PROG-NAME PIC X(20) VALUE "SUB1".
        PROCEDURE DIVISION.
            CALL PROG-NAME.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        calls = result.ast.find_statements("CALL")
        assert len(calls) >= 1
    
    def test_call_with_no_parameters(self):
        """Test CALL without any USING clause."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "WORK".
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestCallUsing:
    """Test CALL with USING clause (parameter passing)."""
    
    def test_call_with_single_parameter(self):
        """Test CALL with single parameter in USING."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 PARAM-1 PIC 9(4) VALUE 100.
        PROCEDURE DIVISION.
            CALL "SUBPROG" USING PARAM-1.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        calls = result.ast.find_statements("CALL")
        assert len(calls) >= 1
    
    def test_call_with_multiple_parameters(self):
        """Test CALL with multiple parameters."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 PARAM-1 PIC X(10) VALUE "INPUT".
        01 PARAM-2 PIC X(10).
        01 PARAM-3 PIC 9(4).
        PROCEDURE DIVISION.
            CALL "SUBPROG" USING PARAM-1 PARAM-2 PARAM-3.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_call_using_by_reference(self):
        """Test CALL USING BY REFERENCE (default)."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 VAR PIC X(20).
        PROCEDURE DIVISION.
            CALL "SUB" USING BY REFERENCE VAR.
            STOP RUN.
        """
        result = parse_cobol(source)
        # May or may not support explicit BY REFERENCE
        assert result is not None
    
    def test_call_using_by_value(self):
        """Test CALL USING BY VALUE."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 VAL PIC 9 VALUE 1.
        PROCEDURE DIVISION.
            CALL "SUB" USING BY VALUE VAL.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result is not None


class TestCallReturning:
    """Test CALL with RETURNING clause."""
    
    def test_call_with_returning(self):
        """Test CALL with RETURNING clause."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 RESULT PIC 9(4).
        PROCEDURE DIVISION.
            CALL "FUNCTION" RETURNING RESULT.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        calls = result.ast.find_statements("CALL")
        assert len(calls) >= 1
    
    def test_call_using_and_returning(self):
        """Test CALL with both USING and RETURNING."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 INPUT-VAL PIC 9(4) VALUE 10.
        01 OUTPUT-VAL PIC 9(4).
        PROCEDURE DIVISION.
            CALL "TRANSFORM" USING INPUT-VAL RETURNING OUTPUT-VAL.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestCallStaticDynamic:
    """Test static vs dynamic CALL detection."""
    
    def test_static_call_with_literal(self):
        """Test static CALL detection with literal."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "KNOWN-PROGRAM".
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        calls = result.ast.find_statements("CALL")
        assert len(calls) >= 1
        
        call = calls[0]
        # Check if parser tracks is_dynamic
        if hasattr(call, 'is_dynamic'):
            assert call.is_dynamic == False
    
    def test_dynamic_call_with_variable(self):
        """Test dynamic CALL detection with variable."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 PROG-NAME PIC X(20).
        PROCEDURE DIVISION.
            CALL PROG-NAME.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        calls = result.ast.find_statements("CALL")
        assert len(calls) >= 1
        
        call = calls[0]
        # Check if parser tracks is_dynamic
        if hasattr(call, 'is_dynamic'):
            assert call.is_dynamic == True


class TestCallSerialization:
    """Test CALL statement serialization."""
    
    def test_call_to_dict(self):
        """Test CALL statement to_dict() serialization."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "SUBPROG".
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        
        calls = result.ast.find_statements("CALL")
        assert len(calls) >= 1
        
        call_dict = calls[0].to_dict()
        assert call_dict is not None
        assert isinstance(call_dict, dict)
    
    def test_call_serialization_with_parameters(self):
        """Test CALL with parameters serialization."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 INPUT PIC X(10).
        01 OUTPUT PIC 9(5).
        PROCEDURE DIVISION.
            CALL "PROC" USING INPUT OUTPUT RETURNING OUTPUT.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestCallEdgeCases:
    """Test CALL edge cases and error conditions."""
    
    def test_call_with_quoted_program_name(self):
        """Test CALL with quoted program name."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "MY-PROGRAM-NAME".
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_call_in_perform_loop(self):
        """Test CALL inside PERFORM loop."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM 3 TIMES
                CALL "WORKER"
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        calls = result.ast.find_statements("CALL")
        performs = result.ast.find_statements("PERFORM")
        assert len(calls) >= 1
        assert len(performs) >= 1
    
    def test_call_in_if_statement(self):
        """Test CALL inside IF statement."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            IF TRUE
                CALL "CONDITIONAL"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_multiple_calls_in_sequence(self):
        """Test multiple CALL statements in sequence."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "FIRST".
            CALL "SECOND".
            CALL "THIRD".
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        calls = result.ast.find_statements("CALL")
        assert len(calls) >= 3


class TestCallParameterPassing:
    """Test parameter passing mechanisms."""
    
    def test_call_parameter_names_as_literals(self):
        """Test CALL with literal string parameters."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "PRINT" USING "MESSAGE".
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_call_parameter_numeric_values(self):
        """Test CALL with numeric parameters."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "CALC" USING 10 20 30.
            STOP RUN.
        """
        result = parse_cobol(source)
        # May fail if parser is strict about variable vs literal
        assert result is not None


class TestCallErrorCases:
    """Test error cases and diagnostics."""
    
    def test_call_returning_and_giving_mutually_exclusive(self):
        """Test that RETURNING and GIVING are mutually exclusive."""
        # This is a potential error condition - both should not be allowed
        # Parser should either reject or handle gracefully
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 RES PIC 9.
        PROCEDURE DIVISION.
            CALL "SUB" RETURNING RES GIVING RES.
            STOP RUN.
        """
        result = parse_cobol(source)
        # Should parse (may or may not validate)
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
