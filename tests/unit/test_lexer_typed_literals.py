"""Tests for typed-literal prefixes in the COBOL lexer.

IBM Enterprise COBOL (and ISO COBOL) allow a literal to be prefixed by a
type-introducing letter immediately followed by a quote/apostrophe:

    X"1F"     hexadecimal alphanumeric literal
    N"abc"    national literal
    NX"00C1"  national hexadecimal literal
    G"<dbcs>" DBCS / graphic literal
    Z"abc"    null-terminated literal
    U"abc"    UTF-8 literal
    B"1010"   boolean literal

Before this was supported the lexer split ``X"1F"`` into a separate
``IDENTIFIER('X')`` token followed by ``STRING_LITERAL('1F')``, which broke
parsing of any statement that used a typed literal (e.g. ``MOVE X"1F" TO Y``
became two operands before ``TO``).

The lexer now emits a single ``STRING_LITERAL`` token whose ``value`` is the
literal content (so existing consumers keep working) and whose ``raw_value``
preserves the original prefixed source text so the literal kind is recoverable.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.lexer import CobolLexer, TokenType


def _literals(source: str) -> list:
    """Return the STRING_LITERAL tokens produced for ``source`` (free-form)."""
    tokens = CobolLexer(source, free_form=True).tokenize()
    return [t for t in tokens if t.type == TokenType.STRING_LITERAL]


class TestTypedLiteralPrefixes:
    """Each prefix yields exactly one STRING_LITERAL with the prefix in raw_value."""

    @pytest.mark.parametrize(
        ("source", "value", "raw"),
        [
            ('MOVE X"1F" TO WS-A', "1F", 'X"1F"'),
            ("MOVE X'1F' TO WS-A", "1F", "X'1F'"),
            ('MOVE N"abc" TO WS-A', "abc", 'N"abc"'),
            ("MOVE N'abc' TO WS-A", "abc", "N'abc'"),
            ('MOVE NX"00C1" TO WS-A', "00C1", 'NX"00C1"'),
            ('MOVE G"dd" TO WS-A', "dd", 'G"dd"'),
            ('MOVE Z"abc" TO WS-A', "abc", 'Z"abc"'),
            ('MOVE U"abc" TO WS-A', "abc", 'U"abc"'),
            ('MOVE B"1010" TO WS-A', "1010", 'B"1010"'),
        ],
    )
    def test_typed_literal_is_single_token(self, source, value, raw):
        literals = _literals(source)
        assert len(literals) == 1
        assert literals[0].value == value
        assert literals[0].raw_value == raw

    def test_lowercase_prefix_is_recognized(self):
        """COBOL is case-insensitive, so a lowercase prefix is also a literal."""
        literals = _literals('MOVE x"1F" TO WS-A')
        assert len(literals) == 1
        assert literals[0].value == "1F"
        assert literals[0].raw_value == 'x"1F"'

    def test_no_identifier_token_leaks_before_literal(self):
        """The prefix letter must not surface as a standalone IDENTIFIER."""
        tokens = CobolLexer('MOVE X"1F" TO WS-A', free_form=True).tokenize()
        idents = [t.value for t in tokens if t.type == TokenType.IDENTIFIER]
        assert "X" not in idents
        assert idents == ["WS-A"]


class TestPrefixLettersStillFormIdentifiers:
    """Prefix letters NOT followed by a quote remain ordinary identifiers."""

    @pytest.mark.parametrize(
        "source",
        [
            "MOVE X TO N",
            "MOVE XYZ TO NVAL",
            "MOVE N TO G",
            "MOVE ZONE TO UNIT",
            "MOVE NX TO B",
        ],
    )
    def test_bare_prefix_letters_are_identifiers(self, source):
        assert _literals(source) == []

    def test_prefix_letter_with_space_before_quote_is_identifier(self):
        """A space between the prefix and the quote breaks the typed literal."""
        tokens = CobolLexer('MOVE X "1F" TO WS-A', free_form=True).tokenize()
        idents = [t.value for t in tokens if t.type == TokenType.IDENTIFIER]
        literals = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert "X" in idents
        assert len(literals) == 1
        assert literals[0].raw_value is None  # plain, un-prefixed literal


class TestTypedLiteralsParseEndToEnd:
    """A program using typed literals parses without spurious extra operands."""

    def test_move_hex_literal_is_single_operand(self):
        """The typed literal is one operand, not a leaked prefix + literal.

        Before typed-literal support, ``MOVE X"1F" TO WS-FLAG`` produced the
        operands ``["X", "1F", "WS-FLAG"]`` (the prefix ``X`` leaked as its own
        operand, corrupting the source/target split). It should now yield two.
        """
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. HEXTEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-FLAG PIC X.
        PROCEDURE DIVISION.
            MOVE X"1F" TO WS-FLAG.
            DISPLAY N"national".
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.ast is not None
        assert result.errors == []

        statements = result.ast.find_all_by_type("Statement")
        moves = [s for s in statements if s.to_dict()["statement_type"] == "MOVE"]
        assert len(moves) == 1
        move = moves[0].to_dict()
        assert move["operands"] == ['"1F"', "WS-FLAG"]
        assert move["targets"] == ["WS-FLAG"]


class TestTypedLiteralEscapesAndEdges:
    """Doubled quotes and empty content inside typed literals."""

    def test_doubled_quote_inside_hex_prefix(self):
        literals = _literals('MOVE X"A""B" TO WS-A')
        assert len(literals) == 1
        assert literals[0].value == 'A"B'
        assert literals[0].raw_value == 'X"A""B"'

    def test_empty_typed_literal(self):
        literals = _literals('MOVE Z"" TO WS-A')
        assert len(literals) == 1
        assert literals[0].value == ""
        assert literals[0].raw_value == 'Z""'


class TestUnterminatedTypedLiteralMatchesPlainString:
    """An unterminated typed literal is handled like an unterminated plain one.

    The plain free-form string path intentionally suppresses the "unterminated
    string" lexer error (a stray quote must not become a hard failure), so the
    typed-literal path must do the same rather than always recording an error.
    """

    def test_free_form_unterminated_typed_literal_no_error(self):
        plain = CobolLexer('MOVE "abc TO X', free_form=True)
        plain.tokenize()
        typed = CobolLexer('MOVE X"abc TO X', free_form=True)
        typed.tokenize()
        # Parity: neither records a lexer error in free-form mode.
        assert plain.errors == []
        assert typed.errors == []
