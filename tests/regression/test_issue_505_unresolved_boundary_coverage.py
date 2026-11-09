"""Issue #505: a SQL host variable, ACCEPT target, READ record or WRITE
record that did not resolve went only into the report-level ``unresolved``,
never the boundary's own, so ``gen-fixtures`` coverage counted the boundary
resolved although it got no fixture.  A host-variable array (OCCURS) never
resolves at all and now says so explicitly.
"""

from __future__ import annotations

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.generators import ProgramFixtureGenerator
from cobolparser.layout.program import ProgramLayoutIndex


def _program(statements: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. F2.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "           EXEC SQL INCLUDE SQLCA END-EXEC.\n"
        "       01  WS-TAB.\n"
        "           05 TB-NO   PIC X(6) OCCURS 5 TIMES.\n"
        "       01  I          PIC 9.\n"
        "       01  WS-OK      PIC X(6).\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n" + statements + "           GOBACK.\n"
    )


def _bundle(statements: str):
    result = parse_cobol(
        _program(statements),
        filename="f2.cbl",
        error_recovery=ErrorRecoveryMode.FAIL_FAST,
    )
    assert result.ast is not None, result.errors
    index = ProgramLayoutIndex.build(result.ast)
    report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    bundle = ProgramFixtureGenerator().generate(result.ast, index, report, seed=1)
    return result.ast, bundle


def test_unresolved_host_variables_are_unresolved_boundaries() -> None:
    _, bundle = _bundle(
        "           EXEC SQL SELECT NO INTO :NOPE FROM T END-EXEC\n"
        "           EXEC SQL SELECT NO INTO :TB-NO FROM T END-EXEC\n"
        "           DISPLAY TB-NO(1)\n"
    )
    assert bundle.scenarios[0].fixtures == []
    assert bundle.coverage.resolved_boundaries == 0
    assert bundle.coverage.unresolved_boundaries == 2
    assert any("host-variable array" in note for note in bundle.unresolved)
    # Each gap is listed once, not once from the report and again from
    # the boundary.
    assert len(bundle.unresolved) == len(set(bundle.unresolved))


def test_accept_into_a_table_element_is_unresolved() -> None:
    ast, bundle = _bundle("           ACCEPT TB-NO(I)\n")
    assert bundle.coverage.unresolved_boundaries == 1
    report = BoundaryInventoryAnalyzer().analyze(ast, ProgramLayoutIndex.build(ast))
    (boundary,) = report.boundaries
    assert boundary.unresolved and "OCCURS" in boundary.unresolved[0]


def test_resolved_host_variable_still_counts_resolved() -> None:
    _, bundle = _bundle("           EXEC SQL SELECT NO INTO :WS-OK FROM T END-EXEC\n")
    assert bundle.coverage.resolved_boundaries == 1
    assert bundle.coverage.unresolved_boundaries == 0
    assert len(bundle.scenarios[0].fixtures) == 1
