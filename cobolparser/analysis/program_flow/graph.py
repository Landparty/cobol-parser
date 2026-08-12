"""Whole-graph post-passes for program flow analysis.

Runs after statement scanning: implicit fall-through edges between
sequential paragraphs, branch convergence nodes, and reachability from the
entry points.
"""

from collections import deque

from .edges import INTERNAL_EDGE_TYPES
from .models import BranchNode, FlowEdge, FlowEdgeType, FlowNode


def build_fall_through_edges(
    nodes: dict[str, FlowNode],
    edges: list[FlowEdge],
    ordered_procedures: list[str],
    unconditional_gotos: set[str],
) -> None:
    """Build fall-through edges between sequential paragraphs.

    In COBOL, when a paragraph finishes without a GO TO or STOP RUN,
    execution falls through to the next paragraph. This adds those
    implicit edges unless the paragraph ends with a terminator.
    """
    for i in range(len(ordered_procedures) - 1):
        current = ordered_procedures[i]
        next_proc = ordered_procedures[i + 1]

        node = nodes.get(current)
        if not node:
            continue

        # Skip if procedure ends with a hard terminator
        if node.has_stop_run or node.has_goback or node.has_exit_program:
            continue

        # Skip if the paragraph's own last top-level statement is an
        # unconditional (non-DEPENDING) GO TO -- see
        # ProcedureScanner._scan_paragraph_statements, which populates
        # unconditional_gotos. A GO TO nested inside an IF/EVALUATE arm does
        # not qualify: the paragraph still falls through whenever that
        # branch isn't taken, so membership requires the GO TO to be the
        # paragraph's literal last statement, not merely present somewhere
        # in it.
        if current in unconditional_gotos:
            continue

        edges.append(
            FlowEdge(
                source=current,
                target=next_proc,
                edge_type=FlowEdgeType.FALL_THROUGH,
                location=node.location,
            )
        )


def compute_convergence_nodes(
    edges: list[FlowEdge], branch_nodes: list[BranchNode]
) -> None:
    """Set convergence_node on each branch decision.

    The convergence node is the paragraph that execution reaches after all
    arms of the branch complete.  For the common case this is the paragraph
    that follows the branch's parent procedure in source order (i.e. the
    target of the parent's FALL_THROUGH edge).  Called after
    :func:`build_fall_through_edges` so those edges are already present.
    """
    fall_through: dict[str, str] = {}
    for edge in edges:
        if edge.edge_type == FlowEdgeType.FALL_THROUGH:
            fall_through[edge.source] = edge.target
    for bn in branch_nodes:
        bn.convergence_node = fall_through.get(bn.parent_proc)


def find_unreachable_nodes(
    nodes: dict[str, FlowNode],
    edges: list[FlowEdge],
    ordered_procedures: list[str],
    entry_points: list[str],
) -> list[str]:
    """Find nodes not reachable from any entry point via internal edges.

    Uses breadth-first search from all known entry points. Nodes that
    cannot be reached are returned as unreachable, in source order.

    THRU ranges (``PERFORM A THRU C``, SORT/MERGE procedure ranges) execute
    every paragraph the range physically spans, so each ``range_members``
    entry counts as a neighbor of the edge's source. Without this, an
    intermediate member whose fall-through edge from the preceding member is
    suppressed (e.g. the predecessor contains a GO TO) was falsely reported
    unreachable even though the range provably executes it.
    """
    adj: dict[str, list[str]] = {name: [] for name in nodes}
    for edge in edges:
        if edge.edge_type in INTERNAL_EDGE_TYPES and edge.source in adj:
            if edge.target in nodes:
                adj[edge.source].append(edge.target)
            for member in edge.range_members:
                if member in nodes:
                    adj[edge.source].append(member)

    reachable: set[str] = set()
    queue: deque[str] = deque(entry_points)

    while queue:
        node = queue.popleft()
        if node in reachable or node not in nodes:
            continue
        reachable.add(node)
        for neighbor in adj.get(node, []):
            if neighbor not in reachable:
                queue.append(neighbor)

    return [name for name in ordered_procedures if name not in reachable]
