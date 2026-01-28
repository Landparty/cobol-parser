"""
Contract tests for VALUE clause parsing with figurative constants.

These tests ensure API stability for VALUE clause handling across versions.
Specifically documents expected behavior for VALUE + figurative constants
to prevent regressions in future refactoring.

Contract: VALUE with figurative constants (SPACE, SPACES, ZERO, etc.) should:
- Tokenize figurative constant as identifier/keyword, not string literal
- Not trigger multi-line string continuation mode
- Maintain AST structure compatibility across versions
"""

import pytest
from cobolparser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode


class TestValueClauseFigurativeConstantsContract:
    """Contract tests for VALUE clause with figurative constants."""

    def test_backward_compatibility_baseline_value_space(self):
        """Baseline: VALUE SPACE should parse successfully."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-VALUE-SPACE.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 TEST-VAR              PIC X(48) VALUE SPACE.
        
        PROCEDURE DIVISION.
        STOP RUN.
        """
        
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        result = parser.parse(cobol_source)
        
        # Contract: Should parse successfully
        assert result.success, f"Parse failed: {result.errors}"
        assert result.ast is not None
        assert result.ast.program_name == "TEST-VALUE-SPACE"
        
        # Contract: Working storage should contain the data item
        assert result.ast.data_division is not None
        assert result.ast.data_division.working_storage is not None
        
        # Contract: AST structure preserved
        ast_dict = result.ast.to_dict()
        assert "node_type" in ast_dict
        assert "program_name" in ast_dict
        assert "data_division" in ast_dict

    def test_backward_compatibility_baseline_value_spaces(self):
        """Baseline: VALUE SPACES should parse successfully."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-VALUE-SPACES.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 ANSI-REFERENCE        PIC X(48) VALUE SPACES.
        
        PROCEDURE DIVISION.
        STOP RUN.
        """
        
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        result = parser.parse(cobol_source)
        
        assert result.success, f"Parse failed: {result.errors}"
        assert result.ast is not None
        assert result.ast.program_name == "TEST-VALUE-SPACES"

    def test_backward_compatibility_baseline_value_zero(self):
        """Baseline: VALUE ZERO/ZEROS should parse successfully."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-VALUE-ZERO.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 COUNTER               PIC 9(5) VALUE ZERO.
        01 FLAGS                 PIC 9(3) VALUE ZEROS.
        
        PROCEDURE DIVISION.
        STOP RUN.
        """
        
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        result = parser.parse(cobol_source)
        
        assert result.success, f"Parse failed: {result.errors}"
        assert result.ast is not None

    def test_backward_compatibility_baseline_value_high_value(self):
        """Baseline: VALUE HIGH-VALUE/HIGH-VALUES should parse successfully."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-VALUE-HIGH.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 TEST-VAR1             PIC X(10) VALUE HIGH-VALUE.
        01 TEST-VAR2             PIC X(10) VALUE HIGH-VALUES.
        
        PROCEDURE DIVISION.
        STOP RUN.
        """
        
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        result = parser.parse(cobol_source)
        
        assert result.success, f"Parse failed: {result.errors}"
        assert result.ast is not None

    def test_backward_compatibility_baseline_value_low_value(self):
        """Baseline: VALUE LOW-VALUE/LOW-VALUES should parse successfully."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-VALUE-LOW.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 TEST-VAR1             PIC X(10) VALUE LOW-VALUE.
        01 TEST-VAR2             PIC X(10) VALUE LOW-VALUES.
        
        PROCEDURE DIVISION.
        STOP RUN.
        """
        
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        result = parser.parse(cobol_source)
        
        assert result.success, f"Parse failed: {result.errors}"
        assert result.ast is not None

    def test_backward_compatibility_baseline_value_quote_quotes(self):
        """Baseline: VALUE QUOTE/QUOTES should parse successfully."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-VALUE-QUOTE.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 TEST-VAR1             PIC X VALUE QUOTE.
        01 TEST-VAR2             PIC X VALUE QUOTES.
        
        PROCEDURE DIVISION.
        STOP RUN.
        """
        
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        result = parser.parse(cobol_source)
        
        assert result.success, f"Parse failed: {result.errors}"
        assert result.ast is not None

    def test_backward_compatibility_multiple_value_clauses_with_figurative_constants(self):
        """Baseline: Multiple VALUE clauses with mixed figurative constants."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-MULTIPLE-VALUES.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 TEST-RESULTS.
           02 FILLER             PIC X      VALUE SPACE.
           02 FEATURE            PIC X(20)  VALUE SPACE.
           02 FILLER             PIC X      VALUE SPACE.
           02 P-OR-F             PIC X(5)   VALUE SPACE.
           02 FILLER             PIC X      VALUE SPACE.
           02 PAR-NAME.
             03 FILLER           PIC X(19)  VALUE SPACE.
             03 PARDOT-X         PIC X      VALUE SPACE.
             03 DOTVALUE         PIC 99     VALUE ZERO.
        
        PROCEDURE DIVISION.
        STOP RUN.
        """
        
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        result = parser.parse(cobol_source)
        
        # Contract: All VALUE clauses with figurative constants should parse
        assert result.success, f"Parse failed: {result.errors}"
        assert result.ast is not None
        assert result.ast.data_division is not None

    def test_backward_compatibility_value_is_space_with_comment_line(self):
        """Baseline: VALUE SPACE followed by comment line should parse correctly."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-VALUE-COMMENT.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 TEST-VAR              PIC X(48) VALUE SPACE.
      * THIS IS A COMMENT LINE WITH "QUOTES"
        01 NEXT-VAR              PIC X(10) VALUE SPACE.
        
        PROCEDURE DIVISION.
        STOP RUN.
        """
        
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        result = parser.parse(cobol_source)
        
        # Contract: Comment should not interfere with VALUE SPACE parsing
        assert result.success, f"Parse failed: {result.errors}"
        assert result.ast is not None

    def test_api_contract_value_clause_ast_structure(self):
        """API Contract: VALUE clause AST structure with figurative constants."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-API.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 TEST-VAR              PIC X(10) VALUE SPACE.
        
        PROCEDURE DIVISION.
        STOP RUN.
        """
        
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        result = parser.parse(cobol_source)
        
        assert result.success, f"Parse failed: {result.errors}"
        
        # Contract: AST must be serializable to dict
        ast_dict = result.ast.to_dict()
        assert isinstance(ast_dict, dict)
        
        # Contract: Required fields in AST dict
        required_fields = ["node_type", "program_name", "identification_division", 
                          "data_division", "procedure_division"]
        for field in required_fields:
            assert field in ast_dict, f"Missing required field: {field}"
        
        # Contract: Data division must be structured
        data_div = ast_dict["data_division"]
        assert data_div is not None
        assert "working_storage" in data_div or "working_storage_section" in data_div

    def test_api_contract_json_serialization_with_figurative_constants(self):
        """API Contract: VALUE clauses with figurative constants must be JSON-serializable."""
        cobol_source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-JSON.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 TEST-VAR1             PIC X(10) VALUE SPACE.
        01 TEST-VAR2             PIC 9(5)  VALUE ZERO.
        
        PROCEDURE DIVISION.
        STOP RUN.
        """
        
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        result = parser.parse(cobol_source)
        
        assert result.success, f"Parse failed: {result.errors}"
        
        # Contract: Must be JSON-serializable
        import json
        try:
            json_output = result.ast.to_json()
            assert json_output is not None
            
            # Contract: JSON should be parseable
            parsed_json = json.loads(json_output)
            assert isinstance(parsed_json, dict)
            assert "program_name" in parsed_json
        except Exception as e:
            pytest.fail(f"JSON serialization failed: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
