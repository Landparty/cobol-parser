"""Very long AND/OR chains and very deep nesting (#375).

``build_condition_expression`` recursed once per AND/OR term, so a chain of
~1,000 terms hit Python's recursion limit and the IF was dropped (and 3,000
terms took seconds: every level re-cleaned and sliced the token list). Deep
nesting hit the limit in ``try_parse_nested_statement``, which only warned,
leaving ``success=True`` with statements missing from the AST.

Decision taken (the issue's suggestion): build chains in one pass, and let a
RecursionError from nesting reach the statement loop as an error.
"""

from __future__ import annotations

import time

import pytest

from cobolparser import (
    CobolParser,
    ErrorRecoveryMode,
    UnusedVariableAnalyzer,
    parse_cobol,
)
from cobolparser.analysis.program_flow.condition_text import render_condition_text


def _program(body: str) -> str:
    head = (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. D.\n"
        "       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
        "       01 A PIC 9.\n       01 B PIC 9.\n       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
    )
    return head + body + "           STOP RUN.\n"


def _chain(terms: list[str], joiner: str) -> str:
    lines, line = [], "           IF"
    for index, term in enumerate(terms):
        piece = f" {term}" if index == 0 else f" {joiner} {term}"
        if len(line) + len(piece) > 70:
            lines.append(line)
            line = "              "
        line += piece
    lines.append(line)
    return "\n".join(lines) + "\n               DISPLAY 'X'\n           END-IF\n"


def _if(result):
    (stmt,) = [s for s in result.ast.get_all_statements() if s.statement_type == "IF"]
    return stmt


@pytest.mark.parametrize("joiner", ["OR", "AND"])
def test_long_chain_parses_quickly_and_is_walkable(joiner: str) -> None:
    source = _program(_chain([f"A = {i % 10}" for i in range(3000)], joiner))
    start = time.perf_counter()
    result = parse_cobol(source)
    elapsed = time.perf_counter() - start
    assert result.success, result.errors
    assert elapsed < 5
    stmt = _if(result)
    # The tree is shallow enough for every recursive walker.
    stmt.to_dict()
    assert render_condition_text(stmt.condition).count(joiner) == 2999
    UnusedVariableAnalyzer().analyze(result.ast)


def test_short_chain_keeps_its_left_deep_shape() -> None:
    stmt = _if(parse_cobol(_program(_chain(["A = 1", "B = 2", "A = 3"], "OR"))))
    tree = stmt.condition
    assert tree.operator == "OR"
    assert tree.left_condition.operator == "OR"
    assert tree.right_condition.operator == "EQUAL"


def test_abbreviated_legs_still_expand_in_a_long_chain() -> None:
    # ``A = 1 OR 2 OR 3 ...``: every bare literal repeats ``A =``.
    stmt = _if(parse_cobol(_program(_chain(["A = 1"] + ["2"] * 99, "OR"))))
    text = render_condition_text(stmt.condition)
    assert text.count("A = 2") == 99


@pytest.mark.parametrize(
    "mode", [ErrorRecoveryMode.FAIL_FAST, ErrorRecoveryMode.COLLECT_ALL]
)
def test_too_deep_nesting_is_an_error_not_a_silent_drop(mode) -> None:
    depth = 1500
    body = (
        "           IF A = 1\n" * depth
        + "           DISPLAY 'X'\n"
        + "           END-IF\n" * depth
    )
    result = CobolParser(error_recovery=mode).parse(_program(body))
    assert not result.success
    assert any("nested too deeply" in str(e) for e in result.errors)
    assert not any("Nested statement parse failed" in w for w in result.warnings)
