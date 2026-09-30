"""Unit tests for IODiagnosticHelper and IOErrorCode.

analysis/io_diagnostics.py is at 0% coverage because it is never imported.
These tests exercise all enum values and all three static methods.
"""

from cobolparser._errors import ParseError
from cobolparser.analysis.io_diagnostics import IODiagnosticHelper, IOErrorCode


class TestIOErrorCodeEnum:
    """Verify all IOErrorCode enum members are accessible and have non-empty values."""

    def test_read_error_codes_exist(self):
        assert (
            IOErrorCode.IO_READ_INVALID_KEY_ORDER.value == "IO_READ_INVALID_KEY_ORDER"
        )
        assert (
            IOErrorCode.IO_READ_LOCK_ON_SEQUENTIAL.value == "IO_READ_LOCK_ON_SEQUENTIAL"
        )
        assert (
            IOErrorCode.IO_READ_AT_END_WITHOUT_FILE.value
            == "IO_READ_AT_END_WITHOUT_FILE"
        )

    def test_write_error_codes_exist(self):
        assert (
            IOErrorCode.IO_WRITE_ADVANCING_INVALID_UNIT.value
            == "IO_WRITE_ADVANCING_INVALID_UNIT"
        )
        assert (
            IOErrorCode.IO_WRITE_DELETE_INVALID_ORG.value
            == "IO_WRITE_DELETE_INVALID_ORG"
        )

    def test_open_error_codes_exist(self):
        assert IOErrorCode.IO_OPEN_INVALID_MODE.value == "IO_OPEN_INVALID_MODE"
        assert IOErrorCode.IO_OPEN_REEL_ON_DISK.value == "IO_OPEN_REEL_ON_DISK"

    def test_close_error_codes_exist(self):
        assert (
            IOErrorCode.IO_CLOSE_NO_REWIND_INVALID.value == "IO_CLOSE_NO_REWIND_INVALID"
        )
        assert (
            IOErrorCode.IO_CLOSE_WITH_LOCK_INVALID.value == "IO_CLOSE_WITH_LOCK_INVALID"
        )

    def test_rewrite_error_codes_exist(self):
        assert IOErrorCode.IO_REWRITE_INVALID_ORG.value == "IO_REWRITE_INVALID_ORG"
        assert (
            IOErrorCode.IO_REWRITE_INVALID_KEY_ORDER.value
            == "IO_REWRITE_INVALID_KEY_ORDER"
        )

    def test_delete_error_codes_exist(self):
        assert IOErrorCode.IO_DELETE_INVALID_ORG.value == "IO_DELETE_INVALID_ORG"
        assert (
            IOErrorCode.IO_DELETE_INVALID_KEY_ORDER.value
            == "IO_DELETE_INVALID_KEY_ORDER"
        )

    def test_start_error_codes_exist(self):
        assert IOErrorCode.IO_START_INVALID_ORG.value == "IO_START_INVALID_ORG"
        assert IOErrorCode.IO_START_MISSING_KEY.value == "IO_START_MISSING_KEY"
        assert (
            IOErrorCode.IO_START_INVALID_KEY_CONDITION.value
            == "IO_START_INVALID_KEY_CONDITION"
        )

    def test_accept_display_error_codes_exist(self):
        assert IOErrorCode.IO_ACCEPT_INVALID_FROM.value == "IO_ACCEPT_INVALID_FROM"
        assert IOErrorCode.IO_DISPLAY_INVALID_UPON.value == "IO_DISPLAY_INVALID_UPON"

    def test_unlock_error_code_exists(self):
        assert IOErrorCode.IO_UNLOCK_INVALID_ORG.value == "IO_UNLOCK_INVALID_ORG"

    def test_generic_error_codes_exist(self):
        assert IOErrorCode.IO_INVALID_LOCK.value == "IO_INVALID_LOCK"
        assert IOErrorCode.IO_INVALID_FILE_ORG.value == "IO_INVALID_FILE_ORG"
        assert (
            IOErrorCode.IO_MISSING_REQUIRED_CLAUSE.value == "IO_MISSING_REQUIRED_CLAUSE"
        )

    def test_all_codes_are_nonempty_strings(self):
        """Every IOErrorCode value is a non-empty string."""
        for code in IOErrorCode:
            assert isinstance(code.value, str), f"{code} value is not a string"
            assert len(code.value) > 0, f"{code} value is empty"

    def test_enum_has_expected_count(self):
        """Sanity check: at least 15 error codes defined."""
        assert len(list(IOErrorCode)) >= 15


class TestIODiagnosticHelperGetMessage:
    """Tests for IODiagnosticHelper.get_error_message()."""

    def test_known_code_returns_string(self):
        msg = IODiagnosticHelper.get_error_message(
            IOErrorCode.IO_READ_LOCK_ON_SEQUENTIAL
        )
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_all_codes_have_messages(self):
        """Every IOErrorCode should have a non-empty message in ERROR_MESSAGES."""
        for code in IOErrorCode:
            msg = IODiagnosticHelper.get_error_message(code)
            assert isinstance(msg, str), f"No string message for {code}"
            assert len(msg) > 0, f"Empty message for {code}"

    def test_start_invalid_org_message_content(self):
        msg = IODiagnosticHelper.get_error_message(IOErrorCode.IO_START_INVALID_ORG)
        # Should mention indexed, relative, or sequential
        lower = msg.lower()
        assert any(
            word in lower for word in ("indexed", "relative", "sequential")
        ), f"Message should mention file org types: {msg}"

    def test_read_lock_message_mentions_sequential(self):
        msg = IODiagnosticHelper.get_error_message(
            IOErrorCode.IO_READ_LOCK_ON_SEQUENTIAL
        )
        assert "sequential" in msg.lower()

    def test_close_no_rewind_message_mentions_tape(self):
        msg = IODiagnosticHelper.get_error_message(
            IOErrorCode.IO_CLOSE_NO_REWIND_INVALID
        )
        assert "tape" in msg.lower() or "rewind" in msg.lower()


class TestIODiagnosticHelperCreateError:
    """Tests for IODiagnosticHelper.create_io_error()."""

    def test_returns_parse_error_instance(self):
        err = IODiagnosticHelper.create_io_error(IOErrorCode.IO_READ_LOCK_ON_SEQUENTIAL)
        assert isinstance(err, ParseError)

    def test_error_has_code_attribute(self):
        err = IODiagnosticHelper.create_io_error(IOErrorCode.IO_OPEN_INVALID_MODE)
        assert hasattr(err, "code")
        assert err.code == "IO_OPEN_INVALID_MODE"

    def test_error_message_matches_helper(self):
        code = IOErrorCode.IO_CLOSE_NO_REWIND_INVALID
        err = IODiagnosticHelper.create_io_error(code)
        expected_msg = IODiagnosticHelper.get_error_message(code)
        assert expected_msg in err.message

    def test_error_with_context_appended(self):
        err = IODiagnosticHelper.create_io_error(
            IOErrorCode.IO_START_INVALID_ORG, context="CLOSE TAPEFILE WITH NO REWIND"
        )
        assert "CLOSE TAPEFILE WITH NO REWIND" in err.message

    def test_error_with_line(self):
        err = IODiagnosticHelper.create_io_error(
            IOErrorCode.IO_DELETE_INVALID_ORG, line=42, column=8
        )
        assert err.line_number == 42

    def test_error_with_column(self):
        err = IODiagnosticHelper.create_io_error(
            IOErrorCode.IO_DELETE_INVALID_ORG, line=1, column=8
        )
        assert err.column == 8

    def test_error_code_value_stored(self):
        """Code attribute stores the string value of the enum."""
        for code in list(IOErrorCode)[:5]:  # spot check first 5
            err = IODiagnosticHelper.create_io_error(code)
            assert err.code == code.value


class TestIODiagnosticHelperValidate:
    """Tests for IODiagnosticHelper.validate_io_statement_type()."""

    def test_no_org_returns_none(self):
        """No file organization info → no error."""
        result = IODiagnosticHelper.validate_io_statement_type("START")
        assert result is None

    def test_start_on_sequential_returns_start_error(self):
        result = IODiagnosticHelper.validate_io_statement_type("START", "SEQUENTIAL")
        assert result == IOErrorCode.IO_START_INVALID_ORG

    def test_start_on_indexed_returns_none(self):
        result = IODiagnosticHelper.validate_io_statement_type("START", "INDEXED")
        assert result is None

    def test_start_on_relative_returns_none(self):
        result = IODiagnosticHelper.validate_io_statement_type("START", "RELATIVE")
        assert result is None

    def test_rewrite_on_line_sequential_returns_rewrite_error(self):
        result = IODiagnosticHelper.validate_io_statement_type(
            "REWRITE", "LINE SEQUENTIAL"
        )
        assert result == IOErrorCode.IO_REWRITE_INVALID_ORG

    def test_rewrite_on_indexed_returns_none(self):
        result = IODiagnosticHelper.validate_io_statement_type("REWRITE", "INDEXED")
        assert result is None

    def test_delete_on_sequential_returns_delete_error(self):
        result = IODiagnosticHelper.validate_io_statement_type("DELETE", "SEQUENTIAL")
        assert result == IOErrorCode.IO_DELETE_INVALID_ORG

    def test_delete_on_indexed_returns_none(self):
        result = IODiagnosticHelper.validate_io_statement_type("DELETE", "INDEXED")
        assert result is None

    def test_unlock_on_relative_returns_unlock_error(self):
        result = IODiagnosticHelper.validate_io_statement_type("UNLOCK", "RELATIVE")
        assert result == IOErrorCode.IO_UNLOCK_INVALID_ORG

    def test_unlock_on_indexed_returns_none(self):
        result = IODiagnosticHelper.validate_io_statement_type("UNLOCK", "INDEXED")
        assert result is None

    def test_case_insensitive_statement_type(self):
        """Statement type matching is case-insensitive."""
        result = IODiagnosticHelper.validate_io_statement_type("start", "sequential")
        assert result == IOErrorCode.IO_START_INVALID_ORG

    def test_case_insensitive_org(self):
        """Organization matching is case-insensitive."""
        result = IODiagnosticHelper.validate_io_statement_type("DELETE", "sequential")
        assert result == IOErrorCode.IO_DELETE_INVALID_ORG

    def test_read_on_sequential_returns_none(self):
        """READ is not restricted by organization."""
        result = IODiagnosticHelper.validate_io_statement_type("READ", "SEQUENTIAL")
        assert result is None

    def test_read_on_indexed_returns_none(self):
        result = IODiagnosticHelper.validate_io_statement_type("READ", "INDEXED")
        assert result is None

    def test_write_on_sequential_returns_none(self):
        """WRITE is not restricted by validate_io_statement_type."""
        result = IODiagnosticHelper.validate_io_statement_type("WRITE", "SEQUENTIAL")
        assert result is None
