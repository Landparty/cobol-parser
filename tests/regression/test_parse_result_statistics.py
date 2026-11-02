"""Regression tests: ``ParseResult.statistics`` on every return path.

A FAIL_FAST lexer error (and any other early return) handed back
``lines_parsed == 0`` and ``parse_time_seconds == 0``; ``parse_file()`` on a
missing file returned the errors and statistics of the previous parse made
with the same ``CobolParser`` instance.
"""

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser import parser as parser_module
from cobolparser.lexer import LexerError
from cobolparser.models.ast_base import SourceLocation


class TestParseResultStatistics:
    # A program whose lexer reports a hard error after producing tokens. No
    # character fails the lexer any more (a stray one is a warning), so the
    # error is injected; the statistics are what this test is about.
    _LEXER_ERROR = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. BAD.\n"
        "       PROCEDURE DIVISION.\n"
        "           DISPLAY 'X'.\n"
        "           STOP RUN.\n"
    )

    def test_fail_fast_lexer_error_still_reports_lines_and_time(self, monkeypatch):
        real_lexer = parser_module.CobolLexer

        class LexerWithError(real_lexer):  # type: ignore[misc, valid-type]
            def tokenize(self):
                tokens = super().tokenize()
                self.errors.append(LexerError("injected", SourceLocation(4, 12, 1)))
                return tokens

        monkeypatch.setattr(parser_module, "CobolLexer", LexerWithError)
        result = CobolParser().parse(self._LEXER_ERROR)
        assert result.errors
        assert result.ast is None
        stats = result.statistics
        assert stats.lines_parsed == 5
        assert stats.lines_processed == 5
        assert stats.tokens_processed > 0
        assert stats.parse_time_seconds > 0
        assert stats.error_count == len(result.errors)

    def test_parse_file_error_does_not_carry_previous_parse(self, tmp_path):
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        first = parser.parse("garbage")
        assert first.errors
        missing = parser.parse_file(str(tmp_path / "missing.cbl"))
        assert len(missing.errors) == 1
        assert "File error" in missing.errors[0].message
        assert missing.warnings == []
        assert missing.statistics.error_count == 1
        assert missing.statistics.lines_parsed == 0
