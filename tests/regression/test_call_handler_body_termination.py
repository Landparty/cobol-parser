"""Regression tests: CALL handler bodies must stop at END-CALL / sentence period.

CallStatementParser._parse_nested_stmts previously kept collecting statements
after a nested statement had consumed the sentence-terminating period, because
the terminator check only ran between statements. A handler body such as

    CALL "SUBPROG" USING WS-AMT
        ON EXCEPTION
            CALL "ERRH" USING WS-AMT
    END-CALL.
    STOP RUN.

therefore swallowed STOP RUN into on_exception, and the nested CALL's USING
clause swallowed END-CALL as a bogus parameter. Downstream, mockymock marks
the swallowed statements as nested-in-boundary and refuses to mock them even
though they are top-level.
"""

from cobolparser import parse_cobol
from cobolparser.models.statements import CallStatement

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLTERM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-AMT PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
"""


def _main_para_statements(procedure_body: str):
    result = parse_cobol(HEADER + procedure_body, filename="callterm.cbl")
    assert result.success, result.errors
    proc = result.ast.get_division("PROCEDURE")
    paras = [p for p in proc.paragraphs if p.paragraph_name == "MAIN-PARA"]
    assert paras, [p.paragraph_name for p in proc.paragraphs]
    return paras[0].statements


class TestOnExceptionTermination:
    def test_end_call_and_period_stop_handler_body(self):
        """STOP RUN after END-CALL. must stay top-level (the reported bug)."""
        stmts = _main_para_statements(
            '           CALL "SUBPROG" USING WS-AMT\n'
            "               ON EXCEPTION\n"
            '                   CALL "ERRH" USING WS-AMT\n'
            "           END-CALL.\n"
            "           STOP RUN.\n"
        )
        assert [type(s).__name__ for s in stmts] == ["CallStatement", "StopStatement"]

        outer = stmts[0]
        assert outer.called_program == "SUBPROG"
        handler = outer.on_exception
        assert handler is not None
        assert [type(s).__name__ for s in handler] == ["CallStatement"]

    def test_end_call_not_captured_as_using_parameter(self):
        """The nested CALL's USING clause must not swallow END-CALL."""
        stmts = _main_para_statements(
            '           CALL "SUBPROG" USING WS-AMT\n'
            "               ON EXCEPTION\n"
            '                   CALL "ERRH" USING WS-AMT\n'
            "           END-CALL.\n"
            "           STOP RUN.\n"
        )
        inner = stmts[0].on_exception[0]
        assert isinstance(inner, CallStatement)
        assert inner.called_program == "ERRH"
        params = [p["name"] for p in inner.to_dict()["using_parameters"]]
        assert params == ["WS-AMT"]

    def test_period_alone_stops_handler_body(self):
        """Without END-CALL, the sentence period still ends the handler body."""
        stmts = _main_para_statements(
            '           CALL "SUBPROG"\n'
            "               ON EXCEPTION\n"
            '                   DISPLAY "ERR".\n'
            "           STOP RUN.\n"
        )
        assert [type(s).__name__ for s in stmts] == ["CallStatement", "StopStatement"]
        handler = stmts[0].on_exception
        assert handler is not None
        assert [type(s).__name__ for s in handler] == ["DisplayStatement"]


class TestNotOnExceptionTermination:
    def test_not_on_exception_body_stops_at_end_call_period(self):
        stmts = _main_para_statements(
            '           CALL "SUBPROG"\n'
            "               ON EXCEPTION\n"
            "                   MOVE 1 TO WS-AMT\n"
            "               NOT ON EXCEPTION\n"
            "                   MOVE 2 TO WS-AMT\n"
            "           END-CALL.\n"
            "           STOP RUN.\n"
        )
        assert [type(s).__name__ for s in stmts] == ["CallStatement", "StopStatement"]
        outer = stmts[0]
        assert outer.on_exception is not None
        assert [type(s).__name__ for s in outer.on_exception] == ["MoveStatement"]
        assert outer.not_on_exception is not None
        assert [type(s).__name__ for s in outer.not_on_exception] == ["MoveStatement"]


class TestOnOverflowTermination:
    def test_on_overflow_body_stops_at_end_call_period(self):
        stmts = _main_para_statements(
            '           CALL "SUBPROG"\n'
            "               ON OVERFLOW\n"
            "                   MOVE 1 TO WS-AMT\n"
            "           END-CALL.\n"
            "           STOP RUN.\n"
        )
        assert [type(s).__name__ for s in stmts] == ["CallStatement", "StopStatement"]
        overflow = stmts[0].on_overflow
        assert overflow
        assert [type(s).__name__ for s in overflow] == ["MoveStatement"]


class TestMultipleStatementsAfterCall:
    def test_several_top_level_statements_survive(self):
        """Everything after the CALL sentence must remain top-level."""
        stmts = _main_para_statements(
            '           CALL "SUBPROG" USING WS-AMT\n'
            "               ON EXCEPTION\n"
            '                   CALL "ERRH" USING WS-AMT\n'
            "           END-CALL.\n"
            "           MOVE 3 TO WS-AMT.\n"
            '           DISPLAY "DONE".\n'
            "           STOP RUN.\n"
        )
        assert [type(s).__name__ for s in stmts] == [
            "CallStatement",
            "MoveStatement",
            "DisplayStatement",
            "StopStatement",
        ]
