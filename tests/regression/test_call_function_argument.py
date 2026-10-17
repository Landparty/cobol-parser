"""Issue #579: ``CALL ... USING BY CONTENT FUNCTION f(x)`` was split into two
arguments, ``FUNCTION`` and ``f ( x )`` taken as a subscripted name, so every
later argument sat one position too far right. Anything pairing a caller's
argument with the callee's formal parameter in the same position -- field
lineage, ``field-impact``, gen-fixtures -- then joined the wrong parameters
or none, with no caveat.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.analysis.lineage_graph import LineageGraph
from cobolparser.generators import ProgramFixtureGenerator

CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NAME PIC X(10).
       01 WS-RESULT PIC X(10).
       PROCEDURE DIVISION.
           ACCEPT WS-NAME
{call}
           DISPLAY WS-RESULT
           GOBACK.
"""

CALLEE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLEE.
       DATA DIVISION.
       LINKAGE SECTION.
       01 L-IN PIC X(10).
       01 L-OUT PIC X(10).
       PROCEDURE DIVISION USING L-IN L-OUT.
           MOVE L-IN TO L-OUT
           MOVE SPACES TO L-IN
           GOBACK.
"""

ISSUE_CALL = (
    "           CALL 'CALLEE' USING BY CONTENT FUNCTION UPPER-CASE(WS-NAME)\n"
    "                               BY REFERENCE WS-RESULT"
)


def _ast(source: str, name: str):
    result = parse_cobol(source, filename=f"{name}.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    return result.ast


def _arguments(call: str) -> list[tuple[str, str]]:
    ast = _ast(CALLER.format(call=call), "CALLER")
    (stmt,) = ast.find_all_by_type("CallStatement")
    return [(p.name, p.passing_mode) for p in stmt.using_parameters]


@pytest.mark.parametrize(
    ("call", "first"),
    [
        (ISSUE_CALL, ("FUNCTION UPPER-CASE(WS-NAME)", "CONTENT")),
        (
            "           CALL 'CALLEE' USING FUNCTION CURRENT-DATE WS-RESULT",
            ("FUNCTION CURRENT-DATE", "REFERENCE"),
        ),
        (
            "           CALL 'CALLEE' USING FUNCTION CURRENT-DATE(1:8)\n"
            "               WS-RESULT",
            ("FUNCTION CURRENT-DATE(1:8)", "REFERENCE"),
        ),
        (
            "           CALL 'CALLEE' USING FUNCTION UPPER-CASE(WS-NAME)(1:3)\n"
            "               WS-RESULT",
            ("FUNCTION UPPER-CASE(WS-NAME)(1:3)", "REFERENCE"),
        ),
        (
            "           CALL 'CALLEE' USING BY VALUE FUNCTION MAX(WS-NAME, 3)\n"
            "               BY REFERENCE WS-RESULT",
            ("FUNCTION MAX(WS-NAME, 3)", "VALUE"),
        ),
        (
            "           CALL 'CALLEE' USING BY CONTENT\n"
            "               FUNCTION TRIM(WS-NAME LEADING) WS-RESULT",
            ("FUNCTION TRIM(WS-NAME LEADING)", "CONTENT"),
        ),
        (
            "           CALL 'CALLEE' USING FUNCTION LOWER-CASE('ABC')\n"
            "               WS-RESULT",
            # quoted the way MOVE and DISPLAY quote a literal
            ('FUNCTION LOWER-CASE("ABC")', "REFERENCE"),
        ),
    ],
)
def test_function_argument_is_one_parameter(call: str, first) -> None:
    arguments = _arguments(call)
    assert len(arguments) == 2, arguments
    assert arguments[0] == first
    assert arguments[1][0] == "WS-RESULT"


def test_function_argument_spelled_like_a_move_source() -> None:
    ast = _ast(
        CALLER.format(
            call="           MOVE FUNCTION UPPER-CASE(WS-NAME) TO WS-RESULT\n"
            + ISSUE_CALL
        ),
        "CALLER",
    )
    (move,) = ast.find_all_by_type("MoveStatement")
    (call,) = ast.find_all_by_type("CallStatement")
    assert call.using_parameters[0].name == move.source


def _graph(call: str) -> LineageGraph:
    reports = [
        FieldFlowAnalyzer().analyze(_ast(CALLER.format(call=call), "CALLER")),
        FieldFlowAnalyzer().analyze(_ast(CALLEE, "CALLEE")),
    ]
    return LineageGraph(reports)


def test_lineage_joins_the_argument_after_the_function() -> None:
    result = _graph(ISSUE_CALL).impact(
        "WS-RESULT", program="CALLER", direction="backward"
    )
    hits = {(h.program, h.field) for h in result.hits}
    assert ("CALLEE", "L-OUT") in hits
    assert ("CALLEE", "L-IN") in hits
    assert ("CALLER", "WS-NAME") in hits


def test_function_argument_by_reference_flows_one_way() -> None:
    # A function result is a temporary: the callee's write to L-IN cannot
    # reach WS-NAME, even when the argument is passed BY REFERENCE.
    graph = _graph(
        "           CALL 'CALLEE' USING FUNCTION UPPER-CASE(WS-NAME)\n"
        "               WS-RESULT"
    )
    result = graph.impact("L-IN", program="CALLEE")
    assert ("CALLER", "WS-NAME") not in {(h.program, h.field) for h in result.hits}
    backward = graph.impact("WS-RESULT", program="CALLER", direction="backward")
    assert ("CALLER", "WS-NAME") in {(h.program, h.field) for h in backward.hits}


def test_gen_fixtures_records_no_bogus_argument_gaps(tmp_path) -> None:
    path = tmp_path / "CALLER.cbl"
    path.write_text(CALLER.format(call=ISSUE_CALL))
    bundle = ProgramFixtureGenerator().generate_from_file(str(path), seed=1)
    gaps = " ".join(str(u) for u in bundle.unresolved)
    assert "argument FUNCTION " not in gaps
    assert "UPPER-CASE ( WS-NAME )" not in gaps


def test_xref_reads_the_function_argument_as_a_value() -> None:
    from cobolparser.analysis.xref import XrefAnalyzer

    ast = _ast(CALLER.format(call=ISSUE_CALL), "CALLER")
    entry = XrefAnalyzer().analyze(ast).entry_for("WS-NAME")
    assert entry is not None
    call_roles = {r.role for r in entry.references if r.location.line == 9}
    assert "subscript" not in call_roles
    assert call_roles
