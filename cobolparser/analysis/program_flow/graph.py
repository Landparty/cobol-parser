"""Whole-graph post-passes for program flow analysis.

Runs after statement scanning: implicit fall-through edges between
sequential paragraphs, branch convergence nodes, and reachability from the
entry points.
"""

from collections import deque

from .edges import INTERNAL_EDGE_TYPES, PERFORM_EDGE_TYPES
from .models import BranchNode, FlowEdge, FlowEdgeType, FlowNode


def build_fall_through_edges(
    nodes: dict[str, FlowNode],
    edges: list[FlowEdge],
    ordered_procedures: list[str],
    terminating_paragraphs: set[str],
    exit_section_procedures: dict[str, str] | None = None,
    section_ends: dict[str, str] | None = None,
    sections_entered: set[str] | None = None,
    declarative_sections: set[str] | None = None,
    entry_points: list[str] | None = None,
) -> None:
    """Build fall-through edges between sequential paragraphs.

    In COBOL, when a paragraph finishes without a GO TO or STOP RUN,
    execution falls through to the next paragraph. This adds those
    implicit edges unless the paragraph ends with a terminator.

    A procedure in *exit_section_procedures* leaves its section by ``EXIT
    SECTION``: control goes to the end of the section, skipping the rest of
    it. When the section keeps running there -- it is fallen into (an
    incoming fall-through edge), or is in *sections_entered* (the entry
    point, an ENTRY, or a GO TO / ALTER / CICS HANDLE landing in it from
    outside) -- it gets a fall-through edge to the procedure after the
    section's last member (*section_ends*). A section that is only
    PERFORMed returns to its performer, so it gets no onward edge.

    A section in *declarative_sections* (a DECLARATIVES USE procedure)
    returns to the runtime when it ends: control never flows out of it,
    into the next declarative section or past END DECLARATIVES into the
    main code (#533). Its last member, and an EXIT SECTION in it, get no
    fall-through edge.

    Given *entry_points* (the first procedure and every ENTRY), a procedure
    control only ever reaches by PERFORM, as the last procedure of the
    performed range, gets no fall-through edge either: when it ends, control
    returns to the performer (see :func:`_sequential_procedures`). Without
    it, every paragraph that does not stop falls through, as before.
    """
    exits = exit_section_procedures or {}
    ends = section_ends or {}
    entered = sections_entered or set()
    declarative = declarative_sections or set()
    declarative_ends = {ends.get(section, section) for section in declarative}
    position = {name: i for i, name in enumerate(ordered_procedures)}
    falls_on = (
        None
        if entry_points is None
        else _sequential_procedures(
            nodes,
            edges,
            ordered_procedures,
            terminating_paragraphs,
            entry_points,
            ends,
            entered,
            declarative,
        )
    )
    fallen_into: set[str] = set()
    for i in range(len(ordered_procedures) - 1):
        current = ordered_procedures[i]
        next_proc = ordered_procedures[i + 1]

        node = nodes.get(current)
        if not node:
            continue

        section = exits.get(current)
        if section is not None:
            if section in declarative:
                continue
            end = position.get(ends.get(section, section))
            if (
                end is not None
                and end + 1 < len(ordered_procedures)
                and (section in entered or section in fallen_into)
            ):
                successor = ordered_procedures[end + 1]
                fallen_into.add(successor)
                edges.append(
                    FlowEdge(
                        source=current,
                        target=successor,
                        edge_type=FlowEdgeType.FALL_THROUGH,
                        location=node.location,
                    )
                )
            continue

        # Skip if any of the paragraph's own TOP-LEVEL statements is an
        # unconditional terminator (STOP RUN, GOBACK, EXIT PROGRAM, or a
        # bare non-DEPENDING GO TO) -- see ProcedureScanner's
        # _is_terminator, which populates terminating_paragraphs. Once such
        # a statement is reached it always fires, so anything physically
        # written after it in the same paragraph is itself unreachable and
        # doesn't change whether the paragraph falls through -- checking
        # only the last statement would miss a mid-paragraph terminator.
        # Deliberately does NOT use node.has_stop_run/has_goback/
        # has_exit_program: those are set whenever the recursive statement
        # walk encounters one ANYWHERE, including nested inside an
        # IF/EVALUATE arm where it only fires conditionally -- the same
        # class of bug this function's GO TO handling fixes.
        if current in terminating_paragraphs:
            continue
        if current in declarative_ends:
            continue
        if falls_on is not None and current not in falls_on:
            continue

        fallen_into.add(next_proc)
        edges.append(
            FlowEdge(
                source=current,
                target=next_proc,
                edge_type=FlowEdgeType.FALL_THROUGH,
                location=node.location,
            )
        )


def _sequential_procedures(
    nodes: dict[str, FlowNode],
    edges: list[FlowEdge],
    ordered_procedures: list[str],
    terminating_paragraphs: set[str],
    entry_points: list[str],
    section_ends: dict[str, str],
    sections_entered: set[str],
    declarative_sections: set[str],
) -> set[str]:
    """The procedures whose end can run on into the next procedure.

    A PERFORM of ``A`` (``THRU C``) returns to its performer at the end of
    ``C`` (of ``A`` without THRU; of a section's last member when the range
    ends on a section): only ``A`` up to the procedure before that end fall
    through *because of* the PERFORM. Any procedure control can also reach
    otherwise -- the entry point or an ENTRY, the target of a GO TO, ALTER,
    CICS HANDLE or SQL WHENEVER, a member of a section entered from outside,
    a DECLARATIVES procedure, a procedure nothing at all reaches and no
    performed range holds (left as it was, so dead-code results do not
    move), or the one after another such
    procedure that does not stop -- falls through as well.

    So ``1000-READ-EMP`` (only ever PERFORMed, from a main paragraph that
    ends in GOBACK) no longer gets an edge into ``2000-PAY-EMP`` and a
    "cycle" back through it (cobol-test run on PAYMAIN, 2026-11-06).
    """
    position = {name: i for i, name in enumerate(ordered_procedures)}
    in_range: set[str] = set()
    covered: set[str] = set()  # every procedure some performed range holds
    incoming: dict[str, set[FlowEdgeType]] = {}
    for edge in edges:
        if edge.target not in position:
            continue
        incoming.setdefault(edge.target, set()).add(edge.edge_type)
        if edge.edge_type not in PERFORM_EDGE_TYPES:
            continue
        start = position[edge.target]
        last_name = edge.thru_target or edge.target
        last_name = section_ends.get(last_name, last_name)
        last = position.get(last_name)
        if last is None or last < start:
            continue
        in_range.update(ordered_procedures[start:last])
        covered.update(ordered_procedures[start : last + 1])

    free: set[str] = set(entry_points)
    for name in ordered_procedures:
        node = nodes.get(name)
        kinds = incoming.get(name)
        if kinds and any(kind not in PERFORM_EDGE_TYPES for kind in kinds):
            free.add(name)
        elif not kinds and name not in covered:
            free.add(name)
        elif node is not None and node.is_declarative:
            free.add(name)
    for section in sections_entered | declarative_sections:
        first_at = position.get(section)
        last_at = position.get(section_ends.get(section, section))
        if first_at is not None and last_at is not None:
            free.update(ordered_procedures[first_at : last_at + 1])

    falls_on = set(in_range)
    for index, name in enumerate(ordered_procedures[:-1]):
        if name in free and name not in terminating_paragraphs:
            falls_on.add(name)
            free.add(ordered_procedures[index + 1])
    return falls_on


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
