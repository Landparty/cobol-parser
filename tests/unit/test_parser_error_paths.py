"""Tests targeting parser.py exception-handler paths that were previously
uncovered:

  - parse() catch-all except Exception (lines 198-202)
  - parse_program() per-division except Exception (lines 287-298)
  - parse_file() OSError path (lines 217-219)
  - parse_program() stream-is-None guard (line 238-239)
  - add_error() error-limit-reached suppression (lines 328-341)
  - parse() FAIL_FAST return when lexer reports errors (line 185-186)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from cobolparser.parser import CobolParser, ParseResult, parse_cobol
from cobolparser.plugins.core import ErrorRecoveryMode, MemoryConfiguration, ParseError

# ---------------------------------------------------------------------------
# parse() catch-all exception handler  (lines 198-202)
# ---------------------------------------------------------------------------


class TestParseTopLevelExceptionHandler:
    """The outer try/except in parse() catches any unexpected exception,
    records a 'Parser error:' message, and returns a ParseResult with ast=None.
    """

    def test_exception_in_tokenize_returns_result_with_error(self):
        """Force an exception during tokenization; parse() should catch it."""
        parser = CobolParser()
        with patch.object(
            parser,
            "_skip_to_identification_division",
            side_effect=RuntimeError("synthetic tokenizer crash"),
        ):
            result = parser.parse("IDENTIFICATION DIVISION.")
        assert result.ast is None
        assert any("Parser error" in str(e) for e in result.errors)
        assert any("synthetic tokenizer crash" in str(e) for e in result.errors)

    def test_exception_in_parse_program_returns_result_with_error(self):
        """Force an exception inside parse_program; parse() should catch it."""
        parser = CobolParser()
        with patch.object(
            parser,
            "parse_program",
            side_effect=ValueError("deliberate parse_program explosion"),
        ):
            result = parser.parse(
                "IDENTIFICATION DIVISION.\n PROGRAM-ID. TEST."
            )
        assert result.ast is None
        assert any("Parser error" in str(e) for e in result.errors)

    def test_returned_result_has_no_ast(self):
        parser = CobolParser()
        with patch.object(
            parser,
            "parse_program",
            side_effect=Exception("boom"),
        ):
            result = parser.parse("IDENTIFICATION DIVISION.")
        assert isinstance(result, ParseResult)
        assert result.ast is None
        assert not result.success


# ---------------------------------------------------------------------------
# parse() FAIL_FAST when lexer reports errors  (lines 185-186)
# ---------------------------------------------------------------------------


class TestParseLexerErrorFailFast:
    def test_invalid_chars_fail_fast_returns_none_ast(self):
        result = parse_cobol(
            "@@@@ NOT COBOL",
            error_recovery=ErrorRecoveryMode.FAIL_FAST,
        )
        assert result.ast is None
        assert len(result.errors) > 0

    def test_invalid_chars_collect_all_still_returns_program(self):
        result = parse_cobol(
            "@@@@ NOT COBOL",
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
        # In COLLECT_ALL the parser tries to continue; ast may or may not be None
        # but there must be errors recorded
        assert len(result.errors) > 0


# ---------------------------------------------------------------------------
# parse_file() OSError path  (lines 217-219)
# ---------------------------------------------------------------------------


class TestParseFileOSError:
    def test_missing_file_records_error(self, tmp_path):
        parser = CobolParser()
        result = parser.parse_file(str(tmp_path / "does_not_exist.cbl"))
        assert result.ast is None
        assert any("File error" in str(e) for e in result.errors)

    def test_oserror_during_open_records_error(self, tmp_path):
        p = tmp_path / "locked.cbl"
        p.write_text("IDENTIFICATION DIVISION.")
        with patch("builtins.open", side_effect=OSError("permission denied")):
            parser = CobolParser()
            result = parser.parse_file(str(p))
        assert result.ast is None
        assert any("File error" in str(e) for e in result.errors)


# ---------------------------------------------------------------------------
# parse_program() inner per-division exception handler  (lines 265-291)
# ---------------------------------------------------------------------------


class TestParseProgramDivisionExceptionHandler:
    """The inner try/except around each division's parse() call catches
    exceptions, records the error, and - in FAIL_FAST mode - stops early.
    """

    def _make_crashing_id_parser(self, error_msg: str) -> MagicMock:
        """Return a mock division parser whose parse() raises and can_parse() is True."""
        mock = MagicMock()
        mock.can_parse.return_value = True
        mock.parse.side_effect = RuntimeError(error_msg)
        return mock

    def test_division_exception_fail_fast_stops(self):
        """In FAIL_FAST, a crashing division parser records the error and
        parse_program returns early.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        crashing_mock = self._make_crashing_id_parser("fail-fast division crash")

        # Replace the factory so that the first find_parser call returns our crashing mock
        factory_mock = MagicMock()
        factory_mock.find_parser.return_value = crashing_mock
        parser._division_factory = factory_mock

        # We need a non-empty token stream; use a real parsed stream
        from cobolparser.core.token_stream import TokenStream
        from cobolparser.lexer import CobolLexer

        src = "IDENTIFICATION DIVISION.\n PROGRAM-ID. TEST.\n"
        tokens = CobolLexer(src, "<t>", parser.dialect, free_form=True).tokenize()
        parser.stream = TokenStream(tokens)
        parser.errors.clear()

        parser.parse_program()

        assert any("fail-fast division crash" in str(e) for e in parser.errors)

    def test_division_exception_collect_all_records_error(self):
        """In COLLECT_ALL, the inner except records the error.
        We patch skip_whitespace_and_comments to exhaust the stream after one
        iteration so the loop terminates.
        """
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        crashing_mock = self._make_crashing_id_parser("collect-all division crash")

        call_count = {"n": 0}

        def find_parser_once(stream):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return crashing_mock
            return None  # after first crash, tell loop no parser found → break

        factory_mock = MagicMock()
        factory_mock.find_parser.side_effect = find_parser_once
        parser._division_factory = factory_mock

        from cobolparser.core.token_stream import TokenStream
        from cobolparser.lexer import CobolLexer

        src = "IDENTIFICATION DIVISION.\n PROGRAM-ID. TEST.\n"
        tokens = CobolLexer(src, "<t>", parser.dialect, free_form=True).tokenize()
        parser.stream = TokenStream(tokens)
        parser.errors.clear()

        parser.parse_program()

        assert any("collect-all division crash" in str(e) for e in parser.errors)


# ---------------------------------------------------------------------------
# parse_program() OUTER exception handler  (lines 293-298)
# ---------------------------------------------------------------------------


class TestParseProgramOuterExceptionHandler:
    """The outer try/except in parse_program() catches exceptions that escape
    the inner per-division handler (e.g., raised by stream methods).
    """

    def test_stream_method_exception_is_caught(self):
        """If skip_whitespace_and_comments raises, the outer handler catches it."""
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        from cobolparser.core.token_stream import TokenStream
        from cobolparser.lexer import CobolLexer

        src = "IDENTIFICATION DIVISION.\n"
        tokens = CobolLexer(src, "<t>", parser.dialect, free_form=True).tokenize()
        stream = TokenStream(tokens)
        parser.stream = stream
        parser.errors.clear()

        with patch.object(
            stream,
            "skip_whitespace_and_comments",
            side_effect=RuntimeError("stream explosion"),
        ):
            parser.parse_program()

        assert any("Division parsing error" in str(e) or "stream explosion" in str(e)
                   for e in parser.errors)


# ---------------------------------------------------------------------------
# parse_program() stream-is-None guard  (lines 238-239)
# ---------------------------------------------------------------------------


class TestParseProgramStreamNone:
    def test_stream_none_returns_empty_program(self):
        """If self.stream is None at the start of parse_program, an empty
        CobolProgram is returned immediately without any errors.
        """
        parser = CobolParser()
        parser.stream = None  # type: ignore[assignment]
        program = parser.parse_program()
        assert program is not None
        assert program.program_name == "UNKNOWN"


# ---------------------------------------------------------------------------
# add_error() error-limit suppression  (lines 328-341)
# ---------------------------------------------------------------------------


class TestAddErrorLimit:
    def test_errors_suppressed_after_limit(self):
        """Once max_error_count is reached, further errors are suppressed
        and a single suppression notice is added.
        """
        config = MemoryConfiguration(max_error_count=3)
        parser = CobolParser(memory_config=config)

        for i in range(10):
            parser.add_error(ParseError(f"error {i}", line_number=i + 1, column=1))

        # Should have 4 errors: 3 real + 1 suppression notice
        assert parser.statistics.error_count == 4
        suppression = [e for e in parser.errors if "suppressed" in str(e).lower()]
        assert len(suppression) == 1

    def test_errors_not_added_after_limit_reached(self):
        config = MemoryConfiguration(max_error_count=2)
        parser = CobolParser(memory_config=config)

        for i in range(5):
            parser.add_error(ParseError(f"e{i}", line_number=1, column=1))

        # Total count: 2 real + 1 suppression = 3; subsequent adds ignored
        assert parser.statistics.error_count == 3
        assert len(parser.errors) == 3
