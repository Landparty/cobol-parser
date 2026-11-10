"""Every single-program analyzer has the shared shape:
``Analyzer(...).analyze(ast) -> report`` with ``report.to_dict()``.

A new analyzer class lands in exactly one of the two lists below: the test
that discovers analyzer classes fails until it does, so "does it fit the
common interface?" is answered when the class is added.
"""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil

import pytest

import cobolparser.analysis as analysis_pkg
from cobolparser import parse_cobol
from cobolparser.analysis.context import ProgramContext
from cobolparser.analysis.protocol import ProgramAnalyzer, Report

pytestmark = pytest.mark.contract

#: module -> class: ``analyze(ast)`` alone, returning a :class:`Report`.
CONFORMING = {
    "bug_patterns": "BugPatternAnalyzer",
    "business_rules": "BusinessRuleExtractor",
    "code_patterns": "CodePatternAnalyzer",
    "compiler_checks": "CompilerCheckAnalyzer",
    "complexity": "ComplexityAnalyzer",
    "crud_matrix": "CRUDMatrixGenerator",
    "dclgen_check": "DclgenChecker",
    "dead_code": "DeadCodeAnalyzer",
    "field_lineage": "FieldFlowAnalyzer",
    "host_var_resolver": "HostVariableResolver",
    "input_dependence": "InputDependenceAnalyzer",
    "io_logger": "IOLogger",
    "io_sequence": "IOSequenceAnalyzer",
    "language_env_analyzer": "LanguageEnvironmentAnalyzer",
    "linkage_checker": "LinkageChecker",
    "lint": "LintAnalyzer",
    "move_type_checker": "MoveTypeChecker",
    "program_flow.analyzer": "ProgramFlowAnalyzer",
    "program_signature": "ProgramSignatureExtractor",
    "recursion_risk": "RecursionRiskAnalyzer",
    "redundancy": "RedundancyAnalyzer",
    "sql_cics_lint": "SqlCicsAnalyzer",
    "technical_debt": "TechnicalDebtAnalyzer",
    "unused_variables": "UnusedVariableAnalyzer",
    "xref": "XrefAnalyzer",
}

#: Classes with an ``analyze`` that is deliberately not the shared shape.
EXCEPTIONS = {
    "boundary_inventory.BoundaryInventoryAnalyzer": "needs a ProgramLayoutIndex",
    "codebase.CopybookImpactAnalyzer": "answers about a codebase graph",
    "field_widening.FieldWideningAnalyzer": "answers about a codebase graph",
    "ims_segment_analyzer.IMSSegmentAnalyzer": "returns a plain list of calls",
    "value_tracker.DynamicCallAnalyzer": "annotates the AST, returns None",
}

#: Analyzers that also take a ProgramContext in place of the AST.
CONTEXT_AWARE = {
    "BugPatternAnalyzer",
    "CodePatternAnalyzer",
    "CompilerCheckAnalyzer",
    "ComplexityAnalyzer",
    "LintAnalyzer",
    "ProgramFlowAnalyzer",
    "ProgramSignatureExtractor",
    "RecursionRiskAnalyzer",
    "TechnicalDebtAnalyzer",
    "XrefAnalyzer",
}

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROTO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(4) VALUE 0.
       01 WS-B PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM CALC-PARA
           IF WS-A > 10
               MOVE 'BIG' TO WS-B
           END-IF
           STOP RUN.
       CALC-PARA.
           ADD 1 TO WS-A.
"""


def _class(module: str, name: str) -> type:
    return getattr(importlib.import_module(f"cobolparser.analysis.{module}"), name)


def _discovered() -> set[str]:
    found: set[str] = set()
    for info in pkgutil.walk_packages(
        analysis_pkg.__path__, analysis_pkg.__name__ + "."
    ):
        module = importlib.import_module(info.name)
        short = info.name.removeprefix(analysis_pkg.__name__ + ".")
        for name, value in vars(module).items():
            if (
                inspect.isclass(value)
                and value.__module__ == module.__name__
                and not name.startswith("_")
                and value is not ProgramAnalyzer
                and callable(getattr(value, "analyze", None))
            ):
                found.add(f"{short}.{name}")
    return found


def test_every_analyzer_class_is_classified():
    listed = {f"{m}.{c}" for m, c in CONFORMING.items()} | set(EXCEPTIONS)
    assert _discovered() == listed


@pytest.fixture(scope="module")
def ast():
    result = parse_cobol(SOURCE)
    assert result.ast is not None
    return result.ast


@pytest.mark.parametrize("module,name", sorted(CONFORMING.items()))
def test_conforming_analyzer_returns_a_report(module, name, ast):
    analyzer = _class(module, name)()
    assert isinstance(analyzer, ProgramAnalyzer)
    report = analyzer.analyze(ast)
    assert isinstance(report, Report)
    json.dumps(report.to_dict(), default=str)


@pytest.mark.parametrize(
    "module,name", sorted((m, c) for m, c in CONFORMING.items() if c in CONTEXT_AWARE)
)
def test_context_aware_analyzers_accept_a_context(module, name, ast):
    ctx = ProgramContext(ast)
    from_ctx = _class(module, name)().analyze(ctx).to_dict()
    assert from_ctx == _class(module, name)().analyze(ast).to_dict()
