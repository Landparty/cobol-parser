"""Edge construction for the program flow graph.

Holds the edge-type category sets and :class:`EdgeCollector`, which turns
individual control flow statements (PERFORM, GO TO, CALL, SORT/MERGE
procedures, CANCEL, ALTER) into :class:`~.models.FlowEdge` records. The
collector mutates the shared edge / external-call / cancellation lists owned
by the analyzer, so insertion order matches the statement scan order exactly.
"""

from typing import Any

from ...models.statements.call import CallStatement
from ...models.statements.control import GoStatement, PerformStatement
from ...models.statements.misc import (
    AlterStatement,
    CancelStatement,
    MergeStatement,
    SortStatement,
    XmlJsonStatement,
)
from .._procedures import (
    ProcedureIndex,
    enclosing_section,
    statement_qualifier,
    unique,
)
from .condition_text import render_condition_text
from .models import FlowEdge, FlowEdgeType

# Edge types that represent internal flow within the program (not external calls).
INTERNAL_EDGE_TYPES: frozenset[FlowEdgeType] = frozenset(
    {
        FlowEdgeType.PERFORM,
        FlowEdgeType.PERFORM_THRU,
        FlowEdgeType.GOTO,
        FlowEdgeType.GOTO_DEPENDING,
        FlowEdgeType.FALL_THROUGH,
        FlowEdgeType.SORT_INPUT_PROCEDURE,
        FlowEdgeType.SORT_INPUT_PROCEDURE_THRU,
        FlowEdgeType.SORT_OUTPUT_PROCEDURE,
        FlowEdgeType.SORT_OUTPUT_PROCEDURE_THRU,
        FlowEdgeType.MERGE_OUTPUT_PROCEDURE,
        FlowEdgeType.MERGE_OUTPUT_PROCEDURE_THRU,
        FlowEdgeType.XML_PROCESSING_PROCEDURE,
        FlowEdgeType.XML_PROCESSING_PROCEDURE_THRU,
        FlowEdgeType.ALTER,
        FlowEdgeType.CICS_HANDLE,
        FlowEdgeType.SQL_WHENEVER,
        FlowEdgeType.IF_BRANCH,
        FlowEdgeType.IF_THEN,
        FlowEdgeType.IF_ELSE,
        FlowEdgeType.EVALUATE_BRANCH,
        FlowEdgeType.EVALUATE_WHEN,
        FlowEdgeType.EVALUATE_WHEN_OTHER,
    }
)

# Edge types that represent a PERFORM-style "call" (control returns to the
# caller when the callee finishes) versus an unconditional branch.
PERFORM_EDGE_TYPES: frozenset[FlowEdgeType] = frozenset(
    {
        FlowEdgeType.PERFORM,
        FlowEdgeType.PERFORM_THRU,
        FlowEdgeType.SORT_INPUT_PROCEDURE,
        FlowEdgeType.SORT_INPUT_PROCEDURE_THRU,
        FlowEdgeType.SORT_OUTPUT_PROCEDURE,
        FlowEdgeType.SORT_OUTPUT_PROCEDURE_THRU,
        FlowEdgeType.MERGE_OUTPUT_PROCEDURE,
        FlowEdgeType.MERGE_OUTPUT_PROCEDURE_THRU,
        FlowEdgeType.XML_PROCESSING_PROCEDURE,
        FlowEdgeType.XML_PROCESSING_PROCEDURE_THRU,
    }
)

GOTO_EDGE_TYPES: frozenset[FlowEdgeType] = frozenset(
    {
        FlowEdgeType.GOTO,
        FlowEdgeType.GOTO_DEPENDING,
        FlowEdgeType.ALTER,
        FlowEdgeType.CICS_HANDLE,
        FlowEdgeType.SQL_WHENEVER,
    }
)


class EdgeCollector:
    """Builds flow edges from control transfer statements.

    All collections passed to the constructor are shared with (and mutated in
    place for) the owning :class:`~.analyzer.ProgramFlowAnalyzer`.
    """

    def __init__(
        self,
        edges: list[FlowEdge],
        ordered_procedures: list[str],
        external_calls: list[dict[str, Any]],
        program_cancellations: list[dict[str, Any]],
        index: ProcedureIndex | None = None,
    ) -> None:
        self._edges = edges
        self._ordered_procedures = ordered_procedures
        self._external_calls = external_calls
        self._program_cancellations = program_cancellations
        self._index = index
        self._whenever_coverage: dict[int, list[str]] = {}
        self._whenever_edges: set[tuple[str, str]] = set()

    def set_index(self, index: ProcedureIndex) -> None:
        """Resolve procedure references through *index* (see
        :mod:`cobolparser.analysis._procedures`)."""
        self._index = index

    def resolve(
        self, stmt: Any, name: str | None, qualifier_key: str | None = None
    ) -> list[str]:
        """The node key(s) *name*, referenced from *stmt*, means.

        Without an index (a collector built on its own) a reference is its
        upper-cased bare name, as before procedures were qualified.
        """
        if not name:
            return []
        if self._index is None:
            return [name.upper()]
        qualifier = statement_qualifier(stmt, qualifier_key) if qualifier_key else None
        return self._index.resolve(name, qualifier, enclosing_section(stmt))

    def resolve_one(
        self, stmt: Any, name: str | None, qualifier_key: str | None = None
    ) -> str | None:
        """The first key :meth:`resolve` gives (a THRU range has one end)."""
        keys = self.resolve(stmt, name, qualifier_key)
        return keys[0] if keys else None

    def range_members(self, start: str, end: str) -> list[str]:
        """Return the procedures spanned by a THRU range, in source order.

        ``PERFORM A THRU C`` executes A, then every paragraph physically between
        A and C in the source, then C. This expands that implicit range into the
        explicit ordered list ``[A, ..., C]`` so consumers can see exactly which
        procedures the range covers. If either endpoint is unknown, or they are
        out of order, the best-effort endpoints are returned instead.
        """
        order = self._ordered_procedures
        if start == end:
            return [start]
        # Single pass over the procedure list, capturing the first occurrence
        # of each endpoint, so a THRU expansion stays O(n) with one scan even
        # when many THRU edges are present.
        i = j = -1
        for idx, name in enumerate(order):
            if i == -1 and name == start:
                i = idx
            elif j == -1 and name == end:
                j = idx
            if i != -1 and j != -1:
                break
        if i == -1 or j == -1 or j < i:
            return [start, end]
        return order[i : j + 1]

    def process_perform(self, stmt: PerformStatement, source: str) -> None:
        """Create edges for a PERFORM statement."""
        if not stmt.target_paragraph:
            return
        is_loop = stmt.perform_type in ("TIMES", "UNTIL", "VARYING")

        condition = None
        if stmt.until_condition:
            condition = render_condition_text(stmt.until_condition)

        thru_target = self.resolve_one(stmt, stmt.thru_paragraph, "thru_qualifier")
        for target in self.resolve(stmt, stmt.target_paragraph, "target_qualifier"):
            members = self.range_members(target, thru_target) if thru_target else []

            self._edges.append(
                FlowEdge(
                    source=source,
                    target=target,
                    edge_type=FlowEdgeType.PERFORM,
                    location=stmt.location,
                    is_loop=is_loop,
                    perform_type=stmt.perform_type,
                    condition=condition if is_loop else None,
                    thru_target=thru_target,
                    range_members=list(members),
                )
            )

            if thru_target:
                self._edges.append(
                    FlowEdge(
                        source=source,
                        target=thru_target,
                        edge_type=FlowEdgeType.PERFORM_THRU,
                        location=stmt.location,
                        is_loop=is_loop,
                        perform_type=stmt.perform_type,
                        thru_target=thru_target,
                        range_members=list(members),
                    )
                )

    def process_goto(self, stmt: GoStatement, source: str) -> None:
        """Create edges for a GO TO statement."""
        if stmt.depending_on_variable:
            # Computed GO TO: use the AST's own target list. Reconstructing
            # targets by filtering operands would collapse a target that
            # happens to share its name with the DEPENDING ON variable.
            # One edge per distinct target: a computed GO TO may list a
            # paragraph more than once (the list is positional).
            for target in unique(
                key for t in stmt.target_paragraphs for key in self.resolve(stmt, t)
            ):
                self._edges.append(
                    FlowEdge(
                        source=source,
                        target=target,
                        edge_type=FlowEdgeType.GOTO_DEPENDING,
                        location=stmt.location,
                        condition=f"DEPENDING ON {stmt.depending_on_variable}",
                    )
                )
        elif stmt.target_paragraph:
            for target in self.resolve(stmt, stmt.target_paragraph, "target_qualifier"):
                self._edges.append(
                    FlowEdge(
                        source=source,
                        target=target,
                        edge_type=FlowEdgeType.GOTO,
                        location=stmt.location,
                    )
                )

    def process_call(self, stmt: CallStatement, source: str) -> None:
        """Create edges for a CALL statement and record external calls."""
        if stmt.called_program:
            program_name = stmt.called_program.strip("'\"")
            if not program_name:
                return
            edge_type = (
                FlowEdgeType.CALL_DYNAMIC if stmt.is_dynamic else FlowEdgeType.CALL
            )
            self._edges.append(
                FlowEdge(
                    source=source,
                    target=program_name.upper(),
                    edge_type=edge_type,
                    location=stmt.location,
                )
            )

            call_info: dict[str, Any] = {
                "program": program_name,
                "is_dynamic": stmt.is_dynamic,
                "called_from": source,
                "location": stmt.location.to_dict(),
            }
            if stmt.is_dynamic and stmt.possible_values:
                call_info["possible_values"] = stmt.possible_values
            self._external_calls.append(call_info)

    def process_sort(self, stmt: SortStatement, source: str) -> None:
        """Create edges for SORT INPUT/OUTPUT PROCEDURE references.

        Mirrors :meth:`process_perform`: when a THRU range is present, both
        the base edge and the ``*_THRU`` edge carry ``thru_target`` /
        ``range_members`` so consumers that skip the ``*_THRU`` edge (the
        flowchart generators badge the base edge instead of drawing a
        second, redundant arrow) don't lose the range information.
        """
        self._procedure_range_edges(
            stmt,
            source,
            stmt.input_procedure,
            stmt.input_procedure_thru,
            FlowEdgeType.SORT_INPUT_PROCEDURE,
            FlowEdgeType.SORT_INPUT_PROCEDURE_THRU,
        )
        self._procedure_range_edges(
            stmt,
            source,
            stmt.output_procedure,
            stmt.output_procedure_thru,
            FlowEdgeType.SORT_OUTPUT_PROCEDURE,
            FlowEdgeType.SORT_OUTPUT_PROCEDURE_THRU,
        )

    def _procedure_range_edges(
        self,
        stmt: Any,
        source: str,
        name: str | None,
        thru_name: str | None,
        edge_type: FlowEdgeType,
        thru_edge_type: FlowEdgeType,
    ) -> None:
        """Edges for a ``PROCEDURE p [THRU q]`` phrase (SORT/MERGE/XML)."""
        if not name:
            return
        thru = self.resolve_one(stmt, thru_name)
        for target in self.resolve(stmt, name):
            members = self.range_members(target, thru) if thru else []
            self._edges.append(
                FlowEdge(
                    source=source,
                    target=target,
                    edge_type=edge_type,
                    location=stmt.location,
                    thru_target=thru,
                    range_members=list(members),
                )
            )
            if thru:
                self._edges.append(
                    FlowEdge(
                        source=source,
                        target=thru,
                        edge_type=thru_edge_type,
                        location=stmt.location,
                        thru_target=thru,
                        range_members=list(members),
                    )
                )

    def process_xml_parse(self, stmt: XmlJsonStatement, source: str) -> None:
        """Create edges for ``XML PARSE ... PROCESSING PROCEDURE p [THRU q]``.

        The XML parser PERFORMs the handler once per event, so the edge is
        PERFORM-shaped (it returns), carrying the THRU range like
        :meth:`process_sort` does.
        """
        self._procedure_range_edges(
            stmt,
            source,
            stmt.processing_procedure,
            stmt.processing_procedure_thru,
            FlowEdgeType.XML_PROCESSING_PROCEDURE,
            FlowEdgeType.XML_PROCESSING_PROCEDURE_THRU,
        )

    def process_cics_handle(self, stmt: Any, source: str) -> None:
        """Create edges for ``EXEC CICS HANDLE AID|CONDITION|ABEND``.

        Every option whose argument names a procedure of this program
        (``PF3(9000-EXIT)``, ``NOTFND(9000-NOT-FOUND)``, ``LABEL(9100-ABEND)``)
        is a branch CICS takes when that AID/condition occurs: GO TO-shaped,
        control does not come back.
        """
        if (getattr(stmt, "cics_command", "") or "").upper() != "HANDLE":
            return
        known = set(self._ordered_procedures)
        for value in (getattr(stmt, "options", None) or {}).values():
            if not value:
                continue
            for target in self.resolve(stmt, value.strip()):
                if target not in known:
                    continue
                self._edges.append(
                    FlowEdge(
                        source=source,
                        target=target,
                        edge_type=FlowEdgeType.CICS_HANDLE,
                        location=stmt.location,
                    )
                )

    def set_whenever_coverage(self, coverage: dict[int, list[str]]) -> None:
        """Which procedures each SQL statement's WHENEVER directives branch
        to (``_sql_whenever.whenever_coverage``, keyed by ``id``)."""
        self._whenever_coverage = coverage

    def process_sql_whenever(self, stmt: Any, source: str) -> None:
        """Create the edges for ``EXEC SQL WHENEVER ... GO TO p``.

        GO TO-shaped like :meth:`process_cics_handle`, but drawn from each
        procedure holding an SQL statement the directive covers (source
        order decides which), not from the directive's own procedure: the
        directive is never executed, and the paragraph holding it may never
        run (a "SQL setup" paragraph ahead of the SQL it covers). One edge
        per (procedure, target), however many covered statements it holds.
        """
        known = set(self._ordered_procedures)
        for target_name in self._whenever_coverage.get(id(stmt), []):
            for target in self.resolve(stmt, target_name):
                if target not in known or (source, target) in self._whenever_edges:
                    continue
                self._whenever_edges.add((source, target))
                self._edges.append(
                    FlowEdge(
                        source=source,
                        target=target,
                        edge_type=FlowEdgeType.SQL_WHENEVER,
                        location=stmt.location,
                    )
                )

    def process_merge(self, stmt: MergeStatement, source: str) -> None:
        """Create edges for MERGE OUTPUT PROCEDURE references.

        See :meth:`process_sort` -- the base edge carries ``thru_target`` /
        ``range_members`` too, not just the ``*_THRU`` edge.
        """
        self._procedure_range_edges(
            stmt,
            source,
            stmt.output_procedure,
            stmt.output_procedure_thru,
            FlowEdgeType.MERGE_OUTPUT_PROCEDURE,
            FlowEdgeType.MERGE_OUTPUT_PROCEDURE_THRU,
        )

    def process_cancel(self, stmt: CancelStatement, source: str) -> None:
        """Record CANCEL statements as program cancellation events."""
        for name in stmt.program_names:
            program_name = name.strip("'\"")
            if program_name:
                self._program_cancellations.append(
                    {
                        "program": program_name,
                        "cancelled_from": source,
                        "location": stmt.location.to_dict(),
                    }
                )

    def process_alter(self, stmt: AlterStatement, source: str) -> None:
        """Create edges for ALTER statement procedure redirections."""
        for alteration in stmt.alterations:
            for altered in self.resolve(stmt, alteration["from_paragraph"]):
                for target in self.resolve(stmt, alteration["to_paragraph"]):
                    self._edges.append(
                        FlowEdge(
                            source=altered,
                            target=target,
                            edge_type=FlowEdgeType.ALTER,
                            location=stmt.location,
                        )
                    )
