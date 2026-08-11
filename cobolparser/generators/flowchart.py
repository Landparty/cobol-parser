"""Flowchart generators for COBOL program flow reports.

Converts a :class:`~cobolparser.analysis.program_flow.ProgramFlowReport`
into either a **Mermaid** flowchart string (renders on GitHub, VS Code, …)
or a **Graphviz DOT** digraph string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..analysis.program_flow import (
        FlowEdge,
        FlowNode,
        ProgramFlowReport,
    )


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


@dataclass
class FlowchartOptions:
    """Display options shared by both generators.

    Attributes:
        show_statement_counts: Annotate nodes with their statement count.
        show_edge_labels: Show edge-type labels on arrows (e.g. "PERFORM").
        show_fall_through: Include implicit fall-through edges.  Hidden by
            default to keep diagrams readable.
        show_unreachable: Include nodes that are never reached.
        show_external_calls: Add synthetic nodes for external CALL targets.
    """

    show_statement_counts: bool = True
    show_edge_labels: bool = True
    show_fall_through: bool = False
    show_unreachable: bool = True
    show_external_calls: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# FlowEdgeType values whose labels are worth showing explicitly
_VERBOSE_EDGE_TYPES = {
    "GOTO",
    "GOTO_DEPENDING",
    "CALL",
    "CALL_DYNAMIC",
    "SORT_INPUT_PROCEDURE",
    "SORT_INPUT_PROCEDURE_THRU",
    "SORT_OUTPUT_PROCEDURE",
    "SORT_OUTPUT_PROCEDURE_THRU",
    "MERGE_OUTPUT_PROCEDURE",
    "MERGE_OUTPUT_PROCEDURE_THRU",
    "ALTER",
    "IF_THEN",
    "IF_ELSE",
    "EVALUATE_WHEN",
    "EVALUATE_WHEN_OTHER",
}

# Edge types this generator treats as a "PERFORM-style call" versus a GO
# TO-family unconditional branch -- string-value mirrors of the enum sets
# already defined in analysis/program_flow/edges.py, kept local (rather
# than imported) since this module works entirely in the `.value` string
# space already (see etype handling throughout generate()).
_PERFORM_EDGE_TYPE_VALUES = frozenset(
    {
        "PERFORM",
        "PERFORM_THRU",
        "SORT_INPUT_PROCEDURE",
        "SORT_INPUT_PROCEDURE_THRU",
        "SORT_OUTPUT_PROCEDURE",
        "SORT_OUTPUT_PROCEDURE_THRU",
        "MERGE_OUTPUT_PROCEDURE",
        "MERGE_OUTPUT_PROCEDURE_THRU",
    }
)
_GOTO_EDGE_TYPE_VALUES = frozenset({"GOTO", "GOTO_DEPENDING", "ALTER"})

_RECURSION_LINK_STYLE = "stroke:#e0a800,stroke-width:2px,stroke-dasharray:5 5"
_GOTO_LINK_STYLE = "stroke:#d6336c,stroke-width:2px,stroke-dasharray:3 3"


def _sanitize_id(name: str) -> str:
    """Return a safe identifier derived from *name*.

    Replaces every character that is not ``[A-Za-z0-9_]`` with ``_`` and
    prepends ``N_`` when the first character is a digit.
    """
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if safe and safe[0].isdigit():
        safe = "N_" + safe
    return safe or "N_UNKNOWN"


def _recursion_pairs(report: ProgramFlowReport) -> set[tuple[str, str]]:
    """(source, target) pairs that close a PERFORM_RECURSION cycle."""
    pairs: set[tuple[str, str]] = set()
    for cycle in report.cycle_details:
        if cycle.get("kind") != "PERFORM_RECURSION":
            continue
        cycle_nodes = cycle.get("nodes", [])
        n = len(cycle_nodes)
        for i in range(n):
            pairs.add((cycle_nodes[i], cycle_nodes[(i + 1) % n]))
    return pairs


def _short_edge_label(edge_type: str) -> str:
    """Human-readable, concise label for an edge type value."""
    label_map: dict[str, str] = {
        "PERFORM": "PERFORM",
        "PERFORM_THRU": "PERFORM THRU",
        "GOTO": "GO TO",
        "GOTO_DEPENDING": "GO TO … DEPENDING",
        "CALL": "CALL",
        "CALL_DYNAMIC": "CALL (dynamic)",
        "SORT_INPUT_PROCEDURE": "SORT INPUT",
        "SORT_INPUT_PROCEDURE_THRU": "SORT INPUT THRU",
        "SORT_OUTPUT_PROCEDURE": "SORT OUTPUT",
        "SORT_OUTPUT_PROCEDURE_THRU": "SORT OUTPUT THRU",
        "MERGE_OUTPUT_PROCEDURE": "MERGE OUTPUT",
        "MERGE_OUTPUT_PROCEDURE_THRU": "MERGE OUTPUT THRU",
        "ALTER": "ALTER",
        "FALL_THROUGH": "fall-through",
        "IF_BRANCH": "IF",
        "IF_THEN": "THEN",
        "IF_ELSE": "ELSE",
        "EVALUATE_BRANCH": "EVALUATE",
        "EVALUATE_WHEN": "WHEN",
        "EVALUATE_WHEN_OTHER": "WHEN OTHER",
    }
    return label_map.get(edge_type, edge_type)


# ---------------------------------------------------------------------------
# Mermaid generator
# ---------------------------------------------------------------------------


class MermaidFlowchartGenerator:
    """Generates a Mermaid ``flowchart TD`` diagram from a flow report."""

    def generate(
        self,
        report: ProgramFlowReport,
        options: FlowchartOptions | None = None,
    ) -> str:
        """Return the Mermaid diagram as a plain string.

        Parameters
        ----------
        report:
            The analysis result produced by
            :class:`~cobolparser.analysis.program_flow.ProgramFlowAnalyzer`.
        options:
            Display options.  Defaults to :class:`FlowchartOptions` defaults.
        """
        if options is None:
            options = FlowchartOptions()

        lines: list[str] = []
        lines.append(f"%% Program: {report.program_name or 'PROGRAM'}")
        lines.append("flowchart TD")

        # ---- class definitions -------------------------------------------------
        lines.append("    classDef entry fill:#2d6a4f,stroke:#1b4332,color:#fff")
        lines.append("    classDef exit fill:#c1121f,stroke:#780000,color:#fff")
        lines.append("    classDef unreachable fill:#adb5bd,stroke:#6c757d,color:#333")
        lines.append("    classDef external fill:#6a0dad,stroke:#3d007a,color:#fff")
        lines.append("    classDef branch fill:#ffd60a,stroke:#e9c46a,color:#333")
        lines.append("    classDef arm fill:#caf0f8,stroke:#0096c7,color:#333")
        lines.append("    classDef terminal fill:#1b1b1b,stroke:#c1121f,color:#fff")

        if not report.nodes and not report.external_calls:
            lines.append("    EMPTY[No procedures found]")
            return "\n".join(lines)

        unreachable_set = set(report.unreachable_nodes)

        # ---- nodes (paragraphs / sections) ------------------------------------
        for node in report.nodes:
            if not options.show_unreachable and node.name in unreachable_set:
                continue
            nid = _sanitize_id(node.name)
            label = self._node_label(node, options)
            # paragraph → rectangle; section → rounded rectangle
            if node.procedure_type == "SECTION":
                shape = f"({label})"
            else:
                shape = f"[{label}]"
            lines.append(f"    {nid}{shape}")
            # class annotations
            if node.is_entry_point and node.is_exit_point:
                lines.append(f"    class {nid} entry")
            elif node.is_entry_point:
                lines.append(f"    class {nid} entry")
            elif node.is_exit_point:
                lines.append(f"    class {nid} exit")
            elif node.name in unreachable_set:
                lines.append(f"    class {nid} unreachable")

        # ---- exit-statement terminal nodes -------------------------------------
        for node in report.nodes:
            if not node.exit_statement_kind or not node.exit_statement_location:
                continue
            if not options.show_unreachable and node.name in unreachable_set:
                continue
            nid = _sanitize_id(node.name)
            exit_id = f"{nid}_EXIT"
            label = f"{node.exit_statement_kind} · {node.exit_statement_location.line}"
            lines.append(f'    {exit_id}((("{label}")))')
            lines.append(f"    {nid} --> {exit_id}")
            lines.append(f"    class {exit_id} terminal")

        # ---- external call nodes ----------------------------------------------
        if options.show_external_calls:
            seen_ext: set[str] = set()
            for ext in report.external_calls:
                target = ext.get("target", "")
                if not target or target in seen_ext:
                    continue
                seen_ext.add(target)
                eid = "EXT_" + _sanitize_id(target)
                lines.append(f'    {eid}(["{target}"])')
                lines.append(f"    class {eid} external")

        # ---- branch / arm nodes -----------------------------------------------
        for bn in report.branch_nodes:
            bn_id = _sanitize_id(bn.node_id)
            cond = bn.condition_text.replace('"', "#quot;")
            lines.append(f'    {bn_id}{{"[{bn.branch_type}] {cond}"}}')
            lines.append(f"    class {bn_id} branch")
            for arm in bn.arms:
                arm_id = _sanitize_id(arm.arm_id)
                arm_label = arm.label.replace('"', "#quot;")
                lines.append(f'    {arm_id}["{arm_label}"]')
                lines.append(f"    class {arm_id} arm")

        # ---- edges ------------------------------------------------------------
        recursion_pairs = _recursion_pairs(report)
        link_styles: list[str] = []
        link_index = 0
        for edge in report.edges:
            etype = (
                edge.edge_type.value
                if hasattr(edge.edge_type, "value")
                else str(edge.edge_type)
            )

            if etype == "FALL_THROUGH" and not options.show_fall_through:
                continue
            if etype.endswith("_THRU"):
                # THRU spans collapse into a badge on the base edge
                # (Task 6) instead of a second, redundant arrow.
                continue

            src_id = _sanitize_id(edge.source)
            # target: external call or internal procedure
            if etype in ("CALL", "CALL_DYNAMIC"):
                tgt_id = "EXT_" + _sanitize_id(edge.target)
                if not options.show_external_calls:
                    continue
            else:
                if not options.show_unreachable and edge.target in unreachable_set:
                    continue
                tgt_id = _sanitize_id(edge.target)

            arrow, label_parts = self._edge_style(etype, edge, options)
            if label_parts:
                edge_str = f"    {src_id} {arrow}|{' '.join(label_parts)}| {tgt_id}"
            else:
                edge_str = f"    {src_id} {arrow} {tgt_id}"
            lines.append(edge_str)

            if (
                etype in _PERFORM_EDGE_TYPE_VALUES
                and (
                    edge.source,
                    edge.target,
                )
                in recursion_pairs
            ):
                link_styles.append(
                    f"    linkStyle {link_index} {_RECURSION_LINK_STYLE}"
                )
            elif etype in _GOTO_EDGE_TYPE_VALUES:
                link_styles.append(f"    linkStyle {link_index} {_GOTO_LINK_STYLE}")
            link_index += 1

        lines.extend(link_styles)

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _node_label(node: FlowNode, options: FlowchartOptions) -> str:
        """Build the display label for a node, escaping Mermaid special chars."""
        # Mermaid labels inside [] / () don't need quoting but some chars must
        # be escaped.  We keep it simple: wrap in double-quotes when needed.
        name = node.name
        if options.show_statement_counts and node.statement_count > 0:
            label = f'"{name}\\n({node.statement_count} stmts)"'
        else:
            label = f'"{name}"'
        return label

    @staticmethod
    def _edge_style(
        etype: str,
        edge: FlowEdge,
        options: FlowchartOptions,
    ) -> tuple[str, list[str]]:
        """Return ``(arrow_str, label_parts)`` for a Mermaid edge."""
        # Arrow style
        if etype == "FALL_THROUGH":
            arrow = "-.->"
        elif etype in ("GOTO", "GOTO_DEPENDING", "ALTER"):
            arrow = "==>"
        else:
            arrow = "-->"

        label_parts: list[str] = []
        if options.show_edge_labels and etype in _VERBOSE_EDGE_TYPES:
            if etype in ("IF_THEN", "IF_ELSE", "EVALUATE_WHEN", "EVALUATE_WHEN_OTHER"):
                label_parts.append(edge.condition or _short_edge_label(etype))
            else:
                label_parts.append(_short_edge_label(etype))
        if edge.is_loop:
            label_parts.append("(loop)")

        return arrow, label_parts


# ---------------------------------------------------------------------------
# DOT (Graphviz) generator
# ---------------------------------------------------------------------------

# Colour palette (hex, no alpha)
_DOT_COLORS: dict[str, str] = {
    "entry": "#2d6a4f",
    "exit": "#c1121f",
    "unreachable": "#adb5bd",
    "external": "#6a0dad",
    "branch": "#ffd60a",
    "arm": "#caf0f8",
    "default": "#e9ecef",
}

_DOT_FONT_COLOR: dict[str, str] = {
    "entry": "white",
    "exit": "white",
    "unreachable": "#333333",
    "external": "white",
    "branch": "#333333",
    "arm": "#333333",
    "default": "#212529",
}


class DotFlowchartGenerator:
    """Generates a Graphviz DOT digraph from a flow report.

    The generated DOT can be rendered with ``dot -Tsvg``, ``dot -Tpng``, or
    any Graphviz-compatible tool.
    """

    def generate(
        self,
        report: ProgramFlowReport,
        options: FlowchartOptions | None = None,
    ) -> str:
        """Return the DOT source as a plain string.

        Parameters
        ----------
        report:
            The analysis result produced by
            :class:`~cobolparser.analysis.program_flow.ProgramFlowAnalyzer`.
        options:
            Display options.  Defaults to :class:`FlowchartOptions` defaults.
        """
        if options is None:
            options = FlowchartOptions()

        prog_name = report.program_name or "PROGRAM"
        # DOT identifiers must be quoted when they contain special chars
        quoted_name = self._dot_str(prog_name)

        lines: list[str] = []
        lines.append(f"digraph {quoted_name} {{")
        lines.append("    rankdir=TB;")
        lines.append('    node [fontname="Courier New", fontsize=10, style=filled];')
        lines.append('    edge [fontname="Courier New", fontsize=9];')
        lines.append("")

        if not report.nodes and not report.external_calls:
            lines.append('    EMPTY [label="No procedures found"];')
            lines.append("}")
            return "\n".join(lines)

        unreachable_set = set(report.unreachable_nodes)

        # ---- nodes -----------------------------------------------------------
        for node in report.nodes:
            if not options.show_unreachable and node.name in unreachable_set:
                continue
            nid = _sanitize_id(node.name)
            role = self._node_role(node, unreachable_set)
            fill = _DOT_COLORS[role]
            fontcolor = _DOT_FONT_COLOR[role]
            shape = "box" if node.procedure_type == "PARAGRAPH" else "ellipse"
            label = self._node_label_dot(node, options)
            lines.append(
                f"    {nid} [label={label}, shape={shape},"
                f' fillcolor="{fill}", fontcolor="{fontcolor}"];'
            )

        # ---- external call nodes ---------------------------------------------
        if options.show_external_calls:
            seen_ext: set[str] = set()
            for ext in report.external_calls:
                target = ext.get("target", "")
                if not target or target in seen_ext:
                    continue
                seen_ext.add(target)
                eid = "EXT_" + _sanitize_id(target)
                fill = _DOT_COLORS["external"]
                fontcolor = _DOT_FONT_COLOR["external"]
                lines.append(
                    f"    {eid} [label={self._dot_str(target)}, shape=ellipse,"
                    f' fillcolor="{fill}", fontcolor="{fontcolor}"];'
                )

        # ---- branch / arm nodes ----------------------------------------------
        for bn in report.branch_nodes:
            bn_id = _sanitize_id(bn.node_id)
            cond_label = self._dot_str(f"[{bn.branch_type}] {bn.condition_text}")
            fill = _DOT_COLORS["branch"]
            fontcolor = _DOT_FONT_COLOR["branch"]
            lines.append(
                f"    {bn_id} [label={cond_label}, shape=diamond,"
                f' fillcolor="{fill}", fontcolor="{fontcolor}"];'
            )
            for arm in bn.arms:
                arm_id = _sanitize_id(arm.arm_id)
                arm_label = self._dot_str(arm.label)
                afill = _DOT_COLORS["arm"]
                afontcolor = _DOT_FONT_COLOR["arm"]
                lines.append(
                    f"    {arm_id} [label={arm_label}, shape=box,"
                    f' fillcolor="{afill}", fontcolor="{afontcolor}"];'
                )

        lines.append("")

        # ---- edges -----------------------------------------------------------
        for edge in report.edges:
            etype = (
                edge.edge_type.value
                if hasattr(edge.edge_type, "value")
                else str(edge.edge_type)
            )

            if etype == "FALL_THROUGH" and not options.show_fall_through:
                continue

            src_id = _sanitize_id(edge.source)
            if etype in ("CALL", "CALL_DYNAMIC"):
                tgt_id = "EXT_" + _sanitize_id(edge.target)
                if not options.show_external_calls:
                    continue
            else:
                if not options.show_unreachable and edge.target in unreachable_set:
                    continue
                tgt_id = _sanitize_id(edge.target)

            attrs = self._edge_attrs(etype, edge, options)
            if attrs:
                attr_str = (
                    " [" + ", ".join(f'{k}="{v}"' for k, v in attrs.items()) + "]"
                )
            else:
                attr_str = ""
            lines.append(f"    {src_id} -> {tgt_id}{attr_str};")

        lines.append("}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _node_role(node: FlowNode, unreachable_set: set[str]) -> str:
        if node.is_entry_point:
            return "entry"
        if node.is_exit_point:
            return "exit"
        if node.name in unreachable_set:
            return "unreachable"
        return "default"

    @staticmethod
    def _dot_str(text: str) -> str:
        """Wrap *text* in double-quotes, escaping internal quotes."""
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def _node_label_dot(self, node: FlowNode, options: FlowchartOptions) -> str:
        name = node.name
        if options.show_statement_counts and node.statement_count > 0:
            return self._dot_str(f"{name}\\n({node.statement_count} stmts)")
        return self._dot_str(name)

    def _edge_attrs(
        self,
        etype: str,
        edge: FlowEdge,
        options: FlowchartOptions,
    ) -> dict[str, str]:
        attrs: dict[str, str] = {}

        # style
        if etype == "FALL_THROUGH":
            attrs["style"] = "dashed"
        elif etype in ("GOTO", "GOTO_DEPENDING", "ALTER"):
            attrs["penwidth"] = "2"
        if edge.is_loop:
            attrs["color"] = "darkorange"

        # label
        if options.show_edge_labels and etype in _VERBOSE_EDGE_TYPES:
            if etype in ("IF_THEN", "IF_ELSE", "EVALUATE_WHEN", "EVALUATE_WHEN_OTHER"):
                lbl = edge.condition or _short_edge_label(etype)
            else:
                lbl = _short_edge_label(etype)
            if edge.is_loop:
                lbl += " (loop)"
            attrs["label"] = lbl
        elif edge.is_loop:
            attrs["label"] = "(loop)"

        return attrs
