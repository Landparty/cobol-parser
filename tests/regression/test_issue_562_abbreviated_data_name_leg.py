"""Regression tests for issue #562.

In an abbreviated combined relation whose second leg is a bare data-name
(``IF IN-CODE = 'A' OR WS-B``), the leg is a relation against the subject
(``IN-CODE = WS-B``) when WS-B is an ordinary data item, and a condition-name
test only when it is a level-88 name. The builder used to read every bare
identifier leg as a CONDITION_NAME, although the DATA DIVISION had already
been parsed and could tell the two apart.
"""

import json

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.generators import ProgramLayoutIndex

_DATA = (
    "IDENTIFICATION DIVISION.\n"
    "PROGRAM-ID. T.\n"
    "DATA DIVISION.\n"
    "WORKING-STORAGE SECTION.\n"
    "01 IN-CODE PIC X.\n"
    "01 WS-A PIC X VALUE 'A'.\n"
    "01 WS-B PIC X VALUE 'B'.\n"
    "01 WS-FLAG PIC X.\n"
    "   88 FLAG-ON VALUE 'Y'.\n"
    "01 WS-G.\n"
    "   05 WS-Q PIC X.\n"
    "   05 WS-TE PIC X OCCURS 3.\n"
    "PROCEDURE DIVISION.\n"
    "MAIN-PARA.\n"
)


def _parse(statement: str):
    result = parse_cobol(
        _DATA + f"    {statement}\n    STOP RUN.\n",
        free_form=True,
        error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    )
    assert not result.errors
    return result


def _render(node) -> str:
    left = getattr(node, "left_condition", None)
    if left is not None:
        right = node.right_condition
        if right is None:
            return f"({node.operator} {_render(left)})"
        return f"({_render(left)} {node.operator} {_render(right)})"
    if node.right_operand is None:
        return f"{node.left_operand} {node.operator}"
    return f"{node.left_operand} {node.operator} {node.right_operand}"


def _if(condition: str) -> str:
    result = _parse(f"IF {condition} DISPLAY 'X' END-IF")
    (stmt,) = result.ast.find_all_by_type("IfStatement")
    return _render(stmt.condition)


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        (
            "IN-CODE = 'A' OR WS-B",
            "(IN-CODE EQUAL 'A' OR IN-CODE EQUAL WS-B)",
        ),
        (
            "IN-CODE = WS-A OR WS-B",
            "(IN-CODE EQUAL WS-A OR IN-CODE EQUAL WS-B)",
        ),
        (
            "IN-CODE = WS-A AND WS-B",
            "(IN-CODE EQUAL WS-A AND IN-CODE EQUAL WS-B)",
        ),
        (
            "IN-CODE NOT < WS-A OR WS-B",
            "(IN-CODE GREATER_OR_EQUAL WS-A OR IN-CODE GREATER_OR_EQUAL WS-B)",
        ),
        (
            "IN-CODE = WS-A OR NOT WS-B",
            "(IN-CODE EQUAL WS-A OR IN-CODE NOT_EQUAL WS-B)",
        ),
        (
            "IN-CODE = WS-A OR WS-TE (1)",
            "(IN-CODE EQUAL WS-A OR IN-CODE EQUAL WS-TE ( 1 ))",
        ),
        (
            "IN-CODE = WS-A OR WS-Q OF WS-G",
            "(IN-CODE EQUAL WS-A OR IN-CODE EQUAL WS-Q OF WS-G)",
        ),
    ],
)
def test_data_name_leg_is_expanded(condition: str, expected: str) -> None:
    assert _if(condition) == expected


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        # A real level-88 condition-name keeps its reading.
        ("IN-CODE = WS-A OR FLAG-ON", "(IN-CODE EQUAL WS-A OR FLAG-ON CONDITION_NAME)"),
        # A name the DATA DIVISION does not declare (e.g. from an unexpanded
        # COPY) cannot be resolved: it keeps the condition-name reading.
        (
            "IN-CODE = WS-A OR NOT-DECLARED",
            "(IN-CODE EQUAL WS-A OR NOT-DECLARED CONDITION_NAME)",
        ),
    ],
)
def test_condition_name_and_unknown_legs_are_kept(
    condition: str, expected: str
) -> None:
    assert _if(condition) == expected


def test_perform_until_expands_data_name_leg() -> None:
    result = _parse("PERFORM UNTIL IN-CODE = WS-A OR WS-B\n  DISPLAY 'X'\nEND-PERFORM")
    (stmt,) = result.ast.find_all_by_type("PerformStatement")
    tree = stmt.until_condition.condition_tree
    assert _render(tree) == "(IN-CODE EQUAL WS-A OR IN-CODE EQUAL WS-B)"


def test_constraints_no_longer_see_a_bare_condition_name() -> None:
    result = _parse("IF IN-CODE = 'A' OR WS-B DISPLAY 'X' END-IF")
    index = ProgramLayoutIndex.build(result.ast)
    boundaries = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    report = ConstraintExtractor().extract(result.ast, index, boundaries)
    assert "bare condition name" not in json.dumps(report.to_dict())
