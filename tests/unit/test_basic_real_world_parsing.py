"""
Simple unit tests to verify basic parsing functionality works with real-world patterns.

This test module focuses on ensuring that the parser can successfully parse
COBOL programs with patterns found in the examples directory, without
getting into complex AST verification initially.
"""

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol


class TestBasicParsing:
    """Test basic parsing of real-world COBOL patterns."""

    def test_simple_cobol_program_parses(self):
        """Test that a simple COBOL program parses successfully."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-SIMPLE.

        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-MESSAGE    PIC X(20) VALUE "Hello World".

        PROCEDURE DIVISION.
        DISPLAY WS-MESSAGE.
        STOP RUN.
        """

        result = parse_cobol(cobol_source)

        assert result.success, f"Simple program failed to parse: {result.errors[:5]}"
        assert result.ast is not None
        assert result.ast.program_name == "TEST-SIMPLE"

    def test_picture_clause_variations(self):
        """Test various PICTURE clause patterns found in examples."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-PICTURES.

        DATA DIVISION.
        WORKING-STORAGE SECTION.
        77  WRK-DS-18V00                PICTURE S9(18).
        77  A06THREES-DS-03V03          PICTURE S999V999 VALUE 333.333.
        77  WRK-DS-06V06                PICTURE S9(6)V9(6).
        01  SIMPLE-FIELD                PIC X(10).

        PROCEDURE DIVISION.
        STOP RUN.
        """

        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert (
            result.success
        ), f"PICTURE variations failed to parse: {result.errors[:5]}"
        assert result.ast is not None
        item_names = {
            getattr(item, "name", None)
            for item in result.ast.find_all_by_type("CobolDataItem")
        }
        assert {"WRK-DS-18V00", "A06THREES-DS-03V03", "SIMPLE-FIELD"} <= item_names

    def test_redefines_pattern(self):
        """Test REDEFINES clause parsing."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-REDEFINES.

        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WRK-AREA                    PIC X(10).
        01  WRK-NUMERIC REDEFINES WRK-AREA PIC 9(10).

        PROCEDURE DIVISION.
        STOP RUN.
        """

        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert result.success, f"REDEFINES failed to parse: {result.errors[:5]}"
        assert result.ast is not None
        item_names = {
            getattr(item, "name", None)
            for item in result.ast.find_all_by_type("CobolDataItem")
        }
        assert "WRK-NUMERIC" in item_names, "REDEFINES data item missing from AST"

    def test_occurs_pattern(self):
        """Test OCCURS clause parsing."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-OCCURS.

        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  ARR-DATA.
            05  ARR-ITEM OCCURS 10 TIMES PIC 9(5).

        PROCEDURE DIVISION.
        STOP RUN.
        """

        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert result.success, f"OCCURS failed to parse: {result.errors[:5]}"
        assert result.ast is not None
        item_names = {
            getattr(item, "name", None)
            for item in result.ast.find_all_by_type("CobolDataItem")
        }
        assert "ARR-ITEM" in item_names, "OCCURS data item missing from AST"

    def test_call_statement(self):
        """Test CALL statement parsing."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-CALL.

        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-PARAM    PIC X(10).

        PROCEDURE DIVISION.
        CALL "SUBPROG" USING WS-PARAM.
        STOP RUN.
        """

        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert result.success, f"CALL failed to parse: {result.errors[:5]}"
        assert result.ast is not None
        assert (
            len(result.ast.find_all_by_type("CallStatement")) == 1
        ), "CALL statement missing from AST"

    def test_computational_fields(self):
        """Test COMPUTATIONAL field parsing."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-COMP.

        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-COMP-FIELD               PIC 9(5) COMP.
        01  WS-COMP3-FIELD              PIC 9(7)V99 COMP-3.

        PROCEDURE DIVISION.
        STOP RUN.
        """

        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert result.success, f"COMP fields failed to parse: {result.errors[:5]}"
        assert result.ast is not None
        item_names = {
            getattr(item, "name", None)
            for item in result.ast.find_all_by_type("CobolDataItem")
        }
        assert {"WS-COMP-FIELD", "WS-COMP3-FIELD"} <= item_names

    def test_file_control_structure(self):
        """Test file control and FD parsing."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-FILES.

        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT PRINT-FILE ASSIGN TO PRINTER.

        DATA DIVISION.
        FILE SECTION.
        FD  PRINT-FILE.
        01  PRINT-REC PICTURE X(120).

        PROCEDURE DIVISION.
        STOP RUN.
        """

        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert result.success, f"FILE-CONTROL failed to parse: {result.errors[:5]}"
        assert result.ast is not None
        assert result.ast.has_division("ENVIRONMENT")
        item_names = {
            getattr(item, "name", None)
            for item in result.ast.find_all_by_type("CobolDataItem")
        }
        assert "PRINT-REC" in item_names, "FD record missing from AST"


class TestRealWorldPrograms:
    """Test parsing of actual programs from examples directory."""

    def test_parsing_test_program_cob(self):
        """Test parsing the main test_program.cob file."""
        try:
            with open("test_program.cob") as f:
                cobol_source = f.read()

            result = parse_cobol(
                cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL
            )

            assert (
                result.success
            ), f"test_program.cob failed to parse: {result.errors[:5]}"
            assert result.ast is not None

        except FileNotFoundError:
            pytest.skip("test_program.cob not found")

    def test_parsing_sample_nist_program(self):
        """Test parsing one of the NIST COBOL programs."""
        import pathlib

        examples_dir = pathlib.Path("examples/cobol")
        if not examples_dir.exists():
            pytest.skip("examples/cobol directory not found")

        # Try to find a simple example program
        sample_files = ["IC101A.CBL", "NC101A.CBL", "IF101A.CBL"]

        for filename in sample_files:
            sample_file = examples_dir / filename
            if sample_file.exists():
                with open(sample_file) as f:
                    cobol_source = f.read()

                result = parse_cobol(
                    cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL
                )

                assert (
                    result.success
                ), f"{filename} failed to parse: {result.errors[:5]}"
                assert result.ast is not None
                return  # Successfully tested one file

        pytest.skip("No sample COBOL files found in examples/cobol")
