"""Unit tests for MoveStatementParser optimisation: module-level stop sets."""

from cobolparser.lexer import TokenType
from cobolparser.parsers.statements.move_parser import (
    _STOP_KEYWORDS,
    _STOP_TOKEN_TYPES,
)


class TestMoveParserConstants:
    """Verify _STOP_TOKEN_TYPES and _STOP_KEYWORDS are correct module-level frozensets."""

    def test_stop_token_types_is_frozenset(self) -> None:
        assert isinstance(_STOP_TOKEN_TYPES, frozenset)

    def test_stop_keywords_is_frozenset(self) -> None:
        assert isinstance(_STOP_KEYWORDS, frozenset)

    def test_stop_token_types_contains_move(self) -> None:
        assert TokenType.MOVE in _STOP_TOKEN_TYPES

    def test_stop_keywords_contains_move(self) -> None:
        assert "MOVE" in _STOP_KEYWORDS

    def test_stop_keywords_contains_end_move(self) -> None:
        assert "END-MOVE" in _STOP_KEYWORDS

    def test_stop_keywords_upper_case(self) -> None:
        for kw in _STOP_KEYWORDS:
            assert kw == kw.upper(), f"Keyword not uppercase: {kw!r}"

    def test_module_level_same_object_on_repeated_import(self) -> None:
        from cobolparser.parsers.statements import move_parser
        assert move_parser._STOP_TOKEN_TYPES is _STOP_TOKEN_TYPES
        assert move_parser._STOP_KEYWORDS is _STOP_KEYWORDS
