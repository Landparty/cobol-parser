"""Unit tests for TokenStream class and ITokenStream interface."""

import pytest

from cobolparser.core.exceptions import TokenMismatch, UnexpectedEndOfInput
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation


@pytest.fixture
def sample_tokens():
    """Create sample tokens for testing."""
    return [
        Token(
            TokenType.IDENTIFICATION_DIVISION, "IDENTIFICATION", SourceLocation(1, 1)
        ),
        Token(TokenType.IDENTIFICATION_DIVISION, "DIVISION", SourceLocation(1, 16)),
        Token(TokenType.PERIOD, ".", SourceLocation(1, 23)),
        Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
        Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
        Token(TokenType.IDENTIFIER, "TEST-PROGRAM", SourceLocation(2, 13)),
    ]


class TestTokenStreamPeek:
    """Tests for peek() method."""

    def test_peek_next_token(self, sample_tokens):
        """Peek at next token without consuming."""
        stream = TokenStream(sample_tokens)
        token = stream.peek()
        assert token.value == "IDENTIFICATION"
        assert stream.position == 0

    def test_peek_with_offset(self, sample_tokens):
        """Peek at token with offset."""
        stream = TokenStream(sample_tokens)
        token = stream.peek(offset=2)
        assert token.value == "."
        assert stream.position == 0

    def test_peek_beyond_end_returns_none(self, sample_tokens):
        """Peek beyond stream end returns None."""
        stream = TokenStream(sample_tokens)
        token = stream.peek(offset=100)
        assert token is None

    def test_peek_repeated_calls_same_result(self, sample_tokens):
        """Repeated peek calls return same token."""
        stream = TokenStream(sample_tokens)
        token1 = stream.peek()
        token2 = stream.peek()
        assert token1.value == token2.value


class TestTokenStreamConsume:
    """Tests for consume() method."""

    def test_consume_advances_position(self, sample_tokens):
        """Consume advances stream position."""
        stream = TokenStream(sample_tokens)
        assert stream.position == 0
        token = stream.consume()
        assert token.value == "IDENTIFICATION"
        assert stream.position == 1

    def test_consume_returns_next_token(self, sample_tokens):
        """Consume returns next token sequentially."""
        stream = TokenStream(sample_tokens)
        t1 = stream.consume()
        t2 = stream.consume()
        t3 = stream.consume()
        assert t1.value == "IDENTIFICATION"
        assert t2.value == "DIVISION"
        assert t3.value == "."

    def test_consume_on_empty_stream_raises(self, sample_tokens):
        """Consume on exhausted stream raises UnexpectedEndOfInput."""
        stream = TokenStream(sample_tokens)
        # Consume all tokens
        while not stream.is_empty():
            stream.consume()

        with pytest.raises(UnexpectedEndOfInput):
            stream.consume()


class TestTokenStreamExpect:
    """Tests for expect() method."""

    def test_expect_matching_value_succeeds(self, sample_tokens):
        """Expect returns token when value matches."""
        stream = TokenStream(sample_tokens)
        token = stream.expect("IDENTIFICATION")
        assert token.value == "IDENTIFICATION"
        assert stream.position == 1

    def test_expect_case_insensitive(self, sample_tokens):
        """Expect is case-insensitive."""
        stream = TokenStream(sample_tokens)
        token = stream.expect("identification")
        assert token.value == "IDENTIFICATION"

    def test_expect_non_matching_raises_mismatch(self, sample_tokens):
        """Expect raises TokenMismatch when value doesn't match."""
        stream = TokenStream(sample_tokens)
        with pytest.raises(TokenMismatch) as exc_info:
            stream.expect("PROCEDURE")

        error = exc_info.value
        assert error.expected == "PROCEDURE"
        assert error.actual == "IDENTIFICATION"

    def test_expect_on_empty_stream_raises(self, sample_tokens):
        """Expect on exhausted stream raises UnexpectedEndOfInput."""
        stream = TokenStream(sample_tokens)
        while not stream.is_empty():
            stream.consume()

        with pytest.raises(UnexpectedEndOfInput):
            stream.expect("SOMETHING")


class TestTokenStreamIsEmpty:
    """Tests for is_empty() method."""

    def test_is_empty_initially_false(self, sample_tokens):
        """is_empty is False at start."""
        stream = TokenStream(sample_tokens)
        assert not stream.is_empty()

    def test_is_empty_after_consuming_all(self, sample_tokens):
        """is_empty is True when all consumed."""
        stream = TokenStream(sample_tokens)
        while stream.peek():
            stream.consume()
        assert stream.is_empty()

    def test_is_empty_on_empty_token_list(self):
        """is_empty is True on empty token list."""
        stream = TokenStream([])
        assert stream.is_empty()


class TestTokenStreamLookahead:
    """Tests for lookahead buffer functionality."""

    def test_lookahead_configurable(self, sample_tokens):
        """Lookahead buffer size is configurable."""
        stream = TokenStream(sample_tokens, lookahead=5)
        assert stream._lookahead_size == 5

    def test_default_lookahead(self, sample_tokens):
        """Default lookahead is 3."""
        stream = TokenStream(sample_tokens)
        assert stream._lookahead_size == 3

    def test_multiple_peeks_use_lookahead(self, sample_tokens):
        """Multiple peek operations work with lookahead buffer."""
        stream = TokenStream(sample_tokens, lookahead=3)
        # Peek multiple positions
        t0 = stream.peek(0)
        t1 = stream.peek(1)
        t2 = stream.peek(2)

        assert t0.value == "IDENTIFICATION"
        assert t1.value == "DIVISION"
        assert t2.value == "."
        assert stream.position == 0


class TestTokenStreamSourceLocation:
    """Tests for source location tracking."""

    def test_token_contains_source_location(self):
        """Tokens contain source location information."""
        token = Token(
            TokenType.IDENTIFICATION_DIVISION, "IDENTIFICATION", SourceLocation(1, 1)
        )
        assert token.location.line == 1
        assert token.location.column == 1

    def test_peek_preserves_location(self, sample_tokens):
        """Peeked tokens preserve location info."""
        stream = TokenStream(sample_tokens)
        token = stream.peek(3)
        assert token.location.line == 2
        assert token.location.column == 1


class TestTokenStreamIntegration:
    """Integration tests for TokenStream workflow."""

    def test_parse_simple_sequence(self, sample_tokens):
        """Simulate simple parsing sequence."""
        stream = TokenStream(sample_tokens)

        # Expect IDENTIFICATION DIVISION.
        stream.expect("IDENTIFICATION")
        stream.expect("DIVISION")
        stream.expect(".")

        # Expect PROGRAM-ID.
        stream.expect("PROGRAM-ID")
        stream.expect(".")

        # Program name
        program_name = stream.consume().value

        assert program_name == "TEST-PROGRAM"
        assert stream.is_empty()

    def test_backtracking_with_transaction(self, sample_tokens):
        """Transaction context manager enables backtracking."""
        stream = TokenStream(sample_tokens)

        initial_pos = stream.position
        try:
            with stream.transaction():
                stream.consume()  # IDENTIFICATION
                stream.expect("PROCEDURE")  # This will raise
        except Exception:
            pass

        # Position should be restored
        assert stream.position == initial_pos
        assert stream.peek().value == "IDENTIFICATION"
