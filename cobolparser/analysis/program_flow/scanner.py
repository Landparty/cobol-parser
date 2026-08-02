"""Statement scanning for program flow analysis.

:class:`ProcedureScanner` walks the PROCEDURE DIVISION to collect paragraph /
section nodes, per-node statement metrics, branch (IF/EVALUATE) decision
nodes, and control transfer edges (via :class:`~.edges.EdgeCollector`). It
also records exit points (STOP RUN / GOBACK / EXIT PROGRAM) and alternate
ENTRY-statement entry points.
"""

from typing import Any

from ...models.program import CobolDivision, CobolParagraph, CobolProgram
from ...models.statements.call import CallStatement, EntryStatement
from ...models.statements.control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
    StopStatement,
)
from ...models.statements.misc import (
    AlterStatement,
    CancelStatement,
    ExitStatement,
    GobackStatement,
    MergeStatement,
    ReturnStatement,
    SortStatement,
)
from .edges import EdgeCollector
from .models import BranchArm, BranchNode, FlowEdge, FlowEdgeType, FlowNode

# Conditional clause-body attributes that may hold nested statements on IO /
# arithmetic / STRING statements the ``scan()`` dispatch does not special-case.
_CLAUSE_BODY_ATTRS: tuple[str, ...] = (
    "at_end_clause",
    "not_at_end_clause",
    "invalid_key_clause",
    "not_invalid_key_clause",
    "at_eop_clause",
    "not_at_eop_clause",
    "on_size_error",
    "not_on_size_error",
    "on_overflow",
    "not_on_overflow",
)


def is_valid_procedure_name(name: str) -> bool:
    """Check whether name looks like a real COBOL procedure name."""
    return bool(name) and name not in (".",)


class ProcedureScanner:
    """Collects flow nodes and scans statements to build edges and metrics.

    All collections passed to the constructor are shared with (and mutated in
    place for) the owning :class:`~.analyzer.ProgramFlowAnalyzer`.
    """

    def __init__(
        self,
        nodes: dict[str, FlowNode],
        ordered_procedures: list[str],
        edges: list[FlowEdge],
        entry_points: list[str],
        exit_points: set[str],
        branch_nodes: list[BranchNode],
        collector: EdgeCollector,
    ) -> None:
        self._nodes = nodes
        self._ordered_procedures = ordered_procedures
        self._edges = edges
        self._entry_points = entry_points
        self._exit_points = exit_points
        self._branch_nodes = branch_nodes
        self._collector = collector
        # Current procedure context for statement scanning
        self._current_procedure: str | None = None
        self._branch_seq: int = 0

    def collect_procedures(self, proc_division: CobolDivision) -> None:
        """Collect all paragraphs and sections as flow nodes."""
        # Collect sections and their paragraphs
        for section in proc_division._sections.values():
            name = section.section_name
            if name:
                upper_name = name.upper()
                self._nodes[upper_name] = FlowNode(
                    name=upper_name,
                    procedure_type="SECTION",
                    location=section.location,
                )
                self._ordered_procedures.append(upper_name)

            for para in section.paragraphs:
                pname = para.paragraph_name
                if pname and is_valid_procedure_name(pname):
                    upper_pname = pname.upper()
                    self._nodes[upper_pname] = FlowNode(
                        name=upper_pname,
                        procedure_type="PARAGRAPH",
                        location=para.location,
                    )
                    self._ordered_procedures.append(upper_pname)

        # Collect top-level paragraphs
        for para in proc_division.paragraphs:
            pname = para.paragraph_name
            if pname and is_valid_procedure_name(pname):
                upper_pname = pname.upper()
                if upper_pname not in self._nodes:
                    self._nodes[upper_pname] = FlowNode(
                        name=upper_pname,
                        procedure_type="PARAGRAPH",
                        location=para.location,
                    )
                    self._ordered_procedures.append(upper_pname)

    def scan_statements(self, proc_division: CobolDivision) -> None:
        """Scan all statements to build edges and compute node metrics."""
        # Scan sections
        for section in proc_division._sections.values():
            sec_name = section.section_name
            for para in section.paragraphs:
                pname = para.paragraph_name
                if pname and is_valid_procedure_name(pname):
                    self._current_procedure = pname.upper()
                    self._scan_paragraph_statements(para)

            # If section has no paragraphs, scan section-level
            if not section.paragraphs and sec_name:
                self._current_procedure = sec_name.upper()

        # Scan top-level paragraphs
        for para in proc_division.paragraphs:
            pname = para.paragraph_name
            if pname and is_valid_procedure_name(pname):
                self._current_procedure = pname.upper()
                self._scan_paragraph_statements(para)

    def collect_entry_points(self, ast: CobolProgram) -> None:
        """Collect ENTRY statements as alternate entry points."""
        all_statements = ast.get_all_statements()
        for stmt in all_statements:
            if isinstance(stmt, EntryStatement) and stmt.entry_name:
                entry_name = stmt.entry_name.strip("'\"").strip().upper()
                if entry_name and entry_name not in self._entry_points:
                    self._entry_points.append(entry_name)

    def _scan_paragraph_statements(self, para: CobolParagraph) -> None:
        """Scan all statements within a paragraph, including nested ones."""
        proc_name = self._current_procedure
        if not proc_name or proc_name not in self._nodes:
            return

        node = self._nodes[proc_name]
        visited: set[int] = set()
        # Mutable reference so nested scan() calls can read/write current arm context.
        # Used only to populate nested_call_targets; does not affect edge routing.
        arm_ctx: list[BranchArm | None] = [None]

        def _record_type(stmt: Any) -> None:
            stype = getattr(stmt, "statement_type", None)
            if stype:
                node.statement_types[stype] = node.statement_types.get(stype, 0) + 1

        def scan(stmt: Any, source_id: str | None = None) -> None:
            if source_id is None:
                source_id = proc_name
            if not hasattr(stmt, "node_type"):
                return
            if id(stmt) in visited:
                return
            visited.add(id(stmt))

            node.statement_count += 1
            _record_type(stmt)

            if isinstance(stmt, PerformStatement):
                node.perform_count += 1
                # Always use proc_name for inter-procedure edges so that
                # reachability analysis and existing consumers see the
                # containing procedure as the source, regardless of which
                # IF/EVALUATE arm the PERFORM lives in.
                self._collector.process_perform(stmt, proc_name)
                # Record perform target in current arm for swimlane data.
                if arm_ctx[0] is not None and stmt.target_paragraph:
                    target = stmt.target_paragraph.upper()
                    if target not in arm_ctx[0].nested_call_targets:
                        arm_ctx[0].nested_call_targets.append(target)
                # Recurse into inline PERFORM blocks
                for s in stmt.inline_statements:
                    scan(s, source_id)
            elif isinstance(stmt, GoStatement):
                node.goto_count += 1
                self._collector.process_goto(stmt, proc_name)
                if arm_ctx[0] is not None and stmt.target_paragraph:
                    target = stmt.target_paragraph.upper()
                    if target not in arm_ctx[0].nested_call_targets:
                        arm_ctx[0].nested_call_targets.append(target)
            elif isinstance(stmt, CallStatement):
                node.call_count += 1
                self._collector.process_call(stmt, proc_name)
                # Scan exception handler branches for nested flow
                for s in stmt.on_overflow or []:
                    scan(s, source_id)
                for s in stmt.on_exception or []:
                    scan(s, source_id)
                for s in stmt.not_on_exception or []:
                    scan(s, source_id)
            elif isinstance(stmt, IfStatement):
                node.if_count += 1
                # Derive condition text
                cond_text = "IF"
                decision: dict[str, Any] = {
                    "type": "IF",
                    "location": stmt.location.to_dict(),
                    "has_else": len(stmt.else_statements) > 0,
                }
                if stmt.condition:
                    cond_dict = stmt.condition.to_dict()
                    cond_text = cond_dict.get("expression_type", str(cond_dict))
                    decision["condition"] = cond_text
                node.decisions.append(decision)
                # Build BranchNode
                self._branch_seq += 1
                bn_id = f"{proc_name}__IF_{self._branch_seq}"
                then_id = f"{bn_id}__THEN"
                else_id = f"{bn_id}__ELSE"
                then_arm = BranchArm(
                    arm_id=then_id,
                    arm_type="THEN",
                    label="THEN",
                    statement_count=len(stmt.then_statements),
                )
                else_arm = BranchArm(
                    arm_id=else_id,
                    arm_type="ELSE",
                    label="ELSE",
                    statement_count=len(stmt.else_statements),
                )
                bn = BranchNode(
                    node_id=bn_id,
                    branch_type="IF",
                    parent_proc=proc_name,
                    location=stmt.location,
                    condition_text=cond_text,
                    arms=[then_arm, else_arm],
                )
                self._branch_nodes.append(bn)
                # Edges: source_id → branch node, branch node → arms
                self._edges.append(
                    FlowEdge(
                        source=source_id,
                        target=bn_id,
                        edge_type=FlowEdgeType.IF_BRANCH,
                        location=stmt.location,
                    )
                )
                self._edges.append(
                    FlowEdge(
                        source=bn_id,
                        target=then_id,
                        edge_type=FlowEdgeType.IF_THEN,
                        location=stmt.location,
                    )
                )
                self._edges.append(
                    FlowEdge(
                        source=bn_id,
                        target=else_id,
                        edge_type=FlowEdgeType.IF_ELSE,
                        location=stmt.location,
                    )
                )
                prev_arm = arm_ctx[0]
                arm_ctx[0] = then_arm
                for s in stmt.then_statements:
                    scan(s, then_id)
                arm_ctx[0] = else_arm
                for s in stmt.else_statements:
                    scan(s, else_id)
                arm_ctx[0] = prev_arm
            elif isinstance(stmt, EvaluateStatement):
                node.evaluate_count += 1
                subjects: list[Any] = []
                for subj in stmt.subjects:
                    if hasattr(subj, "to_dict"):
                        subjects.append(subj.to_dict())
                    else:
                        subjects.append(subj)
                subj_text = (
                    ", ".join(
                        (
                            s.get("expression_type", str(s))
                            if isinstance(s, dict)
                            else str(s)
                        )
                        for s in subjects
                    )
                    or "EVALUATE"
                )
                decision = {
                    "type": "EVALUATE",
                    "location": stmt.location.to_dict(),
                    "subjects": subjects,
                    "when_count": len(stmt.when_clauses),
                    "has_default": stmt.default_when is not None,
                }
                node.decisions.append(decision)
                # Build BranchNode
                self._branch_seq += 1
                bn_id = f"{proc_name}__EVAL_{self._branch_seq}"
                bn = BranchNode(
                    node_id=bn_id,
                    branch_type="EVALUATE",
                    parent_proc=proc_name,
                    location=stmt.location,
                    condition_text=subj_text,
                )
                self._branch_nodes.append(bn)
                # Edges: source_id → branch node
                self._edges.append(
                    FlowEdge(
                        source=source_id,
                        target=bn_id,
                        edge_type=FlowEdgeType.EVALUATE_BRANCH,
                        location=stmt.location,
                    )
                )
                # WHEN arms
                for wc_idx, wc in enumerate(stmt.when_clauses):
                    sel = wc.selectors[0] if wc.selectors else {}
                    sel_type = sel.get("type", "") if isinstance(sel, dict) else ""
                    if sel_type == "Any":
                        when_label = "WHEN ANY"
                    elif sel_type == "Literal":
                        when_label = f"WHEN {sel.get('value', '')}"
                    elif sel_type == "Identifier":
                        when_label = f"WHEN {sel.get('value', '')}"
                    elif sel_type == "Range":
                        when_label = (
                            f"WHEN {sel.get('start', '')}..{sel.get('end', '')}"
                        )
                    elif sel_type == "Condition":
                        when_label = f"WHEN {sel.get('text', '')}"
                    else:
                        when_label = f"WHEN {wc_idx + 1}"
                    arm_id = f"{bn_id}__WHEN_{wc_idx + 1}"
                    arm = BranchArm(
                        arm_id=arm_id,
                        arm_type="WHEN",
                        label=when_label,
                        statement_count=len(wc.statements),
                    )
                    bn.arms.append(arm)
                    self._edges.append(
                        FlowEdge(
                            source=bn_id,
                            target=arm_id,
                            edge_type=FlowEdgeType.EVALUATE_WHEN,
                            location=stmt.location,
                            condition=when_label,
                        )
                    )
                    prev_arm = arm_ctx[0]
                    arm_ctx[0] = arm
                    for s in wc.statements:
                        scan(s, arm_id)
                    arm_ctx[0] = prev_arm
                # WHEN OTHER arm
                if stmt.default_when:
                    other_id = f"{bn_id}__WHEN_OTHER"
                    other_arm = BranchArm(
                        arm_id=other_id,
                        arm_type="WHEN_OTHER",
                        label="WHEN OTHER",
                        statement_count=len(stmt.default_when.statements),
                    )
                    bn.arms.append(other_arm)
                    self._edges.append(
                        FlowEdge(
                            source=bn_id,
                            target=other_id,
                            edge_type=FlowEdgeType.EVALUATE_WHEN_OTHER,
                            location=stmt.location,
                            condition="WHEN OTHER",
                        )
                    )
                    prev_arm = arm_ctx[0]
                    arm_ctx[0] = other_arm
                    for s in stmt.default_when.statements:
                        scan(s, other_id)
                    arm_ctx[0] = prev_arm
            elif isinstance(stmt, SearchStatement):
                node.search_count += 1
                decision = {
                    "type": "SEARCH",
                    "location": stmt.location.to_dict(),
                    "table_name": stmt.table_name,
                    "when_count": len(stmt.when_clauses),
                    "has_at_end": bool(stmt.at_end_clause),
                }
                node.decisions.append(decision)
                for wc_dict in stmt.when_clauses:
                    for s in wc_dict.get("statements", []):
                        scan(s, source_id)
                if stmt.at_end_clause:
                    for s in stmt.at_end_clause:
                        scan(s, source_id)
            elif isinstance(stmt, SortStatement):
                self._collector.process_sort(stmt, proc_name)
            elif isinstance(stmt, MergeStatement):
                self._collector.process_merge(stmt, proc_name)
            elif isinstance(stmt, AlterStatement):
                self._collector.process_alter(stmt, source_id)
            elif isinstance(stmt, CancelStatement):
                self._collector.process_cancel(stmt, proc_name)
            elif isinstance(stmt, ReturnStatement):
                node.has_return = True
                # Scan AT END / NOT AT END branches for nested flow
                for s in stmt.at_end_clause or []:
                    scan(s)
                for s in stmt.not_at_end_clause or []:
                    scan(s)
            elif isinstance(stmt, StopStatement):
                node.has_stop_run = True
                self._exit_points.add(proc_name)
            elif isinstance(stmt, GobackStatement):
                node.has_goback = True
                self._exit_points.add(proc_name)
            elif isinstance(stmt, ExitStatement):
                exit_type = stmt.exit_type or ""
                if exit_type == "PROGRAM":
                    node.has_exit_program = True
                    self._exit_points.add(proc_name)
                elif exit_type == "SECTION":
                    node.has_exit_section = True
                elif exit_type == "PARAGRAPH":
                    node.has_exit_paragraph = True
                elif exit_type.startswith("PERFORM"):
                    # Covers both "PERFORM" and "PERFORM CYCLE"
                    node.has_exit_perform = True
            else:
                # Any other statement may still host nested control flow in a
                # conditional clause body: IO statements (READ AT END / WRITE
                # INVALID KEY / ...), arithmetic (ON SIZE ERROR), and
                # STRING/UNSTRING (ON OVERFLOW). Without descending here, a
                # PERFORM/GO TO/CALL living inside such a clause produced no
                # edge, cascading into false "unreachable" reports and missing
                # flowchart arrows.
                for attr in _CLAUSE_BODY_ATTRS:
                    clause = getattr(stmt, attr, None)
                    if isinstance(clause, list):
                        for s in clause:
                            scan(s, source_id)

        for stmt in para.statements:
            scan(stmt)
