"""A PERFORM UNTIL condition that ends at a line break, not a period (#347).

The lexer's NEWLINE token used to be copied into the condition, rendered as
``"\\n"``. With that as the last token the shared condition machinery no
longer saw the condition's real end: a bare condition-name, ``NOT cond`` and
a class test fell back to a raw COMPARISON with ``left_operand=None``, and an
enclosing ``( ... )`` was not stripped (``'( A'`` / ``'5 )'``). That broke the
READ / AT END / EOF-flag idiom in gen-fixtures' constraint extraction.
"""

from typing import Any

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.generators import ProgramLayoutIndex
from cobolparser.models.statements.control import PerformStatement


def _program(body: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PNL.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-FLAG PIC X.\n"
        "          88 WS-FLAG1 VALUE 'Y'.\n"
        "       01 A PIC 9.\n"
        "       01 B PIC 9.\n"
        "       01 X PIC X.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n" + body + "       P.\n"
        "           DISPLAY 'P'.\n"
    )


# Each PERFORM form with its condition ending at a line break.
_FORMS = {
    "out-of-line": "           PERFORM P UNTIL {cond}\n           STOP RUN.\n",
    "inline": (
        "           PERFORM UNTIL {cond}\n"
        "               DISPLAY 'X'\n"
        "           END-PERFORM\n"
        "           STOP RUN.\n"
    ),
    "varying": (
        "           PERFORM P VARYING B FROM 1 BY 1 UNTIL {cond}\n"
        "           STOP RUN.\n"
    ),
}


def _until_tree(cond: str, form: str) -> dict[str, Any]:
    result = parse_cobol(_program(_FORMS[form].format(cond=cond)))
    assert result.ast is not None
    assert not result.errors, result.errors
    perform = result.ast.find_all_by_type("PerformStatement")[0]
    assert isinstance(perform, PerformStatement)
    until = perform.until_condition
    assert until is not None
    assert "\n" not in until.operands[0]
    tree = until.condition_tree
    assert tree is not None
    return tree.to_dict()


@pytest.mark.parametrize("form", list(_FORMS))
def test_bare_condition_name(form: str) -> None:
    tree = _until_tree("WS-FLAG1", form)
    assert tree["operator"] == "CONDITION_NAME"
    assert tree["left_operand"] == "WS-FLAG1"
    assert "\n" not in tree["metadata"].get("raw_condition", "")


@pytest.mark.parametrize("form", list(_FORMS))
def test_parenthesised_comparison(form: str) -> None:
    tree = _until_tree("(A > 5)", form)
    assert tree["operator"] == "GREATER"
    assert (tree["left_operand"], tree["right_operand"]) == ("A", "5")


@pytest.mark.parametrize("form", list(_FORMS))
def test_parenthesised_or(form: str) -> None:
    tree = _until_tree("(A > 5) OR (B = 1)", form)
    assert tree["operator"] == "OR"
    right = tree["right_condition"]
    assert (right["left_operand"], right["right_operand"]) == ("B", "1")


@pytest.mark.parametrize("form", list(_FORMS))
def test_not_condition_name(form: str) -> None:
    tree = _until_tree("NOT WS-FLAG1", form)
    assert tree["operator"] == "NOT"
    assert tree["left_condition"]["operator"] == "CONDITION_NAME"
    assert tree["left_condition"]["left_operand"] == "WS-FLAG1"


@pytest.mark.parametrize("form", list(_FORMS))
def test_class_test(form: str) -> None:
    tree = _until_tree("X IS NUMERIC", form)
    assert tree["operator"] == "IS NUMERIC"
    assert tree["left_operand"] == "X"


# An inline PERFORM's body cannot follow a period, so it has no period form.
@pytest.mark.parametrize("form", ["out-of-line", "varying"])
def test_line_break_matches_period(form: str) -> None:
    """``UNTIL WS-FLAG1`` + line break parses like ``UNTIL WS-FLAG1.``."""
    with_period = _FORMS[form].replace("{cond}\n", "{cond}.\n", 1)
    result = parse_cobol(_program(with_period.format(cond="WS-FLAG1")))
    assert result.ast is not None
    perform = result.ast.find_all_by_type("PerformStatement")[0]
    expected = perform.until_condition.condition_tree.to_dict()
    assert _until_tree("WS-FLAG1", form) == expected


def test_multi_line_condition_drops_every_line_break() -> None:
    tree = _until_tree("(A > 5)\n               OR (B = 1)", "inline")
    assert tree["operator"] == "OR"
    assert tree["left_condition"]["left_operand"] == "A"
    assert tree["right_condition"]["right_operand"] == "1"


def test_read_eof_idiom_yields_sequence_constraint() -> None:
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. EOFLOOP.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT INF ASSIGN TO INFILE.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       FD INF.\n"
        "       01 IN-REC PIC X(10).\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-EOF-SW PIC X VALUE 'N'.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n"
        "           OPEN INPUT INF\n"
        "           PERFORM UNTIL (WS-EOF-SW = 'Y')\n"
        "               READ INF\n"
        "                   AT END MOVE 'Y' TO WS-EOF-SW\n"
        "               END-READ\n"
        "           END-PERFORM\n"
        "           CLOSE INF\n"
        "           STOP RUN.\n"
    )
    result = parse_cobol(source)
    assert result.ast is not None
    ast = result.ast
    index = ProgramLayoutIndex.build(ast)
    boundaries = BoundaryInventoryAnalyzer().analyze(ast, index)
    report = ConstraintExtractor().extract(ast, index, boundaries)
    assert report.sequence_constraints
    assert not [u for u in report.unsupported if "PERFORM-UNTIL" in u]
