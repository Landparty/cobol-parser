"""Time budgets for every analyzer on one large generated program.

The survey that set these numbers (2026-10-28) found every analyzer linear
up to 43,000 lines; ``business-rules`` was slightly superlinear. Nothing in
the rest of the suite would notice an analyzer that turned quadratic: test
programs are tens of lines, and a shop's programs are tens of thousands.

Two lanes:

* By default a program of :data:`DEFAULT_LINES` lines, each analyzer held to
  a budget scaled from the large-lane one. Cheap (a few seconds), and enough
  to catch an order-of-magnitude regression.
* ``COBOLPARSER_PERF=1``: a program of :data:`LARGE_LINES` lines against the
  full budgets, plus a scaling check -- each analyzer timed at a quarter of
  that size and at the full size, and the ratio held under
  :data:`MAX_SCALING_RATIO` (linear is 4, quadratic 16).

Budgets are wall-clock, so like ``test_factory_performance.py`` the lane is
skipped under a tracer (coverage.py, a debugger): there it measures the
tracer. They are roughly three times the times measured on the survey's
machine, so a slower laptop still passes and a quadratic analyzer does not.
"""

# `sys` is used only by the string skipif condition below, which pytest
# evaluates against this module's namespace -- ruff cannot see that use.
import os
import sys  # noqa: F401
import time
from collections.abc import Callable
from functools import cache
from typing import Any

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        "sys.gettrace() is not None",
        reason="wall-clock budgets mean nothing under a tracer (coverage, debugger)",
    ),
]

LARGE = os.environ.get("COBOLPARSER_PERF") == "1"
LARGE_LINES = 40_000
DEFAULT_LINES = 4_000
MAX_SCALING_RATIO = 8.0

#: Seconds allowed at LARGE_LINES, per analyzer.
BUDGETS: dict[str, float] = {
    "parse": 8.0,
    "dead-code": 6.0,
    "unused-variables": 6.0,
    "program-flow": 6.0,
    "recursion-check": 6.0,
    "complexity": 8.0,
    "redundancy": 12.0,
    "health": 25.0,
    "business-rules": 25.0,
    "lineage": 15.0,
    "xref": 8.0,
    "move-type-check": 6.0,
    "program-signature": 3.0,
    "lint": 40.0,
}


def generate_program(lines: int) -> str:
    """A fixed-format program of about *lines* lines: a WORKING-STORAGE pool
    and one ten-line paragraph after another, each with an IF, a COMPUTE, a
    MOVE, an EVALUATE and a PERFORM or GO TO of a later paragraph -- so
    every analyzer has real work. Every line fits column 72."""
    paragraphs = max(1, (lines - 40) // 12)
    fields = max(10, paragraphs // 20)
    out = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. BIGPROG.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        "       01  WS-SWITCH            PIC X VALUE 'N'.",
        "           88  WS-DONE          VALUE 'Y'.",
    ]
    for i in range(fields):
        out.append(f"       01  WS-A{i:05d}           PIC S9(7) COMP-3.")
        out.append(f"       01  WS-T{i:05d}           PIC X(10).")
    out += ["       PROCEDURE DIVISION.", "       P00000."]
    out.append("           PERFORM P00001")
    out.append("           STOP RUN.")
    for p in range(1, paragraphs + 1):
        a = f"WS-A{p % fields:05d}"
        b = f"WS-A{(p * 7) % fields:05d}"
        t = f"WS-T{p % fields:05d}"
        out.append(f"       P{p:05d}.")
        out.append(f"           IF {a} > {p % 997}")
        out.append(f"              COMPUTE {b} = {a} * 3 + {p % 13}")
        out.append("           ELSE")
        out.append(f"              MOVE 'P{p:05d}' TO {t}")
        out.append("           END-IF")
        out.append(f"           EVALUATE {b}")
        out.append(f"              WHEN 1 MOVE 'ONE' TO {t}")
        out.append(f"              WHEN 2 ADD 1 TO {a}")
        out.append("              WHEN OTHER CONTINUE")
        out.append("           END-EVALUATE")
        if p < paragraphs:
            if p % 5 == 0:
                out.append(f"           GO TO P{p + 1:05d}.")
            else:
                out.append(f"           PERFORM P{p + 1:05d}.")
        else:
            out.append("           SET WS-DONE TO TRUE.")
    return "\n".join(out) + "\n"


@cache
def _parsed(lines: int) -> Any:
    result = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(
        generate_program(lines)
    )
    assert result.ast is not None and not result.errors, result.errors[:3]
    return result.ast


def _analyzers() -> dict[str, Callable[[Any], Any]]:
    from cobolparser import (
        BusinessRuleExtractor,
        ComplexityAnalyzer,
        DeadCodeAnalyzer,
        LintAnalyzer,
        MoveTypeChecker,
        ProgramFlowAnalyzer,
        RecursionRiskAnalyzer,
        RedundancyAnalyzer,
        TechnicalDebtAnalyzer,
        UnusedVariableAnalyzer,
    )
    from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
    from cobolparser.analysis.program_signature import ProgramSignatureExtractor
    from cobolparser.analysis.xref import XrefAnalyzer

    return {
        "dead-code": lambda ast: DeadCodeAnalyzer().analyze(ast),
        "unused-variables": lambda ast: UnusedVariableAnalyzer().analyze(ast),
        "program-flow": lambda ast: ProgramFlowAnalyzer().analyze(ast),
        "recursion-check": lambda ast: RecursionRiskAnalyzer().analyze(ast),
        "complexity": lambda ast: ComplexityAnalyzer().analyze(ast),
        "redundancy": lambda ast: RedundancyAnalyzer().analyze(ast),
        "health": lambda ast: TechnicalDebtAnalyzer().analyze(ast),
        "business-rules": lambda ast: BusinessRuleExtractor().analyze(ast),
        "lineage": lambda ast: FieldFlowAnalyzer().analyze(ast),
        "xref": lambda ast: XrefAnalyzer().analyze(ast),
        "move-type-check": lambda ast: MoveTypeChecker().check(ast),
        "program-signature": lambda ast: ProgramSignatureExtractor().analyze(ast),
        "lint": lambda ast: LintAnalyzer().analyze(ast),
    }


def _time(name: str, lines: int) -> float:
    if name == "parse":
        source = generate_program(lines)
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        started = time.perf_counter()
        parser.parse(source)
        return time.perf_counter() - started
    ast = _parsed(lines)
    run = _analyzers()[name]
    started = time.perf_counter()
    run(ast)
    return time.perf_counter() - started


def test_generated_program_shape() -> None:
    source = generate_program(DEFAULT_LINES)
    lines = source.splitlines()
    assert abs(len(lines) - DEFAULT_LINES) < DEFAULT_LINES * 0.1
    assert max(len(line) for line in lines) <= 72


def test_every_analyzer_has_a_budget() -> None:
    assert set(BUDGETS) == {"parse", *_analyzers()}


@pytest.mark.parametrize("name", list(BUDGETS))
def test_within_budget(name: str) -> None:
    lines = LARGE_LINES if LARGE else DEFAULT_LINES
    # Below the large size fixed costs dominate, so the scaled budget keeps
    # a floor of one second.
    budget = max(1.0, BUDGETS[name] * lines / LARGE_LINES)
    elapsed = _time(name, lines)
    assert elapsed <= budget, f"{name}: {elapsed:.2f}s on {lines} lines > {budget}s"


@pytest.mark.skipif(not LARGE, reason="set COBOLPARSER_PERF=1 for the large lane")
@pytest.mark.parametrize("name", list(BUDGETS))
def test_scales_linearly(name: str) -> None:
    small = _time(name, LARGE_LINES // 4)
    large = _time(name, LARGE_LINES)
    if large < 0.5:
        return  # too fast to tell noise from growth
    ratio = large / max(small, 1e-3)
    assert ratio <= MAX_SCALING_RATIO, (
        f"{name}: {small:.2f}s at {LARGE_LINES // 4} lines, {large:.2f}s at "
        f"{LARGE_LINES} lines (x{ratio:.1f}; linear is x4)"
    )
