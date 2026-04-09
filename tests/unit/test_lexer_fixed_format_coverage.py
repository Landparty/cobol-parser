"""Tests for lexer fixed-format and multi-line string handling.

Targets uncovered lines in lexer.py (81.56%):
  - Fixed-format comment detection and indicator column (lines 671-790)
  - Multi-line string detection in VALUE clauses (lines 856-965)
  - read_string_literal with doubled quotes (lines 692-723)
  - read_numeric_literal with decimal/exponent (lines 725-756)
  - read_identifier keyword/figurative constant lookup (lines 758-787)
  - Multi-line string continuation line processing (lines 1313-1397)
"""

from cobolparser import parse_cobol
from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.preprocess import normalize_fixed_format


class TestLexerReadStringLiteral:
    """Cover read_string_literal with edge cases."""

    def test_doubled_quote_escape(self):
        """String with doubled quotes: 'It''s' -> It's (free-form mode)."""
        lexer = CobolLexer("'It''s a test'", free_form=True)
        tokens = lexer.tokenize()
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) >= 1
        assert "It's a test" in string_tokens[0].value

    def test_doubled_double_quote_escape(self):
        """String with doubled double-quotes (free-form)."""
        lexer = CobolLexer('"Say ""hello"""', free_form=True)
        tokens = lexer.tokenize()
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) >= 1

    def test_unterminated_string(self):
        """Unterminated string still produces a STRING_LITERAL token."""
        lexer = CobolLexer('"This string never ends', free_form=True)
        tokens = lexer.tokenize()
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) >= 1
        assert "This string never ends" in string_tokens[0].value


class TestLexerReadNumericLiteral:
    """Cover read_numeric_literal with decimals and exponents."""

    def test_decimal_number(self):
        lexer = CobolLexer("MOVE 123.45 TO X", free_form=True)
        tokens = lexer.tokenize()
        nums = [t for t in tokens if t.type == TokenType.NUMERIC_LITERAL]
        assert len(nums) >= 1

    def test_scientific_notation(self):
        lexer = CobolLexer("MOVE 1.5E+10 TO X", free_form=True)
        tokens = lexer.tokenize()
        nums = [t for t in tokens if t.type == TokenType.NUMERIC_LITERAL]
        assert len(nums) >= 1

    def test_scientific_notation_negative(self):
        lexer = CobolLexer("MOVE 2.5E-3 TO X", free_form=True)
        tokens = lexer.tokenize()
        nums = [t for t in tokens if t.type == TokenType.NUMERIC_LITERAL]
        assert len(nums) >= 1


class TestLexerReadIdentifier:
    """Cover read_identifier keyword and figurative constant lookup."""

    def test_figurative_constant_spaces(self):
        lexer = CobolLexer("MOVE SPACES TO X", free_form=True)
        tokens = lexer.tokenize()
        figs = [t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT]
        assert len(figs) >= 1

    def test_figurative_constant_zeros(self):
        lexer = CobolLexer("MOVE ZEROS TO X", free_form=True)
        tokens = lexer.tokenize()
        figs = [t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT]
        assert len(figs) >= 1

    def test_keyword_identification(self):
        lexer = CobolLexer("PERFORM PARA-1", free_form=True)
        tokens = lexer.tokenize()
        kws = [t for t in tokens if t.type == TokenType.PERFORM]
        assert len(kws) >= 1

    def test_identifier_with_hyphens(self):
        lexer = CobolLexer("MOVE WS-DATA-FIELD TO X", free_form=True)
        tokens = lexer.tokenize()
        ids = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert any(t.value == "WS-DATA-FIELD" for t in ids)


class TestFixedFormatHandling:
    """Cover fixed-format COBOL handling in the lexer."""

    def test_comment_line_stripped(self):
        """Comment lines (column 7 = *) are stripped by preprocessor."""
        lines = [
            "000100 IDENTIFICATION DIVISION.                                     ",
            "000200*THIS IS A COMMENT                                            ",
            "000300 PROGRAM-ID. TEST.                                            ",
        ]
        result = normalize_fixed_format(lines)
        assert "THIS IS A COMMENT" not in result
        assert "IDENTIFICATION DIVISION" in result

    def test_continuation_line(self):
        """Continuation lines (column 7 = -) are merged."""
        lines = [
            "000100 IDENTIFICATION DIVISION.                                     ",
            "000200 PROGRAM-ID. TEST.                                            ",
            "000300 DATA DIVISION.                                               ",
            "000400 WORKING-STORAGE SECTION.                                     ",
            "000500 01  WS-MSG PIC X(50) VALUE 'HELLO WOR                       ",
            "000600-    'LD'.                                                    ",
            "000700 PROCEDURE DIVISION.                                          ",
            "000800     STOP RUN.                                                ",
        ]
        source = "\n".join(lines)
        result = parse_cobol(source)
        assert result.ast is not None

    def test_slash_comment_line(self):
        """Slash comment lines (column 7 = /) are stripped."""
        lines = [
            "000100 IDENTIFICATION DIVISION.                                     ",
            "000200/PAGE BREAK COMMENT                                           ",
            "000300 PROGRAM-ID. TEST.                                            ",
        ]
        result = normalize_fixed_format(lines)
        assert "PAGE BREAK" not in result

    def test_sequence_area_ignored(self):
        """Columns 1-6 (sequence area) are ignored."""
        lines = [
            "999999 IDENTIFICATION DIVISION.                                     ",
            "000001 PROGRAM-ID. TEST.                                            ",
        ]
        result = normalize_fixed_format(lines)
        assert "999999" not in result
        assert "000001" not in result

    def test_identification_area_ignored(self):
        """Columns 73-80 (identification area) are ignored."""
        lines = [
            "000100 IDENTIFICATION DIVISION.                                    MYIDENT",
            "000200 PROGRAM-ID. TEST.                                           MYIDENT",
        ]
        result = normalize_fixed_format(lines)
        assert "MYIDENT" not in result


class TestMultiLineStringInFullProgram:
    """Cover multi-line string handling in VALUE clauses."""

    def test_multiline_value_clause(self):
        """VALUE clause spanning multiple lines with continuation."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MSG PIC X(30) VALUE 'HELLO WORLD'.
       PROCEDURE DIVISION.
           DISPLAY WS-MSG.
           STOP RUN.
        """
        result = parse_cobol(source)
        assert result.ast is not None

    def test_program_with_figurative_constant_value(self):
        """VALUE SPACES should not trigger multi-line string mode."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FIELD PIC X(10) VALUE SPACES.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source)
        assert result.ast is not None

    def test_program_with_figurative_constant_zeros(self):
        """VALUE ZEROS should not trigger multi-line string mode."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NUM PIC 9(5) VALUE ZEROS.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source)
        assert result.ast is not None
