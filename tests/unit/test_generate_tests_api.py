"""Unit tests for the generate_cobolcheck_tests convenience function.

Tests the public API function that pipelines parsing -> analysis ->
test plan -> CobolCheck generation.
"""

import pytest

from cobolparser import generate_cobolcheck_tests

# Minimal valid COBOL program with a paragraph that has a MOVE and DISPLAY
_SIMPLE_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NUM       PIC 9(5) VALUE ZEROS.
       01  WS-RESULT    PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE WS-NUM TO WS-RESULT
           DISPLAY WS-RESULT
           STOP RUN.
       COMPUTE-IT.
           ADD 1 TO WS-RESULT.
"""

# Minimal program with no procedure division
_NO_PROCEDURE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOPROC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X    PIC X(10).
"""

# Invalid COBOL source that should fail parsing
_INVALID_SOURCE = "THIS IS NOT COBOL AT ALL !!!!"


class TestGenerateCobolcheckTests:
    """Tests for generate_cobolcheck_tests()."""

    def test_basic_generation(self):
        result = generate_cobolcheck_tests(_SIMPLE_PROGRAM)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_output_contains_testsuite(self):
        result = generate_cobolcheck_tests(_SIMPLE_PROGRAM)
        assert "TESTSUITE" in result

    def test_output_contains_testcase(self):
        result = generate_cobolcheck_tests(_SIMPLE_PROGRAM)
        assert "TESTCASE" in result

    def test_output_contains_perform(self):
        result = generate_cobolcheck_tests(_SIMPLE_PROGRAM)
        assert "PERFORM" in result

    def test_custom_strategies_paragraph_only(self):
        result = generate_cobolcheck_tests(_SIMPLE_PROGRAM, strategies=["paragraph"])
        assert "TESTSUITE" in result
        # Should not have boundary suite
        assert "Boundary" not in result

    def test_custom_strategies_branch_only(self):
        result = generate_cobolcheck_tests(_SIMPLE_PROGRAM, strategies=["branch"])
        assert isinstance(result, str)

    def test_custom_filename(self):
        result = generate_cobolcheck_tests(_SIMPLE_PROGRAM, filename="myprogram.cbl")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_invalid_source_raises_valueerror(self):
        with pytest.raises(ValueError, match="Failed to parse"):
            generate_cobolcheck_tests(_INVALID_SOURCE)

    def test_no_procedure_division_generates_output(self):
        result = generate_cobolcheck_tests(_NO_PROCEDURE)
        assert isinstance(result, str)
        # No procedure division means no test suites, but still valid output
        assert "No test suites generated" in result or "TESTSUITE" not in result

    def test_output_ends_with_newline(self):
        result = generate_cobolcheck_tests(_SIMPLE_PROGRAM)
        assert result.endswith("\n")
