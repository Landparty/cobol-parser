"""Unit tests for cobolparser.analysis.program_flow.statement_text.

Statements come from real parses (``parse_cobol``) rather than hand-built
objects so the summaries are pinned against what the parser actually
produces.
"""

from __future__ import annotations

from typing import Any

from cobolparser.analysis.program_flow.statement_text import (
    summarize_arm,
    summarize_statement,
)
from cobolparser.parser import parse_cobol

_TEMPLATE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUMPROG.
       PROCEDURE DIVISION.
       MAIN-PARA.
{body}
       9000-DONE.
           EXIT.
"""


def _parse_statements(body: str) -> list[Any]:
    source = _TEMPLATE.format(body=body)
    result = parse_cobol(source)
    proc = result.ast.get_division("PROCEDURE")
    para = next(p for p in proc.paragraphs if p.paragraph_name == "MAIN-PARA")
    return para.statements


def _first_summary(body: str) -> str:
    return summarize_statement(_parse_statements(body)[0])


class TestSummarizeStatement:
    def test_move(self) -> None:
        assert (
            _first_summary("           MOVE 8 TO RETURN-CODE-X.")
            == "MOVE 8 TO RETURN-CODE-X"
        )

    def test_perform(self) -> None:
        assert _first_summary("           PERFORM 9000-DONE.") == "PERFORM 9000-DONE"

    def test_perform_thru(self) -> None:
        assert (
            _first_summary("           PERFORM MAIN-PARA THRU 9000-DONE.")
            == "PERFORM MAIN-PARA THRU 9000-DONE"
        )

    def test_go_to(self) -> None:
        assert _first_summary("           GO TO 9000-DONE.") == "GO TO 9000-DONE"

    def test_call(self) -> None:
        assert _first_summary("           CALL 'CBLTDLI' USING WS-A.") == "CALL CBLTDLI"

    def test_set_to_true(self) -> None:
        assert _first_summary("           SET WS-EOF TO TRUE.") == "SET WS-EOF TO TRUE"

    def test_compute(self) -> None:
        assert (
            _first_summary("           COMPUTE WS-X = WS-Y + 1.")
            == "COMPUTE WS-X = WS-Y + 1"
        )

    def test_add(self) -> None:
        assert _first_summary("           ADD 1 TO WS-COUNT.") == "ADD 1 TO WS-COUNT"

    def test_subtract(self) -> None:
        assert (
            _first_summary("           SUBTRACT 1 FROM WS-N.") == "SUBTRACT 1 FROM WS-N"
        )

    def test_display(self) -> None:
        assert (
            _first_summary("           DISPLAY 'BAD' WS-PURGE-ERRORS.")
            == 'DISPLAY "BAD" WS-PURGE-ERRORS'
        )

    def test_nested_if_uses_condition_text(self) -> None:
        body = (
            "           IF WS-A > WS-B\n"
            "               CONTINUE\n"
            "           END-IF."
        )
        assert _first_summary(body) == "IF WS-A > WS-B"

    def test_goback(self) -> None:
        assert _first_summary("           GOBACK.") == "GOBACK"

    def test_generic_fallback_uses_type_and_operands(self) -> None:
        # CLOSE has no dedicated branch; the generic form already reads well.
        assert _first_summary("           CLOSE PURGEIN.") == "CLOSE PURGEIN"

    def test_long_summary_truncated(self) -> None:
        body = "           MOVE WS-VERY-LONG-SOURCE-FIELD-NM TO WS-VERY-LONG-TGT-NM.\n"
        text = _first_summary(body)
        assert len(text) <= 48
        assert text.endswith("...")

    def test_never_raises_on_bare_object(self) -> None:
        class Bare:
            pass

        assert summarize_statement(Bare()) == "Bare"


class TestSummarizeArm:
    def test_empty_arm_is_none(self) -> None:
        assert summarize_arm([]) is None

    def test_arm_summarizes_first_statement_only(self) -> None:
        stmts = _parse_statements(
            "           MOVE 8 TO RETURN-CODE-X.\n           GOBACK.\n"
        )
        assert summarize_arm(stmts) == "MOVE 8 TO RETURN-CODE-X"
