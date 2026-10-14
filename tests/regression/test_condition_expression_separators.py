"""Regression coverage for #386: a separator ``,`` / ``;`` after a condition,
EVALUATE subject or COMPUTE expression became part of its text.

In COBOL a comma or semicolon used as a separator is a space. The IF and
PERFORM UNTIL condition collectors, the EVALUATE subject collector and the
COMPUTE expression collector already dropped NEWLINE but kept the separator,
so ``IF X = 1,`` compared X with ``"1 ,"``, ``IF X-ON;`` no longer read as a
condition-name test, and ``COMPUTE Z = X + Y,`` lost its expression tree.
A comma inside parentheses (a function's argument list) is still kept.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol


def _parse(body: str):
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 X PIC 9.\n"
        "          88 X-ON VALUE 1.\n"
        "       01 Y PIC 9.\n"
        "       01 Z PIC 99.\n"
        "       PROCEDURE DIVISION.\n"
        f"{body}"
        "           STOP RUN.\n"
        "       P1.\n"
        "           ADD 1 TO X.\n"
    )
    result = parse_cobol(src)
    assert result.errors == []
    return result.ast.get_all_statements()


def _first(stmts, cls_name):
    return next(s for s in stmts if type(s).__name__ == cls_name).to_dict()


@pytest.mark.parametrize("sep", [",", ";"])
def test_if_condition_name_followed_by_separator(sep):
    stmts = _parse(f"           IF X-ON{sep} MOVE 3 TO Y END-IF.\n")
    cond = _first(stmts, "IfStatement")["condition"]
    assert cond["operator"] == "CONDITION_NAME"
    assert cond["left_operand"] == "X-ON"
    assert [type(s).__name__ for s in stmts][:2] == ["IfStatement", "MoveStatement"]


@pytest.mark.parametrize("sep", [",", ";"])
def test_if_comparison_followed_by_separator(sep):
    stmts = _parse(f"           IF X = 1{sep} MOVE 3 TO Y END-IF.\n")
    cond = _first(stmts, "IfStatement")["condition"]
    assert cond["operator"] == "EQUAL"
    assert cond["left_operand"] == "X"
    assert cond["right_operand"] == "1"


def test_if_separator_before_then():
    stmts = _parse("           IF X = 1, THEN MOVE 3 TO Y END-IF.\n")
    assert _first(stmts, "IfStatement")["condition"]["right_operand"] == "1"


def test_inline_perform_until_followed_by_separator():
    stmts = _parse("           PERFORM UNTIL X-ON; ADD 1 TO X END-PERFORM.\n")
    until = _first(stmts, "PerformStatement")["until_condition"]
    assert until["operands"] == ["X-ON"]
    assert until["condition_tree"]["operator"] == "CONDITION_NAME"


def test_out_of_line_perform_until_followed_by_separator():
    stmts = _parse("           PERFORM P1 UNTIL X = 1, DISPLAY Y.\n")
    until = _first(stmts, "PerformStatement")["until_condition"]
    assert until["operands"] == ["X = 1"]
    assert "DisplayStatement" in [type(s).__name__ for s in stmts]


def test_perform_varying_until_followed_by_separator():
    stmts = _parse(
        "           PERFORM VARYING X FROM 1 BY 1 UNTIL X > 5;\n"
        "               ADD 1 TO Y\n"
        "           END-PERFORM.\n"
    )
    perform = _first(stmts, "PerformStatement")
    assert "X > 5" in str(perform)
    assert "X > 5 ;" not in str(perform)


@pytest.mark.parametrize("sep", [",", ";"])
def test_evaluate_subject_followed_by_separator(sep):
    stmts = _parse(f"           EVALUATE Y{sep} WHEN 1 CONTINUE END-EVALUATE.\n")
    assert _first(stmts, "EvaluateStatement")["subjects"] == ["Y"]


def test_evaluate_subjects_separated_by_also_and_separator():
    stmts = _parse(
        "           EVALUATE X, ALSO Y; WHEN 1 ALSO 2 CONTINUE END-EVALUATE.\n"
    )
    assert _first(stmts, "EvaluateStatement")["subjects"] == ["X", "Y"]


@pytest.mark.parametrize("sep", [",", ";"])
def test_compute_expression_followed_by_separator(sep):
    stmts = _parse(f"           COMPUTE Z = X + Y{sep} DISPLAY Z.\n")
    compute = _first(stmts, "ComputeStatement")
    assert compute["expression"] == "X + Y"
    assert compute["expression_tree"]["operator"] == "+"
    assert "DisplayStatement" in [type(s).__name__ for s in stmts]


def test_comma_inside_function_arguments_is_kept():
    stmts = _parse(
        "           COMPUTE Z = FUNCTION MAX(X, Y), DISPLAY Z.\n"
        "           IF FUNCTION MAX(X, Y) > 1, DISPLAY Z END-IF.\n"
    )
    assert _first(stmts, "ComputeStatement")["expression"].endswith("( X , Y )")
    cond = _first(stmts, "IfStatement")["condition"]
    assert "," in str(cond)
    assert cond.get("right_operand") != "1 ,"
