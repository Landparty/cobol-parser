"""A LINKAGE 01 that REDEFINES a USING parameter is referenced (#596).

``LinkageChecker`` marked a level-01 LINKAGE item referenced only when its own
name was on a USING / CALL / SET ADDRESS OF, so an overlay of the passed
parameter (or, the other way round, the base of a USING overlay) was reported
``UNREFERENCED_LINKAGE`` although it shares the parameter's storage.
"""

from __future__ import annotations

from cobolparser import LinkageChecker, LintAnalyzer, parse_cobol
from cobolparser.analysis.linkage_checker import LinkageViolationKind


def _source(*linkage: str, using: str) -> str:
    lines = (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. LK.",
        "DATA DIVISION.",
        "LINKAGE SECTION.",
        *linkage,
        f"PROCEDURE DIVISION USING {using}.",
        "    GOBACK.",
    )
    return "".join(f"       {line}\n" for line in lines)


def _unreferenced(source: str) -> set[str]:
    result = parse_cobol(source)
    assert result.success, result.errors
    report = LinkageChecker().check(result.ast)
    return {
        v.item_name
        for v in report.violations
        if v.kind is LinkageViolationKind.UNREFERENCED_LINKAGE
    }


def test_overlay_of_using_parameter_is_referenced():
    source = _source(
        "01 LK-A PIC X(10).",
        "01 LK-B REDEFINES LK-A PIC 9(10).",
        "01 LK-UNUSED PIC X(4).",
        using="LK-A",
    )
    assert _unreferenced(source) == {"LK-UNUSED"}


def test_base_of_using_overlay_is_referenced():
    source = _source(
        "01 LK-A PIC X(10).",
        "01 LK-B REDEFINES LK-A PIC 9(10).",
        using="LK-B",
    )
    assert _unreferenced(source) == set()


def test_redefines_chain_shares_the_reference():
    source = _source(
        "01 LK-A PIC X(10).",
        "01 LK-B REDEFINES LK-A PIC 9(10).",
        "01 LK-C REDEFINES LK-A.",
        "   05 LK-C1 PIC X(5).",
        "   05 LK-C2 PIC X(5).",
        using="LK-C",
    )
    assert _unreferenced(source) == set()


def test_unpassed_redefines_group_is_still_reported():
    source = _source(
        "01 LK-P PIC X(4).",
        "01 LK-A PIC X(10).",
        "01 LK-B REDEFINES LK-A PIC 9(10).",
        using="LK-P",
    )
    assert _unreferenced(source) == {"LK-A", "LK-B"}


def test_lint_has_no_linkage_finding_for_the_overlay():
    source = _source(
        "01 LK-A PIC X(10).",
        "01 LK-B REDEFINES LK-A PIC 9(10).",
        using="LK-A",
    )
    ast = parse_cobol(source).ast
    assert LintAnalyzer(["linkage-check"]).analyze(ast).findings == []
