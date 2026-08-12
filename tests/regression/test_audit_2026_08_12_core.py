"""Regression tests for the 2026-08-12 core audit fixes.

One test class per finding:

* P-B1 -- MoveStatementParser joined multi-token sources with ``"".join``,
  corrupting qualified names and FUNCTION calls.
* P-B2 -- TokenStream.expect() let an empty-valued token (EOF) match any
  expected value instead of raising TokenMismatch.
* P-B3 -- ParseResult was handed the parser's live ParseStatistics object,
  which the next parse() reset in place.
* P-B4 -- _ID_DIV_RE never matched a sequence-numbered fixed-format
  IDENTIFICATION DIVISION header.
* P-B5 -- the compiled _lexer_fast tokenize() did not reset ``warnings``,
  duplicating them across calls on one lexer instance.
* P-B6 -- PathResolver's Tier-2 directory index was last-directory-wins for
  full-filename keys but first-wins for stem keys (and Tier-3 first-wins).
* P-D1 -- expand_copybooks() ignored a caller-supplied ``path_resolver``.
* S-1 -- the exported-but-unused COPY_PATTERN regex (exponential
  backtracking on unterminated REPLACING input) was removed.
"""

import time

import pytest

from cobolparser import parse_cobol
from cobolparser.core.exceptions import TokenMismatch
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType, _CobolLexerPure
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parser import _ID_DIV_RE, CobolParser
from cobolparser.preprocess import copy_statement_parser
from cobolparser.preprocess.copybook_expander import expand_copybooks
from cobolparser.preprocess.models import CopybookSearchPath
from cobolparser.preprocess.path_resolver import PathResolver, find_copybook_file

try:
    from cobolparser._lexer_fast import CobolLexer as _FastLexer
except ImportError:  # pragma: no cover - compiled extension not built
    _FastLexer = None


def _move_program(move_line: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. MOVSRC.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-GRP.\n"
        "          05 WS-A PIC X(5).\n"
        "       01 WS-B PIC X(5).\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        f"           {move_line}\n"
        "           STOP RUN.\n"
    )


def _first_move(result):
    moves = result.ast.find_all_by_type("MoveStatement")
    assert moves, "MOVE statement missing from AST"
    return moves[0]


class TestPB1MoveSourceJoin:
    """P-B1: multi-token MOVE sources must keep their word separation."""

    def test_qualified_source_keeps_of_separators(self):
        result = parse_cobol(
            _move_program("MOVE WS-A OF WS-GRP TO WS-B."), filename="m.cbl"
        )
        assert result.success, [str(e) for e in result.errors]
        assert _first_move(result).source == "WS-A OF WS-GRP"

    def test_function_call_source_keeps_function_keyword_separate(self):
        result = parse_cobol(
            _move_program("MOVE FUNCTION UPPER-CASE(WS-A) TO WS-B."),
            filename="m.cbl",
        )
        assert result.success, [str(e) for e in result.errors]
        assert _first_move(result).source == "FUNCTION UPPER-CASE(WS-A)"

    def test_single_token_source_unchanged(self):
        result = parse_cobol(_move_program("MOVE WS-A TO WS-B."), filename="m.cbl")
        assert _first_move(result).source == "WS-A"

    def test_literal_source_unchanged(self):
        result = parse_cobol(_move_program('MOVE "HELLO" TO WS-B.'), filename="m.cbl")
        assert _first_move(result).source == '"HELLO"'

    def test_subscripted_source_has_no_space_before_paren(self):
        result = parse_cobol(
            _move_program("MOVE WS-A (1, 2) TO WS-B."), filename="m.cbl"
        )
        assert _first_move(result).source == "WS-A(1, 2)"

    def test_signed_numeric_source_keeps_sign_attached(self):
        result = parse_cobol(_move_program("MOVE -5 TO WS-B."), filename="m.cbl")
        assert _first_move(result).source == "-5"


class TestPB2ExpectEmptyValuedToken:
    """P-B2: expect() must mismatch an empty-valued token (EOF)."""

    def _stream_at_eof(self) -> TokenStream:
        return TokenStream([Token(TokenType.EOF, "", SourceLocation(1, 1, 1))])

    def test_expect_period_at_eof_raises_token_mismatch(self):
        stream = self._stream_at_eof()
        with pytest.raises(TokenMismatch):
            stream.expect(".")
        # The EOF token must not have been consumed by the failed expect.
        assert stream.position == 0

    def test_expect_matching_value_still_consumes(self):
        stream = TokenStream([Token(TokenType.PERIOD, ".", SourceLocation(1, 1, 1))])
        token = stream.expect(".")
        assert token.value == "."
        assert stream.position == 1


class TestPB3StatisticsSnapshot:
    """P-B3: reusing one CobolParser must not clobber earlier statistics."""

    def test_reused_parser_keeps_first_results_statistics(self):
        small = _move_program("MOVE WS-A TO WS-B.")
        parser = CobolParser()
        first = parser.parse(small, filename="first.cbl")
        first_tokens = first.statistics.tokens_processed
        first_lines = first.statistics.lines_processed
        assert first_tokens > 0

        big = _move_program("MOVE WS-A TO WS-B.").replace(
            "           STOP RUN.\n",
            "           MOVE WS-A TO WS-B.\n" * 20 + "           STOP RUN.\n",
        )
        second = parser.parse(big, filename="second.cbl")

        # The first result's statistics are an independent snapshot.
        assert first.statistics.tokens_processed == first_tokens
        assert first.statistics.lines_processed == first_lines
        assert second.statistics.tokens_processed > first_tokens
        assert first.statistics is not parser.statistics
        assert second.statistics is not parser.statistics


class TestPB4SequenceNumberedIdDivision:
    """P-B4: the ID-division regex must accept a 6-column sequence area."""

    def test_regex_matches_sequence_numbered_header(self):
        assert _ID_DIV_RE.search("000100 IDENTIFICATION DIVISION.")
        assert _ID_DIV_RE.search("100200 ID DIV.")

    def test_regex_still_matches_plain_headers(self):
        assert _ID_DIV_RE.search("IDENTIFICATION DIVISION.")
        assert _ID_DIV_RE.search("       IDENTIFICATION DIVISION.")
        assert _ID_DIV_RE.search("   ID DIVISION.")

    def test_regex_rejects_random_digit_leading_text(self):
        # The sequence area is exactly 6 characters of digits/spaces --
        # arbitrary text that merely contains digits must not match.
        assert not _ID_DIV_RE.search("12345678 IDENTIFICATION DIVISION.")
        assert not _ID_DIV_RE.search("CALL 12 IDENTIFICATION DIVISION")

    def test_junk_before_sequence_numbered_program_is_skipped(self):
        junk = "MEMBER HEADER GENERATED TEXT\n"
        program = (
            "000100 IDENTIFICATION DIVISION.\n"
            "000200 PROGRAM-ID. SEQPROG.\n"
            "000300 PROCEDURE DIVISION.\n"
            "000400 MAIN-PARA.\n"
            "000500     STOP RUN.\n"
        )
        cleaned = CobolParser._skip_to_identification_division(junk + program)
        assert cleaned.splitlines()[0] == ""
        assert "MEMBER HEADER" not in cleaned
        assert "IDENTIFICATION DIVISION" in cleaned


class TestPB5LexerWarningsReset:
    """P-B5: warnings must reset on every tokenize() call, both paths."""

    #: Free-form source whose unterminated string literal produces exactly
    #: one lexer warning per tokenize() call.
    _SOURCE = "DISPLAY 'UNTERMINATED\n"

    def _assert_no_duplication(self, lexer_cls):
        lexer = lexer_cls(self._SOURCE, free_form=True)
        lexer.tokenize()
        first = list(lexer.get_warnings())
        lexer.tokenize()
        second = list(lexer.get_warnings())
        assert len(first) == 1, first
        assert second == first

    def test_pure_python_lexer_does_not_duplicate_warnings(self):
        self._assert_no_duplication(_CobolLexerPure)

    @pytest.mark.skipif(_FastLexer is None, reason="_lexer_fast not compiled")
    def test_compiled_lexer_does_not_duplicate_warnings(self):
        self._assert_no_duplication(_FastLexer)


class TestPB6FirstDirectoryWins:
    """P-B6: the first configured search directory wins in every tier."""

    @pytest.fixture()
    def two_dirs(self, tmp_path):
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        (first / "SHARED.cpy").write_text("       01 FROM-FIRST PIC X.\n")
        (second / "SHARED.cpy").write_text("       01 FROM-SECOND PIC X.\n")
        return first, second

    def test_indexed_lookup_prefers_first_directory(self, two_dirs):
        first, second = two_dirs
        resolver = PathResolver(
            CopybookSearchPath(directories=[str(first), str(second)])
        )
        # Stem-keyed Tier-2 lookup.
        assert resolver.resolve("SHARED") == str(first / "SHARED.cpy")
        # Full-filename-keyed Tier-2 lookup (was last-directory-wins).
        resolver2 = PathResolver(
            CopybookSearchPath(directories=[str(first), str(second)])
        )
        assert resolver2.resolve("SHARED.cpy") == str(first / "SHARED.cpy")

    def test_non_indexed_lookup_prefers_first_directory(self, two_dirs):
        first, second = two_dirs
        config = CopybookSearchPath(directories=[str(first), str(second)])
        assert find_copybook_file("SHARED", config) == str(first / "SHARED.cpy")
        assert find_copybook_file("SHARED.cpy", config) == str(first / "SHARED.cpy")

    def test_reversed_order_flips_the_winner(self, two_dirs):
        first, second = two_dirs
        resolver = PathResolver(
            CopybookSearchPath(directories=[str(second), str(first)])
        )
        assert resolver.resolve("SHARED") == str(second / "SHARED.cpy")


class TestPD1CallerSuppliedPathResolver:
    """P-D1: expand_copybooks must honor a caller-supplied path_resolver."""

    def test_sentinel_resolver_is_used(self, tmp_path):
        (tmp_path / "CUSTREC.cpy").write_text("       01 CUST-REC PIC X(10).\n")

        calls: list[str] = []

        class SentinelResolver(PathResolver):
            def resolve(self, member_name, library_qualifier=None):
                calls.append(member_name)
                return super().resolve(member_name, library_qualifier)

        sentinel = SentinelResolver(CopybookSearchPath(directories=[str(tmp_path)]))
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. EXPPROG.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY CUSTREC.\n"
        )
        result = expand_copybooks(
            source, copybook_paths=[str(tmp_path)], path_resolver=sentinel
        )
        assert calls == ["CUSTREC"]
        assert "CUST-REC" in result.expanded_source


class TestS1CopyPatternRemoved:
    """S-1: the ReDoS-prone COPY_PATTERN export is gone; the live path is fast."""

    def test_copy_pattern_no_longer_exported(self):
        assert not hasattr(copy_statement_parser, "COPY_PATTERN")
        assert "COPY_PATTERN" not in copy_statement_parser.__all__

    def test_pathological_replacing_input_completes_fast(self):
        # The input that blew up the removed regex: an unterminated
        # REPLACING clause made of many BY keywords. The live scanner
        # (CopyStatementLexer) must stay linear.
        pathological = "COPY X REPLACING " + "BY " * 40 + "%"
        warnings: list[str] = []
        start = time.monotonic()
        copy_statement_parser.extract_copy_statements(
            pathological, "pathological.cbl", warnings=warnings
        )
        assert time.monotonic() - start < 1.0
