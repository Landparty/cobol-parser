"""Regression tests for issue #539.

``IF x IS [NOT] class-name`` (a SPECIAL-NAMES CLASS) and ``IF x IS [NOT]
OMITTED`` fell through to an operand-less COMPARISON node, so the tested
field read as unused, xref had no reference for it, and in EVALUATE TRUE
the class test became the made-up literal ``'WS-C IS VALID-CODE'``. In
PERFORM UNTIL, xref recorded the class-name itself as a data item.
"""

import pytest

from cobolparser import ErrorRecoveryMode, LintAnalyzer, parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.analysis.xref import XrefAnalyzer
from cobolparser.generators import ProgramLayoutIndex
from cobolparser.models.statements.base import ConditionalExpression

_CLASS_PROGRAM = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. CLS.
ENVIRONMENT DIVISION.
CONFIGURATION SECTION.
SPECIAL-NAMES.
    CLASS VALID-CODE IS 'A' THRU 'F' 'X'.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT IN-F ASSIGN TO INDD.
DATA DIVISION.
FILE SECTION.
FD IN-F.
01 IN-REC.
   05 IN-CODE PIC X(3).
   05 IN-AMT  PIC 9(5).
WORKING-STORAGE SECTION.
01 WS-ERR PIC 9(3) VALUE 0.
01 WS-C PIC X.
PROCEDURE DIVISION.
    OPEN INPUT IN-F
    READ IN-F
    IF IN-CODE IS NOT VALID-CODE
       ADD 1 TO WS-ERR
    END-IF
    EVALUATE TRUE
       WHEN WS-C IS VALID-CODE DISPLAY 'V'
    END-EVALUATE
    PERFORM UNTIL WS-C IS NOT VALID-CODE
       MOVE 'Z' TO WS-C
    END-PERFORM
    DISPLAY WS-ERR IN-AMT
    CLOSE IN-F
    GOBACK.
"""

_OMITTED_PROGRAM = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. OMIT.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-X PIC X.
LINKAGE SECTION.
01 L-A PIC X.
01 L-OPT PIC X.
PROCEDURE DIVISION USING L-A L-OPT.
    IF L-OPT IS OMITTED
       MOVE 'D' TO WS-X
    ELSE
       MOVE 'P' TO WS-X
    END-IF
    DISPLAY WS-X L-A
    GOBACK.
"""


def _parse(source: str):
    result = parse_cobol(
        source, free_form=True, error_recovery=ErrorRecoveryMode.COLLECT_ALL
    )
    assert not result.errors
    return result.ast


def _if_condition(condition: str) -> ConditionalExpression:
    ast = _parse(
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. T.\nDATA DIVISION.\n"
        "WORKING-STORAGE SECTION.\n01 A PIC X.\n01 G.\n   05 B PIC X OCCURS 2.\n"
        f"PROCEDURE DIVISION.\nMAIN-PARA.\n    IF {condition} DISPLAY 'X' END-IF\n"
        "    STOP RUN.\n"
    )
    (stmt,) = ast.find_all_by_type("IfStatement")
    assert isinstance(stmt.condition, ConditionalExpression)
    return stmt.condition


@pytest.mark.parametrize(
    ("condition", "operator", "operand"),
    [
        ("A IS VALID-CODE", "IS VALID-CODE", "A"),
        ("A IS NOT VALID-CODE", "IS NOT VALID-CODE", "A"),
        ("B (1) IS VALID-CODE", "IS VALID-CODE", "B ( 1 )"),
        ("B OF G (2) IS NOT VALID-CODE", "IS NOT VALID-CODE", "B OF G ( 2 )"),
        ("A IS OMITTED", "IS OMITTED", "A"),
        ("A IS NOT OMITTED", "IS NOT OMITTED", "A"),
        ("A OMITTED", "IS OMITTED", "A"),
        ("A NOT OMITTED", "IS NOT OMITTED", "A"),
        # A leading NOT folds into the operator, as for IS NUMERIC.
        ("NOT A IS VALID-CODE", "IS NOT VALID-CODE", "A"),
    ],
)
def test_structured_node(condition: str, operator: str, operand: str) -> None:
    expr = _if_condition(condition)
    assert expr.operator == operator
    assert expr.left_operand == operand


def test_tested_field_is_referenced_not_unused() -> None:
    for source in (_CLASS_PROGRAM, _OMITTED_PROGRAM):
        report = LintAnalyzer(["unused-variables"]).analyze(_parse(source))
        assert report.findings == []


def test_xref_has_the_field_and_not_the_class_name() -> None:
    report = XrefAnalyzer().analyze(_parse(_CLASS_PROGRAM)).to_dict()
    entries = {entry["name"]: entry for entry in report["entries"]}
    assert [r["role"] for r in entries["IN-CODE"]["references"]] == ["condition"]
    # Not a data item: since #519 the SPECIAL-NAMES class is declared as
    # its own kind, and the class test references it.
    assert entries["VALID-CODE"]["kind"] == "class-name"
    assert "VALID-CODE" not in report["undefined"]


def test_evaluate_true_class_test_is_a_condition_selector() -> None:
    (stmt,) = _parse(_CLASS_PROGRAM).find_all_by_type("EvaluateStatement")
    (selector,) = stmt.to_dict()["when_clauses"][0]["selectors"]
    assert selector == {"type": "Condition", "text": "WS-C IS VALID-CODE"}


def test_constraints_report_the_real_reason() -> None:
    ast = _parse(_CLASS_PROGRAM)
    index = ProgramLayoutIndex.build(ast)
    boundaries = BoundaryInventoryAnalyzer().analyze(ast, index)
    report = ConstraintExtractor().extract(ast, index, boundaries)
    reasons = " ".join(str(r) for r in report.to_dict().values())
    assert "unparseable condition text" not in reasons
    assert "user-defined class condition" in reasons


@pytest.mark.parametrize("condition", ["WS-I EXCEEDS WS-J", "WS-I VALID-CODE"])
def test_undecomposed_until_guard_still_references_its_fields(condition) -> None:
    # PERFORM UNTIL is now walked through its condition_tree; a node the
    # builder could not decompose keeps only metadata.raw_condition, which
    # must still yield the fields (main read them from the raw text).
    ast = _parse(
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. T.\nDATA DIVISION.\n"
        "WORKING-STORAGE SECTION.\n01 WS-I PIC 9.\n01 WS-J PIC 9.\n"
        f"PROCEDURE DIVISION.\nMAIN-PARA.\n    PERFORM UNTIL {condition}\n"
        "       DISPLAY 'Z'\n    END-PERFORM\n    STOP RUN.\n"
    )
    report = LintAnalyzer(["unused-variables"]).analyze(ast)
    flagged = {f.symbol for f in report.findings}
    assert "WS-I" not in flagged
