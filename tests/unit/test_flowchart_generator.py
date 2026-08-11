"""Unit tests for cobolparser.generators.flowchart.

Tests cover:
- FlowchartOptions defaults
- MermaidFlowchartGenerator output structure
- DotFlowchartGenerator output structure
- Node-ID sanitization via _sanitize_id
- Edge rendering (PERFORM, GOTO, CALL, FALL_THROUGH, loop)
- Unreachable node suppression via show_unreachable=False
- External-call nodes
- Empty report edge case
"""

from __future__ import annotations

import re
from typing import Any

from cobolparser.analysis.program_flow import (
    BranchArm,
    BranchNode,
    FlowEdge,
    FlowEdgeType,
    FlowNode,
    ProgramFlowAnalyzer,
    ProgramFlowReport,
)
from cobolparser.generators.flowchart import (
    DotFlowchartGenerator,
    FlowchartOptions,
    MermaidFlowchartGenerator,
    _sanitize_id,
    _short_edge_label,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parser import parse_cobol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _loc(line: int = 1, col: int = 8) -> SourceLocation:
    return SourceLocation(line=line, column=col)


def _para(
    name: str,
    *,
    entry: bool = False,
    exit_: bool = False,
    stmt_count: int = 0,
    unreachable: bool = False,
) -> FlowNode:
    return FlowNode(
        name=name,
        procedure_type="PARAGRAPH",
        location=_loc(),
        is_entry_point=entry,
        is_exit_point=exit_,
        statement_count=stmt_count,
    )


def _simple_report() -> ProgramFlowReport:
    """Two paragraphs connected by PERFORM, one is entry and the other is exit."""
    nodes = [
        _para("MAIN-LOGIC", entry=True, stmt_count=3),
        _para("PROCESS-RECORD", exit_=True, stmt_count=5),
    ]
    edges = [
        FlowEdge(
            source="MAIN-LOGIC",
            target="PROCESS-RECORD",
            edge_type=FlowEdgeType.PERFORM,
            location=_loc(),
        )
    ]
    return ProgramFlowReport(
        program_name="TEST-PROG",
        nodes=nodes,
        edges=edges,
        entry_points=["MAIN-LOGIC"],
        exit_points=["PROCESS-RECORD"],
    )


def _goto_report() -> ProgramFlowReport:
    """Three paragraphs with a GO TO edge."""
    nodes = [
        _para("SECTION-A", entry=True, stmt_count=2),
        _para("SECTION-B", stmt_count=1),
        _para("END-PARA", exit_=True, stmt_count=1),
    ]
    edges = [
        FlowEdge(
            source="SECTION-A",
            target="SECTION-B",
            edge_type=FlowEdgeType.GOTO,
            location=_loc(),
        ),
        FlowEdge(
            source="SECTION-B",
            target="END-PARA",
            edge_type=FlowEdgeType.FALL_THROUGH,
            location=_loc(),
        ),
    ]
    return ProgramFlowReport(
        program_name="GOTO-PROG",
        nodes=nodes,
        edges=edges,
        entry_points=["SECTION-A"],
        exit_points=["END-PARA"],
    )


def _call_report() -> ProgramFlowReport:
    """A paragraph that CALLs an external program."""
    nodes = [_para("CALL-PARA", entry=True, exit_=True, stmt_count=2)]
    edges = [
        FlowEdge(
            source="CALL-PARA",
            target="EXTPGM",
            edge_type=FlowEdgeType.CALL,
            location=_loc(),
        )
    ]
    return ProgramFlowReport(
        program_name="CALL-PROG",
        nodes=nodes,
        edges=edges,
        entry_points=["CALL-PARA"],
        exit_points=["CALL-PARA"],
        external_calls=[{"target": "EXTPGM", "location": _loc().to_dict()}],
    )


def _loop_report() -> ProgramFlowReport:
    """A PERFORM UNTIL that forms a loop."""
    nodes = [
        _para("MAIN", entry=True, stmt_count=1),
        _para("LOOP-BODY", stmt_count=3),
    ]
    edges = [
        FlowEdge(
            source="MAIN",
            target="LOOP-BODY",
            edge_type=FlowEdgeType.PERFORM,
            location=_loc(),
            is_loop=True,
            perform_type="UNTIL",
        )
    ]
    return ProgramFlowReport(
        program_name="LOOP-PROG",
        nodes=nodes,
        edges=edges,
        entry_points=["MAIN"],
        exit_points=["MAIN"],
    )


def _unreachable_report() -> ProgramFlowReport:
    """One reachable paragraph and one unreachable paragraph."""
    nodes = [
        _para("MAIN", entry=True, stmt_count=1),
        _para("DEAD-CODE", stmt_count=2),
    ]
    edges: list[FlowEdge] = []
    return ProgramFlowReport(
        program_name="DEAD-PROG",
        nodes=nodes,
        edges=edges,
        entry_points=["MAIN"],
        exit_points=["MAIN"],
        unreachable_nodes=["DEAD-CODE"],
    )


def _if_branch_report() -> ProgramFlowReport:
    """Report with a single IF BranchNode (THEN + ELSE arms)."""
    then_arm = BranchArm(
        arm_id="MAIN-LOGIC__IF_1__THEN",
        arm_type="THEN",
        label="THEN",
        statement_count=2,
    )
    else_arm = BranchArm(
        arm_id="MAIN-LOGIC__IF_1__ELSE",
        arm_type="ELSE",
        label="ELSE",
        statement_count=1,
    )
    bn = BranchNode(
        node_id="MAIN-LOGIC__IF_1",
        branch_type="IF",
        parent_proc="MAIN-LOGIC",
        location=_loc(),
        condition_text="COMPARISON",
        arms=[then_arm, else_arm],
    )
    nodes = [_para("MAIN-LOGIC", entry=True, exit_=True, stmt_count=3)]
    edges = [
        FlowEdge(
            source="MAIN-LOGIC",
            target="MAIN-LOGIC__IF_1",
            edge_type=FlowEdgeType.IF_BRANCH,
            location=_loc(),
        ),
        FlowEdge(
            source="MAIN-LOGIC__IF_1",
            target="MAIN-LOGIC__IF_1__THEN",
            edge_type=FlowEdgeType.IF_THEN,
            location=_loc(),
        ),
        FlowEdge(
            source="MAIN-LOGIC__IF_1",
            target="MAIN-LOGIC__IF_1__ELSE",
            edge_type=FlowEdgeType.IF_ELSE,
            location=_loc(),
        ),
    ]
    return ProgramFlowReport(
        program_name="IF-PROG",
        nodes=nodes,
        edges=edges,
        entry_points=["MAIN-LOGIC"],
        exit_points=["MAIN-LOGIC"],
        branch_nodes=[bn],
    )


def _eval_branch_report() -> ProgramFlowReport:
    """Report with a single EVALUATE BranchNode (WHEN + WHEN OTHER arms)."""
    when1_arm = BranchArm(
        arm_id="MAIN-LOGIC__EVAL_1__WHEN_1",
        arm_type="WHEN",
        label="WHEN 1",
        statement_count=1,
    )
    when_other_arm = BranchArm(
        arm_id="MAIN-LOGIC__EVAL_1__WHEN_OTHER",
        arm_type="WHEN_OTHER",
        label="WHEN OTHER",
        statement_count=1,
    )
    bn = BranchNode(
        node_id="MAIN-LOGIC__EVAL_1",
        branch_type="EVALUATE",
        parent_proc="MAIN-LOGIC",
        location=_loc(),
        condition_text="WS-VAR",
        arms=[when1_arm, when_other_arm],
    )
    nodes = [_para("MAIN-LOGIC", entry=True, exit_=True, stmt_count=2)]
    edges = [
        FlowEdge(
            source="MAIN-LOGIC",
            target="MAIN-LOGIC__EVAL_1",
            edge_type=FlowEdgeType.EVALUATE_BRANCH,
            location=_loc(),
        ),
        FlowEdge(
            source="MAIN-LOGIC__EVAL_1",
            target="MAIN-LOGIC__EVAL_1__WHEN_1",
            edge_type=FlowEdgeType.EVALUATE_WHEN,
            location=_loc(),
            condition="WHEN 1",
        ),
        FlowEdge(
            source="MAIN-LOGIC__EVAL_1",
            target="MAIN-LOGIC__EVAL_1__WHEN_OTHER",
            edge_type=FlowEdgeType.EVALUATE_WHEN_OTHER,
            location=_loc(),
        ),
    ]
    return ProgramFlowReport(
        program_name="EVAL-PROG",
        nodes=nodes,
        edges=edges,
        entry_points=["MAIN-LOGIC"],
        exit_points=["MAIN-LOGIC"],
        branch_nodes=[bn],
    )


# ---------------------------------------------------------------------------
# _sanitize_id
# ---------------------------------------------------------------------------


class TestSanitizeId:
    def test_plain_name(self) -> None:
        assert _sanitize_id("MAIN_LOGIC") == "MAIN_LOGIC"

    def test_hyphens_replaced(self) -> None:
        result = _sanitize_id("MAIN-LOGIC")
        assert "-" not in result
        assert re.fullmatch(r"[A-Za-z0-9_]+", result)

    def test_digit_prefix(self) -> None:
        result = _sanitize_id("1ST-PARA")
        assert result.startswith("N_")

    def test_spaces_replaced(self) -> None:
        result = _sanitize_id("MY PARA")
        assert " " not in result

    def test_empty_string(self) -> None:
        result = _sanitize_id("")
        assert result == "N_UNKNOWN"


# ---------------------------------------------------------------------------
# _short_edge_label
# ---------------------------------------------------------------------------


class TestShortEdgeLabel:
    def test_goto_label(self) -> None:
        assert _short_edge_label("GOTO") == "GO TO"

    def test_perform_label(self) -> None:
        assert _short_edge_label("PERFORM") == "PERFORM"

    def test_call_label(self) -> None:
        assert _short_edge_label("CALL") == "CALL"

    def test_unknown_passthrough(self) -> None:
        assert _short_edge_label("WEIRD_TYPE") == "WEIRD_TYPE"


# ---------------------------------------------------------------------------
# FlowchartOptions
# ---------------------------------------------------------------------------


class TestFlowchartOptions:
    def test_defaults(self) -> None:
        opts = FlowchartOptions()
        assert opts.show_statement_counts is True
        assert opts.show_edge_labels is True
        assert opts.show_fall_through is False
        assert opts.show_unreachable is True
        assert opts.show_external_calls is True

    def test_custom(self) -> None:
        opts = FlowchartOptions(show_fall_through=True, show_unreachable=False)
        assert opts.show_fall_through is True
        assert opts.show_unreachable is False


# ---------------------------------------------------------------------------
# MermaidFlowchartGenerator
# ---------------------------------------------------------------------------


class TestMermaidFlowchartGenerator:
    def _gen(self, report: ProgramFlowReport, **kw: object) -> str:
        return MermaidFlowchartGenerator().generate(report, FlowchartOptions(**kw))  # type: ignore[arg-type]

    # -- basic structure -------------------------------------------------

    def test_starts_with_program_header_then_flowchart_td(self) -> None:
        out = self._gen(_simple_report())
        lines = out.splitlines()
        assert lines[0].startswith("%% Program: ")
        assert lines[1] == "flowchart TD"

    def test_classdef_entry_present(self) -> None:
        out = self._gen(_simple_report())
        assert "classDef entry" in out

    def test_classdef_exit_present(self) -> None:
        out = self._gen(_simple_report())
        assert "classDef exit" in out

    def test_classdef_unreachable_present(self) -> None:
        out = self._gen(_simple_report())
        assert "classDef unreachable" in out

    def test_classdef_external_present(self) -> None:
        out = self._gen(_simple_report())
        assert "classDef external" in out

    # -- nodes -----------------------------------------------------------

    def test_entry_node_present(self) -> None:
        out = self._gen(_simple_report())
        assert "MAIN_LOGIC" in out or "MAIN-LOGIC" in out.replace("-", "_")

    def test_node_id_sanitized(self) -> None:
        out = self._gen(_simple_report())
        # Hyphens must not appear as raw node IDs — they should be sanitized
        lines = [line for line in out.splitlines() if "MAIN_LOGIC" in line]
        assert lines, "Expected sanitized node ID MAIN_LOGIC"

    def test_entry_node_annotated(self) -> None:
        out = self._gen(_simple_report())
        assert "class MAIN_LOGIC entry" in out

    def test_exit_node_annotated(self) -> None:
        out = self._gen(_simple_report())
        assert "class PROCESS_RECORD exit" in out

    def test_statement_count_in_label(self) -> None:
        out = self._gen(_simple_report(), show_statement_counts=True)
        assert "stmts" in out

    def test_statement_count_hidden(self) -> None:
        out = self._gen(_simple_report(), show_statement_counts=False)
        assert "stmts" not in out

    # -- edges -----------------------------------------------------------

    def test_perform_edge_present(self) -> None:
        out = self._gen(_simple_report())
        # There should be an arrow between the two sanitized node IDs
        assert "MAIN_LOGIC" in out and "PROCESS_RECORD" in out

    def test_goto_uses_thick_arrow(self) -> None:
        out = self._gen(_goto_report())
        assert "==>" in out

    def test_fall_through_hidden_by_default(self) -> None:
        out = self._gen(_goto_report())
        assert "fall-through" not in out
        # The dashed arrow should not appear when show_fall_through=False
        assert "-..->" not in out and "-.->" not in out

    def test_fall_through_shown_when_enabled(self) -> None:
        out = self._gen(_goto_report(), show_fall_through=True)
        assert "-.->" in out or "-..->" in out

    def test_loop_annotation(self) -> None:
        out = self._gen(_loop_report())
        assert "loop" in out.lower()

    # -- external calls --------------------------------------------------

    def test_external_call_node_created(self) -> None:
        out = self._gen(_call_report())
        assert "EXT_EXTPGM" in out

    def test_external_call_class_annotated(self) -> None:
        out = self._gen(_call_report())
        assert "class EXT_EXTPGM external" in out

    def test_external_calls_hidden_when_disabled(self) -> None:
        out = self._gen(_call_report(), show_external_calls=False)
        assert "EXT_EXTPGM" not in out

    # -- unreachable nodes -----------------------------------------------

    def test_unreachable_annotated(self) -> None:
        out = self._gen(_unreachable_report())
        assert "class DEAD_CODE unreachable" in out

    def test_unreachable_hidden_when_disabled(self) -> None:
        out = self._gen(_unreachable_report(), show_unreachable=False)
        assert "DEAD_CODE" not in out

    # -- empty report ----------------------------------------------------

    def test_empty_report(self) -> None:
        report = ProgramFlowReport(program_name="EMPTY")
        out = self._gen(report)
        assert "flowchart TD" in out
        assert "No procedures found" in out

    # -- default options (no explicit options arg) -----------------------

    def test_no_options_arg(self) -> None:
        out = MermaidFlowchartGenerator().generate(_simple_report())
        assert "flowchart TD" in out

    # -- edge linkStyle (recursion / GO TO) -------------------------------

    def test_perform_recursion_edge_gets_linkstyle(self) -> None:
        nodes = [
            _para("A", entry=True, stmt_count=1),
            _para("B", stmt_count=1),
        ]
        edges = [
            FlowEdge(
                source="A", target="B", edge_type=FlowEdgeType.PERFORM, location=_loc()
            ),
            FlowEdge(
                source="B", target="A", edge_type=FlowEdgeType.PERFORM, location=_loc()
            ),
        ]
        report = ProgramFlowReport(
            program_name="RECUR-PROG",
            nodes=nodes,
            edges=edges,
            entry_points=["A"],
            cycles=[["A", "B"]],
            cycle_details=[
                {
                    "nodes": ["A", "B"],
                    "kind": "PERFORM_RECURSION",
                    "length": 2,
                    "self_recursive": False,
                    "edge_types": ["PERFORM"],
                }
            ],
        )
        out = self._gen(report)
        assert "linkStyle" in out

    def test_non_recursive_perform_edge_gets_no_linkstyle(self) -> None:
        out = self._gen(_simple_report())
        assert "linkStyle" not in out

    def test_goto_edge_gets_linkstyle(self) -> None:
        out = self._gen(_goto_report())
        assert "linkStyle" in out

    # -- exit-statement terminal nodes ------------------------------------

    def test_stop_run_renders_terminal_node(self) -> None:
        node = _para("MAIN-LOGIC", entry=True, exit_=True, stmt_count=2)
        node.exit_statement_kind = "STOP RUN"
        node.exit_statement_location = _loc(line=42)
        report = ProgramFlowReport(
            program_name="TERM-PROG",
            nodes=[node],
            entry_points=["MAIN-LOGIC"],
        )
        out = self._gen(report)
        assert "STOP RUN" in out
        assert "42" in out
        assert "MAIN_LOGIC_EXIT" in out
        assert "MAIN_LOGIC --> MAIN_LOGIC_EXIT" in out
        assert "classDef terminal" in out

    def test_no_exit_statement_no_terminal_node(self) -> None:
        out = self._gen(_simple_report())
        assert "_EXIT" not in out

    def test_terminal_node_hidden_when_unreachable_and_disabled(self) -> None:
        report = _unreachable_report()
        dead = next(n for n in report.nodes if n.name == "DEAD-CODE")
        dead.exit_statement_kind = "STOP RUN"
        dead.exit_statement_location = _loc(line=99)
        out = self._gen(report, show_unreachable=False)
        assert "_EXIT" not in out

    def test_terminal_id_does_not_collide_with_real_exit_paragraph(self) -> None:
        """Regression guard: a paragraph named '9000-TERM' with a GOBACK gets
        a synthetic '..._EXIT' terminal node, but a program can also contain
        a REAL paragraph literally named '9000-TERM-EXIT' (the common
        PERFORM X THRU X-EXIT idiom). Both must render as distinct nodes,
        not silently merge."""
        term = _para("9000-TERM", entry=True, exit_=True, stmt_count=1)
        term.exit_statement_kind = "GOBACK"
        term.exit_statement_location = _loc(line=20)
        real_exit_para = _para("9000-TERM-EXIT", stmt_count=1)
        report = ProgramFlowReport(
            program_name="COLLIDE-PROG",
            nodes=[term, real_exit_para],
            entry_points=["9000-TERM"],
        )
        out = self._gen(report)
        # The real paragraph keeps its own sanitized id.
        assert "N_9000_TERM_EXIT[" in out
        # The synthetic terminal node must use a DIFFERENT id.
        assert "N_9000_TERM_EXIT(((" not in out
        assert "N_9000_TERM_FLOWEXIT" in out
        assert "N_9000_TERM --> N_9000_TERM_FLOWEXIT" in out

    def test_linkstyle_index_skips_hidden_edges_correctly(self) -> None:
        """A skipped (hidden) edge before a styled edge must not consume a
        linkStyle index -- the first EMITTED, styled edge must be linkStyle 0,
        not linkStyle 1."""
        nodes = [
            _para("A", entry=True, stmt_count=1),
            _para("B", stmt_count=1),
        ]
        edges = [
            # Skipped since show_fall_through defaults to False; must NOT
            # consume a linkStyle index.
            FlowEdge(
                source="A",
                target="B",
                edge_type=FlowEdgeType.FALL_THROUGH,
                location=_loc(),
            ),
            # First (and only) EMITTED edge -- must get linkStyle 0.
            FlowEdge(
                source="A", target="B", edge_type=FlowEdgeType.PERFORM, location=_loc()
            ),
        ]
        report = ProgramFlowReport(
            program_name="SKIP-PROG",
            nodes=nodes,
            edges=edges,
            entry_points=["A"],
            cycle_details=[
                {
                    "nodes": ["A", "B"],
                    "kind": "PERFORM_RECURSION",
                    "length": 2,
                    "self_recursive": False,
                    "edge_types": ["PERFORM"],
                }
            ],
        )
        out = self._gen(report)
        assert "linkStyle 0 " in out
        assert "linkStyle 1" not in out

    def test_linkstyle_index_accounts_for_terminal_node_links(self) -> None:
        """Regression guard for the critical composition bug: a report with
        BOTH a terminal-node link (emitted by the exit-statement loop, which
        runs BEFORE the edges loop) AND a PERFORM_RECURSION-cycle edge.
        Mermaid's `linkStyle N` addresses links by definition order across
        the WHOLE diagram, so the recursion edge's linkStyle index must be
        offset by the number of terminal-node links already emitted --
        not start counting from 0 as if the edges loop were the only
        link-emitting loop in the diagram."""
        nodes = [
            _para("A", entry=True, stmt_count=1),
            _para("B", stmt_count=1),
            _para("C", stmt_count=1),
            _para("TERM", exit_=True, stmt_count=1),
        ]
        nodes[3].exit_statement_kind = "STOP RUN"
        nodes[3].exit_statement_location = _loc(line=50)
        edges = [
            # Non-recursion edge -- edges-loop position 0. (A, C) is not part
            # of the (A, B) cycle below, so it must NOT get a linkStyle.
            FlowEdge(
                source="A", target="C", edge_type=FlowEdgeType.PERFORM, location=_loc()
            ),
            # Recursion edge -- edges-loop position 1. (A, B) closes the
            # cycle below and must get styled.
            FlowEdge(
                source="A", target="B", edge_type=FlowEdgeType.PERFORM, location=_loc()
            ),
        ]
        report = ProgramFlowReport(
            program_name="COMPOSITION-PROG",
            nodes=nodes,
            edges=edges,
            entry_points=["A"],
            cycle_details=[
                {
                    "nodes": ["A", "B"],
                    "kind": "PERFORM_RECURSION",
                    "length": 2,
                    "self_recursive": False,
                    "edge_types": ["PERFORM"],
                }
            ],
        )
        out = self._gen(report)
        lines = out.splitlines()
        arrow_lines = [line for line in lines if "-->" in line]
        # Expected definition order: [0] TERM --> TERM_EXIT (terminal link,
        # emitted before the edges loop), [1] A --> C (edges-loop position
        # 0, unstyled), [2] A --> B (edges-loop position 1, the recursion
        # edge that must get styled).
        assert len(arrow_lines) == 3
        assert "TERM --> TERM_EXIT" in arrow_lines[0]
        assert "A --> C" in arrow_lines[1]
        assert "A --> B" in arrow_lines[2]
        # terminal_link_count (1) + edges-loop position of the recursion
        # edge (1) == 2 -- linkStyle 2 must reference arrow_lines[2].
        expected_index = 1 + 1
        assert f"linkStyle {expected_index} " in out
        # And no OTHER linkStyle line is emitted for this scenario (the
        # non-recursion A --> C edge must not be styled).
        linkstyle_lines = [
            line for line in lines if line.strip().startswith("linkStyle")
        ]
        assert len(linkstyle_lines) == 1

    def test_thru_range_renders_as_badge_not_second_arrow(self) -> None:
        nodes = [
            _para("A", entry=True, stmt_count=1),
            _para("B", stmt_count=1),
            _para("C", stmt_count=1),
            _para("D", exit_=True, stmt_count=1),
        ]
        edges = [
            FlowEdge(
                source="A",
                target="B",
                edge_type=FlowEdgeType.PERFORM,
                location=_loc(),
                thru_target="D",
                range_members=["B", "C", "D"],
            ),
            FlowEdge(
                source="A",
                target="D",
                edge_type=FlowEdgeType.PERFORM_THRU,
                location=_loc(),
                thru_target="D",
                range_members=["B", "C", "D"],
            ),
        ]
        report = ProgramFlowReport(
            program_name="THRU-PROG",
            nodes=nodes,
            edges=edges,
            entry_points=["A"],
        )
        out = self._gen(report)
        assert "[THRU 3]" in out
        # Exactly one arrow from A to D-range's entry (B), not a second
        # A -> D arrow duplicating the same span.
        # The PERFORM_THRU edge (A -> D) is skipped by the endswith("_THRU") filter.
        assert "A --> D" not in out
        # The badge should be on the A -> B edge
        assert "A -->|[THRU 3]| B" in out

    def test_sort_input_procedure_thru_range_renders_as_badge(self) -> None:
        """Regression guard: SORT/MERGE THRU ranges must not vanish -- the
        base SORT_INPUT_PROCEDURE edge (not just the *_THRU edge) now carries
        thru_target/range_members, matching the PERFORM THRU pattern above."""
        nodes = [
            _para("A", entry=True, stmt_count=1),
            _para("B", stmt_count=1),
            _para("C", stmt_count=1),
            _para("D", exit_=True, stmt_count=1),
        ]
        edges = [
            FlowEdge(
                source="A",
                target="B",
                edge_type=FlowEdgeType.SORT_INPUT_PROCEDURE,
                location=_loc(),
                thru_target="D",
                range_members=["B", "C", "D"],
            ),
            FlowEdge(
                source="A",
                target="D",
                edge_type=FlowEdgeType.SORT_INPUT_PROCEDURE_THRU,
                location=_loc(),
                thru_target="D",
                range_members=["B", "C", "D"],
            ),
        ]
        report = ProgramFlowReport(
            program_name="SORT-THRU-PROG",
            nodes=nodes,
            edges=edges,
            entry_points=["A"],
        )
        out = self._gen(report)
        assert "[THRU 3]" in out
        assert "A --> D" not in out
        assert "A -->|SORT INPUT [THRU 3]| B" in out


# ---------------------------------------------------------------------------
# DotFlowchartGenerator
# ---------------------------------------------------------------------------


class TestDotFlowchartGenerator:
    def _gen(self, report: ProgramFlowReport, **kw: object) -> str:
        return DotFlowchartGenerator().generate(report, FlowchartOptions(**kw))  # type: ignore[arg-type]

    # -- basic structure -------------------------------------------------

    def test_starts_with_digraph(self) -> None:
        out = self._gen(_simple_report())
        assert out.startswith("digraph")

    def test_program_name_in_header(self) -> None:
        out = self._gen(_simple_report())
        assert "TEST-PROG" in out or "TEST_PROG" in out

    def test_rankdir_tb(self) -> None:
        out = self._gen(_simple_report())
        assert "rankdir" in out and "TB" in out

    def test_closing_brace(self) -> None:
        out = self._gen(_simple_report())
        assert out.strip().endswith("}")

    # -- nodes -----------------------------------------------------------

    def test_entry_node_color(self) -> None:
        out = self._gen(_simple_report())
        # Entry nodes get the entry colour
        assert "#2d6a4f" in out or "entry" in out.lower()

    def test_exit_node_color(self) -> None:
        out = self._gen(_simple_report())
        assert "#c1121f" in out or "exit" in out.lower()

    def test_node_shape_box(self) -> None:
        out = self._gen(_simple_report())
        assert "box" in out

    def test_statement_count_in_label(self) -> None:
        out = self._gen(_simple_report(), show_statement_counts=True)
        assert "stmts" in out

    # -- edges -----------------------------------------------------------

    def test_goto_edge_penwidth(self) -> None:
        out = self._gen(_goto_report())
        assert "penwidth" in out

    def test_fall_through_hidden_by_default(self) -> None:
        out = self._gen(_goto_report())
        assert "fall-through" not in out
        # The FALL_THROUGH edge itself (SECTION_B -> END_PARA) must not be
        # rendered when hidden. Note "dashed" alone is no longer a reliable
        # signal here: the GOTO edge (SECTION_A -> SECTION_B) legitimately
        # gets style="dashed" from the Task 7 GOTO color/style treatment.
        assert "SECTION_B -> END_PARA" not in out

    def test_fall_through_shown_when_enabled(self) -> None:
        out = self._gen(_goto_report(), show_fall_through=True)
        assert "SECTION_B -> END_PARA" in out
        assert "dashed" in out

    def test_loop_edge_color(self) -> None:
        out = self._gen(_loop_report())
        assert "darkorange" in out

    # -- external calls --------------------------------------------------

    def test_external_call_node_created(self) -> None:
        out = self._gen(_call_report())
        assert "EXT_EXTPGM" in out or "EXTPGM" in out

    def test_external_calls_hidden_when_disabled(self) -> None:
        out = self._gen(_call_report(), show_external_calls=False)
        assert "EXT_EXTPGM" not in out

    # -- unreachable nodes -----------------------------------------------

    def test_unreachable_color(self) -> None:
        out = self._gen(_unreachable_report())
        assert "#adb5bd" in out or "unreachable" in out.lower()

    def test_unreachable_hidden_when_disabled(self) -> None:
        out = self._gen(_unreachable_report(), show_unreachable=False)
        assert "DEAD_CODE" not in out

    # -- empty report ----------------------------------------------------

    def test_empty_report(self) -> None:
        report = ProgramFlowReport(program_name="EMPTY")
        out = self._gen(report)
        assert "digraph" in out

    # -- default options -------------------------------------------------

    def test_no_options_arg(self) -> None:
        out = DotFlowchartGenerator().generate(_simple_report())
        assert "digraph" in out


# ---------------------------------------------------------------------------
# TestMermaidBranchNodes
# ---------------------------------------------------------------------------


class TestMermaidBranchNodes:
    """Branch-node rendering in MermaidFlowchartGenerator."""

    def _gen(self, report: ProgramFlowReport, **kw: object) -> str:
        return MermaidFlowchartGenerator().generate(report, FlowchartOptions(**kw))  # type: ignore[arg-type]

    # -- classDef emission -----------------------------------------------

    def test_classdef_branch_always_present(self) -> None:
        """The branch classDef is always emitted, even without branch nodes."""
        out = self._gen(_simple_report())
        assert "classDef branch" in out

    def test_classdef_arm_always_present(self) -> None:
        """The arm classDef is always emitted, even without branch nodes."""
        out = self._gen(_simple_report())
        assert "classDef arm" in out

    def test_classdef_branch_colors(self) -> None:
        out = self._gen(_simple_report())
        assert "classDef branch fill:#ffd60a" in out

    def test_classdef_arm_colors(self) -> None:
        out = self._gen(_simple_report())
        assert "classDef arm fill:#caf0f8" in out

    # -- IF branch node (diamond) ----------------------------------------

    def test_branch_node_rendered_as_diamond(self) -> None:
        out = self._gen(_if_branch_report())
        assert 'MAIN_LOGIC__IF_1{"[IF] COMPARISON"}' in out

    def test_branch_node_css_class(self) -> None:
        out = self._gen(_if_branch_report())
        assert "class MAIN_LOGIC__IF_1 branch" in out

    # -- arm nodes (rectangle) -------------------------------------------

    def test_arm_nodes_rendered(self) -> None:
        out = self._gen(_if_branch_report())
        assert 'MAIN_LOGIC__IF_1__THEN["THEN"]' in out
        assert 'MAIN_LOGIC__IF_1__ELSE["ELSE"]' in out

    def test_arm_nodes_css_class(self) -> None:
        out = self._gen(_if_branch_report())
        assert "class MAIN_LOGIC__IF_1__THEN arm" in out
        assert "class MAIN_LOGIC__IF_1__ELSE arm" in out

    # -- edge labels for IF branches ------------------------------------

    def test_if_then_edge_label(self) -> None:
        out = self._gen(_if_branch_report())
        assert "-->|THEN|" in out

    def test_if_else_edge_label(self) -> None:
        out = self._gen(_if_branch_report())
        assert "-->|ELSE|" in out

    # -- EVALUATE branch -------------------------------------------------

    def test_evaluate_diamond_label(self) -> None:
        out = self._gen(_eval_branch_report())
        assert 'MAIN_LOGIC__EVAL_1{"[EVALUATE] WS-VAR"}' in out

    def test_evaluate_when_edge_label_from_condition(self) -> None:
        """EVALUATE_WHEN edge uses edge.condition when set."""
        out = self._gen(_eval_branch_report())
        assert "-->|WHEN 1|" in out

    def test_evaluate_when_other_edge_label_fallback(self) -> None:
        """EVALUATE_WHEN_OTHER falls back to _short_edge_label when condition is None."""
        out = self._gen(_eval_branch_report())
        assert "-->|WHEN OTHER|" in out

    # -- absence guard ----------------------------------------------------

    def test_no_branch_nodes_no_diamond(self) -> None:
        """Without branch nodes, no diamond syntax appears."""
        out = self._gen(_simple_report())
        assert '{"' not in out


# ---------------------------------------------------------------------------
# TestDotBranchNodes
# ---------------------------------------------------------------------------


class TestDotBranchNodes:
    """Branch-node rendering in DotFlowchartGenerator."""

    def _gen(self, report: ProgramFlowReport, **kw: object) -> str:
        return DotFlowchartGenerator().generate(report, FlowchartOptions(**kw))  # type: ignore[arg-type]

    # -- IF branch node (diamond) ----------------------------------------

    def test_branch_node_diamond_shape(self) -> None:
        out = self._gen(_if_branch_report())
        assert "shape=diamond" in out

    def test_branch_node_fill_color(self) -> None:
        out = self._gen(_if_branch_report())
        assert 'fillcolor="#ffd60a"' in out

    def test_branch_node_label(self) -> None:
        out = self._gen(_if_branch_report())
        assert 'label="[IF] COMPARISON"' in out

    # -- arm nodes (box) --------------------------------------------------

    def test_arm_node_box_shape(self) -> None:
        out = self._gen(_if_branch_report())
        assert "shape=box" in out

    def test_arm_node_fill_color(self) -> None:
        out = self._gen(_if_branch_report())
        assert 'fillcolor="#caf0f8"' in out

    def test_arm_node_label(self) -> None:
        out = self._gen(_if_branch_report())
        assert 'label="THEN"' in out
        assert 'label="ELSE"' in out

    # -- edge labels for IF branches ------------------------------------

    def test_if_then_edge_label(self) -> None:
        out = self._gen(_if_branch_report())
        assert "MAIN_LOGIC__IF_1 -> MAIN_LOGIC__IF_1__THEN" in out
        assert 'label="THEN"' in out

    def test_if_else_edge_label(self) -> None:
        out = self._gen(_if_branch_report())
        assert "MAIN_LOGIC__IF_1 -> MAIN_LOGIC__IF_1__ELSE" in out
        assert 'label="ELSE"' in out

    # -- EVALUATE branch -------------------------------------------------

    def test_evaluate_branch_node_label(self) -> None:
        out = self._gen(_eval_branch_report())
        assert 'label="[EVALUATE] WS-VAR"' in out

    def test_evaluate_when_edge_label_from_condition(self) -> None:
        """EVALUATE_WHEN edge uses edge.condition when set."""
        out = self._gen(_eval_branch_report())
        assert 'label="WHEN 1"' in out

    def test_evaluate_when_other_edge_label_fallback(self) -> None:
        """EVALUATE_WHEN_OTHER falls back to _short_edge_label when condition is None."""
        out = self._gen(_eval_branch_report())
        assert 'label="WHEN OTHER"' in out

    # -- absence guard ----------------------------------------------------

    def test_no_branch_nodes_no_diamond_shape(self) -> None:
        """Without branch nodes, no diamond shapes appear."""
        out = self._gen(_simple_report())
        assert "shape=diamond" not in out


# ---------------------------------------------------------------------------
# TestDotFlowchartParity
# ---------------------------------------------------------------------------


class TestDotFlowchartParity:
    """DotFlowchartGenerator parity with the Mermaid recursion/GOTO/exit/THRU
    styling added in Tasks 4-6."""

    def _gen(self, report: ProgramFlowReport, **opts: Any) -> str:
        return DotFlowchartGenerator().generate(report, FlowchartOptions(**opts))

    def test_perform_recursion_edge_gets_orange_color(self) -> None:
        nodes = [_para("A", entry=True, stmt_count=1), _para("B", stmt_count=1)]
        edges = [
            FlowEdge(
                source="A", target="B", edge_type=FlowEdgeType.PERFORM, location=_loc()
            ),
            FlowEdge(
                source="B", target="A", edge_type=FlowEdgeType.PERFORM, location=_loc()
            ),
        ]
        report = ProgramFlowReport(
            program_name="RECUR-PROG",
            nodes=nodes,
            edges=edges,
            entry_points=["A"],
            cycle_details=[
                {
                    "nodes": ["A", "B"],
                    "kind": "PERFORM_RECURSION",
                    "length": 2,
                    "self_recursive": False,
                    "edge_types": ["PERFORM"],
                }
            ],
        )
        out = self._gen(report)
        assert "#e0a800" in out

    def test_goto_edge_gets_magenta_color(self) -> None:
        out = self._gen(_goto_report())
        assert "#d6336c" in out

    def test_stop_run_renders_doublecircle_terminal_node(self) -> None:
        node = _para("MAIN-LOGIC", entry=True, exit_=True, stmt_count=2)
        node.exit_statement_kind = "STOP RUN"
        node.exit_statement_location = _loc(line=42)
        report = ProgramFlowReport(
            program_name="TERM-PROG",
            nodes=[node],
            entry_points=["MAIN-LOGIC"],
        )
        out = self._gen(report)
        assert "shape=doublecircle" in out
        assert "STOP RUN" in out and "42" in out

    def test_thru_range_renders_as_dot_label_badge(self) -> None:
        nodes = [
            _para("A", entry=True, stmt_count=1),
            _para("B", stmt_count=1),
            _para("C", stmt_count=1),
            _para("D", exit_=True, stmt_count=1),
        ]
        edges = [
            FlowEdge(
                source="A",
                target="B",
                edge_type=FlowEdgeType.PERFORM,
                location=_loc(),
                thru_target="D",
                range_members=["B", "C", "D"],
            ),
            FlowEdge(
                source="A",
                target="D",
                edge_type=FlowEdgeType.PERFORM_THRU,
                location=_loc(),
                thru_target="D",
                range_members=["B", "C", "D"],
            ),
        ]
        report = ProgramFlowReport(
            program_name="THRU-PROG", nodes=nodes, edges=edges, entry_points=["A"]
        )
        out = self._gen(report)
        assert "[THRU 3]" in out
        assert "A -> D" not in out

    def test_sort_input_procedure_thru_range_renders_as_dot_badge(self) -> None:
        """Same regression guard as the Mermaid test above, for DOT output."""
        nodes = [
            _para("A", entry=True, stmt_count=1),
            _para("B", stmt_count=1),
            _para("C", stmt_count=1),
            _para("D", exit_=True, stmt_count=1),
        ]
        edges = [
            FlowEdge(
                source="A",
                target="B",
                edge_type=FlowEdgeType.SORT_INPUT_PROCEDURE,
                location=_loc(),
                thru_target="D",
                range_members=["B", "C", "D"],
            ),
            FlowEdge(
                source="A",
                target="D",
                edge_type=FlowEdgeType.SORT_INPUT_PROCEDURE_THRU,
                location=_loc(),
                thru_target="D",
                range_members=["B", "C", "D"],
            ),
        ]
        report = ProgramFlowReport(
            program_name="SORT-THRU-PROG", nodes=nodes, edges=edges, entry_points=["A"]
        )
        out = self._gen(report)
        assert "[THRU 3]" in out
        assert "A -> D" not in out

    # -- negative cases (mirroring TestMermaidFlowchartGenerator) --------

    def test_no_exit_statement_no_terminal_node(self) -> None:
        out = self._gen(_simple_report())
        assert "shape=doublecircle" not in out

    def test_terminal_node_hidden_when_unreachable_and_disabled(self) -> None:
        report = _unreachable_report()
        dead = next(n for n in report.nodes if n.name == "DEAD-CODE")
        dead.exit_statement_kind = "STOP RUN"
        dead.exit_statement_location = _loc(line=99)
        out = self._gen(report, show_unreachable=False)
        assert "shape=doublecircle" not in out

    def test_terminal_id_does_not_collide_with_real_exit_paragraph(self) -> None:
        """DOT parity with the Mermaid collision-disambiguation test above."""
        term = _para("9000-TERM", entry=True, exit_=True, stmt_count=1)
        term.exit_statement_kind = "GOBACK"
        term.exit_statement_location = _loc(line=20)
        real_exit_para = _para("9000-TERM-EXIT", stmt_count=1)
        report = ProgramFlowReport(
            program_name="COLLIDE-PROG",
            nodes=[term, real_exit_para],
            entry_points=["9000-TERM"],
        )
        out = self._gen(report)
        # The real paragraph keeps its own sanitized id and box shape.
        assert 'N_9000_TERM_EXIT [label="9000-TERM-EXIT' in out
        # The synthetic terminal node must use a DIFFERENT id.
        assert "N_9000_TERM_FLOWEXIT" in out
        assert "shape=doublecircle" in out
        assert "N_9000_TERM -> N_9000_TERM_FLOWEXIT;" in out

    def test_non_recursive_perform_edge_gets_no_color(self) -> None:
        out = self._gen(_simple_report())
        assert "#e0a800" not in out
        assert "#d6336c" not in out


# ---------------------------------------------------------------------------
# Regression: end-to-end SORT ... OUTPUT PROCEDURE ... THRU ... through the
# REAL analyzer, not a hand-built FlowEdge. This is the actual user-visible
# claim of Fix 2 -- the earlier badge-only tests above construct their own
# FlowEdge with thru_target/range_members already populated, so they pass
# unchanged whether or not analysis/program_flow/edges.py carries that data
# on the base edge. This test fails on the pre-fix analyzer (base edge had
# thru_target=None, range_members=[]) and passes on the fixed one.
# ---------------------------------------------------------------------------


class TestSortThruEndToEnd:
    def _report(self) -> ProgramFlowReport:
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SORTTHRU.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SORT-WRK ASSIGN TO 'SORTWRK'.
           SELECT IN-FILE  ASSIGN TO 'INPUT'.
       DATA DIVISION.
       FILE SECTION.
       SD SORT-WRK.
       01 SORT-REC PIC X(80).
       FD IN-FILE.
       01 IN-REC PIC X(80).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           SORT SORT-WRK ON ASCENDING KEY SORT-REC
               USING IN-FILE
               OUTPUT PROCEDURE OUT-START THRU OUT-END.
           STOP RUN.
       OUT-START.
           DISPLAY 'START'.
       OUT-MID.
           DISPLAY 'MID'.
       OUT-END.
           DISPLAY 'END'.
"""
        result = parse_cobol(source, filename="test.cbl")
        assert result.success, result.errors
        return ProgramFlowAnalyzer().analyze(result.ast)

    def test_mermaid_renders_sort_output_thru_badge(self) -> None:
        out = MermaidFlowchartGenerator().generate(self._report())
        assert "[THRU 3]" in out
        assert "MAIN_LOGIC -->|SORT OUTPUT [THRU 3]| OUT_START" in out

    def test_dot_renders_sort_output_thru_badge(self) -> None:
        out = DotFlowchartGenerator().generate(self._report())
        assert "[THRU 3]" in out
        assert "MAIN_LOGIC -> OUT_START" in out
