"""Regression tests for issue #403.

An abbreviated combined relation may open its second leg with the optional
``IS`` of the relational operator (``IF A > 1 AND IS < 5``). That ``IS``
used to survive into the leg, so the leg was not recognised as operator-led
and became a COMPARISON with no operands -- and every analyzer reading the
condition tree (constraints, scenarios, business rules) lost it.
"""

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol


def _source(statement: str) -> str:
    return (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. T.\n"
        "DATA DIVISION.\n"
        "WORKING-STORAGE SECTION.\n"
        "01 A PIC 9.\n"
        "PROCEDURE DIVISION.\n"
        "MAIN-PARA.\n"
        f"    {statement}\n"
        "    STOP RUN.\n"
    )


def _strip(node):
    if isinstance(node, dict):
        return {
            k: _strip(v)
            for k, v in node.items()
            if k not in ("location", "node_type", "operands", "metadata")
            and v is not None
        }
    return node


def _cmp(op, left, right):
    return {
        "expression_type": "COMPARISON",
        "operator": op,
        "left_operand": left,
        "right_operand": right,
        "condition_type": "COMPARISON",
    }


def _if_condition(condition: str):
    result = parse_cobol(
        _source(f"IF {condition} DISPLAY 'X' END-IF."),
        free_form=True,
        error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    )
    assert not result.errors
    (stmt,) = result.ast.find_all_by_type("IfStatement")
    return _strip(stmt.to_dict()["condition"])


CASES = [
    ("A > 1 AND IS < 5", "AND", _cmp("GREATER", "A", "1"), _cmp("LESS", "A", "5")),
    (
        "A IS GREATER THAN 1 AND IS LESS THAN 5",
        "AND",
        _cmp("GREATER", "A", "1"),
        _cmp("LESS", "A", "5"),
    ),
    (
        "A = 1 OR IS EQUAL TO 2",
        "OR",
        _cmp("EQUAL", "A", "1"),
        _cmp("EQUAL", "A", "2"),
    ),
    (
        "A > 1 AND IS NOT > 5",
        "AND",
        _cmp("GREATER", "A", "1"),
        _cmp("LESS_OR_EQUAL", "A", "5"),
    ),
    (
        "A IS GREATER THAN 1 AND IS NOT GREATER THAN 5",
        "AND",
        _cmp("GREATER", "A", "1"),
        _cmp("LESS_OR_EQUAL", "A", "5"),
    ),
]


@pytest.mark.parametrize(("condition", "op", "left", "right"), CASES)
def test_leading_is_leg_is_expanded(condition, op, left, right):
    assert _if_condition(condition) == {
        "expression_type": "LOGICAL",
        "operator": op,
        "left_condition": left,
        "right_condition": right,
    }


@pytest.mark.parametrize(("condition", "op", "left", "right"), CASES)
def test_leading_is_matches_the_form_without_is(condition, op, left, right):
    without_is = condition.replace(" AND IS ", " AND ").replace(" OR IS ", " OR ")
    assert _if_condition(condition) == _if_condition(without_is)


def test_leading_is_leg_under_a_further_or():
    cond = _if_condition("A > 1 AND IS < 5 OR IS = 9")
    assert cond["operator"] == "OR"
    assert cond["left_condition"]["right_condition"] == _cmp("LESS", "A", "5")
    assert cond["right_condition"] == _cmp("EQUAL", "A", "9")


def test_perform_until_leading_is_leg():
    result = parse_cobol(
        _source("PERFORM UNTIL A > 1 AND IS < 5 DISPLAY 'Y' END-PERFORM."),
        free_form=True,
        error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    )
    assert not result.errors
    (perform,) = result.ast.find_all_by_type("PerformStatement")
    tree = _strip(perform.until_condition.to_dict()["condition_tree"])
    assert tree["left_condition"] == _cmp("GREATER", "A", "1")
    assert tree["right_condition"] == _cmp("LESS", "A", "5")


def test_bare_identifier_after_is_is_left_alone():
    # ``IS`` before something that is not an operator is not this form;
    # nothing is invented for it.
    cond = _if_condition("A = 1 OR IS 2")
    assert cond["right_condition"].get("left_operand") != "A"
