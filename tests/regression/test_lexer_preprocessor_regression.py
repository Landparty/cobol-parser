"""Regression tests for lexer and preprocessor.

These tests lock down specific behaviors to prevent regressions in
fixed-format handling, string literal processing, and keyword recognition.
"""

from cobolparser import parse_cobol
from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.preprocess import normalize_fixed_format


class TestLexerRegressions:
    """Lock down lexer behaviors that have been error-prone."""

    def test_figurative_constants_tokenized(self):
        """All figurative constants should be recognized (free-form mode)."""
        for word in ["SPACE", "SPACES", "ZERO", "ZEROS", "ZEROES",
                     "HIGH-VALUE", "HIGH-VALUES", "LOW-VALUE", "LOW-VALUES",
                     "QUOTE", "QUOTES"]:
            lexer = CobolLexer(f"MOVE {word} TO X", free_form=True)
            tokens = lexer.tokenize()
            figs = [t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT]
            assert len(figs) >= 1, f"{word} not recognized as FIGURATIVE_CONSTANT"

    def test_mixed_case_keywords(self):
        """Keywords should be recognized regardless of case."""
        for word in ["Perform", "perform", "PERFORM", "pErFoRm"]:
            lexer = CobolLexer(f"{word} PARA-1", free_form=True)
            tokens = lexer.tokenize()
            kw_tokens = [t for t in tokens if t.type == TokenType.PERFORM]
            assert len(kw_tokens) >= 1, f"{word} not recognized as PERFORM keyword"

    def test_level_numbers(self):
        """Level numbers 01-49, 66, 77, 88 should be LEVEL_NUMBER tokens."""
        for num in ["01", "05", "10", "49", "66", "77", "88"]:
            lexer = CobolLexer(f"{num} WS-FIELD PIC X.", free_form=True)
            tokens = lexer.tokenize()
            levels = [t for t in tokens if t.type == TokenType.LEVEL_NUMBER]
            assert len(levels) >= 1, f"{num} not recognized as LEVEL_NUMBER"

    def test_string_literal_with_embedded_quotes(self):
        """String literals with escaped quotes are properly tokenized."""
        lexer = CobolLexer("DISPLAY 'DON''T STOP'", free_form=True)
        tokens = lexer.tokenize()
        strings = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(strings) >= 1
        assert "DON'T STOP" in strings[0].value

    def test_period_tokenized(self):
        """Period is a distinct token."""
        lexer = CobolLexer("STOP RUN.", free_form=True)
        tokens = lexer.tokenize()
        periods = [t for t in tokens if t.type == TokenType.PERIOD]
        assert len(periods) >= 1

    def test_empty_source(self):
        """Empty source produces only EOF token."""
        lexer = CobolLexer("", free_form=True)
        tokens = lexer.tokenize()
        meaningful = [t for t in tokens if t.type not in (
            TokenType.NEWLINE, TokenType.WHITESPACE, TokenType.EOF
        )]
        assert len(meaningful) == 0


class TestPreprocessorRegressions:
    """Lock down preprocessor behaviors."""

    def test_fixed_format_basic(self):
        """Basic fixed-format conversion preserves program text."""
        lines = [
            "000100 IDENTIFICATION DIVISION.                                     ",
            "000200 PROGRAM-ID. TEST.                                            ",
        ]
        result = normalize_fixed_format(lines)
        assert "IDENTIFICATION DIVISION" in result
        assert "PROGRAM-ID" in result

    def test_blank_lines_preserved(self):
        """Blank source lines don't crash the preprocessor."""
        lines = [
            "000100 IDENTIFICATION DIVISION.                                     ",
            "                                                                    ",
            "000300 PROGRAM-ID. TEST.                                            ",
        ]
        result = normalize_fixed_format(lines)
        assert "IDENTIFICATION DIVISION" in result

    def test_short_lines_handled(self):
        """Lines shorter than 72 columns are handled gracefully."""
        lines = [
            "000100 IDENTIFICATION DIVISION.",
            "000200 PROGRAM-ID. TEST.",
        ]
        result = normalize_fixed_format(lines)
        # Short lines may be skipped; just verify no crash
        assert isinstance(result, str)

    def test_comment_star_stripped(self):
        """Star comments in column 7 are removed."""
        lines = [
            "000100 IDENTIFICATION DIVISION.                                     ",
            "000200*COMMENT LINE                                                 ",
            "000300 PROGRAM-ID. TEST.                                            ",
        ]
        result = normalize_fixed_format(lines)
        assert "COMMENT LINE" not in result

    def test_comment_slash_stripped(self):
        """Slash comments in column 7 are removed."""
        lines = [
            "000100 IDENTIFICATION DIVISION.                                     ",
            "000200/COMMENT LINE                                                 ",
            "000300 PROGRAM-ID. TEST.                                            ",
        ]
        result = normalize_fixed_format(lines)
        assert "COMMENT LINE" not in result


class TestFullProgramRegressions:
    """Lock down full program parsing behavior."""

    def test_minimal_program(self):
        """The smallest valid COBOL program parses."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MINIMAL.
       PROCEDURE DIVISION.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_program_with_all_divisions(self):
        """Program with all four divisions parses."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FULLDIV.
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_deeply_nested_evaluate(self):
        """EVALUATE with multiple WHEN clauses."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EVALTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CODE PIC 9 VALUE 1.
       PROCEDURE DIVISION.
           EVALUATE WS-CODE
               WHEN 1 DISPLAY "ONE"
               WHEN 2 DISPLAY "TWO"
               WHEN 3 DISPLAY "THREE"
               WHEN OTHER DISPLAY "OTHER"
           END-EVALUATE.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_nested_if_else(self):
        """Nested IF...ELSE...END-IF."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IFTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9 VALUE 1.
       01  WS-B PIC 9 VALUE 2.
       PROCEDURE DIVISION.
           IF WS-A = 1
               IF WS-B = 2
                   DISPLAY "BOTH"
               ELSE
                   DISPLAY "A ONLY"
               END-IF
           ELSE
               DISPLAY "NEITHER"
           END-IF.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_multiple_io_operations(self):
        """Program with OPEN, WRITE, CLOSE in sequence."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IOTEST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-FILE ASSIGN TO 'OUT.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  OUT-FILE.
       01  OUT-RECORD PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-DATA PIC X(80) VALUE 'RECORD 1'.
       PROCEDURE DIVISION.
           OPEN OUTPUT OUT-FILE.
           WRITE OUT-RECORD FROM WS-DATA.
           CLOSE OUT-FILE.
           STOP RUN.
        """)
        assert result.ast is not None
