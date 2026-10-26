"""Statement scanning for program flow analysis.

:class:`ProcedureScanner` walks the PROCEDURE DIVISION to collect paragraph /
section nodes, per-node statement metrics, branch (IF/EVALUATE) decision
nodes, and control transfer edges (via :class:`~.edges.EdgeCollector`). It
also records exit points (STOP RUN / GOBACK / EXIT PROGRAM) and alternate
ENTRY-statement entry points.
"""

from collections.abc import Callable
from typing import Any, cast

from ...models.program import CobolDivision, CobolParagraph, CobolProgram, CobolSection
from ...models.sql_statements import ExecSQLStatement
from ...models.statements.base import CobolExpression
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
    XmlJsonStatement,
)
from .._cics import cics_exit_kind, cics_terminator_kind
from .._procedures import ProcedureIndex, branch_terminates, enclosing_section
from .condition_text import render_condition_text
from .edges import EdgeCollector
from .models import BranchArm, BranchNode, FlowEdge, FlowEdgeType, FlowNode
from .statement_text import summarize_arm

# Conditional clause-body attributes that may hold nested statements on IO /
# arithmetic / STRING / ACCEPT / DISPLAY statements the ``scan()`` dispatch
# does not special-case (XML/JSON PARSE and GENERATE are special-cased for
# their PROCESSING PROCEDURE edge, and queue the same exception bodies there).
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
    "on_exception",
    "not_on_exception",
)


# The flow node standing for sentences written before the PROCEDURE
# DIVISION's first paragraph/section header (the parser keeps them as an
# unnamed top-level paragraph). They are what runs first, so they are the
# program's entry; the name holds a blank, so no COBOL procedure name can
# ever collide with it.
LEADING_SENTENCES_NODE = "PROCEDURE DIVISION"


def leading_sentences(proc_division: CobolDivision) -> CobolParagraph | None:
    """The unnamed paragraph holding the division's leading sentences, if
    it comes before every named paragraph and section and has statements."""
    items: list[Any] = sorted(
        [*proc_division._sections.values(), *proc_division.paragraphs],
        key=lambda item: item.location.line,
    )
    if not items or isinstance(items[0], CobolSection):
        return None
    first = items[0]
    if first.paragraph_name or not first.statements:
        return None
    return cast(CobolParagraph, first)


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
        terminating_paragraphs: set[str],
        exit_section_procedures: dict[str, str] | None = None,
    ) -> None:
        self._nodes = nodes
        self._ordered_procedures = ordered_procedures
        self._edges = edges
        self._entry_points = entry_points
        self._exit_points = exit_points
        self._branch_nodes = branch_nodes
        self._collector = collector
        # Paragraphs where at least one of the paragraph's own TOP-LEVEL
        # statements unconditionally transfers control away (STOP RUN,
        # GOBACK, EXIT PROGRAM, or a bare non-DEPENDING GO TO) -- i.e. one
        # that always fires when reached, as opposed to the same kind of
        # statement nested inside an IF/EVALUATE arm, which only fires
        # conditionally. Populated below; consumed by
        # build_fall_through_edges() to decide fall-through suppression.
        self._terminating_paragraphs = terminating_paragraphs
        # Procedure -> the section it leaves by a top-level EXIT SECTION
        # (no unconditional terminator before it). Such a procedure never
        # falls into the next paragraph; build_fall_through_edges() decides
        # whether control carries on past the end of the section.
        self._exit_section_procedures: dict[str, str] = (
            exit_section_procedures if exit_section_procedures is not None else {}
        )
        # Current procedure context for statement scanning
        self._current_procedure: str | None = None
        self._branch_seq: int = 0
        # Procedure identities (unique keys for same-named paragraphs);
        # rebuilt by collect_procedures().
        self._index = ProcedureIndex([])

    @property
    def index(self) -> ProcedureIndex:
        """The procedure identities :meth:`collect_procedures` built."""
        return self._index

    def collect_procedures(self, proc_division: CobolDivision) -> None:
        """Collect all paragraphs and sections as flow nodes.

        COBOL allows paragraphs before the first SECTION header, so sections
        and top-level paragraphs are interleaved by source line to preserve
        physical order (entry-point detection and fall-through edges both
        depend on ``_ordered_procedures`` matching source order).
        """
        leading = leading_sentences(proc_division)
        if leading is not None:
            self._nodes[LEADING_SENTENCES_NODE] = FlowNode(
                name=LEADING_SENTENCES_NODE,
                procedure_type="PARAGRAPH",
                location=leading.location,
            )
            self._ordered_procedures.append(LEADING_SENTENCES_NODE)

        self._index = ProcedureIndex.build(proc_division)
        self._collector.set_index(self._index)
        for entry in self._index.entries:
            if entry.key in self._nodes:
                continue
            self._nodes[entry.key] = FlowNode(
                name=entry.name,
                procedure_type=entry.procedure_type,
                location=entry.location,
                qualified_name=entry.qualified_name,
            )
            self._ordered_procedures.append(entry.key)

    def scan_statements(self, proc_division: CobolDivision) -> None:
        """Scan all statements to build edges and compute node metrics."""
        # Scan sections. A bare SECTION header owns no statements of its own
        # (CobolSection carries only paragraphs/data_items), so an empty
        # section has nothing to scan. Sentences written between the header
        # and the first paragraph header land in an unnamed paragraph: they
        # are the section node's own statements (its PERFORMs, its STOP RUN
        # suppressing the section's fall-through), not something to skip.
        keys = {id(entry.node): entry.key for entry in self._index.entries}
        for section in proc_division._sections.values():
            for para in section.paragraphs:
                pname = para.paragraph_name or section.section_name
                body = section if not para.paragraph_name else para
                # A procedure the index dropped as a duplicate key (which
                # the compiler rejects) still merges into its namesake.
                key = keys.get(id(body)) or (
                    pname.upper() if pname and is_valid_procedure_name(pname) else None
                )
                if key is not None:
                    self._current_procedure = key
                    self._scan_paragraph_statements(para)

        # Scan top-level paragraphs
        leading = leading_sentences(proc_division)
        for para in proc_division.paragraphs:
            pname = para.paragraph_name
            if para is leading:
                pname = LEADING_SENTENCES_NODE
            if pname and is_valid_procedure_name(pname):
                self._current_procedure = pname.upper()
                self._scan_paragraph_statements(para)

    def collect_entry_points(self, ast: CobolProgram) -> None:
        """Collect the paragraphs containing ENTRY statements as alternate
        entry points.

        An ENTRY statement's literal name (e.g. ``'ALTENTRY'``) is not a node
        key in the paragraph graph -- it is the *containing paragraph* that
        must be treated as reachable, since that is what actually runs when
        the alternate entry point is called.
        """
        all_statements = ast.get_all_statements()
        # A contained program's ENTRY names a paragraph of *that* unit, not
        # of this one (procedure names are local to a program unit).
        inner = {
            id(stmt)
            for contained in ast.contained_programs
            for stmt in contained.get_all_statements()
        }
        for stmt in all_statements:
            if id(stmt) in inner:
                continue
            if not isinstance(stmt, EntryStatement) or not stmt.entry_name:
                continue
            # An ENTRY statement with a blank/whitespace-only literal name
            # isn't a real alternate entry point; keep the existing filter
            # so such statements don't register a spurious entry point.
            if not stmt.entry_name.strip("'\"").strip():
                continue
            para_name = stmt.section_name
            if not para_name or not para_name.strip():
                continue
            for key in self._index.resolve(
                para_name, from_section=enclosing_section(stmt)
            ):
                if key not in self._entry_points:
                    self._entry_points.append(key)

    @staticmethod
    def _record_exit_statement(node: FlowNode, kind: str, location: Any) -> None:
        """Record the first exit statement seen in this paragraph.

        First-write-wins: a paragraph with more than one exit statement
        (e.g. one per IF branch) keeps whichever was scanned first: the
        terminal-node rendering (flowchart.py, Task 5) draws one terminal
        node per paragraph, not per statement.
        """
        if node.exit_statement_kind is None:
            node.exit_statement_kind = kind
            node.exit_statement_location = location

    def _scan_paragraph_statements(self, para: CobolParagraph) -> None:
        """Scan all statements within a paragraph, including nested ones.

        Uses an explicit work stack of zero-argument thunks instead of
        recursing through Python's call stack — mirrors
        :func:`.cycles.detect_cycles`'s frame-stack fix — so IF/EVALUATE/
        PERFORM trees of arbitrary nesting depth (e.g. machine-generated
        COBOL with hundreds of nested inline blocks) cannot exceed
        ``sys.getrecursionlimit()``. Each queued statement carries the
        branch arm it is nested under explicitly (what the old mutable
        ``arm_ctx`` slot held at that point in the recursive call chain)
        rather than relying on a shared variable restored when a call
        returns.
        """
        proc_name = self._current_procedure
        if not proc_name or proc_name not in self._nodes:
            return

        node = self._nodes[proc_name]
        visited: set[int] = set()
        work: list[Callable[[], None]] = []

        def _record_type(stmt: Any) -> None:
            stype = getattr(stmt, "statement_type", None)
            if stype:
                node.statement_types[stype] = node.statement_types.get(stype, 0) + 1

        def push_one(stmt: Any, source_id: str, arm: BranchArm | None) -> None:
            work.append(lambda: visit(stmt, source_id, arm))

        def push_many(stmts: list[Any], source_id: str, arm: BranchArm | None) -> None:
            # Push in reverse so the LIFO ``work`` stack pops them back out in
            # original left-to-right order, with each item's full subtree
            # processed before its next sibling — the same order the old
            # recursive ``for s in stmts: scan(s, ...)`` loop produced.
            for s in reversed(stmts):
                push_one(s, source_id, arm)

        def push_sequential(
            groups: list[tuple[list[Any], str, BranchArm | None]],
        ) -> None:
            # ``groups`` lists statement lists in the order they must be
            # fully drained — each list's own subtree processed before the
            # next list's first item — replicating consecutive
            # ``for``/``scan()`` loops from the pre-stack version.
            for stmts, source_id, arm in reversed(groups):
                push_many(stmts, source_id, arm)

        def visit(stmt: Any, source_id: str, arm: BranchArm | None) -> None:
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
                if arm is not None:
                    for target in self._collector.resolve(
                        stmt, stmt.target_paragraph, "target_qualifier"
                    ):
                        if target not in arm.nested_call_targets:
                            arm.nested_call_targets.append(target)
                # Queue inline PERFORM blocks
                push_many(stmt.inline_statements, source_id, arm)
            elif isinstance(stmt, GoStatement):
                node.goto_count += 1
                self._collector.process_goto(stmt, proc_name)
                if arm is not None:
                    for target in self._collector.resolve(
                        stmt, stmt.target_paragraph, "target_qualifier"
                    ):
                        if target not in arm.nested_call_targets:
                            arm.nested_call_targets.append(target)
            elif isinstance(stmt, CallStatement):
                node.call_count += 1
                self._collector.process_call(stmt, proc_name)
                # Queue exception handler branches for nested flow
                push_sequential(
                    [
                        (stmt.on_overflow or [], source_id, arm),
                        (stmt.on_exception or [], source_id, arm),
                        (stmt.not_on_exception or [], source_id, arm),
                    ]
                )
            elif isinstance(stmt, IfStatement):
                node.if_count += 1
                # Derive condition text
                cond_text = (
                    render_condition_text(stmt.condition) if stmt.condition else "IF"
                )
                decision: dict[str, Any] = {
                    "type": "IF",
                    "location": stmt.location.to_dict(),
                    "has_else": len(stmt.else_statements) > 0,
                }
                if stmt.condition:
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
                    summary=summarize_arm(stmt.then_statements),
                )
                else_arm = BranchArm(
                    arm_id=else_id,
                    arm_type="ELSE",
                    label="ELSE",
                    statement_count=len(stmt.else_statements),
                    summary=summarize_arm(stmt.else_statements),
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
                push_sequential(
                    [
                        (stmt.then_statements, then_id, then_arm),
                        (stmt.else_statements, else_id, else_arm),
                    ]
                )
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
                            render_condition_text(cast(CobolExpression, subj))
                            if hasattr(subj, "to_dict")
                            else str(subj)
                        )
                        for subj in stmt.subjects
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
                # WHEN arms. Each clause's own arm/edge bookkeeping is
                # deferred into a thunk queued alongside its statements, so
                # WHEN k+1's edge is only appended once WHEN k's subtree is
                # fully drained from the work stack — matching the
                # interleaving the old recursive version produced.
                #
                # Stacked WHENs (``WHEN 'A' WHEN 'B' stmt``) are one arm: the
                # statements after the last WHEN run for every WHEN in the
                # stack, so the group is numbered and drawn as one.
                clause_thunks: list[Callable[[], None]] = []
                for wc_idx, group in enumerate(stmt.when_groups()):
                    wc = group[-1]
                    when_label = " / ".join(
                        _when_label(member, wc_idx) for member in group
                    )
                    arm_id = f"{bn_id}__WHEN_{wc_idx + 1}"
                    when_arm = BranchArm(
                        arm_id=arm_id,
                        arm_type="WHEN",
                        label=when_label,
                        statement_count=len(wc.statements),
                        summary=summarize_arm(wc.statements),
                    )

                    def _when_thunk(
                        wc: Any = wc,
                        arm_id: str = arm_id,
                        when_arm: BranchArm = when_arm,
                        when_label: str = when_label,
                    ) -> None:
                        bn.arms.append(when_arm)
                        self._edges.append(
                            FlowEdge(
                                source=bn_id,
                                target=arm_id,
                                edge_type=FlowEdgeType.EVALUATE_WHEN,
                                location=stmt.location,
                                condition=when_label,
                            )
                        )
                        push_many(wc.statements, arm_id, when_arm)

                    clause_thunks.append(_when_thunk)
                # WHEN OTHER arm
                if stmt.default_when:
                    other_id = f"{bn_id}__WHEN_OTHER"
                    other_arm = BranchArm(
                        arm_id=other_id,
                        arm_type="WHEN_OTHER",
                        label="WHEN OTHER",
                        statement_count=len(stmt.default_when.statements),
                        summary=summarize_arm(stmt.default_when.statements),
                    )
                    default_when = stmt.default_when

                    def _other_thunk(
                        other_id: str = other_id,
                        other_arm: BranchArm = other_arm,
                        default_when: Any = default_when,
                    ) -> None:
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
                        push_many(default_when.statements, other_id, other_arm)

                    clause_thunks.append(_other_thunk)
                for thunk in reversed(clause_thunks):
                    work.append(thunk)
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
                search_groups: list[tuple[list[Any], str, BranchArm | None]] = [
                    (wc_dict.get("statements", []), source_id, arm)
                    for wc_dict in stmt.when_clauses
                ]
                if stmt.at_end_clause:
                    search_groups.append((stmt.at_end_clause, source_id, arm))
                push_sequential(search_groups)
            elif isinstance(stmt, SortStatement):
                self._collector.process_sort(stmt, proc_name)
            elif isinstance(stmt, MergeStatement):
                self._collector.process_merge(stmt, proc_name)
            elif isinstance(stmt, XmlJsonStatement):
                self._collector.process_xml_parse(stmt, proc_name)
                # ON EXCEPTION / NOT ON EXCEPTION bodies run in this
                # paragraph like any other conditional clause: a PERFORM or
                # GO TO there is an edge, not dead text.
                push_sequential(
                    [
                        (stmt.on_exception or [], source_id, arm),
                        (stmt.not_on_exception or [], source_id, arm),
                    ]
                )
            elif getattr(stmt, "node_type", None) == "EXEC_CICS":
                self._collector.process_cics_handle(stmt, proc_name)
                # Set even when RESP/NOHANDLE lets a failure fall through:
                # on success the command still leaves the program, so it is
                # an exit point and a way out of a loop (_is_terminator
                # alone applies the RESP exemption).
                cics_exit = cics_exit_kind(stmt)
                if cics_exit is not None:
                    node.has_cics_exit = True
                    self._exit_points.add(proc_name)
                    self._record_exit_statement(node, cics_exit, stmt.location)
            elif isinstance(stmt, ExecSQLStatement):
                self._collector.process_sql_whenever(stmt, proc_name)
            elif isinstance(stmt, AlterStatement):
                self._collector.process_alter(stmt, source_id)
            elif isinstance(stmt, CancelStatement):
                self._collector.process_cancel(stmt, proc_name)
            elif isinstance(stmt, ReturnStatement):
                node.has_return = True
                # Queue AT END / NOT AT END branches for nested flow. The
                # original recursive scan(s) call (no source_id argument)
                # defaulted to proc_name rather than inheriting source_id —
                # preserved here.
                push_sequential(
                    [
                        (stmt.at_end_clause or [], proc_name, arm),
                        (stmt.not_at_end_clause or [], proc_name, arm),
                    ]
                )
            elif isinstance(stmt, StopStatement):
                if stmt.stop_type == "RUN":
                    node.has_stop_run = True
                    self._exit_points.add(proc_name)
                    self._record_exit_statement(node, "STOP RUN", stmt.location)
            elif isinstance(stmt, GobackStatement):
                node.has_goback = True
                self._exit_points.add(proc_name)
                self._record_exit_statement(node, "GOBACK", stmt.location)
            elif isinstance(stmt, ExitStatement):
                exit_type = stmt.exit_type or ""
                if exit_type == "PROGRAM":
                    node.has_exit_program = True
                    self._exit_points.add(proc_name)
                    self._record_exit_statement(node, "EXIT PROGRAM", stmt.location)
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
                clause_groups: list[tuple[list[Any], str, BranchArm | None]] = []
                for attr in _CLAUSE_BODY_ATTRS:
                    clause = getattr(stmt, attr, None)
                    if isinstance(clause, list):
                        clause_groups.append((clause, source_id, arm))
                push_sequential(clause_groups)

        push_many(para.statements, proc_name, None)
        while work:
            work.pop()()

        # A paragraph never falls through to the next one when any of its
        # own TOP-LEVEL statements unconditionally transfers control away.
        # Any position counts, not just the last: once such a statement is
        # reached it always fires, so whatever is physically written after
        # it in the same paragraph is itself unreachable and irrelevant to
        # whether the paragraph as a whole falls through -- checking only
        # para.statements[-1] would miss a mid-paragraph terminator followed
        # by dead trailing statements. Only statements directly in
        # para.statements qualify: one nested inside a single IF/EVALUATE arm
        # only fires conditionally and must not suppress fall-through
        # whenever that branch isn't taken -- unless the branch is exhaustive
        # and every arm terminates (_is_terminator, #586). (A terminator inside an unconditional
        # bare PERFORM ... END-PERFORM block -- no UNTIL/TIMES -- is a rare
        # construct not covered here, since inline PERFORM bodies are not
        # top-level statements either.)
        if any(self._is_terminator(stmt) for stmt in para.statements):
            self._terminating_paragraphs.add(proc_name)
        # EXIT SECTION passes control to the end of the section, so it never
        # falls into the next paragraph either. Outside a section the
        # compiler rejects it, and nothing is assumed of it.
        section = self._index.section_of(proc_name)
        if section is not None:
            for stmt in para.statements:
                if self._is_terminator(stmt):
                    break
                if isinstance(stmt, ExitStatement) and stmt.exit_type == "SECTION":
                    self._terminating_paragraphs.add(proc_name)
                    self._exit_section_procedures[proc_name] = section
                    break

    @staticmethod
    def _is_terminator(stmt: Any) -> bool:
        """Check whether *stmt* unconditionally transfers control away when
        reached: STOP RUN (not STOP 'literal', which merely halts pending
        operator action), GOBACK, EXIT PROGRAM, a non-DEPENDING GO TO --
        including the alterable ``GO TO.`` with no operand, which always
        transfers to whatever an ALTER last set it to -- or EXEC CICS
        RETURN / XCTL / ABEND (see ``_cics``). Mirrors
        DeadCodeAnalyzer._is_terminator, kept independent per this package's
        existing collaborator architecture. An exhaustive IF/EVALUATE whose
        every arm terminates counts too (``_procedures.branch_terminates``).
        """
        if branch_terminates(stmt, ProcedureScanner._is_terminator):
            return True
        if cics_terminator_kind(stmt) is not None:
            return True
        if isinstance(stmt, GobackStatement):
            return True
        if isinstance(stmt, StopStatement):
            return stmt.stop_type == "RUN"
        if isinstance(stmt, ExitStatement):
            return stmt.exit_type == "PROGRAM"
        if isinstance(stmt, GoStatement):
            return not stmt.depending_on_variable
        return False


def _when_label(clause: Any, wc_idx: int) -> str:
    """One WHEN phrase's display label, from its first selector."""
    sel = clause.selectors[0] if clause.selectors else {}
    sel_type = sel.get("type", "") if isinstance(sel, dict) else ""
    if sel_type == "Any":
        return "WHEN ANY"
    if sel_type in ("Literal", "Identifier"):
        return f"WHEN {sel.get('value', '')}"
    if sel_type == "Range":
        return f"WHEN {sel.get('start', '')}..{sel.get('end', '')}"
    if sel_type == "Condition":
        return f"WHEN {sel.get('text', '')}"
    return f"WHEN {wc_idx + 1}"
