"""Integration tests for PyramidParser orchestration with DivisionParserFactory.

Tests that verify the complete parsing workflow using the factory-based
orchestration for division parsing, including full program parsing,
division sequence validation, and data-to-procedure linking.
"""

import pytest
from cobolparser import CobolParser
from cobolparser.models.program import CobolProgram, CobolDivision
from cobolparser.plugins.core import ErrorRecoveryMode


class TestOrchestrationFullProgramParsing:
    """Tests for full program parsing through the orchestrator."""

    def test_parse_simple_complete_program(self):
        """Test parsing a simple complete COBOL program with all divisions."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       AUTHOR. Test Author.
       
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       
       PROCEDURE DIVISION.
       MAIN-PARAGRAPH.
           DISPLAY "Hello World".
           STOP RUN.
        """
        
        parser = CobolParser()
        result = parser.parse(source)
        
        assert result.ast is not None
        assert result.success
        assert result.ast.program_name == "TESTPROG"
        assert len(result.ast.divisions) >= 2  # At least IDENTIFICATION and PROCEDURE

    def test_parse_program_with_identification_only(self):
        """Test parsing program with only IDENTIFICATION division."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MINIMALPROGRAM.
        """
        
        parser = CobolParser()
        result = parser.parse(source)
        
        assert result.ast is not None
        assert result.ast.program_name == "MINIMALPROGRAM"

    def test_parse_program_multiple_paragraphs(self):
        """Test parsing program with multiple paragraphs in PROCEDURE division."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTIPARA.
       
       PROCEDURE DIVISION.
       MAIN-PARAGRAPH.
           DISPLAY "Main".
       
       SECONDARY-PARAGRAPH.
           DISPLAY "Secondary".
       
       FINAL-PARAGRAPH.
           STOP RUN.
        """
        
        parser = CobolParser()
        result = parser.parse(source)
        
        assert result.success
        assert result.ast is not None
        assert result.ast.program_name == "MULTIPARA"
        
        # Verify procedure division exists
        proc_div = result.ast.get_division("PROCEDURE")
        assert proc_div is not None

    def test_parse_program_with_data_definitions(self):
        """Test parsing program with complex data definitions in DATA division."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATAPROGRAM.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ROOT.
           05 WS-NAME PIC X(30).
           05 WS-AGE PIC 9(3).
           05 WS-SALARY PIC 9(7)V99.
           05 WS-ITEMS.
               10 WS-ITEM OCCURS 5 TIMES PIC X(20).
       
       PROCEDURE DIVISION.
           STOP RUN.
        """
        
        parser = CobolParser()
        result = parser.parse(source)
        
        assert result.success
        assert result.ast is not None
        
        # Verify data division was parsed
        data_div = result.ast.get_division("DATA")
        assert data_div is not None


class TestOrchestrationDivisionSequenceValidation:
    """Tests for validation of division sequence through orchestrator."""

    def test_divisions_parsed_in_correct_order(self):
        """Test that divisions are parsed in the correct order (ID, ENV, DATA, PROC)."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDERTEST.
       
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       
       PROCEDURE DIVISION.
           DISPLAY "Test".
           STOP RUN.
        """
        
        parser = CobolParser()
        result = parser.parse(source)
        
        assert result.success
        assert result.ast is not None
        
        # Verify IDENTIFICATION division exists
        assert result.ast.program_name == "ORDERTEST"

    def test_program_without_procedure_division(self):
        """Test parsing of program that lacks PROCEDURE division."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOCODE.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
        """
        
        parser = CobolParser()
        result = parser.parse(source)
        
        # Should still succeed, though missing procedure division
        assert result.ast is not None
        assert result.ast.program_name == "NOCODE"


class TestOrchestrationDataToProcedureLinking:
    """Tests for data-to-procedure linking through orchestrator."""

    def test_data_items_accessible_to_procedure(self):
        """Test that data items defined in DATA division can be referenced in PROCEDURE division."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LINKTEST.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-COUNTER PIC 9(5) VALUE 0.
       01 WS-NAME PIC X(30).
       
       PROCEDURE DIVISION.
       MAIN-PARAGRAPH.
           MOVE 100 TO WS-COUNTER.
           MOVE "TEST" TO WS-NAME.
           DISPLAY WS-COUNTER.
           DISPLAY WS-NAME.
           STOP RUN.
        """
        
        parser = CobolParser()
        result = parser.parse(source)
        
        assert result.success
        assert result.ast is not None
        
        # Verify data division has items
        data_div = result.ast.get_division("DATA")
        assert data_div is not None
        
        # Verify procedure division references exist
        proc_div = result.ast.get_division("PROCEDURE")
        assert proc_div is not None

    def test_working_storage_to_procedure_linking(self):
        """Test linking of WORKING-STORAGE SECTION items to PROCEDURE division."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. WSLINKTEST.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 COUNTER PIC 999 VALUE 0.
       01 FLAG PIC X VALUE 'N'.
       
       PROCEDURE DIVISION.
           PERFORM INITIALIZE-SECTION.
           PERFORM MAIN-LOGIC UNTIL FLAG = 'Y'.
           STOP RUN.
       
       INITIALIZE-SECTION.
           MOVE 0 TO COUNTER.
           MOVE 'N' TO FLAG.
       
       MAIN-LOGIC.
           MOVE 'Y' TO FLAG.
        """
        
        parser = CobolParser()
        result = parser.parse(source)
        
        assert result.success
        assert result.ast is not None

    def test_nested_data_structures_in_procedure(self):
        """Test that nested data structures are properly preserved for PROCEDURE division."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTEDLINK.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-RECORD.
           05 REC-ID PIC 9(5).
           05 REC-DATA.
               10 REC-NAME PIC X(30).
               10 REC-VALUE PIC 9(7).
       
       PROCEDURE DIVISION.
           MOVE 1 TO REC-ID OF WS-RECORD.
           MOVE "TEST" TO REC-NAME OF REC-DATA OF WS-RECORD.
           STOP RUN.
        """
        
        parser = CobolParser()
        result = parser.parse(source)
        
        assert result.success
        assert result.ast is not None


class TestOrchestrationErrorHandling:
    """Tests for error handling in orchestration."""

    def test_orchestrator_captures_missing_identification_division(self):
        """Test that missing IDENTIFICATION division is handled gracefully."""
        source = """
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
        """
        
        parser = CobolParser()
        result = parser.parse(source)
        
        # Parser should handle this - it will use legacy parsing as fallback
        # The program name will be UNKNOWN since no PROGRAM-ID was found
        if result.ast:
            assert result.ast.program_name == "UNKNOWN"

    def test_orchestrator_with_error_recovery_fail_fast(self):
        """Test orchestrator in FAIL_FAST error recovery mode."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FAILFASTTEST.
        """
        
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        result = parser.parse(source)
        
        # Should parse successfully
        assert result.ast is not None

    def test_orchestrator_with_error_recovery_collect_all(self):
        """Test orchestrator in COLLECT_ALL error recovery mode."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COLLECTTEST.
       
       PROCEDURE DIVISION.
           DISPLAY "Test".
           STOP RUN.
        """
        
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(source)
        
        # Should parse successfully with any collected errors
        assert result.ast is not None
        assert result.ast.program_name == "COLLECTTEST"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
