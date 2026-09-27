"""Regression tests for INSPECT TALLYING/REPLACING FOR-phrases that carry
BOTH a BEFORE INITIAL and an AFTER INITIAL qualifier simultaneously.

Prior to this fix, ``_parse_tallying``/``_parse_replacing`` in
``initialize_inspect_parsers.py`` used a single ``if`` check for the
BEFORE/AFTER qualifier, so only the first one found was captured -- the
second was silently swallowed by the statement's generic "consume to
period" trailer with zero errors/warnings. The COBOL grammar allows a
single FOR-phrase to carry both:

    INSPECT identifier TALLYING counter
        FOR ALL "X" BEFORE INITIAL "Y" AFTER INITIAL "Z"

Covers:
- INSPECT TALLYING FOR ALL with both BEFORE and AFTER on one FOR-phrase
- INSPECT REPLACING ALL ... BY ... with both BEFORE and AFTER on one phrase
- A multi-phrase statement mixing a "both qualifiers" phrase with a
  "single qualifier" phrase, to confirm they do not interfere
- End-to-end sanity checks via parse_cobol()/.to_dict()
"""

from cobolparser import parse_cobol
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements.initialize_inspect_parsers import (
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
# TALLYING: single FOR-phrase with both BEFORE and AFTER
# ---------------------------------------------------------------------------


class TestTallyingBeforeAndAfterOnSamePhrase:
    def test_captures_both_qualifiers(self):
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("TALLYING"),
            _ident("WS-COUNT"),
            _ident("FOR"),
            _ident("ALL"),
            _tok(TokenType.STRING_LITERAL, "X"),
            _ident("BEFORE"),
            _ident("INITIAL"),
            _tok(TokenType.STRING_LITERAL, "Y"),
            _ident("AFTER"),
            _ident("INITIAL"),
            _tok(TokenType.STRING_LITERAL, "Z"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        assert stmt.inspect_type == "TALLYING"
        assert len(stmt.tallying_clauses) == 1
        clause = stmt.tallying_clauses[0]
        assert clause["counter"] == "WS-COUNT"
        assert clause["for_type"] == "ALL"
        assert clause["value"] == "X"
        assert clause["before"] == "Y"
        assert clause["after"] == "Z"

    def test_multi_phrase_both_and_single_do_not_interfere(self):
        """One FOR-phrase with BEFORE+AFTER, another with just AFTER."""
        tokens = [
            _tok(TokenType.INSPECT, "INSPECT"),
            _ident("WS-FIELD"),
            _ident("TALLYING"),
            _ident("WS-COUNT"),
            _ident("FOR"),
            _ident("ALL"),
            _tok(TokenType.STRING_LITERAL, "X"),
            _ident("BEFORE"),
            _ident("INITIAL"),
            _tok(TokenType.STRING_LITERAL, "Y"),
            _ident("AFTER"),
            _ident("INITIAL"),
            _tok(TokenType.STRING_LITERAL, "Z"),
            _ident("WS-COUNT2"),
            _ident("FOR"),
            _ident("LEADING"),
            _tok(TokenType.STRING_LITERAL, "A"),
            _ident("AFTER"),
            _ident("INITIAL"),
            _tok(TokenType.STRING_LITERAL, "B"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        assert len(stmt.tallying_clauses) == 2

        first = stmt.tallying_clauses[0]
        assert first["counter"] == "WS-COUNT"
        assert first["before"] == "Y"
        assert first["after"] == "Z"

        second = stmt.tallying_clauses[1]
        assert second["counter"] == "WS-COUNT2"
        assert second["for_type"] == "LEADING"
        assert second["before"] is None
        assert second["after"] == "B"


# ---------------------------------------------------------------------------
# REPLACING: single phrase with both BEFORE and AFTER
# ---------------------------------------------------------------------------


class TestReplacingBeforeAndAfterOnSamePhrase:
    def test_captures_both_qualifiers(self):
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
            _tok(TokenType.STRING_LITERAL, "X"),
            _ident("AFTER"),
            _ident("INITIAL"),
            _tok(TokenType.STRING_LITERAL, "Y"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        assert stmt.inspect_type == "REPLACING"
        assert len(stmt.replacing_clauses) == 1
        clause = stmt.replacing_clauses[0]
        assert clause["replace_type"] == "ALL"
        assert clause["from_value"] == "A"
        assert clause["to_value"] == "B"
        assert clause["before"] == "X"
        assert clause["after"] == "Y"

    def test_multi_phrase_both_and_single_do_not_interfere(self):
        """One REPLACING phrase with BEFORE+AFTER, another with just BEFORE."""
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
            _tok(TokenType.STRING_LITERAL, "X"),
            _ident("AFTER"),
            _ident("INITIAL"),
            _tok(TokenType.STRING_LITERAL, "Y"),
            _ident("LEADING"),
            _tok(TokenType.STRING_LITERAL, "C"),
            _ident("BY"),
            _tok(TokenType.STRING_LITERAL, "D"),
            _ident("BEFORE"),
            _ident("INITIAL"),
            _tok(TokenType.STRING_LITERAL, "E"),
            _period(),
            _eof(),
        ]
        stmt = InspectStatementParser().parse(_stream(*tokens))
        assert len(stmt.replacing_clauses) == 2

        first = stmt.replacing_clauses[0]
        assert first["before"] == "X"
        assert first["after"] == "Y"

        second = stmt.replacing_clauses[1]
        assert second["replace_type"] == "LEADING"
        assert second["before"] == "E"
        assert second["after"] is None


# ---------------------------------------------------------------------------
# End-to-end sanity checks via parse_cobol()/.to_dict()
# ---------------------------------------------------------------------------


class TestInspectBeforeAfterEndToEnd:
    def _parse(self, statement: str):
        src = f"""IDENTIFICATION DIVISION.
PROGRAM-ID. TESTPROG.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-FIELD PIC X(20).
01 WS-COUNT PIC 9(4).
PROCEDURE DIVISION.
MAIN-PARA.
    {statement}
    STOP RUN.
"""
        return parse_cobol(src, filename="test.cbl", free_form=True)

    def test_tallying_both_qualifiers_end_to_end(self):
        result = self._parse(
            'INSPECT WS-FIELD TALLYING WS-COUNT FOR ALL "X" '
            'BEFORE INITIAL "Y" AFTER INITIAL "Z".'
        )
        assert result.success is True
        assert result.errors == []
        assert result.warnings == []

        stmts = result.ast.find_all_by_type("InspectStatement")
        assert len(stmts) == 1
        clause = stmts[0].to_dict()["tallying_clauses"][0]
        assert clause["before"] == "Y"
        assert clause["after"] == "Z"

    def test_replacing_both_qualifiers_end_to_end(self):
        result = self._parse(
            'INSPECT WS-FIELD REPLACING ALL "A" BY "B" '
            'BEFORE INITIAL "X" AFTER INITIAL "Y".'
        )
        assert result.success is True
        assert result.errors == []
        assert result.warnings == []

        stmts = result.ast.find_all_by_type("InspectStatement")
        assert len(stmts) == 1
        clause = stmts[0].to_dict()["replacing_clauses"][0]
        assert clause["before"] == "X"
        assert clause["after"] == "Y"

    def test_tallying_reversed_qualifier_order(self):
        """IBM Enterprise COBOL allows AFTER before BEFORE -- both must be
        captured regardless of which qualifier is written first."""
        result = self._parse(
            'INSPECT WS-FIELD TALLYING WS-COUNT FOR ALL "X" '
            'AFTER INITIAL "Z" BEFORE INITIAL "Y".'
        )
        assert result.success is True
        assert result.errors == []
        assert result.warnings == []

        stmts = result.ast.find_all_by_type("InspectStatement")
        assert len(stmts) == 1
        clause = stmts[0].to_dict()["tallying_clauses"][0]
        assert clause["before"] == "Y"
        assert clause["after"] == "Z"

    def test_replacing_reversed_qualifier_order(self):
        result = self._parse(
            'INSPECT WS-FIELD REPLACING ALL "A" BY "B" '
            'AFTER INITIAL "Y" BEFORE INITIAL "X".'
        )
        assert result.success is True
        assert result.errors == []

        stmts = result.ast.find_all_by_type("InspectStatement")
        assert len(stmts) == 1
        clause = stmts[0].to_dict()["replacing_clauses"][0]
        assert clause["before"] == "X"
        assert clause["after"] == "Y"


# ---------------------------------------------------------------------------
# Figurative / subscripted delimiters, subscripted counters, CONVERTING
# ---------------------------------------------------------------------------


def _inspect_of(statement: str) -> dict:
    source = f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC X(10).
       01 B PIC X(10).
       01 C PIC 9(4).
       01 D PIC 9(4).
       01 P PIC X.
       01 TBL.
          05 ENT PIC X OCCURS 5.
          05 CNT PIC 9(4) OCCURS 5.
       PROCEDURE DIVISION.
       MAIN.
           {statement}
           MOVE 1 TO C.
           STOP RUN.
"""
    result = parse_cobol(source)
    assert result.ast is not None and not result.errors
    stmts = [s.to_dict() for s in result.ast.get_all_statements()]
    assert [s["statement_type"] for s in stmts] == ["INSPECT", "MOVE", "STOP"]
    return stmts[0]


class TestInspectDelimiterAndOperandShapes:
    def test_figurative_delimiter_keeps_following_counter_clause(self) -> None:
        d = _inspect_of(
            "INSPECT A TALLYING C FOR CHARACTERS BEFORE INITIAL SPACE\n"
            "                                 D FOR ALL 'Z'"
        )
        assert d["tallying_clauses"] == [
            {
                "counter": "C",
                "for_type": "CHARACTERS",
                "value": None,
                "before": "SPACE",
                "after": None,
            },
            {
                "counter": "D",
                "for_type": "ALL",
                "value": "Z",
                "before": None,
                "after": None,
            },
        ]

    def test_subscripted_delimiter_and_counter(self) -> None:
        d = _inspect_of("INSPECT A TALLYING CNT(2) FOR ALL 'X' AFTER INITIAL ENT(2)")
        [clause] = d["tallying_clauses"]
        assert clause["counter"] == "CNT ( 2 )"
        assert clause["after"] == "ENT ( 2 )"

    def test_converting_keeps_subscripted_operand_and_before_after(self) -> None:
        d = _inspect_of("INSPECT A CONVERTING ENT(1) TO B AFTER INITIAL P")
        assert d["converting_from"] == "ENT ( 1 )"
        assert d["converting_to"] == "B"
        assert d["converting_after"] == "P"
        assert "converting_before" not in d

    def test_converting_delimiter_counts_as_a_reference(self) -> None:
        from cobolparser import UnusedVariableAnalyzer

        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC X(10).
       01 P PIC X.
       PROCEDURE DIVISION.
       MAIN.
           INSPECT A CONVERTING 'ab' TO 'AB' BEFORE INITIAL P.
           STOP RUN.
"""
        result = parse_cobol(source)
        assert result.ast is not None
        report = UnusedVariableAnalyzer().analyze(result.ast)
        assert "P" not in {item.name for item in report.unused_items}
