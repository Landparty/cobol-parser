"""XML/JSON GENERATE/PARSE: structured PROCESSING PROCEDURE fields and real
[ON] EXCEPTION / NOT [ON] EXCEPTION handler bodies (2026-09-02).

Before this, `XmlJsonStatement` flattened its exception-handler bodies into
`clause_text`, so a CALL/file-op/EXEC inside `XML PARSE ... ON EXCEPTION`
never became an AST statement at all -- invisible to `get_all_statements()`
and to every consumer walking nested clause bodies (mocky-mock's fail-closed
boundary gate among them). `PROCESSING PROCEDURE` was likewise only text,
so the implicit PERFORM edge it represents could not be followed.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.models.statements import (
    CallStatement,
    DisplayStatement,
    XmlJsonStatement,
)

_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. XMLCL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DOC              PIC X(200).
       01  WS-OUT              PIC X(200).
       01  WS-N                PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
"""

_TAIL = """\
       HANDLE-XML.
           CALL "XMLSUB" USING WS-DOC.
       HANDLE-XML-END.
           EXIT.
"""


def _main_statements(body: str):
    result = parse_cobol(_HEADER + body + _TAIL, filename="xmlcl.cbl")
    assert result.success, result.errors
    assert not result.warnings, result.warnings
    return result, result.ast.get_division("PROCEDURE").paragraphs[0].statements


def test_processing_procedure_with_thru_is_captured():
    _, stmts = _main_statements(
        "           XML PARSE WS-DOC WITH ENCODING 1208\n"
        "               PROCESSING PROCEDURE IS HANDLE-XML THRU HANDLE-XML-END\n"
        "           END-XML.\n"
    )
    node = stmts[0]
    assert isinstance(node, XmlJsonStatement)
    assert node.action == "PARSE"
    assert node.processing_procedure == "HANDLE-XML"
    assert node.processing_procedure_thru == "HANDLE-XML-END"
    # the text is still preserved verbatim for consumers reading clause_text
    assert node.clause_text == (
        "WITH ENCODING 1208 PROCESSING PROCEDURE IS HANDLE-XML THRU HANDLE-XML-END"
    )
    d = node.to_dict()
    assert d["processing_procedure"] == "HANDLE-XML"
    assert d["processing_procedure_thru"] == "HANDLE-XML-END"


def test_processing_procedure_without_is_or_thru():
    _, stmts = _main_statements(
        "           XML PARSE WS-DOC PROCESSING PROCEDURE HANDLE-XML.\n"
    )
    node = stmts[0]
    assert node.processing_procedure == "HANDLE-XML"
    assert node.processing_procedure_thru is None
    assert node.clause_text == "PROCESSING PROCEDURE HANDLE-XML"


def test_exception_handler_bodies_are_real_statements():
    result, stmts = _main_statements(
        "           XML PARSE WS-DOC PROCESSING PROCEDURE HANDLE-XML\n"
        "             ON EXCEPTION\n"
        '               CALL "ERRSUB" USING WS-DOC\n'
        '               DISPLAY "bad xml"\n'
        "             NOT ON EXCEPTION\n"
        '               DISPLAY "ok"\n'
        "           END-XML.\n"
        '           DISPLAY "after".\n'
    )
    node = stmts[0]
    assert isinstance(node, XmlJsonStatement)
    assert [type(s) for s in node.on_exception] == [CallStatement, DisplayStatement]
    assert node.on_exception[0].called_program == "ERRSUB"
    assert [type(s) for s in node.not_on_exception] == [DisplayStatement]
    # the handler bodies did not escape into the paragraph
    assert isinstance(stmts[1], DisplayStatement)
    assert len(stmts) == 2
    # and the nested CALL is visible to the whole-tree walk
    calls = [s for s in result.ast.get_all_statements() if isinstance(s, CallStatement)]
    assert {c.called_program for c in calls} == {"ERRSUB", "XMLSUB"}
    d = node.to_dict()
    assert [s["statement_type"] for s in d["on_exception"]] == ["CALL", "DISPLAY"]
    assert [s["statement_type"] for s in d["not_on_exception"]] == ["DISPLAY"]


def test_bare_exception_keyword_and_json_forms():
    _, stmts = _main_statements(
        "           XML GENERATE WS-OUT FROM WS-N COUNT IN WS-N\n"
        "               SUPPRESS WHEN SPACES\n"
        "             EXCEPTION MOVE 1 TO WS-N\n"
        "           END-XML.\n"
        "           JSON PARSE WS-DOC INTO WS-N\n"
        '               ON EXCEPTION DISPLAY "bad json".\n'
        "           JSON GENERATE WS-OUT FROM WS-N.\n"
    )
    xml_gen, json_parse, json_gen = stmts
    assert xml_gen.clause_text == "COUNT IN WS-N SUPPRESS WHEN SPACES"
    assert [s.statement_type for s in xml_gen.on_exception] == ["MOVE"]
    assert json_parse.clause_text == "INTO WS-N"
    assert [s.statement_type for s in json_parse.on_exception] == ["DISPLAY"]
    assert json_gen.on_exception is None
    assert json_gen.not_on_exception is None
    assert "on_exception" not in json_gen.to_dict()  # omit_empty


def test_nested_inside_if_stops_at_end_json():
    _, stmts = _main_statements(
        "           IF WS-N = 1\n"
        "              JSON GENERATE WS-OUT FROM WS-N\n"
        '                 ON EXCEPTION DISPLAY "bad"\n'
        "              END-JSON\n"
        "           END-IF.\n"
        '           DISPLAY "after".\n'
    )
    if_stmt, after = stmts
    (json_gen,) = if_stmt.then_statements
    assert isinstance(json_gen, XmlJsonStatement)
    assert [s.statement_type for s in json_gen.on_exception] == ["DISPLAY"]
    assert if_stmt.else_statements in (None, [])
    assert isinstance(after, DisplayStatement)


# Issue #394: a line break between the clause's words must not hide them.
# The lookahead for IS / THRU used to read the NEWLINE token, so a THRU on
# the next line fell through into clause text and the paragraphs it covers
# were reported dead.


def test_processing_procedure_thru_on_next_line_is_captured():
    _, stmts = _main_statements(
        "           XML PARSE WS-DOC PROCESSING PROCEDURE HANDLE-XML\n"
        "               THRU HANDLE-XML-END\n"
        "           END-XML.\n"
    )
    node = stmts[0]
    assert node.processing_procedure == "HANDLE-XML"
    assert node.processing_procedure_thru == "HANDLE-XML-END"
    assert node.clause_text == "PROCESSING PROCEDURE HANDLE-XML THRU HANDLE-XML-END"
    assert "THRU" not in node.operands
    assert "HANDLE-XML-END" not in node.operands


def test_processing_procedure_is_and_through_each_on_own_line():
    _, stmts = _main_statements(
        "           XML PARSE WS-DOC PROCESSING PROCEDURE\n"
        "               IS\n"
        "               HANDLE-XML\n"
        "               THROUGH\n"
        "               HANDLE-XML-END\n"
        "           END-XML.\n"
    )
    node = stmts[0]
    assert node.processing_procedure == "HANDLE-XML"
    assert node.processing_procedure_thru == "HANDLE-XML-END"
    assert node.clause_text == (
        "PROCESSING PROCEDURE IS HANDLE-XML THROUGH HANDLE-XML-END"
    )


def test_processing_procedure_thru_on_next_line_keeps_range_live():
    from cobolparser import DeadCodeAnalyzer

    body = (
        "           XML PARSE WS-DOC PROCESSING PROCEDURE HANDLE-XML\n"
        "               THRU HANDLE-XML-END\n"
        "           END-XML\n"
        "           STOP RUN.\n"
    )
    tail = (
        "       HANDLE-XML.\n"
        "           CONTINUE.\n"
        "       HANDLE-XML-MIDDLE.\n"
        "           CONTINUE.\n"
        "       HANDLE-XML-END.\n"
        "           EXIT.\n"
        "       TRULY-DEAD.\n"
        "           CONTINUE.\n"
    )
    result = parse_cobol(_HEADER + body + tail, filename="xmlcl.cbl")
    assert result.success, result.errors
    dead = [item.name for item in DeadCodeAnalyzer().analyze(result.ast).dead_items]
    assert dead == ["TRULY-DEAD"]


def test_bare_procedure_with_is_and_thru_on_next_lines():
    _, stmts = _main_statements(
        "           XML PARSE WS-DOC PROCEDURE\n"
        "               IS HANDLE-XML\n"
        "               THRU HANDLE-XML-END\n"
        "           END-XML.\n"
    )
    node = stmts[0]
    assert node.processing_procedure == "HANDLE-XML"
    assert node.processing_procedure_thru == "HANDLE-XML-END"
    assert "IS" not in node.operands


# --- #574: CONVERTING item [TO|FROM] JSON BOOLEAN|DECIMAL -------------------
#
# The clause loop exempted the word JSON only after TO (JSON GENERATE's
# form), so JSON PARSE's ``FROM JSON BOOLEAN`` and both bare forms ended the
# statement at JSON: the rest, ON EXCEPTION included, was dropped with an
# "Unparsed tokens" warning and the handler's CALL became an unconditional
# statement of the paragraph.

_CONVERTING_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. JSONCV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-J                PIC X(100).
       01  WS-REC.
           05  WS-FLAG         PIC X.
       01  WS-MSG              PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-J
"""


def _converting_program(head: str, word: str) -> str:
    return _CONVERTING_HEADER + (
        f"           {head}\n"
        f"               CONVERTING WS-FLAG {word}JSON BOOLEAN USING 'Y' AND 'N'\n"
        "               ON EXCEPTION\n"
        "                   CALL 'ERRLOG' USING WS-MSG\n"
        "           END-JSON\n"
        "           STOP RUN.\n"
    )


@pytest.mark.parametrize(
    "head",
    ["JSON PARSE WS-J INTO WS-REC", "JSON GENERATE WS-J FROM WS-REC"],
    ids=["parse", "generate"],
)
@pytest.mark.parametrize("word", ["FROM ", "TO ", ""], ids=["from", "to", "bare"])
def test_converting_json_boolean_keeps_exception_handler(head, word):
    result = parse_cobol(_converting_program(head, word), filename="jsoncv.cbl")
    assert result.success, result.errors
    assert not result.warnings, result.warnings
    stmts = result.ast.get_division("PROCEDURE").paragraphs[0].statements
    assert [type(s).__name__ for s in stmts] == [
        "IOAcceptStatement",
        "XmlJsonStatement",
        "StopStatement",
    ]
    node = stmts[1]
    assert f"CONVERTING WS-FLAG {word}JSON BOOLEAN USING" in node.clause_text
    assert [type(s) for s in node.on_exception] == [CallStatement]
    assert node.on_exception[0].called_program == "ERRLOG"


def test_json_converting_does_not_swallow_a_following_json_statement():
    # The lookahead keys on the word after JSON, so a new JSON statement
    # (JSON GENERATE / JSON PARSE) still ends the clause region.
    result = parse_cobol(
        _CONVERTING_HEADER + "           JSON GENERATE WS-J FROM WS-REC\n"
        "               CONVERTING WS-FLAG TO JSON BOOLEAN USING 'Y' AND 'N'\n"
        "           JSON PARSE WS-J INTO WS-REC\n"
        "               CONVERTING WS-FLAG FROM JSON BOOLEAN USING 'Y' AND 'N'\n"
        "           STOP RUN.\n",
        filename="jsoncv.cbl",
    )
    assert result.success, result.errors
    assert not result.warnings, result.warnings
    stmts = result.ast.get_division("PROCEDURE").paragraphs[0].statements
    assert [getattr(s, "action", None) for s in stmts[1:3]] == ["GENERATE", "PARSE"]
    assert "TO JSON BOOLEAN USING" in stmts[1].clause_text
    assert "FROM JSON BOOLEAN USING" in stmts[2].clause_text


def test_gen_fixtures_counts_no_call_inside_json_exception_handler():
    from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
    from cobolparser.layout.program import ProgramLayoutIndex
    from cobolparser.generators.program_fixtures import ProgramFixtureGenerator

    result = parse_cobol(
        _converting_program("JSON PARSE WS-J INTO WS-REC", "FROM "),
        filename="jsoncv.cbl",
    )
    assert result.ast is not None, result.errors
    index = ProgramLayoutIndex.build(result.ast)
    report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    bundle = ProgramFixtureGenerator().generate(result.ast, index, report, seed=1)
    counts = {
        e.ref: e.value
        for e in bundle.scenarios[0].expectations
        if e.kind == "call_count"
    }
    assert "CALL:ERRLOG" not in counts
    assert counts.get("ACCEPT:WS-J") == 1
