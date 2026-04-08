"""Tests for division parser base error recovery coverage.

Targets uncovered lines in parsers/divisions/base.py (74.49%):
  - Composite division token handling (e.g. "IDENTIFICATION DIVISION" as single token)
  - _skip_to_next_section_or_division() error recovery
  - DivisionNotFoundError when can_parse fails
"""

import pytest

from cobolparser.core.exceptions import DivisionNotFoundError
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.divisions.identification import IdentificationDivisionParser


class TestCompositeDivisionToken:
    """Cover composite division token matching in can_parse."""

    def test_composite_identification_division_token(self):
        """Token with value 'IDENTIFICATION DIVISION' matches the ID division parser."""
        parser = IdentificationDivisionParser()
        token = Token(TokenType.IDENTIFIER, "IDENTIFICATION DIVISION", SourceLocation(1, 1))
        stream = TokenStream([token, Token(TokenType.PERIOD, ".", SourceLocation(1, 30))])
        assert parser.can_parse(stream) is True

    def test_composite_id_division_token(self):
        """Token with value 'ID DIVISION' matches the ID division parser."""
        parser = IdentificationDivisionParser()
        token = Token(TokenType.IDENTIFIER, "ID DIVISION", SourceLocation(1, 1))
        stream = TokenStream([token, Token(TokenType.PERIOD, ".", SourceLocation(1, 20))])
        assert parser.can_parse(stream) is True

    def test_non_matching_token(self):
        """Token with unrelated value doesn't match."""
        parser = IdentificationDivisionParser()
        token = Token(TokenType.IDENTIFIER, "DATA", SourceLocation(1, 1))
        stream = TokenStream([token])
        assert parser.can_parse(stream) is False

    def test_empty_stream(self):
        """Empty stream returns False for can_parse."""
        parser = IdentificationDivisionParser()
        stream = TokenStream([])
        assert parser.can_parse(stream) is False


class TestDivisionNotFoundError:
    """Cover DivisionNotFoundError when parse is called on wrong division."""

    def test_raises_on_wrong_division(self):
        parser = IdentificationDivisionParser()
        token = Token(TokenType.IDENTIFIER, "DATA", SourceLocation(1, 1))
        stream = TokenStream([token])
        with pytest.raises(DivisionNotFoundError):
            parser.parse(stream)


class TestSkipToNextSectionOrDivision:
    """Cover _skip_to_next_section_or_division error recovery."""

    def test_skips_to_section_keyword(self):
        parser = IdentificationDivisionParser()
        tokens = [
            Token(TokenType.IDENTIFIER, "GARBAGE", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "MORE-JUNK", SourceLocation(2, 1)),
            Token(TokenType.IDENTIFIER, "WORKING-STORAGE", SourceLocation(3, 1)),
            Token(TokenType.IDENTIFIER, "SECTION", SourceLocation(3, 20)),
        ]
        stream = TokenStream(tokens)
        parser._skip_to_next_section_or_division(stream)
        # Should stop at WORKING-STORAGE
        assert not stream.is_empty()
        tok = stream.peek()
        assert tok.value == "WORKING-STORAGE"

    def test_skips_to_division_keyword(self):
        parser = IdentificationDivisionParser()
        tokens = [
            Token(TokenType.IDENTIFIER, "GARBAGE", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "PROCEDURE", SourceLocation(2, 1)),
        ]
        stream = TokenStream(tokens)
        parser._skip_to_next_section_or_division(stream)
        assert not stream.is_empty()
        tok = stream.peek()
        assert tok.value == "PROCEDURE"

    def test_exhausts_stream_if_no_keyword(self):
        parser = IdentificationDivisionParser()
        tokens = [
            Token(TokenType.IDENTIFIER, "GARBAGE", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "MORE-JUNK", SourceLocation(2, 1)),
        ]
        stream = TokenStream(tokens)
        parser._skip_to_next_section_or_division(stream)
        assert stream.is_empty()
