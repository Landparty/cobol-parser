"""``slice``: only the statements that can affect a field, or that it affects.

"How is WS-INTEREST computed?" is a question about perhaps twenty lines of
a three-thousand-line program. A model reading the program to find them
spends its context on the other lines; ``slice`` returns just those
statements, grouped under their paragraphs, each cited ``file:line`` with
its text on disk.

The data part comes from the program's field-flow report
(:class:`~cobolparser.analysis.field_lineage.FieldFlowAnalyzer`): backward,
every edge into the field and, transitively, into whatever fed it; forward,
every edge out of it and on. It stops at the program's ports (a file, a DB2
column, a CALL argument, the console), which the answer lists as where the
values come from or go. The control part is the statements a data
statement is written under (the IF, EVALUATE, inline PERFORM or AT END it
only runs inside), and, forward, the conditions that test a field of the
slice. Alias edges (REDEFINES, a table's occurrences) are followed as the
lineage tools follow them: never two of one kind in a row.

The slice is static and flow-insensitive: a statement whose value is
overwritten before it reaches the field is still listed (``where_from``
marks those paths). Like :mod:`.tools`, this module imports no SDK.
"""

from __future__ import annotations

import difflib
import functools
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..models.program import CobolParagraph, CobolProgram
from ..models.statements.base import CobolStatement
from .envelope import Response, ToolError
from .workspace import Workspace

if TYPE_CHECKING:
    from ..analysis.xref import XrefReport

#: Most statements one slice lists.
MAX_SLICE_STATEMENTS = 200


@dataclass
class _Row:
    line: int
    verb: str
    paragraph: str | None
    role: str  # "data" | "control" | "decision" | "controlled"
    flows: set[str] = field(default_factory=set)


def slice_field(
    workspace: Workspace,
    file: str,
    field_name: str,
    direction: str = "backward",
    program: str | None = None,
    limit: int | None = None,
    aliases: bool = False,
) -> dict[str, Any]:
    """The statements of one program that can affect *field_name*
    (``backward``) or that it affects (``forward``). An inexact alias edge
    (a REDEFINES or a shared record area over fields of other layouts, a
    table as a whole) is followed only with *aliases*: it reaches every
    field under the other name, which is mostly noise."""
    from ..analysis.lineage_graph import LineageGraph, overlay_class
    from .codebase_index import _field_flow
    from .navigation import (
        _Lines,
        _procedure_of,
        _statement_text,
        _statements_under,
        statement_verb,
    )

    direction = direction.lower()
    if direction not in ("backward", "forward"):
        raise ToolError("direction must be backward or forward")
    response = Response()
    parsed = workspace.program(file)
    from .tools.common import _carry_parse_caveats

    _carry_parse_caveats(parsed, response)
    unit = parsed.unit(program, response)
    program_info = parsed.program_info(unit)
    report = parsed.report("lineage", unit, functools.partial(_field_flow, unit))
    graph = LineageGraph([report])
    program_id = (report.program_id or "").upper()
    wanted = " ".join(field_name.upper().replace(" IN ", " OF ").split())
    groups, matched = graph._start_groups(wanted, [program_id])
    start_names = sorted(n for names in matched.values() for n in names)
    if not start_names:
        names = sorted(
            {str(item["qualified_name"]).split(".")[-1] for item in report.items}
        )
        return response.build(
            {
                "field": wanted,
                "direction": direction,
                "found": False,
                "suggestions": difflib.get_close_matches(
                    wanted.split(" OF ")[0], [n for n in names if n != wanted], n=5
                ),
            },
            program_info,
        )

    adjacency = graph._out if direction == "forward" else graph._in
    item_nodes = [
        n
        for n in {*graph._out, *graph._in}
        if n[0] == "P" and n[1] == program_id and n[2] == overlay_item_kind()
    ]
    statements = _statements_by_line(unit)
    xref = _XrefIndex(parsed.xref(unit))
    rows: dict[int, _Row] = {}
    fields: set[str] = set()
    ports: set[str] = set()
    seen: set[tuple[Any, int]] = set()
    skipped: set[str] = set()
    done_names: set[str] = set()
    pending: deque[str] = deque(start_names)

    def add_row(line: int, statement: Any, role: str) -> _Row:
        held = rows.get(line)
        if held is None:
            paragraph, _section = _procedure_of(statement)
            held = rows[line] = _Row(line, statement_verb(statement), paragraph, role)
        return held

    def follow_graph(name: str) -> None:
        """The field-flow edges from (forward) or into (backward) *name*."""
        queue: deque[tuple[Any, int]] = deque()
        for node in item_nodes:
            if node[3] == name or node[3].startswith((name + ".", name + "(")):
                if (node, 0) not in seen:
                    seen.add((node, 0))
                    queue.append((node, 0))
        while queue:
            node, arrived = queue.popleft()
            for nxt, info in adjacency.get(node, []):
                overlay = overlay_class(info.kind)
                if overlay and overlay == arrived:
                    continue
                src, dst = (node, nxt) if direction == "forward" else (nxt, node)
                if overlay and info.confidence != "exact" and not aliases:
                    skipped.add(
                        f"{_label(graph, src)} -> {_label(graph, dst)} ({info.kind})"
                    )
                    continue
                if info.seq_line:
                    row = rows.setdefault(
                        info.seq_line,
                        _Row(
                            info.seq_line,
                            info.statement or info.kind,
                            info.paragraph,
                            "data",
                        ),
                    )
                    row.flows.add(f"{_label(graph, src)} -> {_label(graph, dst)}")
                _p, reached, kind = graph._describe(nxt)
                if kind == "port":
                    ports.add(reached)
                    continue  # a boundary, never a pass-through
                fields.add(reached)
                if reached not in done_names:
                    pending.append(reached)
                state = (nxt, overlay)
                if state not in seen:
                    seen.add(state)
                    queue.append(state)

    def add_controls(line: int) -> None:
        """The statements a data statement runs under; backward, the fields
        their conditions test decide the value too (#796)."""
        for ancestor in _enclosing(statements.get(line)):
            a_line = ancestor.location.line
            if not a_line:
                continue
            if a_line not in rows:
                add_row(a_line, ancestor, "control")
            if direction == "backward":
                for tested in xref.tested_on(a_line):
                    fields.add(tested)
                    if tested not in done_names:
                        pending.append(tested)

    while pending:
        name = pending.popleft()
        if name in done_names:
            continue
        done_names.add(name)
        before = set(rows)
        follow_graph(name)
        if direction == "backward":
            # Writes from no field (a literal, a figurative constant, SET
            # ... TO TRUE, INITIALIZE) make no field-flow edge.
            for line in xref.writes_of(name):
                statement = statements.get(line)
                if statement is None:
                    continue
                row = add_row(line, statement, "data")
                row.role = "data"
                if not any(f.endswith(f"-> {name}") for f in row.flows):
                    row.flows.add(f"sets {name}")
        for line in set(rows) - before:
            add_controls(line)
        if direction == "forward":
            for line in xref.tests_of(name):
                statement = statements.get(line)
                if statement is None:
                    continue
                held = add_row(line, statement, "decision")
                held.flows.add(f"tests {name}")
                # What runs only when the test goes one way is affected too,
                # and so is whatever it writes (#796).
                for inner in _statements_under(statement):
                    i_line = inner.location.line
                    if not i_line:
                        continue
                    if i_line not in rows:
                        add_row(i_line, inner, "controlled")
                    for written in xref.written_on(i_line):
                        fields.add(written)
                        if written not in done_names:
                            pending.append(written)

    lines = _Lines(workspace)
    shown: list[dict[str, Any]] = []
    for row in sorted(rows.values(), key=lambda r: r.line):
        located = parsed.locate(row.line, None, response)
        entry: dict[str, Any] = {
            "location": located,
            "paragraph": row.paragraph,
            "verb": row.verb,
            "role": row.role,
            "text": (
                _statement_text(lines.line(located["file"], located["line"]))
                if located
                else ""
            ),
        }
        if row.flows:
            entry["flows"] = sorted(row.flows)
        shown.append(entry)
    cap = MAX_SLICE_STATEMENTS if limit is None else max(1, min(limit, 1000))
    kept = response.cap(shown, cap, "statements")
    paragraphs: list[dict[str, Any]] = []
    for entry in kept:
        name = entry.pop("paragraph")
        if not paragraphs or paragraphs[-1]["paragraph"] != name:
            paragraphs.append({"paragraph": name, "statements": []})
        paragraphs[-1]["statements"].append(entry)
    answer: dict[str, Any] = {
        "field": wanted,
        "matched": start_names,
        "direction": direction,
        "found": True,
        "statement_count": len(shown),
        "by_role": _by_role(shown),
        "fields": sorted(fields - set(start_names)),
        **(
            {
                "note": (
                    "nothing in this program writes the field from another "
                    "field; the statements listed set it from literals or "
                    "conditions"
                    if rows
                    else "nothing in this program writes or tests the field"
                )
            }
            if not ports and not (fields - set(start_names)) and direction == "backward"
            else {}
        ),
        "ports": sorted(ports),
        "paragraphs": paragraphs,
        **(
            {
                "aliases_not_followed": response.cap(
                    sorted(skipped), 20, "aliases_not_followed"
                )
            }
            if skipped
            else {}
        ),
        "legend": (
            "the statements that can affect the field (backward) or that it "
            "affects (forward), in source order under their paragraphs. role "
            "data: the statement moves a value (flows: from -> to); control: "
            "a data statement runs only inside it (backward, the fields its "
            "condition tests join the slice); decision (forward): it "
            "tests a field of the slice; controlled: it runs only on one "
            "outcome of such a test, and the fields it writes join the "
            "slice. A write from a literal or SET ... TO TRUE is a data "
            "statement with flow 'sets <field>'. ports: the files, DB2 columns, CALL "
            "arguments and console the values "
            + ("come from" if direction == "backward" else "go to")
            + "; where_from / impact_of_change follow them across programs. "
            "Flow-insensitive: a value overwritten before it is used is "
            "still listed. aliases_not_followed: inexact REDEFINES / record-"
            "area / whole-table aliases left out; aliases=true follows them."
        ),
    }
    return response.build(answer, program_info)


def _label(graph: Any, node: Any) -> str:
    _program, name, _kind = graph._describe(node)
    return str(name)


def _by_role(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["role"]] = counts.get(row["role"], 0) + 1
    return counts


def _statements_by_line(unit: CobolProgram) -> dict[int, Any]:
    """The innermost statement starting on each parsed line of *unit*."""
    from ..models.walk import own_statements

    by_line: dict[int, Any] = {}
    for statement in own_statements(unit):
        location = getattr(statement, "location", None)
        if location is None or not location.line:
            continue
        held = by_line.get(location.line)
        # get_all_statements lists a statement before the ones inside it,
        # so the last on a line is the innermost.
        if held is None or _depth(statement) >= _depth(held):
            by_line[location.line] = statement
    return by_line


def _depth(statement: Any) -> int:
    depth = 0
    node = getattr(statement, "parent", None)
    while node is not None and not isinstance(node, CobolParagraph):
        depth += 1
        node = getattr(node, "parent", None)
    return depth


def _enclosing(statement: Any) -> list[Any]:
    """The statements *statement* is written inside, innermost first."""
    found: list[Any] = []
    node = getattr(statement, "parent", None) if statement is not None else None
    while node is not None and not isinstance(node, (CobolParagraph, CobolProgram)):
        if isinstance(node, CobolStatement):
            found.append(node)
        node = getattr(node, "parent", None)
    return found


class _XrefIndex:
    """Where each field of a unit is written and tested, keyed by the
    qualified name the field-flow report spells (outermost first, ``.``).

    A level-88 is read as the item it is declared under: ``SET FLAG-ON TO
    TRUE`` writes it, ``IF FLAG-ON`` tests it.
    """

    def __init__(self, report: XrefReport) -> None:
        from ..analysis.xref import ROLE_CONDITION, ROLE_WRITE

        self._writes: dict[str, set[int]] = {}
        self._tests: dict[str, set[int]] = {}
        self._written_on: dict[int, set[str]] = {}
        self._tested_on: dict[int, set[str]] = {}
        for entry in report.entries:
            if entry.kind not in ("data-item", "condition-name"):
                continue
            chain = [a.upper() for a in reversed(entry.ancestors)]
            if entry.kind == "data-item":
                chain.append(entry.name.upper())
            if not chain:
                continue
            qualified = ".".join(chain)
            for ref in entry.references:
                line = ref.location.line
                if not line:
                    continue
                if ref.role == ROLE_WRITE:
                    self._writes.setdefault(qualified, set()).add(line)
                    self._written_on.setdefault(line, set()).add(qualified)
                elif ref.role == ROLE_CONDITION:
                    self._tests.setdefault(qualified, set()).add(line)
                    self._tested_on.setdefault(line, set()).add(qualified)

    def _under(self, table: dict[str, set[int]], name: str) -> set[int]:
        """Lines of *name* and of every field under it (a group's writes)."""
        out: set[int] = set()
        for key, lines in table.items():
            if key == name or key.startswith((name + ".", name + "(")):
                out |= lines
        return out

    def writes_of(self, name: str) -> list[int]:
        return sorted(self._under(self._writes, name))

    def tests_of(self, name: str) -> list[int]:
        return sorted(self._under(self._tests, name))

    def written_on(self, line: int) -> set[str]:
        return self._written_on.get(line, set())

    def tested_on(self, line: int) -> set[str]:
        return self._tested_on.get(line, set())


def overlay_item_kind() -> str:
    """The node kind of a data item in the lineage graph."""
    from ..analysis.lineage_graph import ITEM

    return str(ITEM)
