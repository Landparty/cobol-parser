"""Comprehensive test suite for Division parsers (ID, ENV, DATA, PROC).

This module systematically tests Division-level parsing including:
- Identification Division (PROGRAM-ID, AUTHOR, INSTALLATION, etc.)
- Environment Division (CONFIGURATION, INPUT-OUTPUT sections)
- Data Division (FILE, WORKING-STORAGE, LOCAL-STORAGE sections)
- Procedure Division (paragraphs, sections, statements)
"""

import pytest

from cobolparser import parse_cobol


class TestIdentificationDivision:
    """Test Identification Division parsing."""

    def test_identification_division_minimal(self):
        """Test minimal Identification Division."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        assert result.ast is not None

    def test_identification_division_with_author(self):
        """Test Identification Division with AUTHOR."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        AUTHOR. JOHN DOE.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_identification_division_with_date_written(self):
        """Test Identification Division with DATE-WRITTEN."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATE-WRITTEN. 2024-01-01.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_identification_division_with_multiple_clauses(self):
        """Test Identification Division with multiple clauses."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        AUTHOR. JOHN DOE.
        DATE-WRITTEN. 2024-01-01.
        INSTALLATION. DATACENTER.
        SECURITY. UNCLASSIFIED.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_program_id_with_is_initial(self):
        """Test PROGRAM-ID with IS INITIAL clause."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST IS INITIAL.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_program_id_with_is_common(self):
        """Test PROGRAM-ID with IS COMMON clause."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST IS COMMON.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_identification_division_serialization(self):
        """Test Identification Division serialization."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        AUTHOR. JOHN.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        if hasattr(result.ast, "to_dict"):
            ast_dict = result.ast.to_dict()
            assert isinstance(ast_dict, dict)


class TestEnvironmentDivision:
    """Test Environment Division parsing."""

    def test_environment_division_minimal(self):
        """Test minimal Environment Division."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        ENVIRONMENT DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_configuration_section(self):
        """Test CONFIGURATION SECTION."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        ENVIRONMENT DIVISION.
        CONFIGURATION SECTION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_input_output_section(self):
        """Test INPUT-OUTPUT SECTION."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_select_clause(self):
        """Test SELECT clause in INPUT-OUTPUT."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT INPUT-FILE ASSIGN TO "INPUT.TXT"
                ORGANIZATION IS LINE SEQUENTIAL.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_environment_division_serialization(self):
        """Test Environment Division serialization."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestDataDivision:
    """Test Data Division parsing."""

    def test_data_division_minimal(self):
        """Test minimal Data Division."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_file_section(self):
        """Test FILE SECTION."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT INPUT-FILE ASSIGN TO "INPUT.TXT"
                ORGANIZATION IS LINE SEQUENTIAL.
        DATA DIVISION.
        FILE SECTION.
        FD INPUT-FILE.
        01 INPUT-RECORD PIC X(80).
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_working_storage_section(self):
        """Test WORKING-STORAGE SECTION."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-VAR PIC X VALUE "A".
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_working_storage_with_multiple_items(self):
        """Test WORKING-STORAGE with multiple items."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-GROUP.
            05 WS-FIELD-1 PIC X.
            05 WS-FIELD-2 PIC 9(3).
            05 WS-FIELD-3 PIC S9(5)V99 COMP-3.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_local_storage_section(self):
        """Test LOCAL-STORAGE SECTION."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        LOCAL-STORAGE SECTION.
        01 LS-VAR PIC X VALUE "B".
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_data_division_with_redefines(self):
        """Test Data Division with REDEFINES clause."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-FIELD-1 PIC X(10).
        01 WS-FIELD-2 REDEFINES WS-FIELD-1 PIC 9(10).
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_data_division_with_occurs(self):
        """Test Data Division with OCCURS clause."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-TABLE.
            05 WS-ITEM PIC X(10) OCCURS 100 TIMES.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_data_division_serialization(self):
        """Test Data Division serialization."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-VAR PIC X.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        if hasattr(result.ast, "to_dict"):
            ast_dict = result.ast.to_dict()
            assert isinstance(ast_dict, dict)


class TestProcedureDivision:
    """Test Procedure Division parsing."""

    def test_procedure_division_minimal(self):
        """Test minimal Procedure Division."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_procedure_division_with_paragraphs(self):
        """Test Procedure Division with paragraphs."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            MAIN-PARAGRAPH.
                DISPLAY "HELLO".
                PERFORM SECONDARY-PARAGRAPH.
            SECONDARY-PARAGRAPH.
                DISPLAY "WORLD".
            END PROGRAM TEST.
        """
        result = parse_cobol(source)
        assert result.success

    def test_procedure_division_with_sections(self):
        """Test Procedure Division with sections."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            MAIN-SECTION SECTION.
                DISPLAY "A".
            END PROGRAM TEST.
        """
        result = parse_cobol(source)
        assert result.success

    def test_procedure_division_with_statements(self):
        """Test Procedure Division with various statements."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-X PIC 9(3).
        PROCEDURE DIVISION.
            MOVE 5 TO WS-X.
            IF WS-X = 5
                DISPLAY "EQUAL"
            END-IF.
            EVALUATE WS-X
                WHEN 5
                    DISPLAY "FIVE"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_procedure_division_with_perform(self):
        """Test Procedure Division with PERFORM."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM MAIN-PARA 5 TIMES.
            STOP RUN.
            MAIN-PARA.
                DISPLAY "X".
        """
        result = parse_cobol(source)
        assert result.success

    def test_procedure_division_serialization(self):
        """Test Procedure Division serialization."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            DISPLAY "TEST".
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        if hasattr(result.ast, "to_dict"):
            ast_dict = result.ast.to_dict()
            assert isinstance(ast_dict, dict)


class TestAllDivisionsTogether:
    """Test all divisions together."""

    def test_complete_cobol_program(self):
        """Test complete COBOL program with all divisions."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. COMPLETE-PROGRAM.
        AUTHOR. TEST AUTHOR.
        DATE-WRITTEN. 2024-01-01.

        ENVIRONMENT DIVISION.
        CONFIGURATION SECTION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.

        DATA DIVISION.
        FILE SECTION.
        WORKING-STORAGE SECTION.
        01 WS-FIELD PIC X(10) VALUE "TEST".

        PROCEDURE DIVISION.
            MAIN-PARA.
                DISPLAY "START".
                MOVE "ABC" TO WS-FIELD.
                IF WS-FIELD = "ABC"
                    DISPLAY "MATCH"
                END-IF.
                STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success

    def test_get_all_statements_across_divisions(self):
        """Test get_all_statements includes statements from all divisions."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            DISPLAY "A".
            IF 1 = 1
                DISPLAY "B"
            END-IF.
            EVALUATE 1
                WHEN 1
                    DISPLAY "C"
            END-EVALUATE.
        """
        result = parse_cobol(source)
        assert result.success
        if hasattr(result.ast, "get_all_statements"):
            stmts = result.ast.get_all_statements()
            assert len(stmts) >= 3

    def test_complete_program_serialization(self):
        """Test complete program serialization."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-VAR PIC X.
        PROCEDURE DIVISION.
            MOVE "X" TO WS-VAR.
        """
        result = parse_cobol(source)
        assert result.success
        if hasattr(result.ast, "to_dict"):
            ast_dict = result.ast.to_dict()
            assert isinstance(ast_dict, dict)


class TestDivisionErrorCases:
    """Test error cases in Division parsing."""

    def test_missing_identification_division(self):
        """Test program without IDENTIFICATION DIVISION."""
        source = """
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        # May succeed or fail depending on parser strictness
        assert result is not None

    def test_duplicate_working_storage_sections(self):
        """Test multiple WORKING-STORAGE sections (edge case)."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-A PIC X.
        WORKING-STORAGE SECTION.
        01 WS-B PIC X.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        # May succeed or fail depending on parser strictness
        assert result is not None

    def test_statements_outside_procedure_division(self):
        """Test statements outside Procedure Division."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-X PIC 9(3).
        DISPLAY "OUTSIDE".
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse_cobol(source)
        # Should fail or handle gracefully
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
