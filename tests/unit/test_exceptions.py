"""Unit tests for ParseError hierarchy and exception handling."""

from cobolparser.core.exceptions import (
    DivisionNotFoundError,
    ParseError,
    TokenMismatch,
    UnexpectedEndOfInput,
    UnknownStatementError,
    ValidationError,
)


class TestParseErrorBase:
    """Tests for base ParseError class."""

    def test_parse_error_creation(self):
        """Create basic ParseError."""
        error = ParseError("Test error message")
        assert error.message == "Test error message"
        assert error.file_path is None
        assert error.line_number is None
        assert error.column is None

    def test_parse_error_with_location(self):
        """Create ParseError with location info."""
        error = ParseError("Error", file_path="test.cbl", line_number=10, column=5)
        assert error.message == "Error"
        assert error.file_path == "test.cbl"
        assert error.line_number == 10
        assert error.column == 5

    def test_parse_error_string_no_location(self):
        """ParseError formats without location."""
        error = ParseError("Test error")
        assert str(error) == "Parse error: Test error"

    def test_parse_error_string_with_file_only(self):
        """ParseError formats with file only."""
        error = ParseError("Test error", file_path="test.cbl")
        assert str(error) == "test.cbl: Test error"

    def test_parse_error_string_with_line(self):
        """ParseError formats with file and line."""
        error = ParseError("Test error", file_path="test.cbl", line_number=42)
        assert str(error) == "test.cbl:42: Test error"

    def test_parse_error_string_with_full_location(self):
        """ParseError formats with complete location."""
        error = ParseError(
            "Test error", file_path="test.cbl", line_number=42, column=15
        )
        assert str(error) == "test.cbl:42:15: Test error"

    def test_parse_error_string_line_only(self):
        """ParseError formats with line number only."""
        error = ParseError("Test error", line_number=42)
        assert "line 42" in str(error)
        assert "Test error" in str(error)

    def test_parse_error_string_line_and_column(self):
        """ParseError formats with line and column."""
        error = ParseError("Test error", line_number=42, column=15)
        assert "line 42, column 15" in str(error)
        assert "Test error" in str(error)

    def test_parse_error_is_exception(self):
        """ParseError is an Exception."""
        error = ParseError("Test")
        assert isinstance(error, Exception)


class TestTokenMismatch:
    """Tests for TokenMismatch exception."""

    def test_token_mismatch_creation(self):
        """Create TokenMismatch."""
        error = TokenMismatch("EXPECTED", "ACTUAL")
        assert error.expected == "EXPECTED"
        assert error.actual == "ACTUAL"
        assert "Expected 'EXPECTED'" in str(error)
        assert "got 'ACTUAL'" in str(error)

    def test_token_mismatch_with_location(self):
        """Create TokenMismatch with location."""
        error = TokenMismatch(
            "PROCEDURE", "DATA", file_path="prog.cbl", line_number=5, column=1
        )
        assert error.expected == "PROCEDURE"
        assert error.actual == "DATA"
        assert "prog.cbl" in str(error)

    def test_token_mismatch_inheritance(self):
        """TokenMismatch inherits from ParseError."""
        error = TokenMismatch("A", "B")
        assert isinstance(error, ParseError)


class TestUnexpectedEndOfInput:
    """Tests for UnexpectedEndOfInput exception."""

    def test_unexpected_end_simple(self):
        """Create UnexpectedEndOfInput."""
        error = UnexpectedEndOfInput()
        assert "Unexpected end of input" in str(error)

    def test_unexpected_end_with_expected(self):
        """UnexpectedEndOfInput with what was expected."""
        error = UnexpectedEndOfInput("PERIOD")
        assert "Unexpected end of input" in str(error)
        assert "expected: PERIOD" in str(error)

    def test_unexpected_end_with_location(self):
        """UnexpectedEndOfInput with file location."""
        error = UnexpectedEndOfInput(None, file_path="prog.cbl", line_number=100)
        assert "prog.cbl" in str(error)

    def test_unexpected_end_inheritance(self):
        """UnexpectedEndOfInput inherits from ParseError."""
        error = UnexpectedEndOfInput()
        assert isinstance(error, ParseError)


class TestDivisionNotFoundError:
    """Tests for DivisionNotFoundError exception."""

    def test_division_not_found(self):
        """Create DivisionNotFoundError."""
        error = DivisionNotFoundError("UNKNOWN")
        assert error.division_name == "UNKNOWN"
        assert "Unknown division: UNKNOWN" in str(error)

    def test_division_not_found_with_location(self):
        """DivisionNotFoundError with location."""
        error = DivisionNotFoundError("CUSTOM", file_path="prog.cbl", line_number=50)
        assert "prog.cbl" in str(error)
        assert "CUSTOM" in str(error)

    def test_division_not_found_inheritance(self):
        """DivisionNotFoundError inherits from ParseError."""
        error = DivisionNotFoundError("UNKNOWN")
        assert isinstance(error, ParseError)


class TestUnknownStatementError:
    """Tests for UnknownStatementError exception."""

    def test_unknown_statement_no_token(self):
        """Create UnknownStatementError without token."""
        error = UnknownStatementError()
        assert "Unknown or unrecognized statement" in str(error)

    def test_unknown_statement_with_token(self):
        """Create UnknownStatementError with token value."""
        error = UnknownStatementError("WEIRDKEYWORD")
        assert error.token_value == "WEIRDKEYWORD"
        assert "WEIRDKEYWORD" in str(error)

    def test_unknown_statement_with_location(self):
        """UnknownStatementError with location."""
        error = UnknownStatementError(
            "BADSTMT", file_path="prog.cbl", line_number=25, column=10
        )
        assert "prog.cbl:25:10" in str(error)

    def test_unknown_statement_inheritance(self):
        """UnknownStatementError inherits from ParseError."""
        error = UnknownStatementError()
        assert isinstance(error, ParseError)


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_validation_error_creation(self):
        """Create ValidationError."""
        error = ValidationError("DataItem", "Missing required field 'name'")
        assert error.node_type == "DataItem"
        assert error.issue == "Missing required field 'name'"
        assert "Validation error in DataItem" in str(error)
        assert "Missing required field 'name'" in str(error)

    def test_validation_error_with_location(self):
        """ValidationError with location."""
        error = ValidationError(
            "Statement", "Invalid value", file_path="prog.cbl", line_number=15
        )
        assert "prog.cbl" in str(error)

    def test_validation_error_inheritance(self):
        """ValidationError inherits from ParseError."""
        error = ValidationError("Node", "Issue")
        assert isinstance(error, ParseError)


class TestExceptionHierarchy:
    """Tests for exception hierarchy relationships."""

    def test_all_exceptions_inherit_from_parse_error(self):
        """All specific errors inherit from ParseError."""
        errors = [
            TokenMismatch("A", "B"),
            UnexpectedEndOfInput(),
            DivisionNotFoundError("UNKNOWN"),
            UnknownStatementError(),
            ValidationError("Type", "Issue"),
        ]

        for error in errors:
            assert isinstance(error, ParseError)

    def test_all_exceptions_are_exceptions(self):
        """All errors are proper Python exceptions."""
        errors = [
            ParseError("Test"),
            TokenMismatch("A", "B"),
            UnexpectedEndOfInput(),
            DivisionNotFoundError("UNKNOWN"),
            UnknownStatementError(),
            ValidationError("Type", "Issue"),
        ]

        for error in errors:
            assert isinstance(error, Exception)

    def test_exception_string_representations(self):
        """All exceptions have meaningful string representations."""
        errors = [
            ParseError("Test error"),
            TokenMismatch("EXPECTED", "ACTUAL"),
            UnexpectedEndOfInput(),
            DivisionNotFoundError("UNKNOWN"),
            UnknownStatementError("BADKEYWORD"),
            ValidationError("Node", "Issue"),
        ]

        for error in errors:
            str_repr = str(error)
            assert len(str_repr) > 0
            assert "error" in str_repr.lower() or "unknown" in str_repr.lower()


class TestExceptionCatching:
    """Tests for exception catching and handling patterns."""

    def test_catch_specific_token_mismatch(self):
        """Catch specific TokenMismatch."""
        try:
            raise TokenMismatch("PROCEDURE", "DATA")
        except TokenMismatch as e:
            assert e.expected == "PROCEDURE"
            assert e.actual == "DATA"

    def test_catch_as_parse_error(self):
        """Catch specific errors as ParseError."""
        try:
            raise UnknownStatementError("WEIRD")
        except ParseError as e:
            assert "WEIRD" in str(e)

    def test_catch_parse_error_catches_all(self):
        """Catching ParseError catches all subclasses."""
        errors = [
            TokenMismatch("A", "B"),
            UnexpectedEndOfInput(),
            DivisionNotFoundError("X"),
            UnknownStatementError(),
            ValidationError("T", "I"),
        ]

        for error in errors:
            caught = False
            try:
                raise error
            except ParseError:
                caught = True
            assert caught
