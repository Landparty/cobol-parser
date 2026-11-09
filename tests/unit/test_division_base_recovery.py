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
        token = Token(
            TokenType.IDENTIFIER, "IDENTIFICATION DIVISION", SourceLocation(1, 1)
        )
        stream = TokenStream(
            [token, Token(TokenType.PERIOD, ".", SourceLocation(1, 30))]
        )
        assert parser.can_parse(stream) is True

    def test_composite_id_division_token(self):
        """Token with value 'ID DIVISION' matches the ID division parser."""
        parser = IdentificationDivisionParser()
        token = Token(TokenType.IDENTIFIER, "ID DIVISION", SourceLocation(1, 1))
        stream = TokenStream(
            [token, Token(TokenType.PERIOD, ".", SourceLocation(1, 20))]
        )
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
