"""
Regression tests for public API stability.

These tests verify that all exports in cobolparser.__all__ remain importable
and that core parse functions return objects with the expected shape.
Any accidental removal of a public symbol will be caught here.
"""

import pytest

import cobolparser

# ── Importability ──────────────────────────────────────────────────────────────


class TestAllExportsImportable:
    """Every name in __all__ must be importable from cobolparser."""

    @pytest.mark.parametrize("name", cobolparser.__all__)
    def test_symbol_is_accessible(self, name):
        assert hasattr(
            cobolparser, name
        ), f"cobolparser.{name} is in __all__ but cannot be accessed"

    def test_star_import_matches_all(self):
        """Importing * from cobolparser should expose every __all__ name."""
        ns = {}
        exec("from cobolparser import *", ns)
        for name in cobolparser.__all__:
            assert name in ns, f"{name!r} missing from 'from cobolparser import *'"


# ── ParseResult contract ───────────────────────────────────────────────────────

MINIMAL_COBOL = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. REGTEST.
PROCEDURE DIVISION.
    STOP RUN.
"""


class TestParseResultContract:
    """parse_cobol() must return a ParseResult with stable fields."""

    def test_parse_result_has_ast(self):
        result = cobolparser.parse_cobol(MINIMAL_COBOL)
        assert result is not None
        assert result.ast is not None

    def test_parse_result_ast_is_cobol_program(self):
        result = cobolparser.parse_cobol(MINIMAL_COBOL)
        assert isinstance(result.ast, cobolparser.CobolProgram)

    def test_parse_result_errors_is_list(self):
        result = cobolparser.parse_cobol(MINIMAL_COBOL)
        assert isinstance(result.errors, list)

    def test_parse_result_warnings_is_list(self):
        result = cobolparser.parse_cobol(MINIMAL_COBOL)
        assert isinstance(result.warnings, list)

    def test_parse_result_statistics_present(self):
        result = cobolparser.parse_cobol(MINIMAL_COBOL)
        assert result.statistics is not None

    def test_cobol_parser_class_instantiates(self):
        parser = cobolparser.CobolParser()
        assert parser is not None

    def test_cobol_parser_with_error_recovery(self):
        parser = cobolparser.CobolParser(
            error_recovery=cobolparser.ErrorRecoveryMode.COLLECT_ALL
        )
        result = parser.parse(MINIMAL_COBOL)
        assert result is not None

    def test_program_name_populated(self):
        result = cobolparser.parse_cobol(MINIMAL_COBOL)
        assert result.ast.program_name == "REGTEST"

    def test_ast_to_json_returns_string(self):
        result = cobolparser.parse_cobol(MINIMAL_COBOL)
        json_str = result.ast.to_json()
        assert isinstance(json_str, str)
        assert len(json_str) > 0

    def test_ast_to_dict_returns_dict(self):
        result = cobolparser.parse_cobol(MINIMAL_COBOL)
        d = result.ast.to_dict()
        assert isinstance(d, dict)
        assert "program_name" in d


# ── Exception hierarchy ────────────────────────────────────────────────────────


class TestExceptionHierarchy:
    """Public exceptions must be catchable as their documented base types."""

    def test_preprocessing_error_is_exception(self):
        assert issubclass(cobolparser.PreprocessingError, Exception)

    def test_circular_reference_error_is_preprocessing_error(self):
        assert issubclass(
            cobolparser.CircularReferenceError, cobolparser.PreprocessingError
        )

    def test_copybook_not_found_is_preprocessing_error(self):
        assert issubclass(
            cobolparser.CopybookNotFoundError, cobolparser.PreprocessingError
        )

    def test_path_traversal_error_is_preprocessing_error(self):
        assert issubclass(
            cobolparser.PathTraversalError, cobolparser.PreprocessingError
        )

    def test_encoding_error_is_preprocessing_error(self):
        assert issubclass(cobolparser.EncodingError, cobolparser.PreprocessingError)

    def test_nesting_depth_error_is_preprocessing_error(self):
        assert issubclass(cobolparser.NestingDepthError, cobolparser.PreprocessingError)

    def test_parse_error_is_exception(self):
        assert issubclass(cobolparser.ParseError, Exception)
