"""Regression tests for issue #553: a clause and its NOT- twin are one decision.

``ComplexityAnalyzer`` added +1 per present exception-handling clause, so
``READ F AT END ... NOT AT END ...`` (and the ON SIZE ERROR / ON EXCEPTION
pairs) scored 3 where ``IF ... ELSE`` scores 2, and a SEARCH scored one more
for an AT END body although its not-found path exists without one. A pair
now adds 1 whether one or both bodies are written; SEARCH's AT END adds
nothing.
"""

from cobolparser import parse_cobol
from cobolparser.analysis.complexity import ComplexityAnalyzer

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CC.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO 'F'.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 R PIC X.
       WORKING-STORAGE SECTION.
       01 A PIC 9.
       01 K PIC 9.
       01 T.
          05 E PIC 9 OCCURS 5 INDEXED BY IX.
       PROCEDURE DIVISION.
       P-IF.
           IF A = 1 DISPLAY 'Y' ELSE DISPLAY 'N' END-IF.
       P-READ1.
           READ F AT END DISPLAY 'E' END-READ.
       P-READ2.
           READ F AT END DISPLAY 'E' NOT AT END DISPLAY 'N' END-READ.
       P-NOTONLY.
           READ F NOT AT END DISPLAY 'N' END-READ.
       P-ADD.
           ADD 1 TO A ON SIZE ERROR DISPLAY 'S'
              NOT ON SIZE ERROR DISPLAY 'K' END-ADD.
       P-CALL.
           CALL 'X' ON EXCEPTION DISPLAY 'X'
              NOT ON EXCEPTION DISPLAY 'Y' END-CALL.
       P-EVAL.
           EVALUATE A WHEN 1 DISPLAY '1' WHEN OTHER DISPLAY 'O'
           END-EVALUATE.
       P-SRCH1.
           SEARCH E AT END DISPLAY 'NF'
              WHEN E(IX) = K DISPLAY 'F'
           END-SEARCH.
       P-SRCH2.
           SEARCH E
              WHEN E(IX) = K DISPLAY 'F'
           END-SEARCH.
       P-NESTED.
           READ F AT END
                   IF A = 1 DISPLAY 'Y' END-IF
               NOT AT END
                   IF A = 2 DISPLAY 'Z' END-IF
           END-READ
           STOP RUN.
"""


def _scores() -> dict[str, int]:
    result = parse_cobol(_SOURCE, filename="cc.cbl")
    assert result.ast is not None
    report = ComplexityAnalyzer().analyze(result.ast)
    return {p.name: p.cyclomatic_complexity for p in report.procedures}


def test_clause_pairs_score_like_if_else() -> None:
    scores = _scores()
    for name in ("P-IF", "P-READ1", "P-READ2", "P-NOTONLY", "P-ADD", "P-CALL"):
        assert scores[name] == 2, name
    assert scores["P-EVAL"] == 2


def test_search_at_end_adds_nothing() -> None:
    scores = _scores()
    assert scores["P-SRCH1"] == scores["P-SRCH2"] == 2


def test_both_clause_bodies_are_still_walked() -> None:
    # One decision for the pair, plus each IF inside either body.
    assert _scores()["P-NESTED"] == 4
