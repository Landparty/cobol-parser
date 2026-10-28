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
from typing import Any

from ..models.program import CobolParagraph, CobolProgram
from ..models.statements.base import CobolStatement
from .envelope import Response, ToolError
from .workspace import Workspace

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
    from .tools import _carry_parse_caveats

    _carry_parse_caveats(parsed, response)
    unit = parsed.unit(program, response)
    program_info = parsed.program_info(unit)
    report = parsed.report("lineage", unit, functools.partial(_field_flow, unit))
    graph = LineageGraph([report])
    program_id = (report.program_id or "").upper()
    wanted = " ".join(field_name.upper().replace(" IN ", " OF ").split())
    groups, matched = graph._start_groups(wanted, [program_id])
    starts = sorted({n for group in groups for n in group}, key=repr)
    if not starts:
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
    rows: dict[int, _Row] = {}
    fields: set[str] = set()
    ports: set[str] = set()
    seen: set[tuple[Any, int]] = set()
    queue: deque[tuple[Any, int]] = deque((s, 0) for s in starts)
    seen.update(queue)
    skipped: set[str] = set()
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
            _p, name, kind = graph._describe(nxt)
            if kind == "port":
                ports.add(name)
                continue  # a boundary, never a pass-through
            fields.add(name)
            state = (nxt, overlay)
            if state not in seen:
                seen.add(state)
                queue.append(state)

    statements = _statements_by_line(unit)
    for line in list(rows):
        for ancestor in _enclosing(statements.get(line)):
            a_line = ancestor.location.line
            if a_line and a_line not in rows:
                paragraph, _section = _procedure_of(ancestor)
                rows[a_line] = _Row(
                    a_line, statement_verb(ancestor), paragraph, "control"
                )
    if direction == "forward":
        tested = _condition_lines(
            unit, fields | {n for _p, n, _k in map(graph._describe, starts)}
        )
        for line, tested_names in tested.items():
            statement = statements.get(line)
            if statement is None:
                continue
            held = rows.get(line)
            if held is None:
                paragraph, _section = _procedure_of(statement)
                held = rows[line] = _Row(
                    line, statement_verb(statement), paragraph, "decision"
                )
            held.flows.update(f"tests {n}" for n in sorted(tested_names))
            # What runs only when the test goes one way is affected too.
            for inner in _statements_under(statement):
                i_line = inner.location.line
                if i_line and i_line not in rows:
                    paragraph, _section = _procedure_of(inner)
                    rows[i_line] = _Row(
                        i_line, statement_verb(inner), paragraph, "controlled"
                    )

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
    start_names = sorted(n for names in matched.values() for n in names)
    answer: dict[str, Any] = {
        "field": wanted,
        "matched": start_names,
        "direction": direction,
        "found": True,
        "statement_count": len(shown),
        "by_role": _by_role(shown),
        "fields": sorted(fields - set(start_names)),
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
            "a data statement runs only inside it; decision (forward): it "
            "tests a field of the slice; controlled: it runs only on one "
            "outcome of such a test. ports: the files, DB2 columns, CALL "
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
    from .tools import _own_statements

    by_line: dict[int, Any] = {}
    for statement in _own_statements(unit):
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


def _condition_lines(unit: CobolProgram, names: set[str]) -> dict[int, set[str]]:
    """Parsed line -> the fields of *names* (qualified, as the field-flow
    report spells them) a condition on that line tests."""
    from ..analysis.xref import ROLE_CONDITION, XrefAnalyzer
    from .workspace import stdout_to_stderr

    wanted = {n.upper() for n in names}
    with stdout_to_stderr():
        report = XrefAnalyzer().analyze(unit)
    lines: dict[int, set[str]] = {}
    for entry in report.entries:
        if entry.kind not in ("data-item", "condition-name"):
            continue
        # Spelled as the field-flow report spells it: outermost first; a
        # level-88 tests the item it is declared under.
        chain = [a.upper() for a in reversed(entry.ancestors)]
        if entry.kind == "data-item":
            chain.append(entry.name.upper())
        qualified = ".".join(chain)
        if qualified not in wanted:
            continue
        for ref in entry.references:
            if ref.role == ROLE_CONDITION and ref.location.line:
                lines.setdefault(ref.location.line, set()).add(qualified)
    return lines
