"""Unit tests for the statement parsers added by the 2026-09-02 statement-
coverage audit: Report Writer (INITIATE / TERMINATE / SUPPRESS), the
COBOL-85 Communication Module (SEND / RECEIVE / ENABLE / DISABLE / PURGE),
OS/VS and dialect legacy verbs (EXHIBIT / EXAMINE / TRANSFORM / ENTER /
NOTE / CHAIN), IBM compiler-directing statements (READY TRACE / RESET TRACE
/ SERVICE LABEL / SERVICE RELOAD / TITLE) and COBOL 2002 exception handling
(RAISE / RESUME / VALIDATE).

Before this audit every one of these verbs reached the PROCEDURE DIVISION's
"unsupported statement" path: an ``errors=0`` parse with the statement
discarded from the AST. Each case here asserts three things -- the verb
produces its own node, its operands are captured, and the parse emits no
warning at all.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.models.statements import (
    ChainStatement,
    DisableStatement,
    EnableStatement,
    EnterStatement,
    ExamineStatement,
    ExhibitStatement,
    InitiateStatement,
    NoteStatement,
    PurgeStatement,
    RaiseStatement,
    ReceiveStatement,
    ResumeStatement,
    SendStatement,
    ServiceStatement,
    SuppressStatement,
    TerminateStatement,
    TitleStatement,
    TraceStatement,
    TransformStatement,
    ValidateStatement,
)
from cobolparser.parsers.divisions.procedure_registry import create_statement_registry

_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXTVERBS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A               PIC X(10).
       01  WS-B               PIC X(10).
       01  WS-N               PIC 9(4).
       01  WS-T.
           05 WS-E OCCURS 3 TIMES PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
"""


def _parse(*lines: str):
    body = "".join(f"           {line}\n" for line in lines)
    return parse_cobol(_HEADER + body + "           STOP RUN.\n")


def _first(result, cls):
    result_statements = result.ast.get_division("PROCEDURE").paragraphs[0].statements
    matches = [s for s in result_statements if isinstance(s, cls)]
    assert matches, [type(s).__name__ for s in result_statements]
    return matches[0]


def _clean(result):
    assert result.errors == [], result.errors
    assert result.warnings == [], result.warnings


# ---------------------------------------------------------------------------
# Report Writer
# ---------------------------------------------------------------------------


class TestReportWriterVerbs:
    def test_initiate_single_and_multiple_reports(self):
        result = _parse("INITIATE SALES-REPORT.", "INITIATE RPT-A RPT-B.")
        _clean(result)
        stmts = [
            s
            for s in result.ast.get_division("PROCEDURE").paragraphs[0].statements
            if isinstance(s, InitiateStatement)
        ]
        assert [s.report_names for s in stmts] == [["SALES-REPORT"], ["RPT-A", "RPT-B"]]
        assert stmts[1].to_dict()["report_names"] == ["RPT-A", "RPT-B"]
        assert stmts[1].operands == ["RPT-A", "RPT-B"]

    def test_terminate(self):
        result = _parse("TERMINATE SALES-REPORT.")
        _clean(result)
        stmt = _first(result, TerminateStatement)
        assert stmt.statement_type == "TERMINATE"
        assert stmt.report_names == ["SALES-REPORT"]

    @pytest.mark.parametrize(
        "source,printing", [("SUPPRESS.", False), ("SUPPRESS PRINTING.", True)]
    )
    def test_suppress(self, source, printing):
        result = _parse(source)
        _clean(result)
        stmt = _first(result, SuppressStatement)
        assert stmt.printing is printing
        assert stmt.to_dict()["printing"] is printing

    def test_report_writer_sample_program_keeps_initiate_and_terminate(self):
        """tests/samples/report_writer.cbl lost both verbs before this audit."""
        source = open("tests/samples/report_writer.cbl", encoding="utf-8").read()
        result = parse_cobol(source)
        types = [type(s).__name__ for s in result.ast.get_all_statements()]
        assert "InitiateStatement" in types
        assert "TerminateStatement" in types
        assert not any("INITIATE" in w or "TERMINATE" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Communication Module
# ---------------------------------------------------------------------------


class TestCommunicationVerbs:
    def test_send_full_form(self):
        result = _parse(
            "SEND CM-OUTQUE-1 FROM MSG-70 WITH EMI",
            "    AFTER ADVANCING 2 LINES REPLACING LINE.",
        )
        _clean(result)
        stmt = _first(result, SendStatement)
        d = stmt.to_dict()
        assert d["cd_name"] == "CM-OUTQUE-1"
        assert d["from_identifier"] == "MSG-70"
        assert d["indicator"] == "EMI"
        assert d["advancing_mode"] == "AFTER"
        assert d["advancing_value"] == "2"
        assert d["advancing_unit"] == "LINES"
        assert d["replacing_line"] is True
        assert stmt.operands == ["CM-OUTQUE-1", "MSG-70"]

    def test_send_before_advancing_page_and_identifier_indicator(self):
        result = _parse("SEND CM-OUTQUE-1 FROM MSG-70 WITH WS-A BEFORE ADVANCING PAGE.")
        _clean(result)
        stmt = _first(result, SendStatement)
        assert stmt.indicator == "WS-A"
        assert stmt.advancing_mode == "BEFORE"
        assert stmt.advancing_value == "PAGE"
        assert "WS-A" in stmt.operands

    def test_receive_with_no_data_and_with_data_handlers(self):
        result = _parse(
            "RECEIVE CM-INQUE-1 MESSAGE INTO INCOMING-MSG",
            "    NO DATA MOVE 'N' TO WS-A",
            "    WITH DATA MOVE 'Y' TO WS-A",
            "END-RECEIVE.",
        )
        _clean(result)
        stmt = _first(result, ReceiveStatement)
        assert stmt.cd_name == "CM-INQUE-1"
        assert stmt.mode == "MESSAGE"
        assert stmt.into_target == "INCOMING-MSG"
        assert [type(s).__name__ for s in stmt.no_data_clause] == ["MoveStatement"]
        assert [type(s).__name__ for s in stmt.with_data_clause] == ["MoveStatement"]
        # handler bodies are children, so the generic walk sees them
        nested = [
            s
            for s in result.ast.get_all_statements()
            if type(s).__name__ == "MoveStatement"
        ]
        assert len(nested) == 2
        d = stmt.to_dict()
        assert len(d["no_data_clause"]) == 1 and len(d["with_data_clause"]) == 1

    def test_receive_segment_period_terminated_with_go_to_in_handler(self):
        """NIST CM101M: ``NO DATA PERFORM ... GO TO ...`` ends at the period."""
        result = _parse(
            "RECEIVE CM-INQUE-1 SEGMENT INTO INCOMING-MSG",
            "    NO DATA PERFORM INCREMENT-POLL-COUNT GO TO LOG-MSG.",
            "MOVE 'X' TO WS-A.",
        )
        _clean(result)
        stmt = _first(result, ReceiveStatement)
        assert stmt.mode == "SEGMENT"
        assert [type(s).__name__ for s in stmt.no_data_clause] == [
            "PerformStatement",
            "GoStatement",
        ]
        top = [
            type(s).__name__
            for s in result.ast.get_division("PROCEDURE").paragraphs[0].statements
        ]
        assert top == ["ReceiveStatement", "MoveStatement", "StopStatement"]

    @pytest.mark.parametrize(
        "source,cls,mode,key",
        [
            (
                "ENABLE INPUT CM-INQUE-1 WITH KEY 'PASSWORD'.",
                EnableStatement,
                "INPUT",
                '"PASSWORD"',
            ),
            (
                "ENABLE INPUT TERMINAL CM-INQUE-1.",
                EnableStatement,
                "INPUT TERMINAL",
                None,
            ),
            (
                "DISABLE OUTPUT CM-OUTQUE-1 KEY WS-A.",
                DisableStatement,
                "OUTPUT",
                "WS-A",
            ),
            (
                "DISABLE I-O TERMINAL CM-INQUE-1.",
                DisableStatement,
                "I-O TERMINAL",
                None,
            ),
        ],
    )
    def test_enable_disable(self, source, cls, mode, key):
        result = _parse(source)
        _clean(result)
        stmt = _first(result, cls)
        assert stmt.mode == mode
        assert stmt.cd_name in ("CM-INQUE-1", "CM-OUTQUE-1")
        assert stmt.key == key
        assert stmt.to_dict()["mode"] == mode

    def test_purge(self):
        result = _parse("PURGE CM-OUTQUE-1.")
        _clean(result)
        stmt = _first(result, PurgeStatement)
        assert stmt.cd_name == "CM-OUTQUE-1"
        assert stmt.operands == ["CM-OUTQUE-1"]

    def test_nist_cm101m_has_no_unsupported_statement_warnings(self):
        source = open(
            "examples/cobol/CM101M.CBL", encoding="utf-8", errors="replace"
        ).read()
        result = parse_cobol(source)
        assert not any(
            "Unsupported statement" in w for w in result.warnings
        ), result.warnings
        assert not any("Unparsed tokens" in w for w in result.warnings), result.warnings
        types = {type(s).__name__ for s in result.ast.get_all_statements()}
        assert {"EnableStatement", "DisableStatement", "ReceiveStatement"} <= types
        source = open(
            "examples/cobol/CM102M.CBL", encoding="utf-8", errors="replace"
        ).read()
        result = parse_cobol(source)
        assert not any(
            "Unsupported statement" in w for w in result.warnings
        ), result.warnings
        assert "SendStatement" in {
            type(s).__name__ for s in result.ast.get_all_statements()
        }


# ---------------------------------------------------------------------------
# Legacy / dialect verbs
# ---------------------------------------------------------------------------


class TestLegacyVerbs:
    @pytest.mark.parametrize(
        "source,mode,items",
        [
            ("EXHIBIT WS-A WS-B.", None, ["WS-A", "WS-B"]),
            ("EXHIBIT NAMED WS-A.", "NAMED", ["WS-A"]),
            ("EXHIBIT CHANGED NAMED WS-A 'LIT'.", "CHANGED NAMED", ["WS-A", '"LIT"']),
            ("EXHIBIT CHANGED WS-E (2).", "CHANGED", ["WS-E ( 2 )"]),
        ],
    )
    def test_exhibit(self, source, mode, items):
        result = _parse(source)
        _clean(result)
        stmt = _first(result, ExhibitStatement)
        assert stmt.mode == mode
        assert stmt.items == items

    def test_examine_tallying_with_replacing(self):
        result = _parse("EXAMINE WS-A TALLYING ALL 'A' REPLACING BY 'B'.")
        _clean(result)
        stmt = _first(result, ExamineStatement)
        d = stmt.to_dict()
        assert d["target"] == "WS-A"
        assert d["action"] == "TALLYING"
        assert d["mode"] == "ALL"
        assert d["search_value"] == '"A"'
        assert d["replacing_value"] == '"B"'

    def test_examine_replacing_until_first(self):
        result = _parse("EXAMINE WS-A REPLACING UNTIL FIRST ' ' BY '0'.")
        _clean(result)
        stmt = _first(result, ExamineStatement)
        assert stmt.action == "REPLACING"
        assert stmt.mode == "UNTIL FIRST"
        assert stmt.search_value == '" "'
        assert stmt.replacing_value == '"0"'

    def test_transform(self):
        result = _parse("TRANSFORM WS-A CHARACTERS FROM 'abc' TO 'ABC'.")
        _clean(result)
        stmt = _first(result, TransformStatement)
        assert stmt.target == "WS-A"
        assert stmt.from_value == '"abc"'
        assert stmt.to_value == '"ABC"'

    def test_enter(self):
        result = _parse("ENTER COBOL.", "ENTER LINKAGE MYROUTINE.")
        _clean(result)
        stmts = [
            s
            for s in result.ast.get_division("PROCEDURE").paragraphs[0].statements
            if isinstance(s, EnterStatement)
        ]
        assert (stmts[0].language, stmts[0].routine) == ("COBOL", None)
        assert (stmts[1].language, stmts[1].routine) == ("LINKAGE", "MYROUTINE")

    def test_note_swallows_text_up_to_period_only(self):
        result = _parse(
            "NOTE THIS PARAGRAPH MOVES A TO B, THEN STOPS.",
            "MOVE WS-A TO WS-B.",
        )
        _clean(result)
        stmt = _first(result, NoteStatement)
        assert stmt.text.startswith("THIS PARAGRAPH MOVES A TO B")
        top = [
            type(s).__name__
            for s in result.ast.get_division("PROCEDURE").paragraphs[0].statements
        ]
        assert top == ["NoteStatement", "MoveStatement", "StopStatement"]

    @pytest.mark.parametrize(
        "source,program,is_dynamic,params",
        [
            ("CHAIN 'NEXTPROG'.", '"NEXTPROG"', False, []),
            ("CHAIN WS-A USING WS-B WS-N.", "WS-A", True, ["WS-B", "WS-N"]),
        ],
    )
    def test_chain(self, source, program, is_dynamic, params):
        result = _parse(source)
        _clean(result)
        stmt = _first(result, ChainStatement)
        assert stmt.program == program
        assert stmt.is_dynamic is is_dynamic
        assert stmt.using_parameters == params


# ---------------------------------------------------------------------------
# IBM compiler-directing / debugging statements
# ---------------------------------------------------------------------------


class TestCompilerDirectingStatements:
    @pytest.mark.parametrize(
        "source,action", [("READY TRACE.", "READY"), ("RESET TRACE.", "RESET")]
    )
    def test_trace(self, source, action):
        result = _parse(source)
        _clean(result)
        stmt = _first(result, TraceStatement)
        assert stmt.action == action
        assert stmt.to_dict()["action"] == action

    def test_ready_without_trace_is_not_claimed(self):
        # RESET also appears in Report Writer SUM ... RESET ON; only the
        # two-word form is a statement.
        registry = create_statement_registry()
        from cobolparser.core.token_stream import TokenStream
        from cobolparser.lexer import Token, TokenType
        from cobolparser.models.ast_base import SourceLocation

        stream = TokenStream(
            [
                Token(TokenType.RESET, "RESET", SourceLocation(1, 1)),
                Token(TokenType.IDENTIFIER, "WS-A", SourceLocation(1, 7)),
            ]
        )
        assert registry.find_parser(stream) is None

    @pytest.mark.parametrize(
        "source,kind,operand",
        [("SERVICE LABEL.", "LABEL", None), ("SERVICE RELOAD WS-A.", "RELOAD", "WS-A")],
    )
    def test_service(self, source, kind, operand):
        result = _parse(source)
        _clean(result)
        stmt = _first(result, ServiceStatement)
        assert stmt.kind == kind
        assert stmt.operand == operand

    def test_title(self):
        result = _parse("TITLE 'Payroll listing'.", "MOVE WS-A TO WS-B.")
        _clean(result)
        stmt = _first(result, TitleStatement)
        assert stmt.title == "Payroll listing"

    def test_title_as_data_name_is_left_alone(self):
        # TITLE is not reserved outside IBM; the parser only claims it when a
        # literal follows, so ``MOVE X TO TITLE`` still parses as a MOVE.
        result = _parse("MOVE WS-A TO TITLE.")
        _clean(result)
        top = [
            type(s).__name__
            for s in result.ast.get_division("PROCEDURE").paragraphs[0].statements
        ]
        assert top == ["MoveStatement", "StopStatement"]


# ---------------------------------------------------------------------------
# COBOL 2002
# ---------------------------------------------------------------------------


class TestCobol2002Verbs:
    def test_raise_exception_name(self):
        result = _parse("RAISE EXCEPTION EC-BOUND-SUBSCRIPT.")
        _clean(result)
        stmt = _first(result, RaiseStatement)
        assert stmt.raise_type == "EXCEPTION"
        assert stmt.target == "EC-BOUND-SUBSCRIPT"
        assert stmt.operands == []

    def test_raise_identifier(self):
        result = _parse("RAISE WS-A.")
        _clean(result)
        stmt = _first(result, RaiseStatement)
        assert stmt.raise_type == "IDENTIFIER"
        assert stmt.target == "WS-A"
        assert stmt.operands == ["WS-A"]

    @pytest.mark.parametrize(
        "source,target,next_stmt",
        [
            ("RESUME NEXT STATEMENT.", "NEXT STATEMENT", True),
            ("RESUME AT NEXT STATEMENT.", "NEXT STATEMENT", True),
            ("RESUME AT MAIN-PARA.", "MAIN-PARA", False),
            ("RESUME MAIN-PARA.", "MAIN-PARA", False),
        ],
    )
    def test_resume(self, source, target, next_stmt):
        result = _parse(source)
        _clean(result)
        stmt = _first(result, ResumeStatement)
        assert stmt.target == target
        assert stmt.resumes_next_statement is next_stmt

    def test_validate(self):
        result = _parse("VALIDATE WS-A WS-B.")
        _clean(result)
        stmt = _first(result, ValidateStatement)
        assert stmt.targets == ["WS-A", "WS-B"]

    def test_validate_paragraph_name_is_not_claimed(self):
        # VALIDATE is not reserved by IBM Enterprise COBOL: a paragraph named
        # VALIDATE must still be a paragraph.
        result = parse_cobol(
            _HEADER
            + "           PERFORM VALIDATE.\n"
            + "           STOP RUN.\n"
            + "       VALIDATE.\n"
            + "           MOVE WS-A TO WS-B.\n"
        )
        _clean(result)
        names = [
            p.paragraph_name for p in result.ast.get_division("PROCEDURE").paragraphs
        ]
        assert names == ["MAIN-PARA", "VALIDATE"]


# ---------------------------------------------------------------------------
# Registry / recovery invariants
# ---------------------------------------------------------------------------


class TestNoRealVerbIsUnsupported:
    def test_unsupported_verb_list_only_holds_non_verbs(self):
        from cobolparser.parsers.divisions.procedure_recovery import UNSUPPORTED_VERBS

        assert UNSUPPORTED_VERBS == frozenset({"EXECUTE", "GOTO", "RECOVER"})

    def test_every_statement_keyword_with_a_verb_dispatches(self):
        """Every entry of STATEMENT_KEYWORDS that names a real verb must have
        a parser claiming it -- the three non-verbs are the only exceptions."""
        from cobolparser.core.token_stream import TokenStream
        from cobolparser.lexer import CobolLexer
        from cobolparser.parsers.statements._utils import STATEMENT_KEYWORDS

        registry = create_statement_registry()
        two_word = {
            "READY": "READY TRACE",
            "RESET": "RESET TRACE",
            "SERVICE": "SERVICE LABEL",
            "NEXT": "NEXT SENTENCE",
            "EXEC": "EXEC SQL SELECT 1 END-EXEC",
            "XML": "XML GENERATE A FROM B",
            "JSON": "JSON GENERATE A FROM B",
            "GO": "GO TO X",
        }
        unclaimed = []
        for word in sorted(STATEMENT_KEYWORDS):
            if word in {"EXECUTE", "GOTO", "RECOVER"}:
                continue
            text = two_word.get(word, f"{word} WS-A")
            tokens = CobolLexer("       " + text).tokenize()
            if registry.find_parser(TokenStream(tokens)) is None:
                unclaimed.append(word)
        assert unclaimed == []
