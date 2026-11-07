"""XML / JSON GENERATE and PARSE: the branches the other XML tests leave open.

``XmlJsonStatementParser`` driven through ``CobolParser`` with real
statements; each test checks the ``XmlJsonStatement`` (primary operand,
FROM item, COUNT IN / clause items, PROCESSING PROCEDURE, handlers), the
statements around it and the errors / warnings: the verb and its action on
different lines, an operand or FROM source that is missing because a new
statement starts, qualified and (nested-)subscripted clause items, a
PROCESSING PROCEDURE clause cut short, and an enclosing READ's ``NOT
INVALID KEY`` closing the XML statement's ON EXCEPTION handler. A period
standing where an operand should be is pinned as a strict xfail.
"""

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode

PRE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. XMLBR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT DOC-FILE ASSIGN TO "DOCS"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS DOC-KEY.
       DATA DIVISION.
       FILE SECTION.
       FD  DOC-FILE.
       01  DOC-REC.
           05  DOC-KEY         PIC X(8).
           05  DOC-BODY        PIC X(200).
       WORKING-STORAGE SECTION.
       01  WS-DOC              PIC X(200).
       01  WS-GRP.
           05  WS-CNT          PIC 9(4) OCCURS 3.
       01  WS-IX               PIC 9.
       PROCEDURE DIVISION.
       MAIN-PARA.
"""
POST = """\
       H1.
           EXIT.
       H2.
           EXIT.
"""


def _parse(body: str):
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    result = parser.parse(PRE + body + POST, "xmlbr.cbl")
    assert result.ast is not None
    return result


def _xml(result):
    stmts = result.ast.find_all_by_type("XmlJsonStatement")
    assert len(stmts) == 1, stmts
    return stmts[0]


def _main(result) -> list[str]:
    main = result.ast.procedure_division.paragraphs[0]
    return [s.to_dict()["statement_type"] for s in main.statements]


def _paragraphs(result) -> list[str]:
    return [p.paragraph_name for p in result.ast.procedure_division.paragraphs]


class TestVerbAndOperands:
    def test_action_on_the_next_line(self):
        result = _parse("           XML\n               GENERATE WS-DOC FROM WS-GRP.\n")
        assert result.errors == []
        assert result.warnings == []
        stmt = _xml(result)
        assert (stmt.verb, stmt.action) == ("XML", "GENERATE")
        assert (stmt.primary_operand, stmt.from_item) == ("WS-DOC", "WS-GRP")

    def test_action_after_floating_comments(self):
        result = _parse(
            "           JSON\n"
            "           *> the action word follows the comments\n"
            "           *> on a later line\n"
            "               GENERATE WS-DOC FROM WS-GRP.\n"
        )
        assert result.errors == []
        stmt = _xml(result)
        assert (stmt.verb, stmt.action) == ("JSON", "GENERATE")
        assert stmt.from_item == "WS-GRP"

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "XmlJsonStatementParser.matches looks at most 5 tokens past XML/"
            "JSON for GENERATE/PARSE; floating comment lines in between push "
            "it out of reach, so the XML statement is dropped as unparsed "
            "tokens and its GENERATE is parsed as a Report Writer GENERATE"
        ),
    )
    def test_action_after_a_block_of_floating_comments(self):
        # JSON <newline> PARSE on purpose: the shared statement registry
        # caches dispatch on (verb, layout, action word), and the comments
        # are layout, so an earlier ``XML``/``JSON`` <newline> action parse
        # in the same process would hand this statement a cached hit and
        # mask the bug. No other test source has JSON alone on a line.
        result = _parse(
            "           JSON\n"
            + "           *> explain the document layout\n" * 7
            + "               PARSE WS-DOC INTO WS-GRP.\n"
        )
        assert result.warnings == []
        assert _main(result) == ["JSON PARSE"]

    def test_missing_operand_before_next_statement(self):
        result = _parse("           XML GENERATE\n               DISPLAY 'X'.\n")
        assert [str(e) for e in result.errors] == [
            "line 23, column 5: XML GENERATE requires an operand"
        ]
        assert _xml(result).primary_operand is None
        assert _main(result) == ["XML GENERATE", "DISPLAY"]

    def test_missing_from_source_before_next_statement(self):
        result = _parse(
            "           JSON GENERATE WS-DOC FROM\n               DISPLAY 'X'.\n"
        )
        assert [str(e) for e in result.errors] == [
            "line 23, column 5: JSON GENERATE requires a source item after FROM"
        ]
        stmt = _xml(result)
        assert (stmt.primary_operand, stmt.from_item) == ("WS-DOC", None)
        assert _main(result) == ["JSON GENERATE", "DISPLAY"]

    @pytest.mark.parametrize(
        "body",
        [
            "           XML GENERATE.\n",
            "           XML GENERATE WS-DOC FROM.\n",
            "           XML PARSE WS-DOC PROCESSING PROCEDURE.\n",
        ],
        ids=["primary", "from", "processing-procedure"],
    )
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "XmlJsonStatementParser takes the sentence period as the missing "
            "operand / FROM item / PROCESSING PROCEDURE name (is_statement_"
            "boundary('.') is False), so no error is reported and the clause "
            "loop then swallows the next paragraph header (H1) as clause text"
        ),
    )
    def test_period_in_place_of_an_operand(self, body):
        result = _parse(body)
        assert _paragraphs(result) == ["MAIN-PARA", "H1", "H2"]
        assert _main(result) == [_xml(result).to_dict()["statement_type"]]


class TestClauseItems:
    def test_qualified_and_subscripted_items(self):
        result = _parse("""\
           XML GENERATE WS-DOC FROM WS-GRP
               COUNT IN WS-CNT OF WS-GRP (WS-IX)
               NAME OF WS-CNT (1) IS 'C'.
""")
        assert result.errors == []
        assert result.warnings == []
        stmt = _xml(result)
        assert stmt.count_in == "WS-CNT OF WS-GRP ( WS-IX )"
        assert stmt.clause_items == ["WS-CNT ( 1 )"]
        assert stmt.clause_text == (
            "COUNT IN WS-CNT OF WS-GRP ( WS-IX ) NAME OF WS-CNT ( 1 ) IS C"
        )

    def test_unclosed_subscript_runs_to_the_period(self):
        result = _parse(
            "           XML GENERATE WS-DOC FROM WS-GRP COUNT WS-CNT (WS-IX.\n"
        )
        stmt = _xml(result)
        assert stmt.count_in == "WS-CNT ( WS-IX"
        assert _paragraphs(result) == ["MAIN-PARA", "H1", "H2"]

    def test_nested_subscript(self):
        result = _parse(
            "           XML GENERATE WS-DOC FROM WS-GRP COUNT WS-CNT (WS-IX (1)).\n"
        )
        assert result.errors == []
        assert _xml(result).count_in == "WS-CNT ( WS-IX ( 1 ) )"


class TestProcessingProcedure:
    def test_processing_without_procedure_is_plain_clause_text(self):
        result = _parse("           XML PARSE WS-DOC PROCESSING WS-IX.\n")
        assert result.errors == []
        stmt = _xml(result)
        assert stmt.processing_procedure is None
        assert stmt.clause_text == "PROCESSING WS-IX"

    def test_procedure_name_missing_before_next_statement(self):
        result = _parse(
            "           XML PARSE WS-DOC PROCESSING PROCEDURE\n"
            "               DISPLAY 'X'.\n"
        )
        stmt = _xml(result)
        assert stmt.processing_procedure is None
        assert stmt.clause_text == "PROCESSING PROCEDURE"
        assert _main(result) == ["XML PARSE", "DISPLAY"]

    def test_thru_name_missing_before_next_statement(self):
        result = _parse(
            "           XML PARSE WS-DOC PROCESSING PROCEDURE H1 THRU\n"
            "               DISPLAY 'X'.\n"
        )
        stmt = _xml(result)
        assert (stmt.processing_procedure, stmt.processing_procedure_thru) == (
            "H1",
            None,
        )
        assert _main(result) == ["XML PARSE", "DISPLAY"]


class TestHandlers:
    def test_enclosing_not_invalid_key_closes_the_on_exception_body(self):
        result = _parse("""\
           READ DOC-FILE
               INVALID KEY
                   XML PARSE DOC-BODY PROCESSING PROCEDURE H1
                       ON EXCEPTION DISPLAY 'E'
               NOT INVALID KEY
                   DISPLAY 'N'
           END-READ.
""")
        assert result.errors == []
        assert result.warnings == []
        stmt = _xml(result)
        assert [s.display_items for s in stmt.on_exception] == [['"E"']]
        assert stmt.not_on_exception is None
        (read,) = result.ast.procedure_division.paragraphs[0].statements
        read_dict = read.to_dict()
        assert read_dict["statement_type"] == "READ"
        assert [s["statement_type"] for s in read_dict["invalid_key_clause"]] == [
            "XML PARSE"
        ]
        assert [s["display_items"] for s in read_dict["not_invalid_key_clause"]] == [
            ['"N"']
        ]
