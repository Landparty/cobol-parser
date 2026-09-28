"""EVALUATE is first-match: a later WHEN arm must also falsify every earlier one.

Before the fix each WHEN arm was solved from its own selector alone, so
``WHEN F1-QTY > 50 / WHEN F1-QTY > 10`` witnessed 51 for WHEN_2 -- a value
that takes WHEN_1 -- and the scenario named for WHEN_2 never reached it. A
duplicate ``WHEN 1 / WHEN 1`` reported the unreachable second arm as
satisfiable.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.analysis.domains import Unsatisfiable, Witness, solve
from cobolparser.generators import ProgramLayoutIndex

# A READ of F1 makes F1-REC's fields boundary-fed, the precondition for any
# constraint to be extracted at all.
_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EVALFM.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC.
           05  F1-QTY          PIC 9(3).
           05  F1-STATUS       PIC X.
       WORKING-STORAGE SECTION.
       01  WS-EOF              PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           READ F1
               AT END MOVE 'Y' TO WS-EOF
           END-READ
"""


def _extract(procedure_body: str):
    result = parse_cobol(_HEADER + procedure_body, filename="t.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    index = ProgramLayoutIndex.build(result.ast)
    boundaries = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    return ConstraintExtractor().extract(result.ast, index, boundaries)


def _branch(report):
    assert len(report.branches) == 1, report.branches
    return report.branches[0]


def _solve(arm):
    return solve(arm[0].field.spec, arm)


def _evaluate(*whens: str, subject: str = "TRUE") -> str:
    body = f"           EVALUATE {subject}\n"
    for i, when in enumerate(whens):
        body += f"               WHEN {when}\n                   DISPLAY '{i}'\n"
    return body + "           END-EVALUATE.\n"


def test_later_relational_arm_excludes_the_earlier_one():
    report = _extract(_evaluate("F1-QTY > 50", "F1-QTY > 10"))
    arms = _branch(report).arms
    assert [(c.op, c.values) for c in arms["WHEN_1"]] == [("gt", ("50",))]
    assert [(c.op, c.values) for c in arms["WHEN_2"]] == [
        ("gt", ("10",)),
        ("le", ("50",)),
    ]
    witness = _solve(arms["WHEN_2"])
    assert isinstance(witness, Witness)
    assert 10 < int(witness.value) <= 50


def test_duplicate_when_value_is_unsatisfiable():
    report = _extract(_evaluate("1", "1", subject="F1-QTY"))
    arms = _branch(report).arms
    assert isinstance(_solve(arms["WHEN_1"]), Witness)
    assert isinstance(_solve(arms["WHEN_2"]), Unsatisfiable)


def test_when_other_still_negates_only_the_arms_own_selectors():
    report = _extract(
        "           EVALUATE F1-STATUS\n"
        "               WHEN 'A'\n"
        "                   DISPLAY 'A'\n"
        "               WHEN 'B'\n"
        "                   DISPLAY 'B'\n"
        "               WHEN OTHER\n"
        "                   DISPLAY 'X'\n"
        "           END-EVALUATE.\n"
    )
    branch = _branch(report)
    assert [(c.op, c.values) for c in branch.arms["WHEN_2"]] == [
        ("eq", ("B",)),
        ("ne", ("A",)),
    ]
    assert [(c.op, c.values) for c in branch.arms["WHEN_OTHER"]] == [
        ("not_in_set", ("A", "B"))
    ]
    assert branch.unsupported == []


def test_an_earlier_range_arm_that_cannot_be_negated_is_reported():
    report = _extract(_evaluate("10 THRU 20", "15", subject="F1-QTY"))
    branch = _branch(report)
    assert [(c.op, c.values) for c in branch.arms["WHEN_2"]] == [("eq", ("15",))]
    assert any("earlier WHEN arm" in note for note in branch.unsupported)
