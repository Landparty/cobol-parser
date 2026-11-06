"""Issue #842: entering a section by PERFORM of one of its paragraphs does
not make every later paragraph of that section reachable by falling through."""

from cobolparser.analysis.program_flow import FlowEdgeType, ProgramFlowAnalyzer
from cobolparser.parser import parse_cobol

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T842.
       PROCEDURE DIVISION.
"""


def _flow(body: str) -> tuple[set[tuple[str, str]], list[str]]:
    result = parse_cobol(HEADER + body, filename="t842.cbl")
    assert result.ast is not None and not result.errors
    flow = ProgramFlowAnalyzer().analyze(result.ast)
    fall_through = {
        (e.source, e.target)
        for e in flow.edges
        if e.edge_type == FlowEdgeType.FALL_THROUGH
    }
    return fall_through, flow.unreachable_nodes


def test_performed_paragraphs_do_not_free_the_rest_of_their_section():
    fall_through, unreachable = _flow("""\
       MAIN-SEC SECTION.
       M1.
           PERFORM 1000-READ
           PERFORM 2000-CALC
           GOBACK.
       IO-SEC SECTION.
       1000-READ.
           DISPLAY 'R'.
       2000-CALC.
           DISPLAY 'C'.
       3000-WRITE.
           DISPLAY 'W'.
""")
    assert fall_through == {("MAIN-SEC", "M1")}
    assert "3000-WRITE" in unreachable


def test_perform_thru_stops_at_its_last_paragraph():
    fall_through, unreachable = _flow("""\
       M1.
           PERFORM P-A THRU P-C
           GOBACK.
       IO-SEC SECTION.
       P-A.
           DISPLAY 'A'.
       P-B.
           DISPLAY 'B'.
       P-C.
           DISPLAY 'C'.
       P-D.
           DISPLAY 'D'.
""")
    assert ("P-C", "P-D") not in fall_through
    assert {("P-A", "P-B"), ("P-B", "P-C")} <= fall_through
    assert "P-D" in unreachable


def test_go_to_still_falls_through_the_paragraphs_after_its_target():
    fall_through, unreachable = _flow("""\
       MAIN-SEC SECTION.
       M1.
           DISPLAY 'M1'.
       M2.
           GO TO X1.
       OTHER-SEC SECTION.
       X1.
           DISPLAY 'X1'.
       X2.
           DISPLAY 'X2'.
       X3.
           GOBACK.
""")
    assert {("X1", "X2"), ("X2", "X3")} <= fall_through
    assert not {"X1", "X2", "X3"} & set(unreachable)
