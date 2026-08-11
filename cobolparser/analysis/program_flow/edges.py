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
        FlowEdgeType.ALTER,
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
    }
)

GOTO_EDGE_TYPES: frozenset[FlowEdgeType] = frozenset(
    {FlowEdgeType.GOTO, FlowEdgeType.GOTO_DEPENDING, FlowEdgeType.ALTER}
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
    ) -> None:
        self._edges = edges
        self._ordered_procedures = ordered_procedures
        self._external_calls = external_calls
        self._program_cancellations = program_cancellations

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
        if stmt.target_paragraph:
            target = stmt.target_paragraph.upper()
            is_loop = stmt.perform_type in ("TIMES", "UNTIL", "VARYING")

            condition = None
            if stmt.until_condition:
                condition = render_condition_text(stmt.until_condition)

            thru_target = stmt.thru_paragraph.upper() if stmt.thru_paragraph else None
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
            # Computed GO TO: multiple targets
            for operand in stmt.operands:
                if operand != stmt.depending_on_variable:
                    self._edges.append(
                        FlowEdge(
                            source=source,
                            target=operand.upper(),
                            edge_type=FlowEdgeType.GOTO_DEPENDING,
                            location=stmt.location,
                            condition=f"DEPENDING ON {stmt.depending_on_variable}",
                        )
                    )
        elif stmt.target_paragraph:
            self._edges.append(
                FlowEdge(
                    source=source,
                    target=stmt.target_paragraph.upper(),
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
        """Create edges for SORT INPUT/OUTPUT PROCEDURE references."""
        if stmt.input_procedure:
            self._edges.append(
                FlowEdge(
                    source=source,
                    target=stmt.input_procedure.upper(),
                    edge_type=FlowEdgeType.SORT_INPUT_PROCEDURE,
                    location=stmt.location,
                )
            )
            if stmt.input_procedure_thru:
                thru = stmt.input_procedure_thru.upper()
                self._edges.append(
                    FlowEdge(
                        source=source,
                        target=thru,
                        edge_type=FlowEdgeType.SORT_INPUT_PROCEDURE_THRU,
                        location=stmt.location,
                        thru_target=thru,
                        range_members=self.range_members(
                            stmt.input_procedure.upper(), thru
                        ),
                    )
                )
        if stmt.output_procedure:
            self._edges.append(
                FlowEdge(
                    source=source,
                    target=stmt.output_procedure.upper(),
                    edge_type=FlowEdgeType.SORT_OUTPUT_PROCEDURE,
                    location=stmt.location,
                )
            )
            if stmt.output_procedure_thru:
                thru = stmt.output_procedure_thru.upper()
                self._edges.append(
                    FlowEdge(
                        source=source,
                        target=thru,
                        edge_type=FlowEdgeType.SORT_OUTPUT_PROCEDURE_THRU,
                        location=stmt.location,
                        thru_target=thru,
                        range_members=self.range_members(
                            stmt.output_procedure.upper(), thru
                        ),
                    )
                )

    def process_merge(self, stmt: MergeStatement, source: str) -> None:
        """Create edges for MERGE OUTPUT PROCEDURE references."""
        if stmt.output_procedure:
            self._edges.append(
                FlowEdge(
                    source=source,
                    target=stmt.output_procedure.upper(),
                    edge_type=FlowEdgeType.MERGE_OUTPUT_PROCEDURE,
                    location=stmt.location,
                )
            )
            if stmt.output_procedure_thru:
                thru = stmt.output_procedure_thru.upper()
                self._edges.append(
                    FlowEdge(
                        source=source,
                        target=thru,
                        edge_type=FlowEdgeType.MERGE_OUTPUT_PROCEDURE_THRU,
                        location=stmt.location,
                        thru_target=thru,
                        range_members=self.range_members(
                            stmt.output_procedure.upper(), thru
                        ),
                    )
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
            self._edges.append(
                FlowEdge(
                    source=alteration["from_paragraph"].upper(),
                    target=alteration["to_paragraph"].upper(),
                    edge_type=FlowEdgeType.ALTER,
                    location=stmt.location,
                )
            )
