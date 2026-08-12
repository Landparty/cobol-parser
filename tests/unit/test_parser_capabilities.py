"""
Comprehensive unit tests for real-world COBOL patterns with proper error handling.

This test module identifies what COBOL patterns are currently supported
and what needs to be implemented to handle the examples directory programs.
"""

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol


class TestCurrentParserCapabilities:
    """Test what the parser currently handles successfully."""

    def test_basic_program_structure(self):
        """Test basic COBOL program structure parsing."""
        cobol_source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. BASIC-TEST.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MESSAGE    PIC X(20) VALUE "Hello World".

       PROCEDURE DIVISION.
       DISPLAY WS-MESSAGE.
       STOP RUN."""

        result = parse_cobol(cobol_source)

        if result.success:
            # Verify basic AST structure exists
            assert result.ast is not None
            assert result.ast.program_name == "BASIC-TEST"

            # Check if divisions are accessible using has_division method
            assert (
                result.ast.has_division("IDENTIFICATION")
                or result.ast.has_division("DATA")
                or result.ast.has_division("PROCEDURE")
            )
        else:
            pytest.fail(
                f"Basic program structure should parse successfully. Errors: {result.errors}"
            )

    def test_picture_clause_parsing(self):
        """Test what PICTURE clause patterns currently work."""
        test_cases = [
            ("PIC X(20)", "Simple alphanumeric"),
            ("PIC 9(5)", "Simple numeric"),
            ("PICTURE X(10)", "Full PICTURE keyword"),
            ("PIC S9(5)", "Signed numeric"),
            ("PIC 9(5)V99", "Decimal numeric"),
            ("PIC S9(5)V9(5)", "Signed decimal"),
        ]

        for pic_clause, description in test_cases:
            cobol_source = f"""IDENTIFICATION DIVISION.
PROGRAM-ID. PIC-TEST.

DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-FIELD    {pic_clause}.

PROCEDURE DIVISION.
STOP RUN."""

            result = parse_cobol(
                cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL
            )

            assert (
                result.success
            ), f"Failed to parse {description} ({pic_clause}): {result.errors[:3]}"
            assert result.ast is not None

    def test_level_number_variations(self):
        """Test different level number patterns."""
        test_cases = [
            ("01", "Group level"),
            ("77", "Independent item"),
            ("05", "Subordinate level"),
        ]

        for level, description in test_cases:
            cobol_source = f"""IDENTIFICATION DIVISION.
PROGRAM-ID. LEVEL-TEST.

DATA DIVISION.
WORKING-STORAGE SECTION.
{level}  WS-FIELD    PIC X(10).

PROCEDURE DIVISION.
STOP RUN."""

            result = parse_cobol(
                cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL
            )

            assert (
                result.success
            ), f"Failed to parse {description} (level {level}): {result.errors[:3]}"
            assert result.ast is not None

    def test_data_division_sections(self):
        """Test parsing different DATA DIVISION sections."""
        sections = [
            ("WORKING-STORAGE SECTION", "Working storage"),
            ("FILE SECTION", "File section"),
            ("LINKAGE SECTION", "Linkage section"),
        ]

        for section, description in sections:
            cobol_source = f"""IDENTIFICATION DIVISION.
PROGRAM-ID. SECTION-TEST.

DATA DIVISION.
{section}.
01  WS-FIELD    PIC X(10).

PROCEDURE DIVISION.
STOP RUN."""

            result = parse_cobol(
                cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL
            )

            assert result.success, f"Failed to parse {description}: {result.errors[:3]}"
            assert result.ast is not None

    def test_usage_clauses(self):
        """Test parsing USAGE clauses."""
        usage_types = [
            ("COMP", "Computational"),
            ("COMP-3", "Packed decimal"),
            ("COMPUTATIONAL", "Full computational"),
            ("DISPLAY", "Display usage"),
        ]

        for usage, description in usage_types:
            cobol_source = f"""IDENTIFICATION DIVISION.
PROGRAM-ID. USAGE-TEST.

DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-FIELD    PIC 9(5) {usage}.

PROCEDURE DIVISION.
STOP RUN."""

            result = parse_cobol(
                cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL
            )

            assert (
                result.success
            ), f"Failed to parse {description} usage: {result.errors[:3]}"
            assert result.ast is not None

    def test_value_clauses(self):
        """Test parsing VALUE clauses with different literal types."""
        value_types = [
            ('"Hello"', "String literal"),
            ("123", "Numeric literal"),
            ("ZERO", "Figurative constant"),
            ("SPACES", "Figurative constant"),
            ("123.45", "Decimal literal"),
        ]

        for value, description in value_types:
            cobol_source = f"""IDENTIFICATION DIVISION.
PROGRAM-ID. VALUE-TEST.

DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-FIELD    PIC X(10) VALUE {value}.

PROCEDURE DIVISION.
STOP RUN."""

            result = parse_cobol(
                cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL
            )

            assert (
                result.success
            ), f"Failed to parse {description} value: {result.errors[:3]}"
            assert result.ast is not None


class TestProblematicPatterns:
    """Test patterns that were historically problematic; all now parse."""

    def test_environment_division_parsing(self):
        """Test ENVIRONMENT DIVISION parsing."""
        cobol_source = """IDENTIFICATION DIVISION.
PROGRAM-ID. ENV-TEST.

ENVIRONMENT DIVISION.
CONFIGURATION SECTION.
SOURCE-COMPUTER. IBM-3090.
OBJECT-COMPUTER. IBM-3090.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT PRINT-FILE ASSIGN TO PRINTER.

DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-FIELD    PIC X(10).

PROCEDURE DIVISION.
STOP RUN."""

        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert (
            result.success
        ), f"ENVIRONMENT DIVISION failed to parse: {result.errors[:5]}"
        assert result.ast is not None
        assert result.ast.has_division("ENVIRONMENT")

    def test_redefines_clause_parsing(self):
        """Test REDEFINES clause parsing."""
        cobol_source = """IDENTIFICATION DIVISION.
PROGRAM-ID. REDEFINES-TEST.

DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-AREA     PIC X(10).
01  WS-NUM REDEFINES WS-AREA PIC 9(10).

PROCEDURE DIVISION.
STOP RUN."""

        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert result.success, f"REDEFINES failed to parse: {result.errors[:5]}"
        assert result.ast is not None
        item_names = {
            getattr(item, "name", None)
            for item in result.ast.find_all_by_type("CobolDataItem")
        }
        assert "WS-NUM" in item_names, "REDEFINES data item missing from AST"

    def test_occurs_clause_parsing(self):
        """Test OCCURS clause parsing."""
        cobol_source = """IDENTIFICATION DIVISION.
PROGRAM-ID. OCCURS-TEST.

DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-ARRAY.
    05  WS-ITEM OCCURS 10 TIMES PIC 9(5).

PROCEDURE DIVISION.
STOP RUN."""

        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert result.success, f"OCCURS failed to parse: {result.errors[:5]}"
        assert result.ast is not None
        item_names = {
            getattr(item, "name", None)
            for item in result.ast.find_all_by_type("CobolDataItem")
        }
        assert "WS-ITEM" in item_names, "OCCURS data item missing from AST"

    def test_procedure_division_statements(self):
        """Test PROCEDURE DIVISION statement parsing."""
        statements = [
            ("DISPLAY WS-FIELD", "DISPLAY statement"),
            ("MOVE 123 TO WS-FIELD", "MOVE statement"),
            ("ADD 1 TO WS-FIELD", "ADD statement"),
            ("CALL 'SUBPROG' USING WS-FIELD", "CALL statement"),
            ("PERFORM PARA-1", "PERFORM statement"),
        ]

        for stmt, description in statements:
            cobol_source = f"""IDENTIFICATION DIVISION.
PROGRAM-ID. STMT-TEST.

DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-FIELD    PIC 9(5).

PROCEDURE DIVISION.
{stmt}.
PARA-1.
    DISPLAY "Test".
STOP RUN."""

            result = parse_cobol(
                cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL
            )

            assert result.success, f"Failed to parse {description}: {result.errors[:3]}"
            assert result.ast is not None


class TestNistProgramPatterns:
    """Test patterns found in NIST example programs."""

    def test_nist_program_header_format(self):
        """Test parsing programs with NIST header format."""
        # Simplified version of NIST program structure
        cobol_source = """      *HEADER,COBOL,IC101A
000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID.
000300     IC101A.
000400*    COMMENTS AND DOCUMENTATION
000500 ENVIRONMENT DIVISION.
000600 CONFIGURATION SECTION.
000700 SOURCE-COMPUTER.
000800     XXXXX082.
000900 OBJECT-COMPUTER.
001000     XXXXX083.
001100 DATA DIVISION.
001200 WORKING-STORAGE SECTION.
001300 77  DN1 PICTURE S9  VALUE ZERO.
001400 PROCEDURE DIVISION.
001500 STOP RUN."""

        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert result.success, f"NIST format failed to parse: {result.errors[:10]}"
        assert result.ast is not None
        assert result.ast.program_name == "IC101A"

    def test_simplified_nist_structure(self):
        """Test a simplified version of NIST program structure."""
        cobol_source = """IDENTIFICATION DIVISION.
PROGRAM-ID. IC101A.

ENVIRONMENT DIVISION.
CONFIGURATION SECTION.
SOURCE-COMPUTER. XXXXX082.
OBJECT-COMPUTER. XXXXX083.

DATA DIVISION.
WORKING-STORAGE SECTION.
77  DN1 PICTURE S9  VALUE ZERO.

PROCEDURE DIVISION.
CALL "IC102A" USING DN1.
STOP RUN."""

        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert result.success, f"Simplified NIST failed to parse: {result.errors[:5]}"
        assert result.ast is not None
        assert result.ast.program_name == "IC101A"
        # The CALL statement must survive into the AST.
        assert len(result.ast.find_all_by_type("CallStatement")) == 1
