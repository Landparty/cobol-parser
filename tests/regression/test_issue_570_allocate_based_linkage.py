"""``ALLOCATE item`` gives a based LINKAGE item its storage (#570).

``LinkageChecker`` exempted ``SET ADDRESS OF item`` but not ``ALLOCATE item``
(the same based-item idiom), so a correct program got an
``UNREFERENCED_LINKAGE`` warning through ``linkage-check`` and ``lint``. xref
had no role mapping for ALLOCATE / FREE, so the RETURNING pointer that
ALLOCATE writes and the pointer FREE nulls were plain references.
"""

from __future__ import annotations

from cobolparser import LinkageChecker, LintAnalyzer, parse_cobol
from cobolparser.analysis.linkage_checker import LinkageViolationKind
from cobolparser.analysis.xref import XrefAnalyzer

SOURCE = "".join(
    f"       {line}\n"
    for line in (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. ALLOC2.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01 WS-PTR USAGE POINTER.",
        "01 WS-N PIC 9(4) VALUE 10.",
        "LINKAGE SECTION.",
        "01 LK-BUF PIC X(100).",
        "01 LK-BUF2 PIC X(10).",
        "01 LK-UNUSED PIC X(10).",
        "PROCEDURE DIVISION.",
        "MAIN-PARA.",
        "    ALLOCATE LK-BUF INITIALIZED RETURNING WS-PTR",
        "    ALLOCATE LK-BUF2",
        "    ALLOCATE WS-N CHARACTERS RETURNING WS-PTR",
        "    DISPLAY LK-BUF",
        "    FREE WS-PTR",
        "    GOBACK.",
    )
)


def _ast():
    result = parse_cobol(SOURCE)
    assert result.success, result.errors
    return result.ast


def test_allocated_linkage_item_is_referenced():
    report = LinkageChecker().check(_ast())
    unreferenced = {
        v.item_name
        for v in report.violations
        if v.kind is LinkageViolationKind.UNREFERENCED_LINKAGE
    }
    assert unreferenced == {"LK-UNUSED"}


def test_lint_reports_only_the_unused_item():
    findings = LintAnalyzer(["linkage-check"]).analyze(_ast()).findings
    assert [f.symbol for f in findings] == ["LK-UNUSED"]


def test_xref_roles_for_allocate_and_free():
    report = XrefAnalyzer().analyze(_ast())
    roles = {
        entry.name: sorted((ref.role, ref.statement) for ref in entry.references)
        for entry in report.entries
    }
    assert roles["LK-BUF"] == [
        ("read", "DisplayStatement"),
        ("reference", "AllocateStatement"),
    ]
    assert roles["LK-BUF2"] == [("reference", "AllocateStatement")]
    assert roles["WS-N"] == [("read", "AllocateStatement")]
    assert roles["WS-PTR"] == [
        ("write", "AllocateStatement"),
        ("write", "AllocateStatement"),
        ("write", "FreeStatement"),
    ]
    assert not report.caveats
