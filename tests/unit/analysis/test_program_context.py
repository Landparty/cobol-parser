"""ProgramContext: one program unit's xref, flow graph and procedure index,
each built at most once and shared by every analyzer handed the context."""

from __future__ import annotations

from unittest import mock

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.complexity import ComplexityAnalyzer
from cobolparser.analysis.context import ProgramContext
from cobolparser.analysis.lint import LintAnalyzer
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.analysis.program_signature import ProgramSignatureExtractor
from cobolparser.analysis.recursion_risk import RecursionRiskAnalyzer
from cobolparser.analysis.technical_debt import TechnicalDebtAnalyzer
from cobolparser.analysis.xref import XrefAnalyzer

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CTXTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(4) VALUE 0.
       01 WS-B PIC 9(4).
       LINKAGE SECTION.
       01 LK-OUT PIC 9(4).
       PROCEDURE DIVISION USING LK-OUT.
       MAIN-PARA.
           PERFORM CALC-PARA
           IF WS-A > 10
               MOVE WS-A TO LK-OUT
           END-IF
           GOBACK.
       CALC-PARA.
           ADD 1 TO WS-A
           MOVE WS-A TO WS-B.
"""


@pytest.fixture
def ast():
    result = parse_cobol(SOURCE)
    assert result.ast is not None
    return result.ast


def _counting(cls):
    """Patch *cls*.analyze to count the bare-AST builds it does."""
    real = cls.analyze
    calls: list[object] = []

    def counted(self, target, *args, **kwargs):
        if not isinstance(target, ProgramContext):
            calls.append(target)
        return real(self, target, *args, **kwargs)

    return mock.patch.object(cls, "analyze", counted), calls


def test_facts_are_built_once_and_shared(ast):
    ctx = ProgramContext(ast)
    assert ctx.flow is ctx.flow
    assert ctx.xref is ctx.xref
    assert ctx.procedures is ctx.procedures
    assert ctx.procedures is not None
    assert [e.name for e in ctx.procedures.entries] == ["MAIN-PARA", "CALC-PARA"]


def test_analyzers_return_the_context_fact(ast):
    ctx = ProgramContext(ast)
    assert XrefAnalyzer().analyze(ctx) is ctx.xref
    assert ProgramFlowAnalyzer().analyze(ctx) is ctx.flow


def test_of_returns_the_same_context_and_seeds_flow(ast):
    ctx = ProgramContext(ast)
    assert ProgramContext.of(ctx) is ctx
    fresh = ProgramContext.of(ast)
    assert fresh is not ctx and fresh.ast is ast

    flow = ProgramFlowAnalyzer().analyze(ast)
    assert ProgramContext.of(ast, flow=flow).flow is flow
    built = ctx.flow
    assert ProgramContext.of(ctx, flow=flow).flow is built  # never replaced


def test_no_procedure_division():
    result = parse_cobol("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. EMPTY.\n")
    assert ProgramContext(result.ast).procedures is None


def test_unit_contexts_are_kept(ast):
    ctx = ProgramContext(ast)
    assert ctx.unit(ast) is ctx
    other = parse_cobol(SOURCE).ast
    child = ctx.unit(other)
    assert child.ast is other and ctx.unit(other) is child


def test_bare_ast_and_context_give_the_same_reports(ast):
    ctx = ProgramContext(ast)
    for analyzer in (
        ComplexityAnalyzer,
        RecursionRiskAnalyzer,
        ProgramSignatureExtractor,
    ):
        assert analyzer().analyze(ast).to_dict() == analyzer().analyze(ctx).to_dict()
    assert (
        LintAnalyzer().analyze(ast).to_dict() == LintAnalyzer().analyze(ctx).to_dict()
    )


def test_lint_builds_flow_and_xref_once(ast):
    flow_patch, flow_calls = _counting(ProgramFlowAnalyzer)
    xref_patch, xref_calls = _counting(XrefAnalyzer)
    with flow_patch, xref_patch:
        LintAnalyzer().analyze(ast)
    assert len(flow_calls) == 1
    assert len(xref_calls) == 1


def test_technical_debt_shares_the_callers_flow(ast):
    ctx = ProgramContext(ast)
    ctx.flow  # noqa: B018 - built before the analyzer runs
    flow_patch, flow_calls = _counting(ProgramFlowAnalyzer)
    with flow_patch:
        TechnicalDebtAnalyzer().analyze(ctx)
    assert flow_calls == []
