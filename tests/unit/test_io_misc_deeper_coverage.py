"""Tests to improve coverage of close_parser, open_parser, display_parser,
evaluate_parser, and accept_parser.

Targets uncovered branches and lines in:
  - close_parser.py: matches() exception, WITH LOCK (TokenType.LOCK),
    WITH NO REWIND, REEL, UNIT, multiple files, empty peek in file loop
  - open_parser.py: matches() exception, no mode after OPEN,
    file loop empty peek, REPOSITION, WITH REPOSITION after file list
  - display_parser.py: isinstance check, empty token in items loop,
    END-DISPLAY, UPON with no device token, _is_keyword no hasattr
  - evaluate_parser.py: matches None, matches exception, identifier check,
    empty condition, WHEN loop, WHEN OTHER, evaluate_type, WHEN clause
    branches, WHEN ALSO, nested stmt, end of EVALUATE, _collect_condition
  - accept_parser.py: matches None, matches IDENTIFIER, empty stream,
    FROM clause branches, FROM with device

Uses both full parse_cobol() round-trips and direct parser invocation
with hand-crafted Token objects for branches only reachable when the
lexer emits IDENTIFIER tokens for keywords the real lexer maps to
dedicated TokenType values.
"""

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements import DisplayStatement, EvaluateStatement
from cobolparser.parsers.statements.accept_parser import AcceptStatementParser
from cobolparser.parsers.statements.close_parser import CloseStatementParser
from cobolparser.parsers.statements.display_parser import DisplayStatementParser
from cobolparser.parsers.statements.evaluate_parser import EvaluateStatementParser
from cobolparser.parsers.statements.open_parser import OpenStatementParser

_LOC = SourceLocation(1, 1)


def _stream(*specs):
    """Build a TokenStream from (TokenType, value) pairs, appending EOF."""
    tokens = [Token(t, v, _LOC) for t, v in specs]
    tokens.append(Token(TokenType.EOF, "", _LOC))
    return TokenStream(tokens)


def _make_source(procedure_body: str, extra_sections: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST-PROG.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT TEST-FILE ASSIGN TO 'TESTFL'.\n"
        "           SELECT TEST-FILE2 ASSIGN TO 'TSTFL2'.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       FD TEST-FILE.\n"
        "       01 TEST-REC PIC X(80).\n"
        "       FD TEST-FILE2.\n"
        "       01 TEST-REC2 PIC X(80).\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-A PIC 9(4) VALUE 1.\n"
        "       01 WS-B PIC 9(4) VALUE 2.\n"
        "       01 WS-DATE PIC 9(8).\n"
        "       01 WS-TIME PIC 9(8).\n"
        f"{extra_sections}"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-LOGIC.\n"
        f"{procedure_body}\n"
    )


def _parse(src):
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    return parser.parse(src)


# =========================================================================
# CLOSE PARSER TESTS
# =========================================================================


class TestCloseParserCoverage:
    """Cover uncovered branches in close_parser.py."""

    # -- Full round-trip tests --

    def test_close_single_file(self):
        """CLOSE a single file -- baseline."""
        src = _make_source("           CLOSE TEST-FILE.\n")
        result = _parse(src)
        assert result.ast is not None
        stmts = result.ast.find_statements("CLOSE")
        assert len(stmts) >= 1
        assert "TEST-FILE" in stmts[0].file_names

    def test_close_multiple_files(self):
        """CLOSE TEST-FILE TEST-FILE2 -- multiple files in one statement."""
        src = _make_source("           CLOSE TEST-FILE TEST-FILE2.\n")
        result = _parse(src)
        assert result.ast is not None
        stmts = result.ast.find_statements("CLOSE")
        assert len(stmts) >= 1
        stmt = stmts[0]
        assert "TEST-FILE" in stmt.file_names
        assert "TEST-FILE2" in stmt.file_names

    # -- Direct parser tests for branches unreachable via round-trip --

    def test_close_with_no_rewind(self):
        """CLOSE file WITH NO REWIND -- lines 76-93 (WITH -> NO -> REWIND)."""
        parser = CloseStatementParser()
        stream = _stream(
            (TokenType.CLOSE, "CLOSE"),
            (TokenType.IDENTIFIER, "TEST-FILE"),
            (TokenType.IDENTIFIER, "WITH"),
            (TokenType.IDENTIFIER, "NO"),
            (TokenType.IDENTIFIER, "REWIND"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert "TEST-FILE" in stmt.file_names
        opts = stmt.close_options["TEST-FILE"]
        assert opts["no_rewind"] is True
        assert opts["with_lock"] is False

    def test_close_with_lock_identifier(self):
        """CLOSE file WITH LOCK (LOCK as IDENTIFIER) -- lines 95-98."""
        parser = CloseStatementParser()
        stream = _stream(
            (TokenType.CLOSE, "CLOSE"),
            (TokenType.IDENTIFIER, "TEST-FILE"),
            (TokenType.IDENTIFIER, "WITH"),
            (TokenType.IDENTIFIER, "LOCK"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert "TEST-FILE" in stmt.file_names
        opts = stmt.close_options["TEST-FILE"]
        assert opts["with_lock"] is True

    def test_close_with_lock_token_type(self):
        """CLOSE file WITH LOCK (LOCK as TokenType.LOCK) -- lines 99-102."""
        parser = CloseStatementParser()
        stream = _stream(
            (TokenType.CLOSE, "CLOSE"),
            (TokenType.IDENTIFIER, "TEST-FILE"),
            (TokenType.IDENTIFIER, "WITH"),
            (TokenType.LOCK, "LOCK"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert "TEST-FILE" in stmt.file_names
        opts = stmt.close_options["TEST-FILE"]
        assert opts["with_lock"] is True

    def test_close_reel(self):
        """CLOSE file REEL -- line 66-69."""
        parser = CloseStatementParser()
        stream = _stream(
            (TokenType.CLOSE, "CLOSE"),
            (TokenType.IDENTIFIER, "TEST-FILE"),
            (TokenType.REEL, "REEL"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert "TEST-FILE" in stmt.file_names
        opts = stmt.close_options["TEST-FILE"]
        assert opts["reel"] is True

    def test_close_unit(self):
        """CLOSE file UNIT -- lines 72-75."""
        parser = CloseStatementParser()
        stream = _stream(
            (TokenType.CLOSE, "CLOSE"),
            (TokenType.IDENTIFIER, "TEST-FILE"),
            (TokenType.IDENTIFIER, "UNIT"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert "TEST-FILE" in stmt.file_names
        opts = stmt.close_options["TEST-FILE"]
        assert opts["unit"] is True

    def test_close_matches_exception_path(self):
        """matches() exception path -- lines 26-27."""
        parser = CloseStatementParser()

        class BrokenStream:
            def peek(self):
                raise RuntimeError("stream error")

        assert parser.matches(BrokenStream()) is False

    def test_close_empty_peek_in_file_loop(self):
        """Empty peek after CLOSE -- lines 46->113, 48-49."""
        parser = CloseStatementParser()
        # Stream with only CLOSE and EOF (no files)
        stream = _stream(
            (TokenType.CLOSE, "CLOSE"),
        )
        stmt = parser.parse(stream)
        assert stmt.file_names == []

    def test_close_non_identifier_after_close(self):
        """Non-identifier token after CLOSE -- line 52-53 break."""
        parser = CloseStatementParser()
        stream = _stream(
            (TokenType.CLOSE, "CLOSE"),
            (TokenType.NUMERIC_LITERAL, "42"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert stmt.file_names == []

    def test_close_with_unknown_option(self):
        """CLOSE file WITH followed by unknown identifier -- line 86->94 branch."""
        parser = CloseStatementParser()
        stream = _stream(
            (TokenType.CLOSE, "CLOSE"),
            (TokenType.IDENTIFIER, "TEST-FILE"),
            (TokenType.IDENTIFIER, "WITH"),
            (TokenType.IDENTIFIER, "SOMETHING-ELSE"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert "TEST-FILE" in stmt.file_names
        opts = stmt.close_options["TEST-FILE"]
        # Neither no_rewind nor with_lock should be set
        assert opts["no_rewind"] is False
        assert opts["with_lock"] is False

    def test_close_with_non_identifier_after_with(self):
        """CLOSE file WITH followed by non-IDENTIFIER token -- line 95->104."""
        parser = CloseStatementParser()
        stream = _stream(
            (TokenType.CLOSE, "CLOSE"),
            (TokenType.IDENTIFIER, "TEST-FILE"),
            (TokenType.IDENTIFIER, "WITH"),
            (TokenType.NUMERIC_LITERAL, "99"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert "TEST-FILE" in stmt.file_names
        opts = stmt.close_options["TEST-FILE"]
        assert opts["with_lock"] is False
        assert opts["no_rewind"] is False


# =========================================================================
# OPEN PARSER TESTS
# =========================================================================


class TestOpenParserCoverage:
    """Cover uncovered branches in open_parser.py."""

    # -- Full round-trip tests --

    def test_open_input(self):
        """OPEN INPUT file -- basic mode."""
        src = _make_source("           OPEN INPUT TEST-FILE.\n")
        result = _parse(src)
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1

    def test_open_output(self):
        """OPEN OUTPUT file."""
        src = _make_source("           OPEN OUTPUT TEST-FILE.\n")
        result = _parse(src)
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1

    def test_open_io(self):
        """OPEN I-O file."""
        src = _make_source("           OPEN I-O TEST-FILE.\n")
        result = _parse(src)
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1

    def test_open_extend(self):
        """OPEN EXTEND file."""
        src = _make_source("           OPEN EXTEND TEST-FILE.\n")
        result = _parse(src)
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1

    # -- Direct parser tests --

    def test_open_matches_exception_path(self):
        """matches() exception path -- lines 31-32."""
        parser = OpenStatementParser()

        class BrokenStream:
            def peek(self):
                raise RuntimeError("stream error")

        assert parser.matches(BrokenStream()) is False

    def test_open_no_mode_after_open(self):
        """No mode token after OPEN -- lines 52->60."""
        parser = OpenStatementParser()
        stream = _stream(
            (TokenType.OPEN, "OPEN"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert stmt.open_mode is None
        assert stmt.file_names == []

    def test_open_empty_peek_in_file_loop(self):
        """Empty peek in file loop -- lines 60->85, 62-63."""
        parser = OpenStatementParser()
        # OPEN INPUT then only EOF
        stream = _stream(
            (TokenType.OPEN, "OPEN"),
            (TokenType.IDENTIFIER, "INPUT"),
        )
        stmt = parser.parse(stream)
        assert stmt.open_mode == "INPUT"
        assert stmt.file_names == []

    def test_open_reposition_within_file_loop(self):
        """REPOSITION within file loop -- lines 72-76."""
        parser = OpenStatementParser()
        stream = _stream(
            (TokenType.OPEN, "OPEN"),
            (TokenType.IDENTIFIER, "I-O"),
            (TokenType.IDENTIFIER, "TEST-FILE"),
            (TokenType.IDENTIFIER, "REPOSITION"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert stmt.open_mode == "I-O"
        assert "TEST-FILE" in stmt.file_names
        assert stmt.with_reposition is True

    def test_open_with_reposition_after_file_list(self):
        """WITH REPOSITION after file list -- lines 85->106."""
        parser = OpenStatementParser()
        stream = _stream(
            (TokenType.OPEN, "OPEN"),
            (TokenType.IDENTIFIER, "I-O"),
            (TokenType.IDENTIFIER, "TEST-FILE"),
            (TokenType.IDENTIFIER, "WITH"),
            (TokenType.IDENTIFIER, "REPOSITION"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert stmt.open_mode == "I-O"
        assert "TEST-FILE" in stmt.file_names
        assert stmt.with_reposition is True

    def test_open_non_identifier_in_file_loop(self):
        """Non-identifier token in file loop -- line 81-82 break."""
        parser = OpenStatementParser()
        stream = _stream(
            (TokenType.OPEN, "OPEN"),
            (TokenType.IDENTIFIER, "INPUT"),
            (TokenType.IDENTIFIER, "MY-FILE"),
            (TokenType.NUMERIC_LITERAL, "42"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert stmt.open_mode == "INPUT"
        assert "MY-FILE" in stmt.file_names

    def test_open_with_but_not_reposition(self):
        """WITH followed by non-REPOSITION after files -- lines 95->106 false branch."""
        parser = OpenStatementParser()
        stream = _stream(
            (TokenType.OPEN, "OPEN"),
            (TokenType.IDENTIFIER, "INPUT"),
            (TokenType.IDENTIFIER, "MY-FILE"),
            (TokenType.IDENTIFIER, "WITH"),
            (TokenType.IDENTIFIER, "SOMETHING"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert stmt.open_mode == "INPUT"
        assert "MY-FILE" in stmt.file_names
        assert stmt.with_reposition is False


# =========================================================================
# DISPLAY PARSER TESTS
# =========================================================================


class TestDisplayParserCoverage:
    """Cover uncovered branches in display_parser.py."""

    # -- Full round-trip tests --

    def test_display_multiple_items(self):
        """DISPLAY with multiple items."""
        src = _make_source('           DISPLAY "HELLO" WS-A.\n')
        result = _parse(src)
        assert result.ast is not None
        stmts = result.ast.find_statements("DISPLAY")
        assert len(stmts) >= 1

    def test_display_upon_console_roundtrip(self):
        """DISPLAY item UPON CONSOLE -- round-trip."""
        src = _make_source('           DISPLAY "HELLO" UPON CONSOLE.\n')
        result = _parse(src)
        assert result.ast is not None

    # -- Direct parser tests --

    def test_display_isinstance_check(self):
        """isinstance check for DisplayStatement -- line 85-86."""
        parser = DisplayStatementParser()
        stream = _stream(
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.STRING_LITERAL, "HELLO"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, DisplayStatement)
        assert len(stmt.display_items) >= 1

    def test_display_empty_token_in_loop(self):
        """Empty token in display items loop -- lines 92->139, 95-96."""
        parser = DisplayStatementParser()
        # Stream with DISPLAY and then only EOF
        stream = _stream(
            (TokenType.DISPLAY, "DISPLAY"),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, DisplayStatement)

    def test_display_end_display_terminator(self):
        """END-DISPLAY terminator -- lines 104-106."""
        parser = DisplayStatementParser()
        stream = _stream(
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.STRING_LITERAL, "HELLO"),
            (TokenType.IDENTIFIER, "END-DISPLAY"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, DisplayStatement)
        assert len(stmt.display_items) >= 1

    def test_display_upon_with_device(self):
        """UPON with device token -- lines 109-117."""
        parser = DisplayStatementParser()
        stream = _stream(
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.STRING_LITERAL, "MESSAGE"),
            (TokenType.IDENTIFIER, "UPON"),
            (TokenType.IDENTIFIER, "CONSOLE"),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, DisplayStatement)
        assert stmt.output_device == "CONSOLE"

    def test_display_upon_no_device(self):
        """UPON with no device token -- lines 113-114 (device_token is None)."""
        parser = DisplayStatementParser()
        stream = _stream(
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.STRING_LITERAL, "MESSAGE"),
            (TokenType.IDENTIFIER, "UPON"),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, DisplayStatement)
        # UPON consumed but no device available

    def test_display_is_keyword_no_hasattr(self):
        """_is_keyword with no hasattr -- line 156-157."""
        result = DisplayStatementParser._is_keyword(None, "DISPLAY")
        assert result is False

        # Object without value attribute
        class NoValue:
            type = TokenType.IDENTIFIER

        result = DisplayStatementParser._is_keyword(NoValue(), "DISPLAY")
        assert result is False

    def test_display_unknown_token_stops_parsing(self):
        """Unknown token type stops display item collection -- line 133-135."""
        parser = DisplayStatementParser()
        stream = _stream(
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.STRING_LITERAL, "HELLO"),
            (TokenType.CLOSE, "CLOSE"),  # Non-display token stops parsing
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, DisplayStatement)
        assert len(stmt.display_items) >= 1

    def test_display_numeric_literal(self):
        """DISPLAY with numeric literal item."""
        parser = DisplayStatementParser()
        stream = _stream(
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.NUMERIC_LITERAL, "42"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, DisplayStatement)
        assert "42" in stmt.display_items


# =========================================================================
# EVALUATE PARSER TESTS
# =========================================================================


class TestEvaluateParserCoverage:
    """Cover uncovered branches in evaluate_parser.py."""

    # -- Full round-trip tests --

    def test_evaluate_true_when_other(self):
        """EVALUATE TRUE WHEN ... WHEN OTHER ... END-EVALUATE."""
        src = _make_source(
            "           EVALUATE TRUE\n"
            "               WHEN WS-A = 1\n"
            '                   DISPLAY "ONE"\n'
            "               WHEN OTHER\n"
            '                   DISPLAY "OTHER"\n'
            "           END-EVALUATE.\n"
        )
        result = _parse(src)
        assert result.ast is not None

    def test_evaluate_variable_when_values(self):
        """EVALUATE WS-A WHEN 1 ... WHEN 2 ... END-EVALUATE."""
        src = _make_source(
            "           EVALUATE WS-A\n"
            "               WHEN 1\n"
            '                   DISPLAY "ONE"\n'
            "               WHEN 2\n"
            '                   DISPLAY "TWO"\n'
            "           END-EVALUATE.\n"
        )
        result = _parse(src)
        assert result.ast is not None

    def test_evaluate_also(self):
        """EVALUATE WS-A ALSO WS-B WHEN 1 ALSO 2 ... END-EVALUATE."""
        src = _make_source(
            "           EVALUATE WS-A ALSO WS-B\n"
            "               WHEN 1 ALSO 2\n"
            '                   DISPLAY "MATCH"\n'
            "           END-EVALUATE.\n"
        )
        result = _parse(src)
        assert result.ast is not None

    # -- Direct parser tests --

    def test_evaluate_matches_none_token(self):
        """matches with None token -- line 25-26."""
        parser = EvaluateStatementParser()

        class EmptyStream:
            def peek(self):
                return None

        assert parser.matches(EmptyStream()) is False

    def test_evaluate_matches_exception(self):
        """matches exception path -- lines 34-35."""
        parser = EvaluateStatementParser()

        class BrokenStream:
            def peek(self):
                raise RuntimeError("stream error")

        assert parser.matches(BrokenStream()) is False

    def test_evaluate_matches_identifier(self):
        """matches with EVALUATE as IDENTIFIER -- lines 28-32, 44."""
        parser = EvaluateStatementParser()
        stream = _stream(
            (TokenType.IDENTIFIER, "EVALUATE"),
        )
        assert parser.matches(stream) is True

    def test_evaluate_matches_non_evaluate_identifier(self):
        """matches with non-EVALUATE identifier -- returns False."""
        parser = EvaluateStatementParser()
        stream = _stream(
            (TokenType.IDENTIFIER, "SOMETHING"),
        )
        assert parser.matches(stream) is False

    def test_evaluate_empty_condition(self):
        """EVALUATE with immediate END-EVALUATE (no WHEN) -- line 63 break."""
        parser = EvaluateStatementParser()
        stream = _stream(
            (TokenType.EVALUATE, "EVALUATE"),
            (TokenType.IDENTIFIER, "TRUE"),
            (TokenType.IDENTIFIER, "END-EVALUATE"),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, EvaluateStatement)

    def test_evaluate_when_other_direct(self):
        """WHEN OTHER clause -- lines 83-88, 96, 158-159."""
        parser = EvaluateStatementParser()
        stream = _stream(
            (TokenType.EVALUATE, "EVALUATE"),
            (TokenType.IDENTIFIER, "TRUE"),
            (TokenType.IDENTIFIER, "WHEN"),
            (TokenType.IDENTIFIER, "OTHER"),
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.STRING_LITERAL, "DEFAULT"),
            (TokenType.PERIOD, "."),
            (TokenType.IDENTIFIER, "END-EVALUATE"),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, EvaluateStatement)
        assert stmt.default_when is not None

    def test_evaluate_when_with_selector(self):
        """WHEN clause with literal selector -- lines 114-141."""
        parser = EvaluateStatementParser()
        stream = _stream(
            (TokenType.EVALUATE, "EVALUATE"),
            (TokenType.IDENTIFIER, "WS-A"),
            (TokenType.IDENTIFIER, "WHEN"),
            (TokenType.NUMERIC_LITERAL, "1"),
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.STRING_LITERAL, "ONE"),
            (TokenType.PERIOD, "."),
            (TokenType.IDENTIFIER, "END-EVALUATE"),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, EvaluateStatement)
        assert len(stmt.when_clauses) >= 1

    def test_evaluate_when_also_selector(self):
        """WHEN clause with ALSO -- lines 219-231."""
        parser = EvaluateStatementParser()
        stream = _stream(
            (TokenType.EVALUATE, "EVALUATE"),
            (TokenType.IDENTIFIER, "WS-A"),
            (TokenType.IDENTIFIER, "ALSO"),
            (TokenType.IDENTIFIER, "WS-B"),
            (TokenType.IDENTIFIER, "WHEN"),
            (TokenType.NUMERIC_LITERAL, "1"),
            (TokenType.IDENTIFIER, "ALSO"),
            (TokenType.NUMERIC_LITERAL, "2"),
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.STRING_LITERAL, "MATCH"),
            (TokenType.PERIOD, "."),
            (TokenType.IDENTIFIER, "END-EVALUATE"),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, EvaluateStatement)
        assert len(stmt.subjects) == 2

    def test_evaluate_no_end_evaluate(self):
        """EVALUATE without END-EVALUATE -- line 150-155."""
        parser = EvaluateStatementParser()
        stream = _stream(
            (TokenType.EVALUATE, "EVALUATE"),
            (TokenType.IDENTIFIER, "TRUE"),
            (TokenType.IDENTIFIER, "WHEN"),
            (TokenType.NUMERIC_LITERAL, "1"),
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.STRING_LITERAL, "ONE"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, EvaluateStatement)

    def test_evaluate_no_when_clause(self):
        """EVALUATE with no WHEN clause -- lines 143-148."""
        parser = EvaluateStatementParser()
        stream = _stream(
            (TokenType.EVALUATE, "EVALUATE"),
            (TokenType.IDENTIFIER, "TRUE"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, EvaluateStatement)

    def test_evaluate_multiple_when_clauses(self):
        """Multiple WHEN clauses -- WHEN loop lines 60-141."""
        parser = EvaluateStatementParser()
        stream = _stream(
            (TokenType.EVALUATE, "EVALUATE"),
            (TokenType.IDENTIFIER, "WS-A"),
            (TokenType.IDENTIFIER, "WHEN"),
            (TokenType.NUMERIC_LITERAL, "1"),
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.STRING_LITERAL, "ONE"),
            (TokenType.PERIOD, "."),
            (TokenType.IDENTIFIER, "WHEN"),
            (TokenType.NUMERIC_LITERAL, "2"),
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.STRING_LITERAL, "TWO"),
            (TokenType.PERIOD, "."),
            (TokenType.IDENTIFIER, "END-EVALUATE"),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, EvaluateStatement)
        assert len(stmt.when_clauses) >= 2

    def test_evaluate_when_any_selector(self):
        """WHEN ANY selector."""
        parser = EvaluateStatementParser()
        stream = _stream(
            (TokenType.EVALUATE, "EVALUATE"),
            (TokenType.IDENTIFIER, "WS-A"),
            (TokenType.IDENTIFIER, "WHEN"),
            (TokenType.IDENTIFIER, "ANY"),
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.STRING_LITERAL, "ANYTHING"),
            (TokenType.PERIOD, "."),
            (TokenType.IDENTIFIER, "END-EVALUATE"),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, EvaluateStatement)
        assert len(stmt.when_clauses) >= 1

    def test_evaluate_when_thru_range(self):
        """WHEN with THRU range selector."""
        parser = EvaluateStatementParser()
        stream = _stream(
            (TokenType.EVALUATE, "EVALUATE"),
            (TokenType.IDENTIFIER, "WS-A"),
            (TokenType.IDENTIFIER, "WHEN"),
            (TokenType.NUMERIC_LITERAL, "1"),
            (TokenType.IDENTIFIER, "THRU"),
            (TokenType.NUMERIC_LITERAL, "10"),
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.STRING_LITERAL, "RANGE"),
            (TokenType.PERIOD, "."),
            (TokenType.IDENTIFIER, "END-EVALUATE"),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, EvaluateStatement)
        assert len(stmt.when_clauses) >= 1

    def test_evaluate_subject_with_also(self):
        """Multiple subjects using ALSO -- lines 176-191."""
        parser = EvaluateStatementParser()
        stream = _stream(
            (TokenType.EVALUATE, "EVALUATE"),
            (TokenType.IDENTIFIER, "WS-A"),
            (TokenType.IDENTIFIER, "ALSO"),
            (TokenType.IDENTIFIER, "WS-B"),
            (TokenType.IDENTIFIER, "ALSO"),
            (TokenType.IDENTIFIER, "WS-DATE"),
            (TokenType.IDENTIFIER, "WHEN"),
            (TokenType.NUMERIC_LITERAL, "1"),
            (TokenType.IDENTIFIER, "ALSO"),
            (TokenType.NUMERIC_LITERAL, "2"),
            (TokenType.IDENTIFIER, "ALSO"),
            (TokenType.NUMERIC_LITERAL, "3"),
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.STRING_LITERAL, "MATCH"),
            (TokenType.PERIOD, "."),
            (TokenType.IDENTIFIER, "END-EVALUATE"),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, EvaluateStatement)
        assert len(stmt.subjects) == 3

    def test_evaluate_empty_stream_after_evaluate(self):
        """Empty stream right after EVALUATE token -- line 169 break."""
        parser = EvaluateStatementParser()
        stream = _stream(
            (TokenType.EVALUATE, "EVALUATE"),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, EvaluateStatement)

    def test_evaluate_consecutive_also_in_selector(self):
        """Consecutive ALSO keywords in selector -- lines 220-221 issue."""
        parser = EvaluateStatementParser()
        stream = _stream(
            (TokenType.EVALUATE, "EVALUATE"),
            (TokenType.IDENTIFIER, "WS-A"),
            (TokenType.IDENTIFIER, "ALSO"),
            (TokenType.IDENTIFIER, "WS-B"),
            (TokenType.IDENTIFIER, "WHEN"),
            (TokenType.NUMERIC_LITERAL, "1"),
            (TokenType.IDENTIFIER, "ALSO"),
            (TokenType.IDENTIFIER, "ALSO"),  # Consecutive ALSO
            (TokenType.NUMERIC_LITERAL, "2"),
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.STRING_LITERAL, "X"),
            (TokenType.PERIOD, "."),
            (TokenType.IDENTIFIER, "END-EVALUATE"),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, EvaluateStatement)

    def test_evaluate_condition_with_or(self):
        """WHEN clause with OR condition."""
        parser = EvaluateStatementParser()
        stream = _stream(
            (TokenType.EVALUATE, "EVALUATE"),
            (TokenType.IDENTIFIER, "TRUE"),
            (TokenType.IDENTIFIER, "WHEN"),
            (TokenType.IDENTIFIER, "WS-A"),
            (TokenType.IDENTIFIER, "="),
            (TokenType.NUMERIC_LITERAL, "1"),
            (TokenType.IDENTIFIER, "OR"),
            (TokenType.IDENTIFIER, "WS-A"),
            (TokenType.IDENTIFIER, "="),
            (TokenType.NUMERIC_LITERAL, "2"),
            (TokenType.DISPLAY, "DISPLAY"),
            (TokenType.STRING_LITERAL, "HIT"),
            (TokenType.PERIOD, "."),
            (TokenType.IDENTIFIER, "END-EVALUATE"),
        )
        stmt = parser.parse(stream)
        assert isinstance(stmt, EvaluateStatement)
        assert len(stmt.when_clauses) >= 1


# =========================================================================
# ACCEPT PARSER TESTS
# =========================================================================


class TestAcceptParserCoverage:
    """Cover uncovered branches in accept_parser.py."""

    # -- Full round-trip tests --

    def test_accept_simple(self):
        """ACCEPT WS-DATE -- baseline."""
        src = _make_source("           ACCEPT WS-DATE.\n")
        result = _parse(src)
        assert result.ast is not None

    def test_accept_from_date(self):
        """ACCEPT WS-DATE FROM DATE."""
        src = _make_source("           ACCEPT WS-DATE FROM DATE.\n")
        result = _parse(src)
        assert result.ast is not None

    def test_accept_from_time(self):
        """ACCEPT WS-TIME FROM TIME."""
        src = _make_source("           ACCEPT WS-TIME FROM TIME.\n")
        result = _parse(src)
        assert result.ast is not None

    # -- Direct parser tests --

    def test_accept_matches_none_token(self):
        """matches with None token -- line 23-24."""
        parser = AcceptStatementParser()

        class EmptyStream:
            def peek(self):
                return None

        assert parser.matches(EmptyStream()) is False

    def test_accept_matches_identifier(self):
        """matches with ACCEPT as IDENTIFIER -- lines 27-30, 41."""
        parser = AcceptStatementParser()
        stream = _stream(
            (TokenType.IDENTIFIER, "ACCEPT"),
        )
        assert parser.matches(stream) is True

    def test_accept_matches_non_accept_identifier(self):
        """matches with non-ACCEPT identifier -- returns False."""
        parser = AcceptStatementParser()
        stream = _stream(
            (TokenType.IDENTIFIER, "SOMETHING"),
        )
        assert parser.matches(stream) is False

    def test_accept_empty_stream_after_accept(self):
        """Empty stream after ACCEPT -- lines 45-46 (token is None/period)."""
        parser = AcceptStatementParser()
        stream = _stream(
            (TokenType.ACCEPT, "ACCEPT"),
        )
        stmt = parser.parse(stream)
        assert stmt is not None
        # EOF token gets consumed as target (empty value)
        assert stmt.target is not None

    def test_accept_period_immediately_after_accept(self):
        """Period immediately after ACCEPT -- line 46 (not in set)."""
        parser = AcceptStatementParser()
        stream = _stream(
            (TokenType.ACCEPT, "ACCEPT"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert stmt is not None
        assert stmt.target is None

    def test_accept_from_clause_with_identifier(self):
        """ACCEPT target FROM source -- lines 52-64."""
        parser = AcceptStatementParser()
        stream = _stream(
            (TokenType.ACCEPT, "ACCEPT"),
            (TokenType.IDENTIFIER, "WS-DATE"),
            (TokenType.FROM, "FROM"),
            (TokenType.IDENTIFIER, "DATE"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert stmt.target == "WS-DATE"
        assert stmt.from_source == "DATE"

    def test_accept_from_time_direct(self):
        """ACCEPT target FROM TIME -- lines 62-64 (direct parser)."""
        parser = AcceptStatementParser()
        stream = _stream(
            (TokenType.ACCEPT, "ACCEPT"),
            (TokenType.IDENTIFIER, "WS-TIME"),
            (TokenType.FROM, "FROM"),
            (TokenType.IDENTIFIER, "TIME"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert stmt.target == "WS-TIME"
        assert stmt.from_source == "TIME"

    def test_accept_from_console(self):
        """ACCEPT target FROM CONSOLE -- device source."""
        parser = AcceptStatementParser()
        stream = _stream(
            (TokenType.ACCEPT, "ACCEPT"),
            (TokenType.IDENTIFIER, "WS-DATE"),
            (TokenType.FROM, "FROM"),
            (TokenType.IDENTIFIER, "CONSOLE"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert stmt.target == "WS-DATE"
        assert stmt.from_source == "CONSOLE"

    def test_accept_from_as_identifier(self):
        """ACCEPT with FROM as IDENTIFIER token -- line 56."""
        parser = AcceptStatementParser()
        stream = _stream(
            (TokenType.ACCEPT, "ACCEPT"),
            (TokenType.IDENTIFIER, "WS-DATE"),
            (TokenType.IDENTIFIER, "FROM"),
            (TokenType.IDENTIFIER, "DATE"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert stmt.target == "WS-DATE"
        assert stmt.from_source == "DATE"

    def test_accept_from_then_period(self):
        """ACCEPT target FROM then period -- lines 62->66 (src is period)."""
        parser = AcceptStatementParser()
        stream = _stream(
            (TokenType.ACCEPT, "ACCEPT"),
            (TokenType.IDENTIFIER, "WS-DATE"),
            (TokenType.FROM, "FROM"),
            (TokenType.PERIOD, "."),
        )
        stmt = parser.parse(stream)
        assert stmt.target == "WS-DATE"
        assert stmt.from_source is None

    def test_accept_no_period_at_end(self):
        """ACCEPT without trailing period -- lines 69-72."""
        parser = AcceptStatementParser()
        stream = _stream(
            (TokenType.ACCEPT, "ACCEPT"),
            (TokenType.IDENTIFIER, "WS-DATE"),
        )
        stmt = parser.parse(stream)
        assert stmt.target == "WS-DATE"
