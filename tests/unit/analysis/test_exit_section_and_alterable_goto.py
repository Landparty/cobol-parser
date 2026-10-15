"""Issue #382: alterable ``GO TO.`` and ``EXIT SECTION`` transfer control.

An alterable ``GO TO.`` (no operand) always jumps to whatever an ALTER set
it to, and ``EXIT SECTION`` always leaves for the end of its section. Both
used to be read as falling into the next paragraph, which hid dead code
and drew fall-through edges no execution can take.
"""

from cobolparser.analysis.dead_code import DeadCodeAnalyzer
from cobolparser.analysis.program_flow import FlowEdgeType, ProgramFlowAnalyzer
from cobolparser.parser import parse_cobol

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T382.
       PROCEDURE DIVISION.
"""


def _analyze(body: str) -> tuple[list[str], set[tuple[str, str]], list[str]]:
    """Dead procedures, fall-through edges, and unreachable nodes."""
    result = parse_cobol(HEADER + body, filename="t382.cbl")
    assert result.ast is not None
    assert not result.errors
    dead = [item.name for item in DeadCodeAnalyzer().analyze(result.ast).dead_items]
    flow = ProgramFlowAnalyzer().analyze(result.ast)
    fall_through = {
        (e.source, e.target)
        for e in flow.edges
        if e.edge_type == FlowEdgeType.FALL_THROUGH
    }
    return dead, fall_through, flow.unreachable_nodes


class TestAlterableGoTo:
    BODY = """\
       P-0.
           ALTER P-SWITCH TO PROCEED TO P-FIRST.
       P-SWITCH.
           GO TO.
       P-AFTER.
           DISPLAY 'NEVER'.
       P-FIRST.
           DISPLAY 'FIRST'
           STOP RUN.
"""

    def test_paragraph_after_alterable_goto_is_dead(self) -> None:
        dead, _, unreachable = _analyze(self.BODY)
        assert dead == ["P-AFTER"]
        assert unreachable == ["P-AFTER"]

    def test_alterable_goto_draws_no_fall_through(self) -> None:
        _, fall_through, _ = _analyze(self.BODY)
        assert ("P-SWITCH", "P-AFTER") not in fall_through
        assert ("P-0", "P-SWITCH") in fall_through

    def test_goto_depending_still_falls_through(self) -> None:
        body = """\
       P-0.
           GO TO P-1 P-2 DEPENDING ON WS-X.
       P-1.
           DISPLAY 'ONE'.
       P-2.
           STOP RUN.
"""
        source = (
            HEADER.replace(
                "       PROCEDURE DIVISION.\n",
                "       DATA DIVISION.\n"
                "       WORKING-STORAGE SECTION.\n"
                "       01 WS-X PIC 9.\n"
                "       PROCEDURE DIVISION.\n",
            )
            + body
        )
        result = parse_cobol(source, filename="t382.cbl")
        assert result.ast is not None
        flow = ProgramFlowAnalyzer().analyze(result.ast)
        assert any(
            e.source == "P-0"
            and e.target == "P-1"
            and e.edge_type == FlowEdgeType.FALL_THROUGH
            for e in flow.edges
        )


class TestExitSection:
    def test_performed_section_skips_paragraphs_after_exit_section(self) -> None:
        dead, fall_through, unreachable = _analyze("""\
       MAIN SECTION.
       M-1.
           PERFORM WORK-SEC
           STOP RUN.
       WORK-SEC SECTION.
       W-1.
           DISPLAY 'W1'.
       W-2.
           EXIT SECTION.
       W-3.
           DISPLAY 'W3'.
       W-4.
           DISPLAY 'W4'.
""")
        assert dead == ["W-3", "W-4"]
        assert ("W-2", "W-3") not in fall_through
        # PERFORMed: the end of the section returns, nothing runs on.
        assert not any(src == "W-2" for src, _ in fall_through)
        assert unreachable == ["W-3", "W-4"]

    def test_performed_section_returns_rather_than_running_on(self) -> None:
        dead, fall_through, _ = _analyze("""\
       MAIN SECTION.
       M-1.
           PERFORM WORK-SEC
           STOP RUN.
       WORK-SEC SECTION.
       W-1.
           EXIT SECTION.
       W-2.
           DISPLAY 'W2'.
       TAIL-SEC SECTION.
       T-1.
           DISPLAY 'T1'.
""")
        assert dead == ["W-2", "TAIL-SEC", "T-1"]
        assert not any(src == "W-1" for src, _ in fall_through)

    def test_fallen_into_section_runs_on_to_next_section(self) -> None:
        dead, fall_through, unreachable = _analyze("""\
       MAIN SECTION.
       M-1.
           DISPLAY 'M1'.
       WORK-SEC SECTION.
       W-1.
           DISPLAY 'W1'.
       W-2.
           EXIT SECTION.
       W-3.
           DISPLAY 'W3'.
       TAIL-SEC SECTION.
       T-1.
           STOP RUN.
""")
        assert dead == ["W-3"]
        assert ("W-2", "TAIL-SEC") in fall_through
        assert ("W-2", "W-3") not in fall_through
        assert unreachable == ["W-3"]

    def test_section_gone_to_from_outside_runs_on(self) -> None:
        dead, fall_through, unreachable = _analyze("""\
       MAIN SECTION.
       M-1.
           GO TO W-1.
       WORK-SEC SECTION.
       W-1.
           EXIT SECTION.
       W-2.
           DISPLAY 'W2'.
       TAIL-SEC SECTION.
       T-1.
           STOP RUN.
""")
        assert dead == ["W-2"]
        assert ("W-1", "TAIL-SEC") in fall_through
        assert "W-2" in unreachable
        assert "TAIL-SEC" not in unreachable

    def test_exit_section_in_section_body(self) -> None:
        # Straight after the header, ``EXIT SECTION.`` used to parse as a
        # section named EXIT.
        result = parse_cobol(HEADER + self.SECTION_BODY, filename="t382.cbl")
        assert result.ast is not None
        assert [
            s.section_name for s in result.ast.procedure_division._sections.values()
        ] == ["MAIN", "WORK-SEC", "TAIL-SEC"]
        dead, fall_through, _ = _analyze(self.SECTION_BODY)
        assert dead == ["W-1"]
        assert ("WORK-SEC", "TAIL-SEC") in fall_through
        assert ("WORK-SEC", "W-1") not in fall_through

    SECTION_BODY = """\
       MAIN SECTION.
       M-1.
           DISPLAY 'M1'.
       WORK-SEC SECTION.
           EXIT SECTION.
       W-1.
           DISPLAY 'W1'.
       TAIL-SEC SECTION.
       T-1.
           STOP RUN.
"""

    def test_conditional_exit_section_still_falls_through(self) -> None:
        dead, fall_through, _ = _analyze("""\
       MAIN SECTION.
       M-1.
           PERFORM WORK-SEC
           STOP RUN.
       WORK-SEC SECTION.
       W-1.
           IF 1 = 1
               EXIT SECTION
           END-IF.
       W-2.
           DISPLAY 'W2'.
""")
        assert dead == []
        assert ("W-1", "W-2") in fall_through

    def test_terminator_before_exit_section_wins(self) -> None:
        dead, fall_through, _ = _analyze("""\
       MAIN SECTION.
       M-1.
           DISPLAY 'M1'.
       WORK-SEC SECTION.
       W-1.
           STOP RUN.
           EXIT SECTION.
       W-2.
           DISPLAY 'W2'.
       TAIL-SEC SECTION.
       T-1.
           DISPLAY 'T1'.
""")
        assert dead == ["W-2", "TAIL-SEC", "T-1"]
        assert not any(src == "W-1" for src, _ in fall_through)

    def test_section_entered_by_cics_handle_runs_on(self) -> None:
        # Any GO TO-shaped edge (GOTO_EDGE_TYPES) enters the section, not
        # only a written GO TO: here the CICS HANDLE branch.
        dead, fall_through, unreachable = _analyze("""\
       MAIN SECTION.
       M-1.
           EXEC CICS HANDLE CONDITION NOTFND(E-1) END-EXEC
           STOP RUN.
       ERR-SEC SECTION.
       E-1.
           EXIT SECTION.
       E-2.
           DISPLAY 'E2'.
       AFTER-SEC SECTION.
       A-1.
           STOP RUN.
""")
        assert dead == ["E-2"]
        assert ("E-1", "AFTER-SEC") in fall_through
        assert "AFTER-SEC" not in unreachable
        assert "E-2" in unreachable
