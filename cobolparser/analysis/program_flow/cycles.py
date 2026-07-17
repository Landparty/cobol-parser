"""Cycle detection and classification for the program flow graph."""

from typing import Any

from .edges import GOTO_EDGE_TYPES, INTERNAL_EDGE_TYPES, PERFORM_EDGE_TYPES
from .models import FlowEdge, FlowEdgeType, FlowNode


def detect_cycles(
    nodes: dict[str, FlowNode],
    edges: list[FlowEdge],
    ordered_procedures: list[str],
) -> list[list[str]]:
    """Detect cycles in the internal control flow graph using iterative DFS.

    A cycle exists when procedure A (directly or transitively) transfers
    control back to itself via PERFORM, GO TO, or fall-through edges.
    Each reported cycle is the list of node names that form the loop.

    Uses an explicit stack instead of recursion to avoid Python's recursion
    limit on large COBOL programs (1 000+ paragraphs). A companion
    ``stack_pos`` dict maps each GRAY node to its index in the current DFS
    path so cycle extraction is O(1) rather than O(depth).
    """
    adj: dict[str, list[str]] = {name: [] for name in nodes}
    for edge in edges:
        if (
            edge.edge_type in INTERNAL_EDGE_TYPES
            and edge.source in adj
            and edge.target in nodes
        ):
            adj[edge.source].append(edge.target)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(nodes, WHITE)
    seen_keys: set[frozenset[str]] = set()
    cycles: list[list[str]] = []

    for start in ordered_procedures:
        if color.get(start, BLACK) != WHITE:
            continue

        # Each stack frame: (node, iterator-over-neighbors, entered-as-new)
        path: list[str] = []
        stack_pos: dict[str, int] = {}  # node -> index in path while GRAY
        # Stack entries: (node, neighbor_iter)
        frame_stack: list[tuple[str, Any]] = [(start, iter(adj.get(start, [])))]
        color[start] = GRAY
        path.append(start)
        stack_pos[start] = 0

        while frame_stack:
            node, neighbors = frame_stack[-1]
            try:
                neighbor = next(neighbors)
                c = color.get(neighbor, BLACK)
                if c == GRAY:
                    # Back edge — extract cycle using O(1) stack_pos lookup
                    idx = stack_pos[neighbor]
                    cycle = path[idx:]
                    key = frozenset(cycle)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        cycles.append(list(cycle))
                elif c == WHITE:
                    color[neighbor] = GRAY
                    path.append(neighbor)
                    stack_pos[neighbor] = len(path) - 1
                    frame_stack.append((neighbor, iter(adj.get(neighbor, []))))
            except StopIteration:
                # Done with this node — pop and mark BLACK
                frame_stack.pop()
                path.pop()
                del stack_pos[node]
                color[node] = BLACK

    return cycles


def classify_cycles(
    cycles: list[list[str]], edges: list[FlowEdge]
) -> list[dict[str, Any]]:
    """Annotate each detected cycle with the kind of dependency it forms.

    A bare list of node names does not tell a consumer whether a cycle is a
    genuine recursive PERFORM chain (a paragraph that, directly or
    transitively, PERFORMs itself), a GO TO loop, or merely an artifact of
    sequential fall-through between adjacent paragraphs. ``cycle_details``
    records, per cycle, the ``kind``:

    - ``PERFORM_RECURSION`` — every edge in the loop is a PERFORM/SORT/MERGE
      procedure call. This is the "circular dependency" worth flagging:
      COBOL forbids a paragraph being re-entered while an earlier PERFORM of
      it is still active.
    - ``GOTO_LOOP`` — the loop is closed entirely by GO TO / ALTER edges.
    - ``FALL_THROUGH`` — the loop only exists because of implicit
      fall-through between adjacent paragraphs.
    - ``MIXED`` — a combination of the above (e.g. a PERFORM into a range
      that then falls through back to the performer).
    """
    # Map (source, target) -> set of internal edge types connecting them.
    pair_types: dict[tuple[str, str], set[FlowEdgeType]] = {}
    for edge in edges:
        if edge.edge_type in INTERNAL_EDGE_TYPES:
            pair_types.setdefault((edge.source, edge.target), set()).add(edge.edge_type)

    details: list[dict[str, Any]] = []
    for cycle in cycles:
        n = len(cycle)
        # Per consecutive pair, the edge types that can connect them. A cycle
        # is classified by whether one edge category can close *every* hop:
        # a parallel fall-through edge must not mask a genuine PERFORM
        # recursion, so availability is checked per pair rather than unioned.
        pair_sets: list[set[FlowEdgeType]] = []
        all_types: set[FlowEdgeType] = set()
        for idx in range(n):
            src = cycle[idx]
            tgt = cycle[(idx + 1) % n]
            types = pair_types.get((src, tgt), set())
            pair_sets.append(types)
            all_types |= types

        if _cycle_closes(pair_sets, PERFORM_EDGE_TYPES):
            kind = "PERFORM_RECURSION"
        elif _cycle_closes(pair_sets, GOTO_EDGE_TYPES):
            kind = "GOTO_LOOP"
        elif _cycle_closes(pair_sets, frozenset({FlowEdgeType.FALL_THROUGH})):
            kind = "FALL_THROUGH"
        else:
            kind = "MIXED"

        details.append(
            {
                "nodes": list(cycle),
                "kind": kind,
                "length": n,
                "self_recursive": n == 1 and kind == "PERFORM_RECURSION",
                "edge_types": sorted(t.value for t in all_types),
            }
        )
    return details


def _cycle_closes(
    pair_sets: list[set[FlowEdgeType]], category: frozenset[FlowEdgeType]
) -> bool:
    """True if every hop of a cycle can be closed by an edge in ``category``."""
    return all(bool(types & category) for types in pair_sets)
