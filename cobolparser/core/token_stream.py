from typing import Optional, Iterator, List
from contextlib import contextmanager
from ..lexer import Token, TokenType

class TokenStream:
    """Encapsulates token list and position cursor."""
    
    def __init__(self, tokens: List[Token]):
        self._tokens = tokens
        self._pos = 0
    
    def peek(self, offset: int = 0) -> Optional[Token]:
        idx = self._pos + offset
        if 0 <= idx < len(self._tokens):
            return self._tokens[idx]
        return None
    
    def advance(self) -> Token:
        if self.is_at_end:
            # Return current token if at end, or last token?
            # Existing parser returns None or handles EOF.
            # safe access
            return self._tokens[-1] if self._tokens else None  # type: ignore
        token = self._tokens[self._pos]
        self._pos += 1
        return token
    
    def match(self, *types: TokenType) -> bool:
        token = self.peek()
        return token is not None and token.type in types
    
    def match_value(self, *values: str) -> bool:
        token = self.peek()
        # Case insensitive comparison
        return token is not None and token.value and token.value.upper() in [v.upper() for v in values]
    
    def skip_whitespace_and_comments(self) -> None:
        while self.match(TokenType.WHITESPACE, TokenType.COMMENT, TokenType.NEWLINE, TokenType.CONTINUATION):
            self.advance()
            
    @contextmanager
    def transaction(self):
        """Context manager for backtracking on failure."""
        saved_pos = self._pos
        try:
            yield
        except Exception:
            self._pos = saved_pos
            raise
    
    @property
    def position(self) -> int:
        return self._pos
    
    @property
    def is_at_end(self) -> bool:
        return self._pos >= len(self._tokens)
