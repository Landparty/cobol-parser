"""XML/JSON PARSE and GENERATE with only a ``NOT ON EXCEPTION`` handler.

IBM's cobol-is-fun JSON sample writes ``JSON PARSE ... NOT ON EXCEPTION
DISPLAY ... END-JSON`` with no ``ON EXCEPTION`` before it (found by the
open-source corpus harness, ``tools/corpus``). The handler parser gave up
when the first phrase was not ``ON EXCEPTION``: ``ON`` was dropped as
unparsed tokens and the handler's statements became unconditional top-level
statements of the paragraph.
"""

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.walk import all_paragraphs

_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 JTXT PIC X(100).
       01 CLIENT-DATA.
          05 A PIC X.
       PROCEDURE DIVISION.
"""


def _parse(body: str):
    return CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(
        _HEADER + body + "           DISPLAY 'MARKER'.\n"
    )


def _top(result):
    return [
        type(s).__name__
        for p in all_paragraphs(result.ast.procedure_division)
        for s in p.statements
    ]


@pytest.mark.parametrize(
    "statement",
    [
        "JSON PARSE JTXT INTO CLIENT-DATA\n             WITH DETAIL",
        "XML PARSE JTXT PROCESSING PROCEDURE P1",
        "JSON GENERATE JTXT FROM CLIENT-DATA",
        "XML GENERATE JTXT FROM CLIENT-DATA",
    ],
)
def test_not_on_exception_alone_is_the_handler(statement):
    verb = statement.split()[0]
    result = _parse(
        f"           {statement}\n"
        "             NOT ON EXCEPTION\n"
        "               DISPLAY 'OK'\n"
        f"           END-{verb}\n"
    )
    assert result.errors == [] and result.warnings == []
    assert _top(result) == ["XmlJsonStatement", "DisplayStatement"]
    xml = next(
        s
        for p in all_paragraphs(result.ast.procedure_division)
        for s in p.statements
        if type(s).__name__ == "XmlJsonStatement"
    )
    assert [type(s).__name__ for s in xml.not_on_exception] == ["DisplayStatement"]
    assert not xml.on_exception


def test_not_exception_without_on():
    result = _parse(
        "           JSON PARSE JTXT INTO CLIENT-DATA\n"
        "             NOT EXCEPTION DISPLAY 'OK'\n"
        "           END-JSON\n"
    )
    assert result.warnings == []
    assert _top(result) == ["XmlJsonStatement", "DisplayStatement"]


def test_both_handlers_still_parse():
    result = _parse(
        "           JSON PARSE JTXT INTO CLIENT-DATA\n"
        "             ON EXCEPTION DISPLAY 'BAD'\n"
        "             NOT ON EXCEPTION DISPLAY 'OK'\n"
        "           END-JSON\n"
    )
    assert result.warnings == []
    xml = next(
        s
        for p in all_paragraphs(result.ast.procedure_division)
        for s in p.statements
        if type(s).__name__ == "XmlJsonStatement"
    )
    assert len(xml.on_exception) == 1 and len(xml.not_on_exception) == 1


def test_nested_in_a_handler_leaves_a_lone_not_phrase_to_the_outer_statement():
    result = _parse(
        "           CALL 'Z'\n"
        "             ON EXCEPTION\n"
        "               JSON GENERATE JTXT FROM CLIENT-DATA\n"
        "             NOT ON EXCEPTION\n"
        "               DISPLAY 'NEG'\n"
        "           END-CALL\n"
    )
    call = all_paragraphs(result.ast.procedure_division)[0].statements[0]
    assert [type(s).__name__ for s in call.on_exception] == ["XmlJsonStatement"]
    assert [type(s).__name__ for s in call.not_on_exception] == ["DisplayStatement"]


def test_nested_with_its_own_terminator_keeps_its_not_phrase():
    result = _parse(
        "           CALL 'Z'\n"
        "             ON EXCEPTION\n"
        "               JSON PARSE JTXT INTO CLIENT-DATA\n"
        "                 NOT ON EXCEPTION DISPLAY 'OK'\n"
        "               END-JSON\n"
        "           END-CALL\n"
    )
    call = all_paragraphs(result.ast.procedure_division)[0].statements[0]
    (json,) = call.on_exception
    assert [type(s).__name__ for s in json.not_on_exception] == ["DisplayStatement"]
    assert not call.not_on_exception
