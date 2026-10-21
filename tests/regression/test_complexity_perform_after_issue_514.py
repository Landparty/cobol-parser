"""Regression tests for issue #514: PERFORM VARYING ... AFTER is nested loops.

Each AFTER phrase is a loop nested inside the previous one, with its own
UNTIL test, so ``PERFORM VARYING A ... AFTER B ...`` is the same control
flow as an inline PERFORM VARYING B inside a PERFORM VARYING A. The AFTER
form scored one decision and one nesting level; it now scores what the
nested form scores.
"""

from cobolparser import parse_cobol
from cobolparser.analysis.complexity import ComplexityAnalyzer

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CX1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC 9.
       01 B PIC 9.
       01 C PIC 9.
       PROCEDURE DIVISION.
       P-AFTER.
           PERFORM VARYING A FROM 1 BY 1 UNTIL A > 3
              AFTER B FROM 1 BY 1 UNTIL B > 3
              DISPLAY A
           END-PERFORM.
       P-NESTED.
           PERFORM VARYING A FROM 1 BY 1 UNTIL A > 3
              PERFORM VARYING B FROM 1 BY 1 UNTIL B > 3
                 DISPLAY A
              END-PERFORM
           END-PERFORM.
       P-AFTER2.
           PERFORM VARYING A FROM 1 BY 1 UNTIL A > 3
              AFTER B FROM 1 BY 1 UNTIL B > 3
              AFTER C FROM 1 BY 1 UNTIL C > 3
              IF A = B DISPLAY A END-IF
           END-PERFORM.
       P-OUT.
           PERFORM P-NESTED VARYING A FROM 1 BY 1 UNTIL A > 3
              AFTER B FROM 1 BY 1 UNTIL B > 3
           STOP RUN.
"""


def _scores() -> dict[str, tuple[int, int]]:
    result = parse_cobol(_SOURCE, filename="cx1.cbl")
    assert result.ast is not None
    report = ComplexityAnalyzer().analyze(result.ast)
    return {
        p.name: (p.cyclomatic_complexity, p.max_nesting_depth)
        for p in report.procedures
    }


def test_after_form_scores_like_nested_loops() -> None:
    scores = _scores()
    assert scores["P-AFTER"] == scores["P-NESTED"] == (3, 2)


def test_each_after_phrase_adds_a_decision_and_a_level() -> None:
    # Three loops, then an IF inside the innermost one.
    assert _scores()["P-AFTER2"] == (5, 4)


def test_out_of_line_varying_after() -> None:
    assert _scores()["P-OUT"] == (3, 2)
