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
        BranchArm,
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
    "XML_PROCESSING_PROCEDURE",
    "XML_PROCESSING_PROCEDURE_THRU",
    "CICS_HANDLE",
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
        "XML_PROCESSING_PROCEDURE",
        "XML_PROCESSING_PROCEDURE_THRU",
    }
)
_GOTO_EDGE_TYPE_VALUES = frozenset({"GOTO", "GOTO_DEPENDING", "ALTER", "CICS_HANDLE"})

_RECURSION_LINK_STYLE = "stroke:#e0a800,stroke-width:2px,stroke-dasharray:5 5"
_GOTO_LINK_STYLE = "stroke:#d6336c,stroke-width:2px,stroke-dasharray:3 3"


def _external_call_target(ext: dict) -> str:
    """The called-program name from an external-call record.

    ``EdgeCollector.process_call`` (analysis/program_flow/edges.py) emits the
    name under the ``"program"`` key; ``"target"`` is kept as a fallback for
    hand-built report dicts that predate this fix. Returned UPPERCASED so the
    synthetic ``EXT_*`` node id agrees with ``FlowEdge.target``, which the
    edge collector uppercases (``call_info["program"]`` keeps the source's
    original case) -- otherwise a lowercase CALL literal produced an edge
    pointing at an ``EXT_`` id no node declared.
    """
    target = ext.get("program") or ext.get("target") or ""
    return target.upper()


def _escape_mermaid_label(text: str) -> str:
    """Escape characters Mermaid mangles inside quoted label text.

    A bare ``>`` is silently swallowed by Mermaid's (v11, htmlLabels:false)
    label sanitization -- ``WS-PURGE-ERRORS > ZERO`` renders as
    ``WS-PURGE-ERRORS ZERO`` and ``>=`` as ``=``. Mermaid's ``#name;``
    entity syntax survives both the lexer and the sanitizer for ``<``/``>``
    (``<`` included: followed by a letter it reads as an HTML tag opener and
    would be stripped the same way).

    ``"`` breaks the quoted-string lexing outright, and its ``#quot;``
    entity is NOT decoded on the SVG-text label path -- it renders as
    literal ``&quot;`` (verified against Mermaid 11.12). These are
    display-only labels, so a double quote becomes a plain apostrophe
    instead: the parser normalizes COBOL literals to double quotes, and
    ``MOVE 'ACTIVE' TO WS-STATE`` is how the source read anyway.
    """
    return text.replace('"', "'").replace("<", "#lt;").replace(">", "#gt;")


def _arm_summary_label(arm: BranchArm) -> str:
    """Display label for a branch arm box.

    Prefers the arm's statement summary ("MOVE 8 TO RETURN-CODE") over the
    bare arm keyword ("THEN"/"ELSE"/"WHEN x"), which duplicates the edge
    label and says nothing about what the arm does.
    """
    if arm.summary:
        return arm.summary
    return arm.label


def _is_empty_if_arm(branch_type: str, arm: BranchArm) -> bool:
    """True for an IF arm with no statements and no nested transfers.

    Every IF gets an ELSE arm from the scanner even when the source has no
    ELSE clause; drawing an empty "ELSE" box is pure noise. EVALUATE arms
    are never dropped -- an empty WHEN still documents that its selector
    value is deliberately handled.
    """
    return (
        branch_type == "IF" and arm.statement_count == 0 and not arm.nested_call_targets
    )


def _sanitize_id(name: str) -> str:
    """Return a safe identifier derived from *name*.

    Replaces every character that is not ``[A-Za-z0-9_]`` with ``_`` and
    prepends ``N_`` when the first character is a digit.
    """
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if safe and safe[0].isdigit():
        safe = "N_" + safe
    return safe or "N_UNKNOWN"


def _unique_exit_id(nid: str, paragraph_ids: set[str]) -> str:
    """Return a terminal-node id derived from *nid* that cannot collide with
    a real paragraph's sanitized id.

    ``PERFORM X THRU X-EXIT`` is a common COBOL range idiom, so a program
    can legitimately contain a paragraph literally named e.g. ``9000-TERM-
    EXIT``. ``_sanitize_id`` turns both "9000-TERM" + our own "_EXIT" suffix
    and the real paragraph "9000-TERM-EXIT" into the same id
    (``N_9000_TERM_EXIT``), which would silently merge two distinct nodes.
    Fall back to a suffix that's very unlikely to collide, then to an
    incrementing numeric suffix in the pathological case that even that
    collides too.
    """
    candidate = f"{nid}_EXIT"
    if candidate not in paragraph_ids:
        return candidate
    candidate = f"{nid}_FLOWEXIT"
    if candidate not in paragraph_ids:
        return candidate
    suffix = 2
    while f"{nid}_FLOWEXIT_{suffix}" in paragraph_ids:
        suffix += 1
    return f"{nid}_FLOWEXIT_{suffix}"


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
        # ASCII only (here and in every emitted label): the CLI writes
        # stdout in the console's locale encoding on Windows (cp1252), while
        # consumers (the VS Code extension among them) decode UTF-8 -- any
        # non-ASCII character renders as U+FFFD "?" in the diagram.
        "GOTO_DEPENDING": "GO TO ... DEPENDING",
        "CALL": "CALL",
        "CALL_DYNAMIC": "CALL (dynamic)",
        "SORT_INPUT_PROCEDURE": "SORT INPUT",
        "SORT_INPUT_PROCEDURE_THRU": "SORT INPUT THRU",
        "SORT_OUTPUT_PROCEDURE": "SORT OUTPUT",
        "SORT_OUTPUT_PROCEDURE_THRU": "SORT OUTPUT THRU",
        "MERGE_OUTPUT_PROCEDURE": "MERGE OUTPUT",
        "MERGE_OUTPUT_PROCEDURE_THRU": "MERGE OUTPUT THRU",
        "XML_PROCESSING_PROCEDURE": "XML PARSE handler",
        "XML_PROCESSING_PROCEDURE_THRU": "XML PARSE handler THRU",
        "CICS_HANDLE": "CICS HANDLE",
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
        paragraph_ids = {_sanitize_id(n.name) for n in report.nodes}
        terminal_link_count = 0
        for node in report.nodes:
            if not node.exit_statement_kind or not node.exit_statement_location:
                continue
            if not options.show_unreachable and node.name in unreachable_set:
                continue
            nid = _sanitize_id(node.name)
            exit_id = _unique_exit_id(nid, paragraph_ids)
            # "@" (not a middle dot) -- emitted labels must stay ASCII, see
            # the encoding note on _short_edge_label's map.
            label = f"{node.exit_statement_kind} @ {node.exit_statement_location.line}"
            lines.append(f'    {exit_id}((("{label}")))')
            lines.append(f"    {nid} --> {exit_id}")
            lines.append(f"    class {exit_id} terminal")
            terminal_link_count += 1

        # ---- external call nodes ----------------------------------------------
        if options.show_external_calls:
            seen_ext: set[str] = set()
            for ext in report.external_calls:
                target = _external_call_target(ext)
                if not target or target in seen_ext:
                    continue
                seen_ext.add(target)
                eid = "EXT_" + _sanitize_id(target)
                lines.append(f'    {eid}(["{target}"])')
                lines.append(f"    class {eid} external")

        # ---- branch / arm nodes -----------------------------------------------
        skipped_arm_ids: set[str] = set()
        for bn in report.branch_nodes:
            bn_id = _sanitize_id(bn.node_id)
            cond = _escape_mermaid_label(bn.condition_text)
            lines.append(f'    {bn_id}{{"[{bn.branch_type}] {cond}"}}')
            lines.append(f"    class {bn_id} branch")
            for arm in bn.arms:
                arm_id = _sanitize_id(arm.arm_id)
                if _is_empty_if_arm(bn.branch_type, arm):
                    skipped_arm_ids.add(arm_id)
                    continue
                arm_label = _escape_mermaid_label(_arm_summary_label(arm))
                if arm.summary and arm.statement_count > 1:
                    arm_label += f"\\n+{arm.statement_count - 1} more"
                lines.append(f'    {arm_id}["{arm_label}"]')
                lines.append(f"    class {arm_id} arm")

        # ---- edges ------------------------------------------------------------
        recursion_pairs = _recursion_pairs(report)
        link_styles: list[str] = []
        # Mermaid's `linkStyle N` addresses links by their order of
        # *definition in the whole diagram*, not just within this loop.
        # The terminal-node loop above already emitted `terminal_link_count`
        # `-->` links, so this loop's own link indices must start after
        # them -- otherwise every terminal-node link shifts all of these
        # indices and recursion/GO TO colors land on the wrong arrows.
        link_index = terminal_link_count
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
                # An edge into an arm box that was dropped as empty would
                # make Mermaid re-create the node with its bare id as label.
                if tgt_id in skipped_arm_ids:
                    continue

            arrow, label_parts = self._edge_style(etype, edge, options)
            if label_parts:
                # Quoted (not bare) label text: an unquoted "(" or "["
                # inside a Mermaid `|label|` is read by the flowchart
                # lexer as the start of a node shape (PS / SQS tokens),
                # not literal text -- e.g. a PERFORM UNTIL edge's "(loop)"
                # suffix or a THRU edge's "[THRU n]" badge breaks parsing
                # without the quotes. _escape_mermaid_label additionally
                # neutralizes the "/</> that COBOL condition text can
                # carry into the label.
                label_text = _escape_mermaid_label(" ".join(label_parts))
                edge_str = f'    {src_id} {arrow}|"{label_text}"| {tgt_id}'
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
        elif options.show_edge_labels and etype == "PERFORM" and edge.condition:
            label_parts.append(f"{_short_edge_label(etype)} UNTIL {edge.condition}")
        if edge.is_loop:
            label_parts.append("(loop)")
        if edge.thru_target and edge.range_members:
            label_parts.append(f"[THRU {len(edge.range_members)}]")

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

        # ---- exit-statement terminal nodes -------------------------------------
        paragraph_ids = {_sanitize_id(n.name) for n in report.nodes}
        for node in report.nodes:
            if not node.exit_statement_kind or not node.exit_statement_location:
                continue
            if not options.show_unreachable and node.name in unreachable_set:
                continue
            nid = _sanitize_id(node.name)
            exit_id = _unique_exit_id(nid, paragraph_ids)
            # "@" (not a middle dot): keep emitted labels ASCII, matching the
            # Mermaid generator (see the encoding note on _short_edge_label).
            label = self._dot_str(
                f"{node.exit_statement_kind} @ {node.exit_statement_location.line}"
            )
            lines.append(
                f"    {exit_id} [label={label}, shape=doublecircle,"
                f' fillcolor="#1b1b1b", fontcolor="#c1121f"];'
            )
            lines.append(f"    {nid} -> {exit_id};")

        # ---- external call nodes ---------------------------------------------
        if options.show_external_calls:
            seen_ext: set[str] = set()
            for ext in report.external_calls:
                target = _external_call_target(ext)
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
        skipped_arm_ids: set[str] = set()
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
                if _is_empty_if_arm(bn.branch_type, arm):
                    skipped_arm_ids.add(arm_id)
                    continue
                arm_text = _arm_summary_label(arm)
                if arm.summary and arm.statement_count > 1:
                    # Single-line "(+N more)" -- a "\n" here would collide
                    # with _dot_str's backslash escaping.
                    arm_text += f" (+{arm.statement_count - 1} more)"
                arm_label = self._dot_str(arm_text)
                afill = _DOT_COLORS["arm"]
                afontcolor = _DOT_FONT_COLOR["arm"]
                lines.append(
                    f"    {arm_id} [label={arm_label}, shape=box,"
                    f' fillcolor="{afill}", fontcolor="{afontcolor}"];'
                )

        lines.append("")

        # ---- edges -----------------------------------------------------------
        recursion_pairs = _recursion_pairs(report)
        for edge in report.edges:
            etype = (
                edge.edge_type.value
                if hasattr(edge.edge_type, "value")
                else str(edge.edge_type)
            )

            if etype == "FALL_THROUGH" and not options.show_fall_through:
                continue
            if etype.endswith("_THRU"):
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
                # Parity with the Mermaid generator: no edges into arm
                # boxes dropped as empty (DOT would auto-create the node).
                if tgt_id in skipped_arm_ids:
                    continue

            attrs = self._edge_attrs(etype, edge, options)
            if (
                etype in _PERFORM_EDGE_TYPE_VALUES
                and (
                    edge.source,
                    edge.target,
                )
                in recursion_pairs
            ):
                attrs["color"] = "#e0a800"
                attrs["style"] = "dashed"
            elif etype in _GOTO_EDGE_TYPE_VALUES:
                attrs["color"] = "#d6336c"
                attrs["style"] = "dashed"
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
        elif options.show_edge_labels and etype == "PERFORM" and edge.condition:
            lbl = f"{_short_edge_label(etype)} UNTIL {edge.condition}"
            if edge.is_loop:
                lbl += " (loop)"
            attrs["label"] = lbl
        elif edge.is_loop:
            attrs["label"] = "(loop)"

        if edge.thru_target and edge.range_members:
            n = len(edge.range_members)
            attrs["label"] = f"{attrs.get('label', '')} [THRU {n}]".strip()

        return attrs
