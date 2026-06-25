from contextlib import contextmanager
from typing import Any

from ..lexer import Token, TokenType
from .exceptions import TokenMismatch, UnexpectedEndOfInput
from .interfaces import ITokenStream


class TokenStream(ITokenStream):
    """Encapsulates token list and position cursor with lookahead support.

    Implements ITokenStream interface for token navigation with peek, consume,
    and expect operations. Supports configurable lookahead buffer for performance.
    """

    def __init__(self, tokens: list[Token], lookahead: int = 3):
        """Initialize token stream.

        Args:
            tokens: List of tokens to parse
            lookahead: Lookahead buffer size for performance optimization
        """
        self._tokens = tokens
        self._pos = 0
        self._len = len(tokens)
        self._lookahead_size = lookahead
        self._parse_context = None

    def peek(self, offset: int = 0) -> Token | None:
        """Look at token without consuming it.

        Args:
            offset: How many tokens ahead (default: 0 = next token)

        Returns:
            Token at position+offset, or None if out of bounds
        """
        idx = self._pos + offset
        if idx < 0:
            return None
        try:
            return self._tokens[idx]
        except IndexError:
            return None

    def consume(self) -> Token:
        """Consume and return the next token (ITokenStream interface).

        Returns:
            The consumed token

        Raises:
            UnexpectedEndOfInput: If stream is exhausted
        """
        try:
            token = self._tokens[self._pos]
        except IndexError as exc:
            raise UnexpectedEndOfInput() from exc
        self._pos += 1
        return token

    def expect(self, value: str) -> Token:
        """Expect a specific token value before consuming (ITokenStream interface).

        Args:
            value: Expected token value (case-insensitive)

        Returns:
            The consumed token if it matches

        Raises:
            TokenMismatch: If next token doesn't match
            UnexpectedEndOfInput: If stream is exhausted
        """
        token = self.peek()
        if token is None:
            raise UnexpectedEndOfInput(f"Expected '{value}'")

        if token.value and token.value.upper() != value.upper():
            raise TokenMismatch(value, token.value)

        return self.consume()

    def is_empty(self) -> bool:
        """Check if stream is exhausted (ITokenStream interface).

        Returns:
            True if no more tokens, False otherwise
        """
        return self._pos >= self._len

    def match(self, *types: TokenType) -> bool:
        """Check if next token matches any of the given types."""
        token = self.peek()
        return token is not None and token.type in types

    def skip_whitespace_and_comments(self) -> None:
        """Skip whitespace, comment, newline, and continuation tokens."""
        while not self.is_empty():
            token = self.peek()
            if not token or token.type not in (
                TokenType.WHITESPACE,
                TokenType.COMMENT,
                TokenType.NEWLINE,
                TokenType.CONTINUATION,
            ):
                break
            self.consume()

    @contextmanager
    def transaction(self) -> Any:
        """Context manager for backtracking on failure."""
        saved_pos = self._pos
        try:
            yield
        except Exception:
            self._pos = saved_pos
            raise

    @property
    def context(self) -> Any | None:
        """Optional ParseContext attached to this stream."""
        return self._parse_context

    @context.setter
    def context(self, value: Any | None) -> None:
        self._parse_context = value

    @property
    def position(self) -> int:
        """Current position in token stream."""
        return self._pos
