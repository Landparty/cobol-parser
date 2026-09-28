"""Unit tests for InitializeStatementParser and InspectStatementParser.

Tests parser directly via TokenStream, asserting on AST node fields.
Covers:
- INITIALIZE basic targets
- INITIALIZE WITH FILLER
- INITIALIZE REPLACING category DATA BY value (with/without DATA keyword)
- INSPECT TALLYING FOR CHARACTERS / ALL / LEADING
- INSPECT TALLYING with BEFORE/AFTER INITIAL
- INSPECT REPLACING CHARACTERS / ALL / LEADING / FIRST
- INSPECT REPLACING with BEFORE/AFTER INITIAL
- INSPECT CONVERTING from TO to
- INSPECT TALLYING then REPLACING (combined)
- matches() on correct and wrong tokens
"""

from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements.initialize_inspect_parsers import (
    InitializeStatementParser,
    InspectStatementParser,
)


def _loc(line: int = 1, col: int = 1) -> SourceLocation:
    return SourceLocation(line, col)


def _tok(ttype: TokenType, value: str, line: int = 1, col: int = 1) -> Token:
    return Token(ttype, value, _loc(line, col))


def _ident(value: str, col: int = 1) -> Token:
    return _tok(TokenType.IDENTIFIER, value, col=col)


def _period() -> Token:
    return _tok(TokenType.PERIOD, ".")


def _eof() -> Token:
    return _tok(TokenType.EOF, "")


def _stream(*tokens: Token) -> TokenStream:
    return TokenStream(list(tokens))


# ---------------------------------------------------------------------------
# InitializeStatementParser
# ---------------------------------------------------------------------------


class TestInitializeStatementParserMatches:
    def test_matches_initialize_token(self):
        parser = InitializeStatementParser()
        stream = _stream(_tok(TokenType.INITIALIZE, "INITIALIZE"), _eof())
        assert parser.matches(stream) is True

    def test_matches_initialize_identifier_fallback(self):
        parser = InitializeStatementParser()
        stream = _stream(_ident("INITIALIZE"), _eof())
        assert parser.matches(stream) is True

    def test_does_not_match_other_keyword(self):
        parser = InitializeStatementParser()
        stream = _stream(_tok(TokenType.MOVE, "MOVE"), _eof())
        assert parser.matches(stream) is False

    def test_does_not_match_empty_stream(self):
        parser = InitializeStatementParser()
        stream = _stream(_eof())
        assert parser.matches(stream) is False


class TestInitializeStatementParserParse:
    def test_single_target(self):
        tokens = [
            _tok(TokenType.INITIALIZE, "INITIALIZE"),
            _ident("WS-RECORD"),
            _period(),
            _eof(),
        ]
        stmt = InitializeStatementParser().parse(_stream(*tokens))
        assert stmt.statement_type == "INITIALIZE"
        assert "WS-RECORD" in stmt.targets

    def test_multiple_targets(self):
        tokens = [
            _tok(TokenType.INITIALIZE, "INITIALIZE"),
            _ident("WS-REC-A"),
            _ident("WS-REC-B"),
            _ident("WS-REC-C"),
            _period(),
            _eof(),
        ]
        stmt = InitializeStatementParser().parse(_stream(*tokens))
        assert "WS-REC-A" in stmt.targets
        assert "WS-REC-B" in stmt.targets
        assert "WS-REC-C" in stmt.targets

    def test_with_filler_clause(self):
        tokens = [
            _tok(TokenType.INITIALIZE, "INITIALIZE"),
            _ident("WS-RECORD"),
            _ident("WITH"),
            _ident("FILLER"),
            _period(),
            _eof(),
        ]
        stmt = InitializeStatementParser().parse(_stream(*tokens))
        assert stmt.with_filler is True
        assert "WS-RECORD" in stmt.targets

    def test_replacing_numeric_category(self):
        tokens = [
            _tok(TokenType.INITIALIZE, "INITIALIZE"),
            _ident("WS-RECORD"),
            _ident("REPLACING"),
            _ident("NUMERIC"),
            _ident("DATA"),
            _ident("BY"),
            _tok(TokenType.NUMERIC_LITERAL, "0"),
            _period(),
            _eof(),
        ]
        stmt = InitializeStatementParser().parse(_stream(*tokens))
        assert len(stmt.replacing_clauses) == 1
        assert stmt.replacing_clauses[0]["category"] == "NUMERIC"
        assert stmt.replacing_clauses[0]["by_value"] == "0"

    def test_replacing_without_data_keyword(self):
        tokens = [
            _tok(TokenType.INITIALIZE, "INITIALIZE"),
            _ident("WS-RECORD"),
            _ident("REPLACING"),
            _ident("ALPHANUMERIC"),
            _ident("BY"),
            _tok(TokenType.STRING_LITERAL, "SPACES"),
            _period(),
            _eof(),
        ]
        stmt = InitializeStatementParser().parse(_stream(*tokens))
        assert len(stmt.replacing_clauses) == 1
        assert stmt.replacing_clauses[0]["category"] == "ALPHANUMERIC"

    def test_replacing_multiple_categories(self):
        tokens = [
            _tok(TokenType.INITIALIZE, "INITIALIZE"),
            _ident("WS-REC"),
            _ident("REPLACING"),
            _ident("NUMERIC"),
            _ident("DATA"),
            _ident("BY"),
            _tok(TokenType.NUMERIC_LITERAL, "0"),
            _ident("ALPHANUMERIC"),
            _ident("DATA"),
            _ident("BY"),
            _tok(TokenType.STRING_LITERAL, "SPACES"),
            _period(),
            _eof(),
        ]
        stmt = InitializeStatementParser().parse(_stream(*tokens))
        assert len(stmt.replacing_clauses) == 2

    def test_subscripted_and_qualified_targets_kept_whole(self):
        """`INITIALIZE TBL(1) B OF C` used to yield targets ["TBL"], the
        subscript and the second (qualified) target dropped as unparsed."""
        tokens = [
            _tok(TokenType.INITIALIZE, "INITIALIZE"),
            _ident("TBL"),
            _tok(TokenType.LEFT_PAREN, "("),
            _tok(TokenType.NUMERIC_LITERAL, "1"),
            _tok(TokenType.RIGHT_PAREN, ")"),
            _ident("B"),
            _tok(TokenType.OF, "OF"),
            _ident("C"),
            _period(),
            _eof(),
        ]
        stream = _stream(*tokens)
        stmt = InitializeStatementParser().parse(stream)
        assert stmt.targets == ["TBL ( 1 )", "B OF C"]
        assert stream.is_empty() or stream.peek().type == TokenType.EOF

    def test_replacing_by_qualified_value(self):
        """`REPLACING NUMERIC BY WS-X OF GRP` -- the BY value is one
        qualified item, not `WS-X` with `OF GRP` stranded."""
        tokens = [
            _tok(TokenType.INITIALIZE, "INITIALIZE"),
            _ident("WS-REC"),
            _ident("REPLACING"),
            _ident("NUMERIC"),
            _ident("BY"),
            _ident("WS-X"),
            _tok(TokenType.OF, "OF"),
            _ident("GRP"),
            _period(),
            _eof(),
        ]
        stream = _stream(*tokens)
        stmt = InitializeStatementParser().parse(stream)
        assert stmt.replacing_clauses == [
            {"category": "NUMERIC", "by_value": "WS-X OF GRP"}
        ]
        assert stream.is_empty() or stream.peek().type == TokenType.EOF

    def test_no_targets_no_crash(self):
        tokens = [
            _tok(TokenType.INITIALIZE, "INITIALIZE"),
            _period(),
            _eof(),
        ]
        stmt = InitializeStatementParser().parse(_stream(*tokens))
        assert stmt.statement_type == "INITIALIZE"
        assert stmt.targets == []

    def test_to_dict_structure(self):
        tokens = [
            _tok(TokenType.INITIALIZE, "INITIALIZE"),
            _ident("WS-RECORD"),
            _period(),
            _eof(),
        ]
        stmt = InitializeStatementParser().parse(_stream(*tokens))
        d = stmt.to_dict()
        assert d["statement_type"] == "INITIALIZE"
        assert "targets" in d
        assert "replacing_clauses" in d
        assert "with_filler" in d


# ---------------------------------------------------------------------------
# InspectStatementParser
# ---------------------------------------------------------------------------


class TestInspectStatementParserMatches:
    def test_matches_inspect_token(self):
        parser = InspectStatementParser()
        stream = _stream(_tok(TokenType.INSPECT, "INSPECT"), _eof())
        assert parser.matches(stream) is True

    def test_matches_inspect_identifier_fallback(self):
        parser = InspectStatementParser()
        stream = _stream(_ident("INSPECT"), _eof())
        assert parser.matches(stream) is True

    def test_does_not_match_other_token(self):
        parser = InspectStatementParser()
        stream = _stream(_tok(TokenType.SORT, "SORT"), _eof())
        assert parser.matches(stream) is False

    def test_does_not_match_empty_stream(self):
        parser = InspectStatementParser()
        stream = _stream(_eof())
        assert parser.matches(stream) is False


class TestInspectTallying:
    def test_tallying_for_characters(self):
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("TALLYING"),
            _ident("WS-COUNT"),
            _ident("FOR"),
            _ident("CHARACTERS"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        assert stmt.target == "WS-FIELD"
        assert stmt.inspect_type == "TALLYING"
        assert len(stmt.tallying_clauses) == 1
        clause = stmt.tallying_clauses[0]
        assert clause["counter"] == "WS-COUNT"
        assert clause["for_type"] == "CHARACTERS"

    def test_tallying_for_all(self):
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("TALLYING"),
            _ident("WS-COUNT"),
            _ident("FOR"),
            _ident("ALL"),
            _tok(TokenType.STRING_LITERAL, "A"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        assert stmt.inspect_type == "TALLYING"
        clause = stmt.tallying_clauses[0]
        assert clause["for_type"] == "ALL"
        assert clause["value"] == "A"

    def test_tallying_for_leading(self):
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("TALLYING"),
            _ident("WS-COUNT"),
            _ident("FOR"),
            _ident("LEADING"),
            _tok(TokenType.STRING_LITERAL, "0"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        clause = stmt.tallying_clauses[0]
        assert clause["for_type"] == "LEADING"
        assert clause["value"] == "0"

    def test_tallying_with_before_initial(self):
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("TALLYING"),
            _ident("WS-COUNT"),
            _ident("FOR"),
            _ident("ALL"),
            _tok(TokenType.STRING_LITERAL, "A"),
            _ident("BEFORE"),
            _ident("INITIAL"),
            _tok(TokenType.STRING_LITERAL, "B"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        clause = stmt.tallying_clauses[0]
        assert clause["before"] == "B"

    def test_tallying_with_after_initial(self):
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("TALLYING"),
            _ident("WS-COUNT"),
            _ident("FOR"),
            _ident("ALL"),
            _tok(TokenType.STRING_LITERAL, "A"),
            _ident("AFTER"),
            _ident("INITIAL"),
            _tok(TokenType.STRING_LITERAL, "X"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        clause = stmt.tallying_clauses[0]
        assert clause["after"] == "X"


class TestInspectReplacing:
    def test_replacing_characters_by(self):
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("REPLACING"),
            _ident("CHARACTERS"),
            _ident("BY"),
            _tok(TokenType.STRING_LITERAL, "X"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        assert stmt.inspect_type == "REPLACING"
        assert len(stmt.replacing_clauses) == 1
        clause = stmt.replacing_clauses[0]
        assert clause["replace_type"] == "CHARACTERS"
        assert clause["to_value"] == "X"

    def test_replacing_all_by(self):
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("REPLACING"),
            _ident("ALL"),
            _tok(TokenType.STRING_LITERAL, "A"),
            _ident("BY"),
            _tok(TokenType.STRING_LITERAL, "B"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        clause = stmt.replacing_clauses[0]
        assert clause["replace_type"] == "ALL"
        assert clause["from_value"] == "A"
        assert clause["to_value"] == "B"

    def test_replacing_first_by(self):
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("REPLACING"),
            _ident("FIRST"),
            _tok(TokenType.STRING_LITERAL, "X"),
            _ident("BY"),
            _tok(TokenType.STRING_LITERAL, "Y"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        clause = stmt.replacing_clauses[0]
        assert clause["replace_type"] == "FIRST"

    def test_replacing_leading_by(self):
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("REPLACING"),
            _ident("LEADING"),
            _tok(TokenType.STRING_LITERAL, "0"),
            _ident("BY"),
            _tok(TokenType.STRING_LITERAL, "SPACE"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        clause = stmt.replacing_clauses[0]
        assert clause["replace_type"] == "LEADING"

    def test_replacing_with_before_initial(self):
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("REPLACING"),
            _ident("ALL"),
            _tok(TokenType.STRING_LITERAL, "A"),
            _ident("BY"),
            _tok(TokenType.STRING_LITERAL, "B"),
            _ident("BEFORE"),
            _ident("INITIAL"),
            _tok(TokenType.STRING_LITERAL, "C"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        clause = stmt.replacing_clauses[0]
        assert clause["before"] == "C"

    def test_replacing_with_after_initial(self):
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("REPLACING"),
            _ident("ALL"),
            _tok(TokenType.STRING_LITERAL, "A"),
            _ident("BY"),
            _tok(TokenType.STRING_LITERAL, "B"),
            _ident("AFTER"),
            _ident("INITIAL"),
            _tok(TokenType.STRING_LITERAL, "D"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        clause = stmt.replacing_clauses[0]
        assert clause["after"] == "D"


class TestInspectConverting:
    def test_converting_from_to(self):
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("CONVERTING"),
            _tok(TokenType.STRING_LITERAL, "ABCDE"),
            _ident("TO"),
            _tok(TokenType.STRING_LITERAL, "abcde"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        assert stmt.inspect_type == "CONVERTING"
        assert stmt.converting_from == "ABCDE"
        assert stmt.converting_to == "abcde"


class TestInspectTallyingReplacing:
    def test_tallying_then_replacing_sets_combined_type(self):
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("TALLYING"),
            _ident("WS-COUNT"),
            _ident("FOR"),
            _ident("CHARACTERS"),
            _ident("REPLACING"),
            _ident("CHARACTERS"),
            _ident("BY"),
            _tok(TokenType.STRING_LITERAL, "X"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        assert stmt.inspect_type == "TALLYING_REPLACING"
        assert len(stmt.tallying_clauses) >= 1
        assert len(stmt.replacing_clauses) >= 1


class TestInspectToDict:
    def test_to_dict_tallying_structure(self):
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("TALLYING"),
            _ident("WS-COUNT"),
            _ident("FOR"),
            _ident("CHARACTERS"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        d = stmt.to_dict()
        assert d["statement_type"] == "INSPECT"
        assert "target" in d
        assert "inspect_type" in d
        # tallying_clauses is only present when non-empty
        assert "tallying_clauses" in d
        assert len(d["tallying_clauses"]) >= 1
        # replacing_clauses and converting fields are conditionally serialized
        # (only present when non-empty/non-None) - not asserted here

    def test_to_dict_converting_structure(self):
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("CONVERTING"),
            _tok(TokenType.STRING_LITERAL, "ABC"),
            _ident("TO"),
            _tok(TokenType.STRING_LITERAL, "abc"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        d = stmt.to_dict()
        # converting fields are conditionally serialised — assert directly on d
        # so that a missing key in to_dict() is caught rather than masked by the
        # stmt attribute fallback.
        assert d["converting_from"] == "ABC"
        assert d["converting_to"] == "abc"
