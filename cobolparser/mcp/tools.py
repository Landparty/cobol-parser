"""The MCP tools, as plain functions over a :class:`Workspace`.

Nothing here imports the MCP SDK: every tool takes plain arguments and
returns a plain dict (the :mod:`.envelope` shape), so it is unit-testable
without the ``[mcp]`` extra and callable from any other front end -- the
backend, the VS Code extension -- exactly as the server calls it.

Each tool answers one question a person asks about COBOL, joining analyzers
server-side, rather than mirroring a CLI subcommand: a whole ``xref`` report
of a large program would spend a model's context on the first call.
"""

from __future__ import annotations

import difflib
import functools
import itertools
import os
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from .._lines import split_source_lines
from ..models.data_items import CobolDataItem, ConditionNameItem, RenamesItem
from ..models.program import CobolProgram, CobolSection
from ..preprocess import PreprocessingError
from .envelope import Response, ToolError, clamp_limit
from .workspace import ParsedProgram, Workspace, stdout_to_stderr

#: Prefixes of the xref caveats that are about undeclared names only.
_UNDECLARED_CAVEATS: tuple[str, ...] = (
    "the kind of an undefined symbol",
    "'undefined' means",
    "special registers",
)

#: Most lines :meth:`CobolTools.read_source` returns in one call.
MAX_SOURCE_LINES = 200

#: JCL steps a brief lists under run_by (jobs_running has them all).
BRIEF_RUN_BY = 10

#: Lint findings a program brief shows (worst first); ``lint`` has the rest.
BRIEF_LINT = 5

#: Length of the "top" lists in a codebase overview (most called, most used
#: copybooks, worst health, duplicated code); ``limit`` can only lower it.
OVERVIEW_TOP = 10

#: Notes named one by one in a caveat that summarizes many.
NOTES_SHOWN = 5

#: Records ``decode_record`` reads when the caller names no ``max_records``.
DEFAULT_DECODE_RECORDS = 10

#: Most bytes of a data file ``decode_record`` reads: enough for any page
#: of records a model can use, never a whole multi-gigabyte extract.
MAX_DECODE_BYTES = 16 * 1024 * 1024

#: Generated rows per boundary sequence in ``gen_fixtures`` (the CLI's 10
#: is sized for a test run, not for a context window), and the most allowed.
DEFAULT_FIXTURE_ROWS = 3
MAX_FIXTURE_ROWS = 100

#: DATA DIVISION sections a record can be declared in, as
#: ``compute_program_data_items`` walks them.
_DATA_SECTIONS: tuple[str, ...] = (
    "FILE",
    "WORKING-STORAGE",
    "LOCAL-STORAGE",
    "LINKAGE",
)

#: Flow edges that CALL another program rather than run a procedure.
_CALL_EDGES = frozenset({"CALL", "CALL_DYNAMIC"})

#: Flow edges that hand control to a paragraph or section. IF/EVALUATE
#: edges are the graph's own branch scaffolding, never a caller.
_CONTROL_EDGES = frozenset(
    {
        "PERFORM",
        "PERFORM_THRU",
        "GOTO",
        "GOTO_DEPENDING",
        "SORT_INPUT_PROCEDURE",
        "SORT_INPUT_PROCEDURE_THRU",
        "SORT_OUTPUT_PROCEDURE",
        "SORT_OUTPUT_PROCEDURE_THRU",
        "MERGE_OUTPUT_PROCEDURE",
        "MERGE_OUTPUT_PROCEDURE_THRU",
        "XML_PROCESSING_PROCEDURE",
        "XML_PROCESSING_PROCEDURE_THRU",
        "CICS_HANDLE",
        "SQL_WHENEVER",
        "ALTER",
        "FALL_THROUGH",
    }
)


def _source_lines(path: Path) -> Iterator[str]:
    """*path*'s lines, decoded as the parse decodes it (#522), so a line
    number in any other answer is the same line here.

    An ASCII-shaped encoding streams (newline="" splits on \n, \r\n and \r
    only, as split_source_lines does: never on a form feed inside a record),
    so a huge file costs no memory; EBCDIC / UTF-16 go through the same
    whole-file conversion the parse uses.
    """
    from ..preprocess.copybook_expander import (
        _is_ebcdic_codec,
        detect_encoding,
        read_program_source,
    )

    encoding = detect_encoding(str(path))
    if _is_ebcdic_codec(encoding) or encoding.startswith("utf-16"):
        yield from split_source_lines(read_program_source(str(path), encoding))
        return
    with path.open(encoding=encoding, errors="replace", newline="") as handle:
        for text in handle:
            yield text.rstrip("\r\n")


class CobolTools:
    """Every tool the MCP server exposes, bound to one workspace."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    # -- read_source ---------------------------------------------------------

    def read_source(
        self, file: str, line: int = 1, before: int = 10, after: int = 10
    ) -> dict[str, Any]:
        """The lines around ``file:line``, numbered as an editor numbers them."""
        path = self.workspace.resolve(file)
        before = max(0, before)
        after = max(0, after)
        # The cap trims context, never the cited line (#537): lines are kept
        # from at most MAX_SOURCE_LINES - 1 either side of *line* while the
        # file streams past (the rest is only counted, so a huge file under
        # the root costs no memory), then cut to the budget once the end of
        # the file is known -- *line* and its ``after`` lines first, the
        # rest of the budget from ``before``.
        first_kept = max(1, line - min(before, MAX_SOURCE_LINES - 1))
        last_kept = line + min(after, MAX_SOURCE_LINES - 1)
        kept: dict[int, str] = {}
        total = 0
        try:
            for total, text in enumerate(_source_lines(path), start=1):
                if first_kept <= total <= last_kept:
                    kept[total] = text
        except (OSError, PreprocessingError) as exc:
            raise ToolError(f"cannot read {path.name}: {exc}") from exc
        if line < 1 or (total and line > total):
            raise ToolError(f"line {line} is outside {file} (1-{total})")
        requested_start = max(1, line - before)
        requested_end = min(total, line + after)
        end = min(requested_end, line + MAX_SOURCE_LINES - 1)
        start = max(requested_start, end - MAX_SOURCE_LINES + 1)
        response = Response()
        if requested_end - requested_start + 1 > MAX_SOURCE_LINES:
            response.truncated.append(
                {
                    "field": "lines",
                    "shown": end - start + 1,
                    "total": requested_end - requested_start + 1,
                }
            )
        return response.build(
            {
                "file": self.workspace.display(path),
                "start_line": start,
                "end_line": end,
                "total_lines": total,
                "lines": [{"line": n, "text": kept[n]} for n in range(start, end + 1)],
            }
        )

    # -- lint ----------------------------------------------------------------

    def lint(
        self,
        file: str,
        rules: list[str] | None = None,
        min_severity: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Every lint finding in *file*, worst first, each cited on disk."""
        from ..analysis.lint import SEVERITIES, LintAnalyzer, filter_by_severity

        config = self.workspace.config.lint
        # Rule ids and severities are lower-case words, matched as every
        # other enumerated argument here is: "WARNING" is "warning".
        selected = [r.strip().lower() for r in rules or ()] or list(config.rules)
        severity = (min_severity or config.min_severity or "info").strip().lower()
        if severity not in SEVERITIES:
            raise ToolError(
                f"unknown severity {severity!r} (expected one of "
                f"{', '.join(SEVERITIES)})"
            )
        try:
            analyzer = LintAnalyzer(selected or None)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

        parsed = self.workspace.program(file)
        response = Response()
        _carry_parse_caveats(parsed, response)
        report, ordered = _run_lint(parsed, analyzer, response)
        findings = filter_by_severity(ordered, severity)
        shown = response.cap(findings, clamp_limit(limit), "findings")
        answer = {
            "rules_run": list(report.rules_run),
            "min_severity": severity,
            "summary": _lint_summary(findings),
            "findings": [_finding(f, parsed, response) for f in shown],
        }
        return response.build(answer, parsed.program_info())

    # -- explain_symbol ------------------------------------------------------

    def explain_symbol(
        self,
        file: str,
        name: str,
        program: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """What *name* is in *file*: declaration, layout, every reference."""
        from ..analysis.xref import XrefAnalyzer, is_special_register

        wanted = " ".join(name.split()).upper()
        if not wanted:
            raise ToolError("no symbol name given")
        parsed = self.workspace.program(file)
        response = Response()
        _carry_parse_caveats(parsed, response)
        unit = parsed.unit(program, response)
        with stdout_to_stderr():
            report = XrefAnalyzer().analyze(unit)

        # A qualified name is resolved as the compiler resolves it: partial
        # chains, ``IN`` for ``OF``, and no need to qualify a unique name.
        matches = report.entries_named(wanted)

        program_info = parsed.program_info(unit)
        undeclared_asked = not matches or any(e.definition is None for e in matches)
        for caveat in report.caveats:
            # xref's notes about *undeclared* names only bear on an answer
            # about one; on every other answer they are noise a model pays for.
            if undeclared_asked or not caveat.startswith(_UNDECLARED_CAVEATS):
                response.caveat("incomplete-analysis", caveat)
        if not matches:
            undeclared = wanted in {u.upper() for u in report.undefined}
            special = is_special_register(wanted)
            names = sorted({e.name.upper() for e in report.entries})
            not_found: dict[str, Any] = {
                "name": wanted,
                "found": False,
                "referenced_but_undeclared": undeclared,
                "special_register": special,
                # A near-miss spelling is no help for RETURN-CODE or SQLCODE:
                # the name is right, it is just never declared.
                "suggestions": (
                    [] if special else difflib.get_close_matches(wanted, names, n=5)
                ),
            }
            if special:
                not_found["note"] = (
                    f"{wanted} is a special register or a precompiler/"
                    "translator-supplied item: the compiler provides it, so "
                    "the program never declares it"
                )
            _declared_elsewhere(
                not_found,
                parsed,
                unit,
                lambda other: any(
                    e.definition is not None
                    for e in XrefAnalyzer().analyze(other).entries_named(wanted)
                ),
            )
            return response.build(not_found, program_info)

        if len(matches) > 1:
            response.caveat(
                "ambiguous-name",
                f"{len(matches)} declarations are named {wanted}",
                "qualify the name (X OF Y) to ask about one of them",
            )
        if any(d.upper() == wanted for d in report.duplicate_declarations):
            response.caveat(
                "duplicate-declaration",
                f"{wanted} is declared more than once in one namespace",
                "every reference is attributed to the first declaration",
            )

        layout = _layout_index(unit, response)
        cap = clamp_limit(limit)
        symbols: list[dict[str, Any]] = []
        for index, entry in enumerate(matches):
            roles: dict[str, int] = {}
            for ref in entry.references:
                roles[ref.role] = roles.get(ref.role, 0) + 1
            refs = response.cap(
                list(entry.references), cap, f"symbols[{index}].references"
            )
            symbol: dict[str, Any] = {
                "name": entry.name,
                "kind": entry.kind,
                "qualified_name": entry.qualified_name,
                "level": entry.level,
                "section": entry.section,
                "declared_at": (
                    parsed.locate(
                        entry.definition.line, entry.definition.column, response
                    )
                    if entry.definition
                    else None
                ),
                "declared": entry.definition is not None,
                "reference_count": entry.reference_count,
                "references_by_role": roles,
                "references": [
                    {
                        # xref's column is the statement's, not the
                        # operand's: the line is exact, a column would mislead.
                        "location": parsed.locate(
                            ref.location.line,
                            None,
                            response,
                            column_known=False,
                        ),
                        "role": ref.role,
                        "statement": ref.statement,
                        "paragraph": ref.context,
                    }
                    for ref in refs
                ],
            }
            # data-items places a level-66 RENAMES item itself (#563).
            item = _layout_for(entry.name, entry.qualified_name, layout)
            if item is None and entry.level == 66:
                response.caveat(
                    "incomplete-analysis",
                    f"RENAMES item {entry.name}: the bytes it renames "
                    "could not be placed",
                    "no layout is reported for it",
                )
            if item is not None:
                _layout_caveats(item, layout, response)
                symbol["layout"] = {
                    key: item.get(key)
                    for key in (
                        "qualified_name",
                        "picture",
                        "usage",
                        "byte_offset",
                        "byte_length",
                        "offset_ambiguous",
                        "redefines_chain",
                        "occurs",
                        "condition_values",
                        "condition_ranges",
                    )
                    if _worth_showing(item.get(key))
                }
            symbols.append(symbol)

        return response.build(
            {"name": wanted, "found": True, "symbols": symbols}, program_info
        )

    # -- program_brief -------------------------------------------------------

    def program_brief(
        self, file: str, program: str | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        """What *file* (or one program unit in it) is, on one page."""
        from ..analysis.lint import LintAnalyzer

        other = self._other_language_path(file)
        if other is not None:
            return self._other_language_brief(other, clamp_limit(limit))
        parsed = self.workspace.program(file)
        response = Response()
        _carry_parse_caveats(parsed, response)
        unit = parsed.unit(program, response)
        cap = clamp_limit(limit)
        answer: dict[str, Any] = {"program_id": unit.program_name}
        if unit.unit_kind != "PROGRAM":
            answer["unit_kind"] = unit.unit_kind

        flow = _attempt(response, "control flow", lambda: _flow(parsed, unit))
        if flow is not None:
            nodes = flow.nodes
            answer["size"] = {
                "sections": sum(1 for n in nodes if n.procedure_type == "SECTION"),
                "paragraphs": sum(1 for n in nodes if n.procedure_type == "PARAGRAPH"),
                "statements": len(_own_statements(unit)),
            }
            answer["entry_points"] = list(flow.entry_points)
            reach = _reachability(parsed, unit, response)
            answer["unreachable_procedures"] = (
                list(flow.unreachable_nodes) if reach is None else reach.unreachable
            )
            answer["perform_cycles"] = len(flow.cycles)

        signature = _attempt(
            response,
            "calling interface",
            lambda: _signature(parsed, unit),
        )
        if signature is not None:
            answer["interface"] = [
                {
                    "name": entry.name,
                    "kind": entry.kind,
                    "call_example": entry.call_example(),
                    "returning": entry.returning,
                    "parameters": [
                        {
                            "name": p.name,
                            "position": p.position,
                            "direction": p.direction,
                            "by": p.by_clause,
                            "declaration": p.declaration(),
                            "declared_at": (
                                parsed.locate(
                                    p.location.line, p.location.column, response
                                )
                                if p.location
                                else None
                            ),
                        }
                        for p in entry.parameters
                    ],
                }
                for entry in signature.entry_points
            ]
            notes = (
                list(signature.unchecked)
                + [
                    f"USING names {name}, which LINKAGE does not declare"
                    for name in signature.undeclared_parameters
                ]
                + [
                    f"LINKAGE item {name} is named by no USING clause"
                    for name in signature.unreferenced_linkage
                ]
            )
            if notes:
                answer["interface_notes"] = notes

        crud = _attempt(response, "file and table use", lambda: _crud(parsed, unit))
        if crud is not None:
            # An EXEC CICS file command naming its file through a data item
            # has no row; say so rather than let ``files`` read as complete.
            for caveat in crud.caveats:
                response.caveat("incomplete-analysis", caveat)
            facts = _attempt(
                response, "file descriptions", lambda: _file_facts(parsed, unit)
            )
            files = []
            for entry in sorted(crud.file_entries, key=lambda e: e.file_name):
                fact = (facts or {}).get(entry.file_name.upper())
                row: dict[str, Any] = {
                    "name": entry.file_name,
                    "access": entry.crud.as_string(),
                    "open_modes": sorted(set(entry.open_modes)),
                    "organization": entry.organization,
                    "access_mode": entry.access_mode,
                }
                if fact is not None:
                    row["records"] = list(fact.record_names)
                    if fact.record_key:
                        row["record_key"] = fact.record_key
                    if fact.file_status_field:
                        row["status_field"] = fact.file_status_field
                files.append({k: v for k, v in row.items() if _worth_showing(v)})
            answer["files"] = response.cap(files, cap, "files")
            tables = [
                {
                    "name": entry.table_name,
                    "access": entry.crud.as_string(),
                    **(
                        {"cursors": sorted(set(entry.cursors))} if entry.cursors else {}
                    ),
                }
                for entry in sorted(crud.table_entries, key=lambda e: e.table_name)
            ]
            answer["sql_tables"] = response.cap(tables, cap, "sql_tables")
            if files or tables:
                answer["access_legend"] = "C=create R=read U=update D=delete"

        if flow is not None:
            calls = _attempt(
                response,
                "called programs",
                lambda: _calls(parsed, unit, flow, response),
            )
            if calls is not None:
                answer["calls"] = response.cap(calls, cap, "calls")

        statements = _own_statements(unit)
        cics = _verb_counts(statements, "EXEC_CICS", "cics_command")
        if cics:
            answer["cics_commands"] = cics
        dli = _verb_counts(statements, "EXEC_IMS", "ims_command")
        if dli:
            answer["exec_dli_commands"] = dli

        debt = _attempt(response, "health score", lambda: _debt(parsed, unit))
        if debt is not None:
            for caveat in debt.caveats:
                response.caveat("incomplete-analysis", caveat)
            answer["health"] = {
                "grade": debt.grade,
                "score": debt.score,
                "concerns": [
                    finding
                    for component in debt.components
                    if component.score > 0
                    for finding in component.findings
                ],
            }

        config = self.workspace.config.lint
        analyzer = _attempt(
            response, "lint", lambda: LintAnalyzer(list(config.rules) or None)
        )
        if analyzer is not None:
            report = _attempt(
                response, "lint", lambda: _run_lint(parsed, analyzer, response)
            )
            if report is not None:
                _, ordered = report
                answer["lint"] = {
                    "scope": "file",
                    "summary": _lint_summary(ordered),
                    "worst": [
                        _finding(f, parsed, response) for f in ordered[:BRIEF_LINT]
                    ],
                }
        if unit is parsed.ast or not parsed.ast.contained_programs:
            names = {
                (unit.program_name or "").upper(),
                Path(str(parsed.path)).stem.upper(),
            } - {""}
            self._brief_run_by(answer, response, names, cap)
        return response.build(answer, parsed.program_info(unit))

    def _brief_run_by(
        self,
        answer: dict[str, Any],
        response: Response,
        names: set[str],
        cap: int,
    ) -> None:
        """``answer["run_by"]``: the JCL steps that run the program, so the
        brief says how it is started without a second call. Left out when
        there is no JCL to look in; a JCL failure costs only this field."""
        from .jcl_tools import run_by

        steps = _attempt(response, "JCL steps", lambda: run_by(self.workspace, names))
        if steps is None:
            return
        answer["run_by"] = response.cap(steps, min(cap, BRIEF_RUN_BY), "run_by")

    # -- PL/I and assembler ---------------------------------------------------

    def _other_language_path(self, file: str) -> Path | None:
        """*file*'s path when it is a PL/I or assembler source, else None."""
        from .languages import language_of

        if language_of(file) is None:
            return None
        path = self.workspace.resolve(file)
        if path.suffix.lower() in self.workspace._program_suffixes():
            return None
        return path

    def _other_language_brief(self, path: Path, cap: int) -> dict[str, Any]:
        """``program_brief`` of a PL/I or assembler source: its names, its
        procedures or sections, what it CALLs and includes, its CICS / SQL /
        MQ / IMS requests, who CALLs it and which JCL steps run it."""
        from .codebase_index import programs_index
        from .languages import LIMITS, facts_for

        source = facts_for(self.workspace, path)
        response = Response()
        for caveat in source.caveats:
            response.caveat(caveat.kind, caveat.detail, caveat.effect)
        if source.failed is not None:
            raise ToolError(
                f"cannot read {source.display} as {source.language}: {source.failed}"
            )
        response.caveat(
            "incomplete-analysis",
            LIMITS[source.language],
            "files, record layouts, field lineage and health are not "
            "available for this program",
        )
        answer: dict[str, Any] = {
            "program_id": source.program_id,
            "language": source.language,
            "file": source.display,
            "line_count": source.line_count,
        }
        if source.entries:
            answer["also_called_as"] = source.entries
        kind = "procedures" if source.language == "PL/I" else "sections"
        answer[kind] = response.cap(source.sections, cap, kind)
        answer["calls"] = response.cap(source.calls, cap, "calls")
        answer["includes"] = response.cap(source.includes, cap, "includes")
        if source.services:
            counts: dict[str, dict[str, int]] = {}
            for service in source.services:
                label = str(service.get("target") or service["command"])
                held = counts.setdefault(service["kind"], {})
                held[label] = held.get(label, 0) + 1
            answer["services"] = {k: dict(sorted(v.items())) for k, v in counts.items()}
            answer["service_requests"] = response.cap(
                source.services, cap, "service_requests"
            )
        index = programs_index(self.workspace)
        names = source.names()
        callers = sorted(
            {
                unit.program_id
                for unit in index.units
                for row in unit.calls
                if str(row.get("program") or "").upper() in names
                or names & {str(c).upper() for c in row.get("candidates") or []}
            }
        )
        answer["called_by"] = response.cap(callers, cap, "called_by")
        self._brief_run_by(answer, response, names | {path.stem.upper()}, cap)
        if not callers and not answer.get("run_by"):
            answer["note"] = (
                "no program under the root CALLs it and no JCL step under the "
                "root runs it: it is started by CICS or IMS, or from elsewhere"
            )
        return response.build(answer)

    # -- callers_of ----------------------------------------------------------

    def callers_of(
        self,
        file: str | None,
        name: str,
        program: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Who transfers control to paragraph or section *name*, and from where.

        A name that is no procedure of *file* (or any name, with no *file*)
        is looked up as a program: which programs under the root CALL, LINK
        or XCTL to it.
        """
        wanted = " ".join(name.split()).upper()
        if not wanted:
            raise ToolError("no paragraph, section or program name given")
        cap = clamp_limit(limit)
        response = Response()
        if file is None:
            return self._program_callers(wanted, response, cap, None, [])
        other = self._other_language_path(file)
        if other is not None:
            # PL/I and assembler procedures are not indexed: a name is a
            # program here.
            return self._program_callers(wanted, response, cap, None, [])
        parsed = self.workspace.program(file)
        _carry_parse_caveats(parsed, response)
        unit = parsed.unit(program, response)
        program_info = parsed.program_info(unit)
        flow = _flow(parsed, unit)

        wanted = wanted.replace(" IN ", " OF ")
        matches = [
            n for n in flow.nodes if n.key.upper() == wanted or n.name.upper() == wanted
        ]
        if len(matches) > 1:
            response.caveat(
                "ambiguous-name",
                f"{len(matches)} procedures are named {wanted}",
                "qualify the name (PARA OF SECTION) to ask about one of them",
            )

        if not matches:
            # Not a procedure here: a program, if any program under the root
            # is called or named so.
            names = sorted({n.key.upper() for n in flow.nodes})
            result = self._program_callers(wanted, response, cap, program_info, names)
            if not result["answer"].get("found"):
                _declared_elsewhere(
                    result["answer"],
                    parsed,
                    unit,
                    lambda other: any(
                        n.key.upper() == wanted or n.name.upper() == wanted
                        for n in _flow(parsed, other).nodes
                    ),
                )
            return result

        # Reachability is DeadCodeAnalyzer's (the same answer as the brief's
        # lint section): the flow graph draws a fall-through out of every
        # non-terminating procedure, PERFORM targets included, so its
        # ``unreachable_nodes`` misses the paragraph after a performed one.
        reach = _reachability(parsed, unit, response)
        if reach is None:
            unreachable = {u.upper() for u in flow.unreachable_nodes}
        else:
            unreachable = {u.upper() for u in reach.unreachable}
        # Where control starts runs on: the first paragraph, or the
        # sentences before it (``PROCEDURE DIVISION``, a node of the flow
        # graph only).
        start = flow.entry_points[0].upper() if flow.entry_points else None
        procedures: list[dict[str, Any]] = []
        for index, node in enumerate(matches):
            key = node.key.upper()
            # A THRU statement is two edges: the opener (to the first
            # paragraph, carrying the whole range) and a ``*_THRU`` closer to
            # the last. One statement is one caller, so only openers count;
            # a paragraph inside the range is run without being named.
            callers = []
            for edge in flow.edges:
                kind = edge.edge_type.value
                if kind not in _CONTROL_EDGES or kind.endswith("_THRU"):
                    continue
                if (
                    kind == "FALL_THROUGH"
                    and reach is not None
                    and edge.source.upper() != start
                    and (edge.source.upper(), edge.target.upper())
                    not in reach.fall_throughs
                ):
                    # Out of a procedure only ever PERFORMed (its end returns
                    # to the performer), or out of one never reached: control
                    # never runs on along this edge.
                    continue
                if edge.target.upper() == key:
                    callers.append(_edge_caller(edge, parsed, response))
                elif key in (m.upper() for m in edge.range_members):
                    caller = _edge_caller(edge, parsed, response)
                    caller["via_range"] = [edge.target, edge.thru_target]
                    callers.append(caller)
            by_type: dict[str, int] = {}
            for caller in callers:
                by_type[caller["type"]] = by_type.get(caller["type"], 0) + 1
            procedure: dict[str, Any] = {
                "name": node.name,
                "kind": node.procedure_type.lower(),
                "declared_at": parsed.locate(
                    node.location.line, node.location.column, response
                ),
                "is_entry_point": node.is_entry_point,
                "reachable": key not in unreachable,
                "caller_count": len(callers),
                "callers_by_type": by_type,
                "callers": response.cap(callers, cap, f"procedures[{index}].callers"),
            }
            if node.qualified_name:
                procedure["qualified_name"] = node.qualified_name
            if node.is_declarative:
                procedure["is_declarative"] = True
                procedure["note"] = (
                    "a DECLARATIVES procedure is run by the runtime when its "
                    "USE condition occurs, not by the program's own flow"
                )
            procedures.append(procedure)
        return response.build(
            {"name": wanted, "found": True, "procedures": procedures}, program_info
        )

    # -- record_layout -------------------------------------------------------

    def record_layout(
        self,
        file: str,
        record: str,
        program: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """The byte map of one record (or of every record of one FD)."""
        wanted = " ".join(record.split()).upper().replace(" IN ", " OF ")
        if not wanted:
            raise ToolError("no record name given")
        parsed = self.workspace.program(file)
        response = Response()
        _carry_parse_caveats(parsed, response)
        unit = parsed.unit(program, response)
        program_info = parsed.program_info(unit)
        cap = clamp_limit(limit)

        answer: dict[str, Any] = {"name": wanted}
        facts = _attempt(
            response, "file descriptions", lambda: _file_facts(parsed, unit)
        )
        fact = (facts or {}).get(wanted)
        if fact is not None:
            items = [
                item
                for record_name in fact.record_names
                for item in _data_items_named(unit, record_name.upper())
            ]
            answer["file"] = {
                "name": fact.file_name,
                "organization": fact.organization,
                "record_key": fact.record_key,
                "records": list(fact.record_names),
            }
            if len(items) > 1:
                answer["file"]["note"] = (
                    "several record descriptions under one FD share the same "
                    "record area, as if each REDEFINES the first"
                )
        else:
            items = _data_items_named(unit, wanted)
        if not items:
            renames = _renames_records(unit, wanted, parsed, response, cap)
            if renames:
                answer["found"] = True
                answer["records"] = renames
                answer["offsets_from"] = "the start of each record's 01/77 item"
                return response.build(answer, program_info)
            renames_name = wanted.split(" OF ")[0].strip()
            if _renames_node(unit, renames_name) is not None:
                # Declared, but data-items could not place it: say so rather
                # than let found: false read as "no such item" (#563).
                response.caveat(
                    "incomplete-analysis",
                    f"RENAMES item {renames_name}: the bytes it renames "
                    "could not be placed",
                    "no layout is reported for it",
                )
            names = sorted(
                {
                    found.item.name.upper()
                    for found in _walk_data_items(unit)
                    if not found.item.is_filler
                }
            )
            answer.update(
                {
                    "found": False,
                    "suggestions": difflib.get_close_matches(wanted, names, n=5),
                }
            )
            _declared_elsewhere(
                answer,
                parsed,
                unit,
                lambda other: bool(
                    (_file_facts(parsed, other)).get(wanted)
                    or _data_items_named(other, wanted)
                    or _renames_node(other, wanted.split(" OF ")[0].strip())
                ),
            )
            return response.build(answer, program_info)
        if len(items) > 1 and fact is None:
            response.caveat(
                "ambiguous-name",
                f"{len(items)} data items are named {wanted}",
                "qualify the name (X OF Y) to ask about one of them",
            )

        records = []
        for index, found in enumerate(items):
            layout = _attempt(
                response,
                "byte layout",
                functools.partial(_record_layout, found.root, response),
            )
            if layout is not None:
                records.append(
                    _layout_answer(found, layout, parsed, response, cap, index)
                )
        answer["found"] = True
        answer["records"] = records
        answer["offsets_from"] = "the start of each record's 01/77 item"
        return response.build(answer, program_info)

    # -- callers_of, at program level ---------------------------------------

    def _program_callers(
        self,
        wanted: str,
        response: Response,
        cap: int,
        program_info: dict[str, Any] | None,
        procedures: list[str],
    ) -> dict[str, Any]:
        """Every CALL, LINK and XCTL to program *wanted* under the root."""
        from .codebase_index import programs_index

        index = programs_index(self.workspace)
        _carry_index_caveats(index, response, "CALL statements")
        callers: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        # A nested program can only be CALLed from its own compilation unit
        # (#532): when every declaration of *wanted* is nested, a CALL that
        # COBOL scope does not send to one reaches a separately compiled
        # program of the same name, not any declared here.
        declared_units = index.units_named(wanted)
        only_nested = bool(declared_units) and all(u.depth for u in declared_units)
        out_of_scope: set[str] = set()
        # A CALL to one of the program's alternate ENTRY names reaches it
        # too (#521); a PROGRAM-ID of that spelling would win instead.
        # A FACTORY / OBJECT / METHOD-ID unit is neither (#500).
        program_ids = {u.program_id.upper() for u in index.units if u.is_call_target}
        entries = {
            entry
            for u in index.units
            if u.is_call_target and u.program_id.upper() == wanted
            for entry in u.entries
            if entry not in program_ids
        }
        names = {wanted} | entries
        for unit in index.units:
            for row in unit.calls:
                target = str(row.get("program") or "").upper()
                candidates = [str(c).upper() for c in row.get("candidates") or []]
                via_entry: str | None = None
                if not row.get("dynamic") and target in names:
                    resolved_from = None
                    reaches_nested = bool(row.get("nested"))
                    via_entry = target if target in entries else None
                elif row.get("dynamic") and names & set(candidates):
                    resolved_from = row.get("program")
                    reaches_nested = wanted in {
                        str(c).upper() for c in row.get("nested_candidates") or []
                    }
                    if wanted not in candidates:
                        via_entry = sorted(names & set(candidates))[0]
                elif row.get("dynamic") and not row.get("candidates_complete"):
                    for site in row.get("sites") or []:
                        unresolved.append(
                            {
                                "program": unit.program_id,
                                "via": row.get("via"),
                                "target_from": row.get("program"),
                                "location": site.get("location"),
                            }
                        )
                    continue
                else:
                    continue
                if only_nested and not reaches_nested:
                    out_of_scope.add(unit.program_id)
                    continue
                for site in row.get("sites") or []:
                    caller: dict[str, Any] = {
                        "program": unit.program_id,
                        "via": row.get("via"),
                        "location": site.get("location"),
                    }
                    if unit.language != "COBOL":
                        caller["language"] = unit.language
                    if reaches_nested:
                        caller["nested"] = True
                    if site.get("paragraph"):
                        # "from", as a paragraph-level caller names its own.
                        caller["from"] = site["paragraph"]
                    if via_entry is not None:
                        caller["entry"] = via_entry
                    if resolved_from is not None:
                        caller["dynamic"] = True
                        caller["target_from"] = resolved_from
                    callers.append(caller)

        declared = []
        for unit in declared_units:
            where: dict[str, Any] = {"file": unit.file}
            if unit.program_id.upper() != wanted:
                # Found through an ENTRY name it declares (#521).
                where["program"] = unit.program_id
            if unit.depth:
                where["contained"] = True
            if unit.unit_kind != "PROGRAM":
                where["unit_kind"] = unit.unit_kind
            if unit.language != "COBOL":
                where["language"] = unit.language
            declared.append(where)
        if not callers and not declared:
            known = sorted(
                {u.program_id.upper() for u in index.units if u.program_id}
                | {
                    str(row.get("program") or "").upper()
                    for u in index.units
                    for row in u.calls
                    if not row.get("dynamic")
                }
            )
            return response.build(
                {
                    "name": wanted,
                    "found": False,
                    "suggestions": difflib.get_close_matches(
                        wanted, sorted(set(procedures) | set(known)), n=5
                    ),
                },
                program_info,
            )

        answer: dict[str, Any] = {
            "name": wanted,
            "found": True,
            "kind": "program",
            "scope": "workspace",
            "declared_in": declared,
            "caller_count": len(callers),
            "calling_programs": sorted({c["program"] for c in callers}),
            "callers": response.cap(callers, cap, "callers"),
            "coverage": _coverage(self.workspace, index),
        }
        if out_of_scope:
            answer["out_of_scope_callers"] = sorted(out_of_scope)
        # Only outermost (or stacked) declarations share one load-module
        # namespace: a nested program is reached from its own compilation
        # unit, whatever else is in the load library (#532).
        top_level = [d for d in declared if not d.get("contained")]
        if len(top_level) > 1:
            response.caveat(
                "duplicate-declaration",
                f"PROGRAM-ID {wanted} is declared in {len(top_level)} places: "
                + ", ".join(d["file"] for d in top_level),
                "which one a CALL reaches depends on the load library order, "
                "which the source does not say",
            )
        other = self.workspace.other_sources().get(wanted.upper())
        if other:
            # Even beside a declaration: a second source of the same name
            # (an assembler twin of a COBOL routine) is what a reader most
            # needs to hear about.
            answer["sources_not_analyzed"] = [
                {"file": self.workspace.display(path), "language": language}
                for path, language in other
            ]
        if other and not declared:
            answer["note"] = (
                f"no COBOL program under the root has PROGRAM-ID {wanted}, but "
                f"its source is here in {other[0][1]} "
                f"({self.workspace.display(other[0][0])}), which these tools "
                "do not parse: read it with read_source" + _install_note(other[0][0])
            )
        elif not declared:
            answer["note"] = (
                f"no program under the root has PROGRAM-ID {wanted}: it is "
                "external to this workspace (a vendor or system program, or "
                "one kept elsewhere)"
            )
        elif not callers and out_of_scope:
            answer["note"] = (
                f"every {wanted} under the root is a nested program, which "
                "only its own compilation unit can CALL; the CALLs from "
                "out_of_scope_callers reach a separately compiled program "
                "of that name"
            )
        elif not callers:
            answer["note"] = (
                "no program under the root CALLs, LINKs or XCTLs to it: it is "
                "started some other way (a JCL EXEC PGM=, a CICS transaction, "
                "a scheduler) or is no longer used"
            )
        if unresolved:
            self._unresolved_near(answer, response, cap, wanted, unresolved)
        return response.build(answer, program_info)

    def _unresolved_near(
        self,
        answer: dict[str, Any],
        response: Response,
        cap: int,
        wanted: str,
        unresolved: list[dict[str, Any]],
    ) -> None:
        """The untraced dynamic CALL sites that could reach *wanted*: those in
        the top-level folder of a declaration or a caller of it (an
        application, in a root holding several), and those whose source text
        names it. The others, in folders that never mention it, are counted:
        a value set the analysis could not trace is still built from
        literals somewhere, and none of them spells this name."""
        anchors = {
            _top_folder(str(where["file"]))
            for where in answer.get("declared_in", [])
            if where.get("file")
        } | {
            _top_folder(str(c["location"]["file"]))
            for c in answer.get("callers", [])
            if (c.get("location") or {}).get("file")
        }
        names = re.compile(rf"(?<![\w-]){re.escape(wanted)}(?![\w-])", re.IGNORECASE)
        near: list[dict[str, Any]] = []
        far: list[dict[str, Any]] = []
        for row in unresolved:
            file = str((row.get("location") or {}).get("file") or "")
            if (
                not anchors
                or not file
                or _top_folder(file) in anchors
                or self._file_names(file, names)
            ):
                near.append(row)
            else:
                far.append(row)
        if near:
            answer["unresolved_dynamic_calls"] = response.cap(
                near, cap, "unresolved_dynamic_calls"
            )
        parts: list[str] = []
        effects: list[str] = []
        if near:
            parts.append(
                f"{len(near)} dynamic CALL/LINK/XCTL site(s) near {wanted} take "
                "their target from a data item whose values could not all be "
                "traced"
            )
            effects.append(
                f"any of them may also reach {wanted}; they are listed in "
                "unresolved_dynamic_calls"
            )
        if far:
            folders = sorted({_top_folder(str(r["location"]["file"])) for r in far})
            answer["unresolved_dynamic_calls_elsewhere"] = {
                "count": len(far),
                "folders": folders,
            }
            parts.append(
                f"{len(far)} untraced dynamic CALL/LINK/XCTL site(s) in other "
                f"folders ({', '.join(folders)}), whose source never names "
                f"{wanted}, are only counted"
            )
            effects.append(
                "those could reach it only through a name read at run time "
                "(a file, a commarea, a table)"
            )
        detail, effect = "; ".join(parts), "; ".join(effects)
        response.caveat("incomplete-analysis", detail, effect)

    def _file_names(self, file: str, names: re.Pattern[str]) -> bool:
        """Whether the source *file* (relative to the root) matches *names*."""
        try:
            text = (self.workspace.root / file).read_text(encoding="latin-1")
        except OSError:
            return True  # unreadable: it may well name it
        return bool(names.search(text))

    def _relative(self, text: str) -> str:
        """*text* (a library note) with the root's absolute path cut, so it
        names files the way every location does."""
        return text.replace(f"{self.workspace.root.as_posix()}/", "")

    # -- impact_of_change / where_from ---------------------------------------

    def impact_of_change(
        self,
        name: str,
        file: str | None = None,
        program: str | None = None,
        depth: int | None = None,
        limit: int | None = None,
        full_paths: bool = False,
    ) -> dict[str, Any]:
        """What a change to copybook member or field *name* reaches.

        A copybook member (or, with no *file*, any name a COPY statement
        names): every program that COPYs it, directly or through another
        member. A field: everything its value flows into, across programs.
        """
        from ..analysis.codebase import _MEMBER_SUFFIXES, _normalize_member
        from .codebase_index import programs_index

        text = " ".join(name.split())
        if not text:
            raise ToolError("no copybook member or field name given")
        cap = clamp_limit(limit)
        suffix = Path(text).suffix.lower()
        if file is None or suffix in _MEMBER_SUFFIXES or "/" in text:
            member = _normalize_member(text)
            index = programs_index(self.workspace)
            if (
                suffix in _MEMBER_SUFFIXES
                or member in index.graph.members
                or member in index.copy_sites
            ):
                return self._copybook_impact(member, cap)
        return self._lineage(text, file, program, depth, cap, "forward", full_paths)

    def where_from(
        self,
        field: str,
        file: str | None = None,
        program: str | None = None,
        depth: int | None = None,
        limit: int | None = None,
        full_paths: bool = False,
    ) -> dict[str, Any]:
        """Where the value of *field* comes from, across programs.

        Paths shared with an earlier hit are given once (``from_hit``)
        unless *full_paths*.
        """
        text = " ".join(field.split())
        if not text:
            raise ToolError("no field name given")
        return self._lineage(
            text, file, program, depth, clamp_limit(limit), "backward", full_paths
        )

    def _copybook_impact(self, member: str, cap: int) -> dict[str, Any]:
        from ..analysis.codebase import CopybookImpactAnalyzer
        from .codebase_index import programs_index

        index = programs_index(self.workspace)
        response = Response()
        _carry_index_caveats(index, response, "COPY statements")
        graph = index.graph
        # A PL/I %INCLUDE or an assembler COPY of the member: not in the
        # COBOL COPY graph, so listed on its own.
        included = [s for s in index.copy_sites.get(member, []) if s.get("language")]
        if included and member not in graph.members:
            return response.build(
                {
                    "name": member,
                    "kind": "copybook",
                    "found": True,
                    "program_count": len(
                        {self._unit_in(index, s["file"]) for s in included}
                    ),
                    "copied_by": [],
                    "coverage": _coverage(self.workspace, index),
                    "included_by_other_languages": response.cap(
                        self._included_rows(index, included, member),
                        cap,
                        "included_by_other_languages",
                    ),
                }
            )
        report = CopybookImpactAnalyzer(graph).analyze(member)
        if member not in graph.members:
            return response.build(
                {
                    "name": member,
                    "kind": "copybook",
                    "found": False,
                    "suggestions": difflib.get_close_matches(
                        member, graph.members, n=5
                    ),
                }
            )
        # One PROGRAM-ID can be declared in several files: keep every file,
        # so the COPY sites of one are never shown under the other.
        files: dict[str, list[str]] = {}
        for node in graph.programs:
            shown = self.workspace.display(node.path)
            if shown not in files.setdefault(node.program_id, []):
                files[node.program_id].append(shown)

        def declared(program_id: str) -> list[str | None]:
            return [*files.get(program_id, [])] or [None]

        sites_by_file: dict[str, list[dict[str, Any]]] = {}
        for site in index.copy_sites.get(member, []):
            sites_by_file.setdefault(site["file"], []).append(
                {"file": site["file"], "line": site["line"]}
            )
        direct = []
        for program_id in report.direct_programs:
            declared_in = declared(program_id)
            for file in declared_in:
                sites = sites_by_file.get(file or "", [])
                if len(declared_in) > 1 and not sites:
                    continue
                direct.append(
                    {"program": program_id, "file": file, "copy_sites": sites}
                )
        through: dict[str, list[list[str]]] = {}
        for chain in report.chains:
            if chain and chain[0] in report.transitive_programs:
                through.setdefault(chain[0], []).append(chain)
        nested = [
            {"program": p, "file": file, "chains": through.get(p, [])}
            for p in report.transitive_programs
            for file in declared(p)
        ]
        duplicated = sorted(
            p
            for p in {*report.direct_programs, *report.transitive_programs}
            if len(files.get(p, [])) > 1
        )
        for program_id in duplicated:
            response.caveat(
                "duplicate-declaration",
                f"PROGRAM-ID {program_id} is declared in "
                f"{', '.join(files[program_id])}",
                "each file is listed on its own; a program name alone does not "
                "say which one runs",
            )
        _notes(
            response,
            "incomplete-analysis",
            [self._relative(note) for note in report.unresolved],
            "programs or fields reached only through what could not be read "
            "are missing",
        )
        return response.build(
            {
                "name": member,
                "kind": "copybook",
                "found": True,
                "resolved_to": [self.workspace.display(p) for p in report.paths],
                "program_count": report.program_count,
                "copied_by": response.cap(direct, cap, "copied_by"),
                "copied_through_other_members": response.cap(
                    nested, cap, "copied_through_other_members"
                ),
                "fields": response.cap(report.fields, cap, "fields"),
                "coverage": _coverage(self.workspace, index),
                **(
                    {
                        "included_by_other_languages": response.cap(
                            self._included_rows(index, included, member),
                            cap,
                            "included_by_other_languages",
                        )
                    }
                    if included
                    else {}
                ),
                "next": "for where one of these fields' values go, ask "
                "impact_of_change with that field and the file of a program "
                "that copies the member",
            }
        )

    def _lineage(
        self,
        field: str,
        file: str | None,
        program: str | None,
        depth: int | None,
        cap: int,
        direction: str,
        full: bool = False,
    ) -> dict[str, Any]:
        from .codebase_index import lineage_index

        if depth is not None and depth < 0:
            raise ToolError("depth must be 0 or more")
        response = Response()
        program_info = None
        programs: list[str] | None = None
        parsed: ParsedProgram | None = None
        if file is not None:
            parsed = self.workspace.program(file)
            program_info = parsed.program_info()
            if program:
                unit = parsed.unit(program, response)
                programs = [unit.program_name or ""]
                program_info = parsed.program_info(unit)
            else:
                programs = [u.program_name or "" for u in parsed.ast.program_units()]
        index = lineage_index(self.workspace)
        _carry_index_caveats(index, response, "field flows")
        if file is None and program:
            # No file, one program: the start is limited to that PROGRAM-ID
            # wherever it is declared, never silently widened to every one.
            chosen = " ".join(program.split()).upper()
            known = {str(p).upper() for p in index.graph.reports}
            if chosen not in known:
                raise ToolError(
                    f"no program under the root has PROGRAM-ID {chosen!r}"
                    + _did_you_mean(chosen, sorted(known))
                )
            programs = [chosen]
        wanted = field.upper().replace(" IN ", " OF ")
        result = index.graph.impact(wanted, programs, direction, depth)
        if not result.start_found:
            names: set[str] = set()
            for program_id, data in index.graph.reports.items():
                if programs and program_id not in {p.upper() for p in programs}:
                    continue
                for item in data.get("items") or []:
                    names.add(str(item.get("qualified_name", "")).split(".")[-1])
            missing: dict[str, Any] = {
                "field": wanted,
                "kind": "field",
                "direction": direction,
                "found": False,
                # Never the very name asked for (#546): it reads as "you
                # meant this". A wrongly qualified name still gets its bare
                # one suggested.
                "suggestions": difflib.get_close_matches(
                    wanted.split(" OF ")[0], sorted(names - {wanted}), n=5
                ),
            }
            if direction == "forward" and self._is_member(wanted, parsed):
                missing["hint"] = (
                    f"{wanted} is a copybook member, not a field: ask "
                    "impact_of_change with it and no file for the programs "
                    "that copy it"
                )
            return response.build(missing, program_info)

        hits = [_hit(hit, index, self.workspace, response) for hit in result.hits]
        hits.sort(
            key=lambda h: (
                _CONFIDENCE_RANK.get(h["confidence"], 9),
                "may_be_overwritten" in h,
                len(h["path"]),
            )
        )
        shown = response.cap(hits, cap, "hits")
        ends = _trail_ends(hits)
        if not full:
            _share_paths(shown)
        reached = set(result.programs) | {p.upper() for p in programs or []}
        for caveat in result.caveats:
            if caveat in result.ambiguous:
                response.caveat(
                    "ambiguous-name",
                    caveat,
                    "every matching field is traced; qualify the name (X OF Y) "
                    "to ask about one of them",
                )
                continue
            response.caveat(
                "incomplete-analysis",
                caveat,
                "a flow past this point is assumed or unknown",
            )
        unjoined = [
            u for u in index.graph.unjoined if u.split(":", 1)[0].upper() in reached
        ]
        if unjoined:
            how = index.jcl_note or (
                "no JCL under the root binds them"
                if not index.jcl_files
                else "the JCL under the root does not bind them"
            )
            _notes(
                response,
                "incomplete-analysis",
                [f"{u} ({how})" for u in unjoined],
                "a flow through these files stops at the program boundary",
            )
        elif index.jcl_note:
            response.caveat("incomplete-analysis", index.jcl_note)
        _notes(
            response,
            "incomplete-analysis",
            [self._relative(p) for p in index.problems],
            "flows through these programs or jobs are missing",
        )
        answer: dict[str, Any] = {
            "field": wanted,
            "kind": "field",
            "direction": direction,
            "found": True,
            "depth": depth,
            "programs": result.programs,
            "tables": result.tables,
            "datasets": result.datasets,
            "hit_count": len(hits),
            "by_confidence": _counts(h["confidence"] for h in hits),
            "may_be_overwritten": sum("may_be_overwritten" in h for h in hits),
            "trail_ends": response.cap(ends, cap, "trail_ends"),
            "hits": shown,
            "notes": list(result.notes),
            "legend": (
                "each hit is a field (or a table column, a dataset byte range, "
                "or the port where a trail ends) with its path from the start, "
                "one step per line; exact hits first. location is the "
                "statement that reaches it (null for a join through a dataset, "
                "table or CALL); derived: the value is computed on the way, "
                "not only copied. may_be_overwritten: a statement replaces "
                "the value on the way, in the same paragraph, before the path "
                "reads it again (a SELECT INTO finding no row or a READ INTO "
                "at end of file would not); such hits come after the others "
                "of their confidence. trail_ends: the hits no other trail runs "
                "through (the "
                + ("ultimate sources" if direction == "backward" else "final receivers")
                + ")."
                + (
                    ""
                    if full
                    else " A hit with from_hit continues hit number from_hit "
                    "(0-based): its path starts with that hit's first "
                    "after_step steps, and only the rest is listed."
                )
            ),
        }
        return response.build(answer, program_info)

    @staticmethod
    def _unit_in(index: Any, file: str) -> str:
        """The program declared in *file* (a PL/I or assembler source)."""
        return next((u.program_id for u in index.units if u.file == file), file)

    def _included_rows(
        self, index: Any, sites: list[dict[str, Any]], member: str
    ) -> list[dict[str, Any]]:
        """One row per PL/I or assembler program including a member, with
        the files under the root that member could be for its language (a
        PL/I ``.inc`` is not the COBOL ``.cpy`` of the same name)."""
        from .languages import member_files

        rows: dict[str, dict[str, Any]] = {}
        found: dict[str, list[str]] = {}
        for site in sites:
            language = site["language"]
            if language not in found:
                found[language] = member_files(self.workspace, language, member)
            row = rows.setdefault(
                site["file"],
                {
                    "program": self._unit_in(index, site["file"]),
                    "file": site["file"],
                    "language": language,
                    "member_files": found[language],
                    "include_sites": [],
                },
            )
            if site.get("line"):
                row["include_sites"].append(
                    {"file": site["file"], "line": site["line"]}
                )
        return list(rows.values())

    def _is_member(self, name: str, parsed: ParsedProgram | None) -> bool:
        """Whether *name* is a copybook member: one *parsed* expanded, or one
        the programs index (only when already built) saw a COPY name."""
        from ..analysis.codebase import _normalize_member

        member = _normalize_member(name)
        if not member or " " in member:
            return False
        if parsed is not None and parsed.source_map:
            expanded = {Path(f).stem.upper() for f, _ in parsed.source_map.values()}
            if member in expanded - {parsed.path.stem.upper()}:
                return True
        built = self.workspace.built_index("programs")
        return built is not None and member in built.graph.members

    # -- codebase_overview ---------------------------------------------------

    def codebase_overview(
        self,
        limit: int | None = None,
        language: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """The programs under the root, how they call each other and share
        copybooks, their health, and the code duplicated between them.
        *language* (COBOL, PL/I, assembler) and *path* (a folder, or a glob
        of root-relative paths) narrow the ``programs`` list; the other
        sections stay root-wide."""
        from .codebase_index import health_index, programs_index

        wanted_language = _language_named(language) if language else None
        cap = clamp_limit(limit)
        top = min(cap, OVERVIEW_TOP)
        response = Response()
        index = programs_index(self.workspace)
        health = health_index(self.workspace)
        _carry_index_caveats(index, response, "programs")
        for caveats in health.file_caveats.values():
            for caveat in caveats:
                if caveat.kind == "analyzer-failed":
                    response.caveat(caveat.kind, caveat.detail, caveat.effect)
        graph = index.graph

        grades = {(u["program"] or "", u["file"]): u for u in health.units}
        callers_of: dict[str, set[str]] = {}
        callees_of: dict[str, set[str]] = {}
        for edge in graph.call_edges:
            callers_of.setdefault(edge.callee, set()).add(edge.caller)
            callees_of.setdefault(edge.caller, set()).add(edge.callee)
        programs = []
        for unit in index.units:
            # The graph's id: a nested program's is qualified (#532). A
            # FACTORY / OBJECT / METHOD-ID unit has no graph node of its
            # own (its CALLs are its class's), so a graph id of the same
            # spelling is a different program, never this unit (#500).
            pid = (
                (unit.graph_id or unit.program_id).upper()
                if unit.is_call_target
                else ""
            )
            graded = grades.get((unit.program_id, unit.file), {})
            row: dict[str, Any] = {
                "program": unit.program_id,
                "file": unit.file,
                "grade": graded.get("grade"),
                "score": graded.get("score"),
                # From the graph, like called_by: a dynamic CALL counts its
                # resolved targets, not the data name it calls through.
                "calls": len(callees_of.get(pid, set())),
                "called_by": len(callers_of.get(pid, set())),
            }
            if unit.depth:
                row["contained"] = True
            if unit.unit_kind != "PROGRAM":
                row["unit_kind"] = unit.unit_kind
            if unit.language != "COBOL":
                row["language"] = unit.language
            if wanted_language is not None and unit.language != wanted_language:
                continue
            if path is not None and not _path_matches(unit.file, path):
                continue
            programs.append(row)

        declared = {
            (u.graph_id or u.program_id).upper()
            for u in index.units
            if u.is_call_target
        }
        external: dict[str, set[str]] = {}
        for edge in graph.call_edges:
            if edge.callee not in declared:
                external.setdefault(edge.callee, set()).add(edge.caller)
        other_sources = self.workspace.other_sources()
        not_parsed = {p: c for p, c in external.items() if p.upper() in other_sources}
        for program_id in not_parsed:
            del external[program_id]
        languages: dict[str, int] = {}
        for _path, language in {
            entry for entries in other_sources.values() for entry in entries
        }:
            languages[language] = languages.get(language, 0) + 1
        most_called = sorted(
            ((p, len(c)) for p, c in callers_of.items() if p in declared),
            key=lambda pc: (-pc[1], pc[0]),
        )
        entry = sorted(
            u.program_id
            for u in index.units
            if not u.depth and u.program_id.upper() not in callers_of
        )
        dynamic = sum(
            1
            for u in index.units
            for row in u.calls
            if row.get("dynamic") and not row.get("candidates_complete")
            for _ in row.get("sites") or []
        )

        usage = sorted(
            (
                (
                    m,
                    len(graph.programs_using(m)),
                    len(graph.programs_using(m, transitive=False)),
                )
                for m in graph.members
            ),
            key=lambda mu: (-mu[1], mu[0]),
        )
        unresolved_members = sorted(
            {e.member for e in graph.copy_edges if e.path is None and not e.nested}
        )

        bands: dict[str, int] = {}
        for graded_unit in health.units:
            grade = graded_unit["grade"] or "ungraded"
            bands[grade] = bands.get(grade, 0) + 1
        worst = sorted(
            (u for u in health.units if u["score"] is not None),
            key=lambda u: (-u["score"], u["program"] or ""),
        )

        by_language: dict[str, int] = {}
        for unit in index.units:
            by_language[unit.language] = by_language.get(unit.language, 0) + 1
        answer: dict[str, Any] = {
            "index": {
                **index.summary(),
                "program_units": len(index.units),
                **(
                    {"program_units_by_language": dict(sorted(by_language.items()))}
                    if set(by_language) != {"COBOL"}
                    else {}
                ),
                **(
                    {"other_sources_not_analyzed": dict(sorted(languages.items()))}
                    if languages
                    else {}
                ),
            },
            **(
                {
                    "programs_filter": {
                        k: v
                        for k, v in (("language", wanted_language), ("path", path))
                        if v
                    },
                    "programs_matched": len(programs),
                }
                if wanted_language or path
                else {}
            ),
            "programs": response.cap(
                sorted(programs, key=lambda r: (r["program"].upper(), r["file"])),
                cap,
                "programs",
            ),
            "call_graph": {
                "edges": len(graph.call_edges),
                "entry_programs": response.cap(entry, cap, "call_graph.entry_programs"),
                "most_called": [
                    {"program": p, "called_by": n} for p, n in most_called[:top]
                ],
                "not_in_workspace": response.cap(
                    [
                        {"program": p, "called_by": sorted(c)}
                        for p, c in sorted(external.items())
                    ],
                    cap,
                    "call_graph.not_in_workspace",
                ),
                "in_workspace_not_analyzed": response.cap(
                    [
                        {
                            "program": p,
                            "called_by": sorted(c),
                            "sources": [
                                {
                                    "file": self.workspace.display(path),
                                    "language": language,
                                }
                                for path, language in other_sources[p.upper()]
                            ],
                        }
                        for p, c in sorted(not_parsed.items())
                    ],
                    cap,
                    "call_graph.in_workspace_not_analyzed",
                ),
                "cycles": response.cap(graph.cycles(), cap, "call_graph.cycles"),
                "unresolved_dynamic_calls": dynamic,
            },
            "copybooks": {
                "members": len(graph.members),
                "most_used": [
                    {"member": m, "programs": n, "copied_directly_by": d}
                    for m, n, d in usage[:top]
                ],
                "not_found": response.cap(
                    unresolved_members, cap, "copybooks.not_found"
                ),
            },
            "health": {
                "grades": dict(sorted(bands.items())),
                "worst": [
                    {k: u[k] for k in ("program", "file", "grade", "score")}
                    for u in worst[:top]
                ],
                "scale": "score 0-100, higher is more technical debt; "
                "A <= 10 < B <= 25 < C <= 45 < D <= 70 < F",
            },
            "duplicated_code": {
                "group_count": len(health.clones),
                "groups": [
                    {
                        **group,
                        "member_count": len(group["members"]),
                        "members": response.cap(
                            group["members"],
                            top,
                            f"duplicated_code.groups[{number}].members",
                        ),
                    }
                    for number, group in enumerate(
                        response.cap(health.clones, top, "duplicated_code.groups")
                    )
                ],
                "ranking": "most duplicated statements first (statements x "
                "copies); a copybook paragraph included by many programs is "
                "one copy",
            },
        }
        _notes(
            response,
            "incomplete-analysis",
            [self._relative(note) for note in graph.unresolved],
            "call and COPY edges near these are missing or only approximately "
            "attributed",
            lead=f"{len(graph.unresolved)} gap(s) in the call and COPY graph",
        )
        if dynamic:
            response.caveat(
                "incomplete-analysis",
                f"{dynamic} dynamic CALL/LINK/XCTL site(s) have targets that "
                "could not all be traced",
                "the call graph may miss edges from them",
            )
        _other_language_caveats(index, response)
        return response.build(answer)

    # -- business_rules ------------------------------------------------------

    def business_rules(
        self,
        file: str,
        program: str | None = None,
        kind: str | None = None,
        procedure: str | None = None,
        include_technical: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """The decisions, validations and calculations *file* implements."""
        from ..analysis.business_rules import RULE_KINDS, BusinessRuleExtractor

        wanted_kind = kind.strip().lower() if kind else None
        if wanted_kind is not None and wanted_kind not in RULE_KINDS:
            raise ToolError(
                f"unknown rule kind {kind!r} (expected one of "
                f"{', '.join(RULE_KINDS)})"
            )
        wanted_procedure = " ".join(procedure.split()).upper() if procedure else None
        parsed = self.workspace.program(file)
        response = Response()
        _carry_parse_caveats(parsed, response)
        unit = parsed.unit(program, response)
        program_info = parsed.program_info(unit)
        name = "rules+technical" if include_technical else "rules"
        report = _attempt(
            response,
            "business rules",
            lambda: parsed.report(
                name,
                unit,
                lambda: BusinessRuleExtractor(
                    include_technical=include_technical
                ).analyze(unit),
            ),
        )
        if report is None:
            return response.build({"found": False, "rules": []}, program_info)
        for caveat in report.caveats:
            response.caveat("incomplete-analysis", caveat)

        rules = [
            rule
            for rule in report.rules
            if (wanted_kind is None or rule.kind == wanted_kind)
            and (
                wanted_procedure is None
                or wanted_procedure
                in {rule.procedure.upper(), (rule.section or "").upper()}
            )
        ]
        cap = clamp_limit(limit)
        shown = response.cap(rules, cap, "rules")
        tested = {name.upper() for rule in shown for name in rule.condition_names}
        answer: dict[str, Any] = {
            "summary": {
                "rules": len(report.rules),
                **{kind: len(report.rules_of_kind(kind)) for kind in RULE_KINDS},
                "technical_rules_excluded": report.technical_rules_excluded,
                "rules_in_dead_code": sum(1 for r in report.rules if r.in_dead_code),
            },
            "rule_count": len(rules),
            "rules": [
                _rule(rule, index, parsed, response, cap)
                for index, rule in enumerate(shown)
            ],
            "condition_names": [
                {"name": c.name, "means": c.condition}
                for c in report.condition_names
                if c.name.upper() in tested
            ],
        }
        if report.technical_rules_excluded and not include_technical:
            answer["note"] = (
                f"{report.technical_rules_excluded} technical rule(s) (FILE "
                "STATUS, end-of-file flags, SQLCODE, EIB fields) are left out; "
                "pass include_technical=true to see them"
            )
        if wanted_procedure is not None and not rules:
            procedures = sorted(
                {r.procedure.upper() for r in report.rules}
                | {(r.section or "").upper() for r in report.rules if r.section}
            )
            answer["suggestions"] = difflib.get_close_matches(
                wanted_procedure, procedures, n=5
            )
        return response.build(answer, program_info)

    # -- diff_programs -------------------------------------------------------

    def diff_programs(
        self,
        old_file: str,
        new_file: str,
        old_program: str | None = None,
        new_program: str | None = None,
        category: str | None = None,
        rename_threshold: float | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """What changed in a program's behaviour between two versions."""
        from ..analysis.ast_diff import ProgramDiffer

        categories = ("program", "file", "data", "procedure")
        wanted = category.strip().lower() if category else None
        if wanted is not None and wanted not in categories:
            raise ToolError(
                f"unknown category {category!r} (expected one of "
                f"{', '.join(categories)})"
            )
        threshold = 0.8 if rename_threshold is None else rename_threshold
        if not 0.0 <= threshold <= 1.0:
            raise ToolError(
                f"rename_threshold must be between 0.0 and 1.0, got {threshold}"
            )
        old = self.workspace.program(old_file)
        new = self.workspace.program(new_file)
        response = Response()
        _carry_parse_caveats(old, response)
        _carry_parse_caveats(new, response)
        old_unit = old.unit(old_program, response)
        new_unit = new.unit(new_program, response)
        answer: dict[str, Any] = {
            "old": old.program_info(old_unit),
            "new": new.program_info(new_unit),
        }
        report = _attempt(
            response,
            "program diff",
            lambda: ProgramDiffer(rename_threshold=threshold).diff(old_unit, new_unit),
        )
        if report is None:
            return response.build(answer)
        for caveat in report.caveats:
            response.caveat("incomplete-analysis", caveat)
        changes = [c for c in report.changes if wanted is None or c.category == wanted]
        shown = response.cap(changes, clamp_limit(limit), "changes")
        answer.update(
            {
                "summary": {
                    "total_changes": report.change_count,
                    "by_category": {
                        key: len(value)
                        for key, value in report.changes_by_category().items()
                    },
                    "by_kind": report.counts_by_kind(),
                },
                "changes": [_change(c, old, new, response) for c in shown],
            }
        )
        if not report.has_changes:
            answer["note"] = (
                "no structural change: the two versions differ at most in "
                "layout, comments, sequence numbers or spacing"
            )
        return response.build(answer)

    # -- decode_record -------------------------------------------------------

    def decode_record(
        self,
        copybook: str,
        data_file: str | None = None,
        record: str | None = None,
        view: str | None = None,
        skip: int = 0,
        max_records: int | None = None,
        fields: list[str] | None = None,
        charset: str | None = None,
        endian: str | None = None,
        record_format: str | None = None,
        record_separator: str | None = None,
        record_length: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """The records of *data_file* read through *copybook*'s layout, or,
        with no data file, the layout's views (its REDEFINES overlays)."""
        from ..generators.data.decoding import RecordDecoder, RecordDecodingError
        from ..generators.data.encoding import RecordFormat
        from ..generators.data.errors import CopybookLayoutError

        if skip < 0:
            raise ToolError("skip cannot be negative")
        if record_length is not None and record_length <= 0:
            raise ToolError("record_length must be a positive number of bytes")
        opts = self._encoding_options(charset, endian, record_format, record_separator)
        path = self.workspace.resolve(copybook)
        source = self.workspace.read_text(path)
        response = Response()
        try:
            with stdout_to_stderr():
                decoder = RecordDecoder.from_copybook_source(
                    source,
                    filename=str(path),
                    record=record,
                    opts=opts,
                    record_length=record_length,
                    copybook_paths=list(self.workspace.config.copybook_path) or None,
                )
        except CopybookLayoutError as exc:
            raise ToolError(self._relative(str(exc))) from exc
        for warning in decoder.layout_warnings:
            response.caveat(
                "unresolved-copybook",
                self._relative(warning),
                "the layout is short by that member's fields: every record "
                "after the first is framed at the wrong offset",
            )
        try:
            chosen = decoder.resolve_view(view)
        except RecordDecodingError as exc:
            raise ToolError(str(exc)) from exc
        views = decoder.views
        cap = clamp_limit(limit)
        placed = list(chosen.fields)
        if fields:
            asked = {" ".join(f.split()).upper() for f in fields}
            placed = [
                p
                for p in placed
                if p.spec.column.upper() in asked or p.spec.name.upper() in asked
            ]
            missing = (
                asked
                - {p.spec.column.upper() for p in placed}
                - {p.spec.name.upper() for p in placed}
            )
            if missing:
                response.caveat(
                    "incomplete-analysis",
                    f"no field of view {chosen.name} is named "
                    f"{_listed(sorted(missing))}",
                    "those fields are not shown",
                )
        shown_fields = response.cap(placed, cap, "fields")
        answer: dict[str, Any] = {
            "copybook": self.workspace.display(path),
            "record_name": views.record_name,
            "record_length": views.base.length,
            "framing_length": views.framing_length,
            "view": chosen.name,
            "views": [
                {
                    "name": v.name,
                    "redefines": v.redefines,
                    "offset": v.offset,
                    "length": v.length,
                }
                for v in views.views
            ],
            "fields": [
                {
                    "name": p.spec.column,
                    "offset": p.offset,
                    "length": p.length,
                    "picture": p.spec.picture,
                    "usage": p.spec.usage or "DISPLAY",
                }
                for p in shown_fields
            ],
        }
        for caveat in views.caveats:
            response.caveat("incomplete-analysis", caveat)
        if data_file is None:
            answer["note"] = (
                "the layout only: pass data_file to read records through it"
            )
            return response.build(answer)

        data_path = self.workspace.resolve(data_file)
        wanted_records = (
            DEFAULT_DECODE_RECORDS if max_records is None else clamp_limit(max_records)
        )
        # Fixed-length records with nothing between them sit at a known
        # stride, so a page past the read window starts by seeking to it.
        # Any other framing has to be walked from the front, and so stops at
        # the window (said below, with no `next` that would ask again).
        stride = 0
        fmt = opts.resolved_format(
            [placed.spec for placed in decoder.views.base.fields],
            varying=decoder.varying is not None,
        )
        if fmt is RecordFormat.FIXED and not opts.record_separator:
            stride = decoder.record_length or decoder.views.framing_length
        start = skip * stride if stride > 0 else 0
        local_skip = 0 if start else skip
        try:
            size = data_path.stat().st_size
            with data_path.open("rb") as handle:
                handle.seek(start)
                data = handle.read(MAX_DECODE_BYTES)
        except OSError as exc:
            raise ToolError(f"cannot read {data_file}: {exc}") from exc
        cut = size > start + len(data)
        try:
            with stdout_to_stderr():
                result = decoder.decode_bytes(
                    data, view=view, max_records=wanted_records, skip=local_skip
                )
        except RecordDecodingError as exc:
            raise ToolError(str(exc)) from exc
        window_spent = cut and len(result.records) < wanted_records
        for caveat in result.caveats:
            if caveat not in decoder.layout_warnings:
                response.caveat("incomplete-analysis", caveat)
        trailing = 0 if cut else len(result.trailing)
        more = result.bytes_read + len(result.trailing) < len(data) or cut
        if trailing:
            response.caveat(
                "incomplete-analysis",
                f"{trailing} trailing byte(s) are not a whole record",
                "the record length or record format is probably wrong: check "
                "record_length / record_format before trusting the values",
            )
        if window_spent:
            response.caveat(
                "incomplete-analysis",
                f"only {MAX_DECODE_BYTES} bytes of {data_file} ({size} bytes) "
                "are read per call, and under this record format each read "
                "starts at the front of the file: records past "
                f"byte {start + len(data)} cannot be reached",
                "decode a smaller extract of the file, or read it as fixed-"
                "length records with no separator if that is what it holds",
            )
        names = {p.spec.column for p in shown_fields}
        records = []
        for decoded in result.records:
            values = {f.name: f.value for f in decoded.fields if f.name in names}
            entry: dict[str, Any] = {
                "index": decoded.index + (skip if start else 0),
                "file_offset": decoded.file_offset + start,
                "length": decoded.length,
                "values": values,
            }
            absent = [
                f.name for f in decoded.fields if f.name in names and not f.present
            ]
            if absent:
                entry["absent"] = absent
            if decoded.errors:
                entry["errors"] = decoded.errors
            records.append(entry)
        answer.update(
            {
                "data_file": self.workspace.display(data_path),
                "file_bytes": size,
                "skip": skip,
                "record_count": len(records),
                "more_records": more,
                "error_count": result.error_count,
                "records": records,
            }
        )
        if more and not window_spent:
            answer["next"] = (
                f"more records follow: ask again with skip={skip + len(records)}"
            )
        return response.build(answer)

    def _encoding_options(
        self,
        charset: str | None,
        endian: str | None,
        record_format: str | None,
        record_separator: str | None,
    ) -> Any:
        """The EncodingOptions a data file is read through: each argument,
        else ``cobol.yml``'s ``data:`` section, else the built-in default."""
        from ..generators.data.encoding import (
            Charset,
            EncodingOptions,
            Endian,
            RecordFormat,
        )

        data = self.workspace.config.data
        chosen = {
            "charset": (charset or data.charset or "ascii").lower(),
            "endian": (endian or data.endian or "auto").lower(),
            "record_format": (record_format or data.record_format or "fixed").lower(),
            "record_separator": (
                record_separator or data.record_separator or "none"
            ).lower(),
        }
        if chosen["record_separator"] not in ("none", "newline"):
            raise ToolError(
                f"unknown record_separator {chosen['record_separator']!r} "
                "(expected none or newline)"
            )
        try:
            return EncodingOptions(
                charset=Charset(chosen["charset"]),
                endian=Endian(chosen["endian"]),
                record_format=RecordFormat(chosen["record_format"]),
                record_separator=(
                    b"\n" if chosen["record_separator"] == "newline" else b""
                ),
            )
        except ValueError as exc:
            raise ToolError(f"bad encoding option: {exc}") from exc

    # -- JCL (the [jcl] extra; implemented in .jcl_tools) --------------------

    # -- navigation ---------------------------------------------------------

    def read_procedure(
        self, file: str, name: str, program: str | None = None
    ) -> dict[str, Any]:
        """One paragraph or section of *file*, whole (:mod:`.navigation`)."""
        from .navigation import read_procedure

        return read_procedure(self.workspace, file, name, program)

    def slice(
        self,
        file: str,
        field: str,
        direction: str = "backward",
        program: str | None = None,
        limit: int | None = None,
        aliases: bool = False,
    ) -> dict[str, Any]:
        """The statements that can affect *field*, or that it affects, in
        one program (:mod:`.slicing`)."""
        from .slicing import slice_field

        return slice_field(
            self.workspace, file, field, direction, program, limit, aliases
        )

    def check_claims(self, claims: list[dict[str, Any]]) -> dict[str, Any]:
        """Each claim confirmed, contradicted or not checkable
        (:mod:`.claims`)."""
        from .claims import check_claims

        return check_claims(self, claims)

    def find_statements(
        self,
        verb: str | None = None,
        operand: str | None = None,
        role: str | None = None,
        literal: str | None = None,
        paragraph: str | None = None,
        file: str | None = None,
        program: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Statements by verb / operand / literal / paragraph
        (:mod:`.navigation`)."""
        from .navigation import find_statements

        return find_statements(
            self.workspace,
            verb,
            operand,
            role,
            literal,
            paragraph,
            file,
            program,
            limit,
        )

    def jcl_job(
        self,
        file: str,
        job: str | None = None,
        step: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """One JCL file's jobs, steps and DD statements, cited on disk."""
        from .jcl_tools import jcl_job

        return jcl_job(self.workspace, file, job, step, limit)

    def jobs_running(
        self, program: str, limit: int | None = None, follow_calls: bool = False
    ) -> dict[str, Any]:
        """Every JCL step under the root that runs *program*, each of its
        ``SELECT`` files bound to a DD and a dataset; with *follow_calls*,
        the programs it CALLs in turn, in any language."""
        from .jcl_tools import jobs_running

        return jobs_running(self.workspace, program, limit, follow_calls)

    def dataset_users(self, dataset: str, limit: int | None = None) -> dict[str, Any]:
        """Every job, step and program under the root that uses *dataset*."""
        from .jcl_tools import dataset_users

        return dataset_users(self.workspace, dataset, limit)

    # -- gen_fixtures --------------------------------------------------------

    def gen_fixtures(
        self,
        file: str,
        program: str | None = None,
        mode: str = "happy",
        seed: int | None = None,
        rows: int | None = None,
        scenario: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Test data for *file*: one scenario per path ``mode`` asks for,
        each with the values every mocked boundary supplies and what to
        assert afterwards."""
        from ..analysis.boundary_inventory import BoundaryInventoryAnalyzer
        from ..generators.data.options import DataGeneratorOptions
        from ..generators.data.program_layout import ProgramLayoutIndex
        from ..generators.program_fixtures import ProgramFixtureGenerator

        modes = ("happy", "branches", "all")
        chosen_mode = (mode or "happy").strip().lower()
        if chosen_mode not in modes:
            raise ToolError(
                f"unknown mode {mode!r} (expected one of {', '.join(modes)})"
            )
        row_count = DEFAULT_FIXTURE_ROWS if rows is None else rows
        if not 0 <= row_count <= MAX_FIXTURE_ROWS:
            raise ToolError(f"rows must be between 0 and {MAX_FIXTURE_ROWS}")
        bundle_seed = seed if seed is not None else (self.workspace.config.seed or 0)
        parsed = self.workspace.program(file)
        response = Response()
        _carry_parse_caveats(parsed, response)
        unit = parsed.unit(program, response)
        program_info = parsed.program_info(unit)
        callee_dirs = self.workspace.callee_directories(response)

        refused_callees: list[str] = []

        def accept(found: str) -> bool:
            # The directory is under the root, but a member of it may be a
            # link out of it: vetted like every other file a tool opens.
            if self.workspace.under_root(Path(found)):
                return True
            refused_callees.append(found)
            return False

        def build() -> Any:
            generator = ProgramFixtureGenerator(DataGeneratorOptions(rows=row_count))
            index = ProgramLayoutIndex.build(unit)
            callee_indexes, callee_asts = generator._resolve_callees(
                unit,
                callee_dirs or None,
                debug_lines=bool(self.workspace.config.debug_lines),
                accept=accept,
            )
            report = BoundaryInventoryAnalyzer().analyze(
                unit, index, callee_indexes=callee_indexes, callee_asts=callee_asts
            )
            return generator.generate_with_scenarios(
                unit, index, report, mode=chosen_mode, seed=bundle_seed
            )

        bundle = _attempt(response, "test fixtures", build)
        if refused_callees:
            response.caveat(
                "incomplete-analysis",
                "callee files that resolve outside the workspace were not read: "
                + ", ".join(
                    sorted(
                        {
                            Path(os.path.relpath(f, self.workspace.root)).as_posix()
                            for f in refused_callees
                        }
                    )
                ),
                "CALL arguments to those programs are classified without the "
                "callee's own PROCEDURE DIVISION USING",
            )
        if bundle is None:
            return response.build({"found": False, "scenarios": []}, program_info)
        cap = clamp_limit(limit)
        if bundle.unresolved:
            _notes(
                response,
                "incomplete-analysis",
                [self._relative(note) for note in bundle.unresolved],
                "the fixtures for these boundaries are partial or missing",
                lead=f"{len(bundle.unresolved)} item(s) could not be resolved",
            )
        scenarios = list(bundle.scenarios)
        if scenario:
            wanted = scenario.strip().lower()
            scenarios = [s for s in scenarios if wanted in s.name.lower()]
        shown = response.cap(scenarios, cap, "scenarios")
        answer: dict[str, Any] = {
            "program_id": bundle.program_name,
            "mode": chosen_mode,
            "seed": bundle.seed,
            "bundle_version": bundle.bundle_version,
            "rows_per_sequence": row_count,
            "coverage": bundle.coverage.to_dict(),
            "scenario_count": len(bundle.scenarios),
            "scenarios": [
                _scenario(s, i, parsed, response, cap) for i, s in enumerate(shown)
            ],
            "replay": (
                f"the same file, mode and seed ({bundle.seed}) give the same "
                "data; cobol-parser gen-fixtures writes the bundle to disk "
                "(JSON or one CSV per boundary)"
            ),
        }
        if bundle.scenario_coverage is not None:
            answer["arm_coverage"] = _arm_coverage(
                bundle.scenario_coverage, parsed, response, cap
            )
        if scenario and not scenarios:
            answer["suggestions"] = difflib.get_close_matches(
                scenario, [s.name for s in bundle.scenarios], n=5
            )
        return response.build(answer, program_info)


_T = TypeVar("_T")


def _attempt(response: Response, what: str, build: Callable[[], _T]) -> _T | None:
    """*build()*, or None with an ``analyzer-failed`` caveat when it raises.

    A brief joins several analyzers; one that fails must not sink the rest.
    """
    try:
        with stdout_to_stderr():
            return build()
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001 -- reported, never swallowed
        response.caveat(
            "analyzer-failed",
            f"{what} could not be analyzed: {exc}",
            f"the answer has no {what} section",
        )
        return None


def _flow(parsed: ParsedProgram, unit: CobolProgram) -> Any:
    from ..analysis.program_flow import ProgramFlowAnalyzer

    return parsed.report("flow", unit, lambda: ProgramFlowAnalyzer().analyze(unit))


@dataclass(frozen=True)
class _Reachability:
    """Which procedures of a unit can run, and which fall-throughs happen."""

    #: Procedure keys (``X OF S`` when the name repeats) control never reaches.
    unreachable: list[str]
    #: Upper-cased ``(from, to)`` keys of the fall-throughs that can happen.
    fall_throughs: frozenset[tuple[str, str]]


def _reachability(
    parsed: ParsedProgram, unit: CobolProgram, response: Response
) -> _Reachability | None:
    """DeadCodeAnalyzer's reachability for *unit*, memoized beside the parse.

    The root-based fixpoint the OKF calls authoritative (issue #486), rather
    than ``ProgramFlowAnalyzer.unreachable_nodes``. None, with an
    ``analyzer-failed`` caveat, when the analyzer raises: callers then fall
    back to the flow graph's answer.
    """
    from ..analysis.dead_code import DeadCodeAnalyzer

    def build() -> _Reachability:
        report = DeadCodeAnalyzer().analyze(unit)
        return _Reachability(
            unreachable=[
                item.qualified_name or item.name for item in report.dead_items
            ],
            fall_throughs=frozenset(
                (source.upper(), target.upper())
                for source, target in report.fall_through_edges
            ),
        )

    return _attempt(
        response,
        "reachability",
        lambda: parsed.report("reachability", unit, build),
    )


def _signature(parsed: ParsedProgram, unit: CobolProgram) -> Any:
    from ..analysis.program_signature import ProgramSignatureExtractor

    return parsed.report(
        "signature", unit, lambda: ProgramSignatureExtractor().analyze(unit)
    )


def _crud(parsed: ParsedProgram, unit: CobolProgram) -> Any:
    from ..analysis.crud_matrix import CRUDMatrixGenerator

    return parsed.report("crud", unit, lambda: CRUDMatrixGenerator().analyze(unit))


def _debt(parsed: ParsedProgram, unit: CobolProgram) -> Any:
    from ..analysis.technical_debt import TechnicalDebtAnalyzer

    return parsed.report("debt", unit, lambda: TechnicalDebtAnalyzer().analyze(unit))


def _file_facts(parsed: ParsedProgram, unit: CobolProgram) -> dict[str, Any]:
    """Every FD/SD's facts (organization, keys, records), by upper-cased name."""
    from ..generators.data.program_layout import ProgramLayoutIndex

    def build() -> dict[str, Any]:
        index = ProgramLayoutIndex.build(unit)
        facts: dict[str, Any] = {}
        for name in index.file_names():
            fact = index.file_facts(name)
            if fact is not None:
                facts[name.upper()] = fact
        return facts

    result: dict[str, Any] = parsed.report("file-facts", unit, build)
    return result


def _calls(
    parsed: ParsedProgram, unit: CobolProgram, flow: Any, response: Response
) -> list[dict[str, Any]]:
    """Every program *unit* CALLs (or LINKs/XCTLs to), one row per target."""
    from ..analysis.value_tracker import DynamicCallAnalyzer

    rows: dict[tuple[str, str], dict[str, Any]] = {}
    tracker: DynamicCallAnalyzer | None = None
    for call in flow.external_calls:
        target = str(call.get("program") or "")
        dynamic = bool(call.get("is_dynamic"))
        row = rows.get((target.upper(), "CALL"))
        if row is None:
            row = {"program": target, "via": "CALL", "dynamic": dynamic, "sites": []}
            if dynamic:
                if tracker is None:
                    tracker = DynamicCallAnalyzer()
                    tracker.analyze(unit)
                values, incomplete = tracker.resolve_variable(target)
                row["candidates"] = values
                row["candidates_complete"] = bool(values) and not incomplete
                nested = [v for v in values if unit.nested_program_called(v)]
                if nested:
                    row["nested_candidates"] = nested
            elif unit.nested_program_called(target) is not None:
                # COBOL scope: the CALL reaches the program nested here,
                # not a separately compiled one of that name (#532).
                row["nested"] = True
            rows[(target.upper(), "CALL")] = row
        location = call.get("location")
        line = location.get("line") if isinstance(location, dict) else None
        row["sites"].append(
            {
                "paragraph": call.get("called_from"),
                "location": parsed.locate(line, None, response),
            }
        )
    for statement in _own_statements(unit):
        if getattr(statement, "node_type", None) != "EXEC_CICS":
            continue
        cics: Any = statement
        command = (cics.cics_command or "").upper()
        linked = (cics.options or {}).get("PROGRAM")
        if command not in ("LINK", "XCTL") or not linked:
            continue
        literal = "PROGRAM" in cics.literal_options
        row = rows.get((linked.upper(), command))
        if row is None:
            row = {
                "program": linked,
                "via": f"EXEC CICS {command}",
                "dynamic": not literal,
                "sites": [],
            }
            if not literal:
                if tracker is None:
                    tracker = DynamicCallAnalyzer()
                    tracker.analyze(unit)
                values, incomplete = tracker.resolve_variable(linked)
                row["candidates"] = values
                row["candidates_complete"] = bool(values) and not incomplete
            rows[(linked.upper(), command)] = row
        row["sites"].append(
            {"location": parsed.locate(cics.location.line, None, response)}
        )
    declared = frozenset(unit.user_function_names())
    if declared:
        # FUNCTION name(...) of a user-defined function the REPOSITORY
        # paragraph declares: control passes to that FUNCTION-ID unit.
        from ..analysis.language_env_analyzer import function_references

        for statement in _own_statements(unit):
            for name in function_references(statement, declared):
                if name not in declared:
                    continue
                row = rows.get((name, "FUNCTION"))
                if row is None:
                    row = rows[(name, "FUNCTION")] = {
                        "program": name,
                        "via": "FUNCTION",
                        "dynamic": False,
                        "sites": [],
                    }
                line = statement.location.line if statement.location else None
                row["sites"].append({"location": parsed.locate(line, None, response)})
    return list(rows.values())


def _own_statements(unit: CobolProgram) -> list[Any]:
    """*unit*'s statements without those of the programs it contains.

    ``get_all_statements()`` walks into nested programs and OO methods;
    a brief of the outer unit must not count theirs.
    """
    nested = {
        id(statement)
        for contained in unit.contained_programs
        for statement in contained.get_all_statements()
    }
    return [s for s in unit.get_all_statements() if id(s) not in nested]


def _verb_counts(
    statements: list[Any], node_type: str, attribute: str
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for statement in statements:
        if getattr(statement, "node_type", None) == node_type:
            verb = (getattr(statement, attribute, "") or "?").upper()
            counts[verb] = counts.get(verb, 0) + 1
    return dict(sorted(counts.items()))


def _edge_caller(
    edge: Any, parsed: ParsedProgram, response: Response
) -> dict[str, Any]:
    caller: dict[str, Any] = {
        "from": edge.source,
        "type": edge.edge_type.value,
        "location": parsed.locate(edge.location.line, None, response),
    }
    if edge.perform_type and edge.perform_type != "SIMPLE":
        caller["perform_type"] = edge.perform_type
    if edge.condition:
        caller["condition"] = edge.condition
    if edge.is_loop:
        caller["loop"] = True
    if edge.thru_target:
        caller["thru"] = edge.thru_target
    return caller


@dataclass
class _FoundItem:
    """A data item, the 01/77 record it lies in, and its section."""

    item: CobolDataItem
    root: CobolDataItem
    section: str
    #: Names from the record down to the item, as layouts name them.
    path: tuple[str, ...]


def _walk_data_items(unit: CobolProgram) -> Iterator[_FoundItem]:
    data = unit.get_division("DATA")
    if data is None:
        return
    for name in _DATA_SECTIONS:
        section = data.get_section_by_name(name)
        if not isinstance(section, CobolSection):
            continue
        for root in section.data_items:
            stack: list[tuple[CobolDataItem, tuple[str, ...]]] = [(root, (root.name,))]
            while stack:
                item, path = stack.pop()
                yield _FoundItem(item, root, name, path)
                children = [
                    c
                    for c in item.children
                    if isinstance(c, CobolDataItem) and c.level != 77
                ]
                for child in reversed(children):
                    stack.append((child, (*path, child.layout_name)))


def _data_items_named(unit: CobolProgram, wanted: str) -> list[_FoundItem]:
    """Data items named *wanted* (``X`` or ``X OF Y [OF Z]``), groups first."""
    parts = [p.strip() for p in wanted.split(" OF ")]
    name, qualifiers = parts[0], parts[1:]
    found = []
    for candidate in _walk_data_items(unit):
        if candidate.item.name.upper() != name:
            continue
        ancestors = {p.upper() for p in candidate.path[:-1]}
        if all(q in ancestors for q in qualifiers):
            found.append(candidate)
    return found


def _record_layout(root: CobolDataItem, response: Response) -> list[dict[str, Any]]:
    """*root*'s byte layout, with what it cannot vouch for (``SYNCHRONIZED``
    slack, partial level-88 values) flagged and carried as caveats -- the
    same flags ``data-items`` reports (#488)."""
    from ..generators.data.layout_offsets import (
        compute_record_layout,
        flag_record_layout,
    )

    layout = compute_record_layout(root)
    for line in flag_record_layout(root, layout):
        response.caveat("incomplete-analysis", line, _unresolved_layout_effect(line))
    return [item.to_dict() for item in layout]


def _declarations(root: CobolDataItem) -> dict[str, list[tuple[int, Any]]]:
    """Each layout qualified name -> (source order, location) per declaration.

    FILLER repeats a qualified name; the layout lists same-named entries in
    source order, so the n-th layout entry of a name is its n-th
    declaration. The layout emits a group after its members, so the order
    is what puts the fields back in the order they are written.
    """
    out: dict[str, list[tuple[int, Any]]] = {}
    order = itertools.count()

    def add(qualified: str, location: Any) -> None:
        out.setdefault(qualified, []).append((next(order), location))

    def walk(item: CobolDataItem, path: tuple[str, ...]) -> None:
        qualified = ".".join(path)
        add(qualified, item.location)
        for child in item.children:
            if isinstance(child, ConditionNameItem):
                add(f"{qualified}.{child.name}", child.location)
            elif isinstance(child, CobolDataItem) and child.level != 77:
                walk(child, (*path, child.layout_name))

    walk(root, (root.name,))
    return out


def _layout_answer(
    found: _FoundItem,
    layout: list[dict[str, Any]],
    parsed: ParsedProgram,
    response: Response,
    cap: int,
    index: int,
) -> dict[str, Any]:
    prefix = ".".join(found.path)
    declared = _declarations(found.root)
    used: dict[str, int] = {}
    own: dict[str, Any] | None = None
    fields: list[tuple[int, dict[str, Any]]] = []
    for entry in layout:
        qualified = str(entry["qualified_name"])
        n = used.get(qualified, 0)
        used[qualified] = n + 1
        if qualified != prefix and not qualified.startswith(prefix + "."):
            continue
        declarations = declared.get(qualified, [])
        order, location = (
            declarations[n] if n < len(declarations) else (len(layout), None)
        )
        row = {
            key: entry.get(key)
            for key in (
                "level",
                "name",
                "picture",
                "usage",
                "byte_offset",
                "byte_length",
                "offset_ambiguous",
                "occurs",
                "redefines_chain",
                "condition_values",
                "condition_ranges",
            )
            if _worth_showing(entry.get(key))
        }
        row["declared_at"] = (
            parsed.locate(location.line, location.column, response)
            if location is not None
            else None
        )
        if qualified == prefix and own is None:
            own = row
        else:
            fields.append((order, row))
    own = own or {}
    record: dict[str, Any] = {
        "name": found.item.name,
        "qualified_name": " OF ".join(reversed(found.path)),
        "section": found.section,
        "level": found.item.level,
        "declared_at": own.get("declared_at"),
        "byte_offset": own.get("byte_offset"),
        "byte_length": own.get("byte_length"),
    }
    if found.item is found.root and found.root.redefines:
        record["redefines"] = found.root.redefines
    elif own.get("redefines_chain"):
        record["redefines_chain"] = own["redefines_chain"]
    if own.get("offset_ambiguous"):
        record["offset_ambiguous"] = True
    ordered = [row for _, row in sorted(fields, key=lambda pair: pair[0])]
    record["field_count"] = len(ordered)
    record["fields"] = response.cap(ordered, cap, f"records[{index}].fields")
    return record


def _run_lint(
    parsed: ParsedProgram, analyzer: Any, response: Response
) -> tuple[Any, list[Any]]:
    """Lint the whole file: the report and its findings, worst first.

    Worst first, then source order, so a list cut to a limit keeps the
    errors. Failed rules and the report's own caveats go on *response*.
    """
    from ..analysis.lint import SEVERITIES, add_parse_errors

    with stdout_to_stderr():
        report = analyzer.analyze(
            parsed.ast, copybook_item_names=_copybook_item_names(parsed)
        )
    add_parse_errors(report, list(parsed.result.errors))
    for failure in report.failed_rules:
        response.caveat(
            "analyzer-failed",
            f"lint rule {failure['rule']} did not run: {failure['error']}",
            f"no {failure['rule']} findings are reported",
        )
    for caveat in report.caveats:
        response.caveat("incomplete-analysis", caveat)
    rank = {name: i for i, name in enumerate(SEVERITIES)}
    ordered = sorted(
        enumerate(report.findings), key=lambda pair: (rank[pair[1].severity], pair[0])
    )
    return report, [f for _, f in ordered]


def _lint_summary(findings: list[Any]) -> dict[str, int]:
    from ..analysis.lint import SEVERITIES

    summary = {"total": len(findings)}
    for name in SEVERITIES:
        summary[name] = sum(1 for f in findings if f.severity == name)
    return summary


def _finding(f: Any, parsed: ParsedProgram, response: Response) -> dict[str, Any]:
    return {
        "rule": f.rule,
        "severity": f.severity,
        "message": f.message,
        "symbol": f.symbol,
        "kind": f.kind,
        "location": parsed.locate(
            f.location.line if f.location else None,
            f.location.column if f.location else None,
            response,
            column_known=f.column_known,
        ),
    }


def _copybook_item_names(parsed: ParsedProgram) -> set[str] | None:
    """Upper-cased names of data items declared only inside a COPY member.

    What lets lint grade an unused copybook field (every SQLCA field a
    program never reads) as info rather than warning, as the ``lint`` CLI
    does. The CLI finds them by diffing an unexpanded parse; the source map
    already says which file each declaration came from, so no second parse
    is needed. A name the program also declares itself is the program's.
    ``None`` -- "not known" -- when nothing was expanded.
    """
    from ..analysis.unused_variables import collect_declared_items

    if parsed.source_map is None:
        return None
    main = str(parsed.path)
    copied: set[str] = set()
    local: set[str] = set()
    for unit in parsed.ast.program_units():
        for item in collect_declared_items(unit):
            location = getattr(item, "location", None)
            origin = parsed.source_map.get(location.line) if location else None
            if origin is None:
                continue
            (local if origin[0] == main else copied).add(item.name.upper())
    return copied - local


def _worth_showing(value: Any) -> bool:
    """A layout value that says something: not absent, empty or ``False``.

    ``byte_offset`` 0 is information; ``0 in (None, [], False)`` is True.
    """
    return value is not None and value is not False and value != []


def _install_note(path: Path) -> str:
    """How to have *path* analyzed, when only a missing parser stops it."""
    from .languages import install_hint, language_of

    language = language_of(path)
    return (
        ""
        if language is None
        else f" (or install its parser: {install_hint(language)})"
    )


def _other_language_caveats(index: Any, response: Response) -> None:
    """What the programs index could not read of the PL/I and assembler
    sources under the root, and what it read of them only in part."""
    from .languages import LIMITS, install_hint

    for language, files in sorted(index.not_installed.items()):
        response.caveat(
            "incomplete-analysis",
            f"{len(files)} {language} file(s) under the root were not read: "
            f"the {language} parser is not installed ({install_hint(language)})",
            "CALLs from them are missing; CALLs to them count as "
            "in_workspace_not_analyzed",
        )
    for language in sorted(index.other_language_files):
        response.caveat(
            "incomplete-analysis",
            f"{index.other_language_files[language]} {language} file(s) read "
            f"through a sibling parser: {LIMITS[language]}",
            f"{language} programs are in the call graph, but have no health "
            "grade, no field lineage and no file I/O",
        )


def _carry_index_caveats(index: Any, response: Response, what: str) -> None:
    """A root-wide index's gaps, as a few caveats rather than one per file."""
    if index.failed:
        _notes(
            response,
            "incomplete-analysis",
            [f"{file}: {why}" for file, why in sorted(index.failed.items())],
            f"{what} in the program files that could not be parsed are missing",
            lead=f"{len(index.failed)} program file(s) could not be parsed",
        )
    by_kind: dict[str, list[str]] = {}
    for file, caveats in sorted(index.file_caveats.items()):
        for caveat in caveats:
            by_kind.setdefault(caveat.kind, []).append(file)
    effects = {
        "partial-parse": f"{what} in the statements that did not parse are missing",
        "unresolved-copybook": f"{what} in the members that were not expanded "
        "are missing",
        "analyzer-failed": f"{what} from those files are missing",
    }
    for kind, effect in effects.items():
        files = sorted(set(by_kind.get(kind, [])))
        if files:
            response.caveat(
                kind,
                f"{len(files)} program file(s): {_listed(files)}",
                effect,
            )


def _coverage(workspace: Workspace, index: Any) -> dict[str, Any]:
    """What a root-wide answer looked through: the source files read, by
    language, and the sources under the root no parser here reads. So an
    empty or short list can be taken at its word, or not."""
    read: dict[str, set[str]] = {}
    for unit in index.units:
        if unit.language != "COBOL":
            read.setdefault(unit.language, set()).add(unit.file)
    others = set().union(*read.values()) if read else set()
    read["COBOL"] = set(index.files) - others
    out: dict[str, Any] = {
        "files_read": {lang: len(files) for lang, files in sorted(read.items())}
    }
    skipped: dict[str, set[str]] = {}
    for entries in workspace.other_sources().values():
        for path, language in entries:
            skipped.setdefault(language, set()).add(str(path))
    if skipped:
        out["files_not_analyzed"] = {
            lang: len(paths) for lang, paths in sorted(skipped.items())
        }
    if index.failed:
        out["files_failed"] = len(index.failed)
    return out


#: Spellings a ``language`` argument may use, upper-cased.
_LANGUAGE_NAMES = {
    "COBOL": "COBOL",
    "CBL": "COBOL",
    "PL/I": "PL/I",
    "PLI": "PL/I",
    "PL1": "PL/I",
    "PL/1": "PL/I",
    "ASSEMBLER": "assembler",
    "ASM": "assembler",
    "HLASM": "assembler",
}


def _language_named(text: str) -> str:
    """The language *text* names, as answers spell it."""
    found = _LANGUAGE_NAMES.get(text.strip().upper())
    if found is None:
        raise ToolError(f"unknown language {text!r}: give COBOL, PL/I or assembler")
    return found


def _path_matches(file: str, pattern: str) -> bool:
    """Whether root-relative *file* is under folder *pattern*, or matches it
    as a glob (``*``, ``?``, ``[...]``)."""
    import fnmatch

    wanted = pattern.strip().strip("/").replace("\\", "/")
    if any(c in wanted for c in "*?["):
        return fnmatch.fnmatchcase(file, wanted) or fnmatch.fnmatchcase(
            file.lower(), wanted.lower()
        )
    return file == wanted or file.startswith(wanted + "/")


def _top_folder(file: str) -> str:
    """The first folder of a root-relative *file*, "" for one at the root."""
    head, sep, _rest = file.partition("/")
    return head if sep else ""


def _notes(
    response: Response,
    kind: str,
    notes: list[str],
    effect: str,
    lead: str | None = None,
) -> None:
    """Many notes as one caveat: the first few in full, then a count."""
    if not notes:
        return
    detail = _listed(notes, separator="; ")
    response.caveat(kind, f"{lead}: {detail}" if lead else detail, effect)


def _declared_elsewhere(
    answer: dict[str, Any],
    parsed: ParsedProgram,
    unit: CobolProgram,
    declares: Callable[[CobolProgram], bool],
) -> None:
    """Name the other program units of *parsed* that *declares*, on a
    not-found *answer* about *unit*.

    A tool answers about one unit (the outermost by default), so a name
    declared only in a nested or stacked program reads as missing; the
    answer says where it is rather than leave "not found" to stand.
    """
    others = []
    for other in parsed.ast.program_units():
        if other is unit:
            continue
        try:
            with stdout_to_stderr():
                found = declares(other)
        except Exception:  # noqa: BLE001 -- only a hint; never fail the answer
            continue
        if found:
            others.append(other.program_name or "<unnamed>")
    if others:
        answer["declared_in_program_units"] = others
        answer["hint"] = (
            f"not in {unit.program_name or '<unnamed>'}, but declared in "
            f"{', '.join(others)} of this file: pass program= to ask about it"
        )


def _did_you_mean(wanted: str, names: list[str]) -> str:
    """`` (did you mean X, Y?)`` for an error message, or ``""``."""
    close = difflib.get_close_matches(wanted, names, n=3)
    return f" (did you mean {', '.join(close)}?)" if close else ""


def _listed(items: list[str], separator: str = ", ") -> str:
    shown = separator.join(items[:NOTES_SHOWN])
    if len(items) > NOTES_SHOWN:
        shown += f"{separator}and {len(items) - NOTES_SHOWN} more"
    return shown


def _hit(
    hit: Any, index: Any, workspace: Workspace, response: Response
) -> dict[str, Any]:
    """One lineage hit: where the value arrives, and the steps between.

    Each step is one line of text naming the node, the statement and its
    ``file:line``: a path can run to a dozen steps, and fifty hits of
    nested objects would spend a model's context on punctuation.
    """
    steps = []
    arrived: dict[str, Any] | None = None
    for hop in hit.path:
        location = _hop_location(hop, index, response, workspace)
        how = hop.statement or hop.kind
        if location is not None:
            how += f" at {location['file']}:{location['line']}"
        if hop.confidence != "exact":
            how += f", {hop.confidence}"
        steps.append(f"{hop.label} ({how})")
        arrived = location
    entry: dict[str, Any] = {
        "program": hit.program,
        "field": hit.field,
        "node_kind": hit.node_kind,
        "derived": hit.derived,
        "confidence": hit.confidence,
    }
    if hit.program:
        entry["file"] = index.program_files.get(hit.program.upper())
    entry["location"] = arrived
    entry["path"] = steps
    overwritten = []
    for kill in getattr(hit, "overwritten", ()):
        if kill.origin_file:
            file = workspace.display(kill.origin_file)
        else:
            file = index.program_files.get(kill.program.upper())
        where = f" at {file}:{kill.line}" if file else ""
        overwritten.append(f"{kill.field} by {kill.statement}{where}")
    if overwritten:
        entry["may_be_overwritten"] = overwritten
    return entry


#: Hits are listed most certain first.
_CONFIDENCE_RANK = {"exact": 0, "overlap": 1, "candidate": 2, "opaque": 3}


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _step_node(step: str) -> str:
    """The node a ``NODE (STATEMENT at file:line)`` step names."""
    return step.split(" (", 1)[0]


def _trail_ends(hits: list[dict[str, Any]]) -> list[str]:
    """The hits no other hit's trail passes through: where each trail
    really ends, rather than every field on the way."""
    passed: set[str] = set()
    for hit in hits:
        passed.update(_step_node(step) for step in hit["path"][:-1])
    ends: list[str] = []
    for hit in hits:
        if not hit["path"]:
            continue
        node = _step_node(hit["path"][-1])
        if node not in passed and node not in ends:
            ends.append(node)
    return ends


def _share_paths(hits: list[dict[str, Any]]) -> None:
    """Shorten each hit's ``path`` to what it adds to an earlier hit's.

    A backward trail through three programs reaches a dozen fields, each
    hit repeating every step before it; the repeats were most of a 40 KB
    answer. A hit whose path begins with at least two steps of an earlier
    one names it (``from_hit``, ``after_step``) and lists only the rest.
    """
    full = [list(h["path"]) for h in hits]
    for i, hit in enumerate(hits):
        best, best_len = None, 1
        for j in range(i):
            common = 0
            for a, b in zip(full[i], full[j], strict=False):
                if a != b:
                    break
                common += 1
            if common > best_len:
                best, best_len = j, common
        if best is not None:
            hit["from_hit"] = best
            hit["after_step"] = best_len
            hit["path"] = full[i][best_len:]


def _hop_location(
    hop: Any, index: Any, response: Response, workspace: Workspace
) -> dict[str, Any] | None:
    """Where one hop's statement is, or None for a join (no line of its own)."""
    if not hop.line or not hop.program:
        return None
    program = hop.program.upper()
    origin = getattr(hop, "origin_file", None)
    if origin:
        # The hop's own edge says which file its line is in (#489): a
        # copybook line and a program line of one number never collide.
        return {"file": workspace.display(origin), "line": hop.line}
    key = (program, hop.line, hop.kind, hop.statement)
    file = index.edge_files.get(key)
    if file is None and key not in index.edge_files and program not in index.expanded:
        file = index.program_files.get(program)
    if file is None:
        response.caveat(
            "unmapped-location",
            "some locations could not be traced back to a file on disk "
            "and are reported as null",
        )
        return None
    return {"file": file, "line": hop.line}


def _carry_parse_caveats(parsed: ParsedProgram, response: Response) -> None:
    for caveat in parsed.caveats:
        response.caveat(caveat.kind, caveat.detail, caveat.effect)


def _unresolved_layout_effect(line: str) -> str:
    """The effect of one byte-layout ``unresolved`` *line*: only SYNC slack
    puts offsets in doubt; a partial level-88 list leaves them exact."""
    if "condition_values lists only part" in line:
        return (
            "a value missing from condition_values may still satisfy the "
            "condition; read condition_ranges"
        )
    return (
        "offsets marked offset_ambiguous may be short; do not build a record "
        "image from them"
    )


def _layout_index(
    unit: CobolProgram, response: Response
) -> dict[str, list[dict[str, Any]]]:
    """Every data item's byte layout, by upper-cased name.

    The layout's ``unresolved`` lines are kept under :data:`_UNRESOLVED_KEY`
    for :func:`_layout_caveats` to carry the ones that bear on an answer.
    """
    from ..generators.data.layout_offsets import compute_program_data_items

    try:
        with stdout_to_stderr():
            computed = compute_program_data_items(unit)
            items = computed["items"]
    except Exception as exc:  # noqa: BLE001 -- one analyzer must not sink the answer
        response.caveat(
            "analyzer-failed",
            f"byte layout could not be computed: {exc}",
            "no layout is reported for data items",
        )
        return {}
    index: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        index.setdefault(str(item["name"]).upper(), []).append(item)
    index[_UNRESOLVED_KEY] = [{"line": line} for line in computed["unresolved"]]
    return index


#: Not a COBOL name (it has a space), so it cannot collide with an item.
_UNRESOLVED_KEY = " unresolved"


def _layout_caveats(
    item: dict[str, Any],
    layout: dict[str, list[dict[str, Any]]],
    response: Response,
) -> None:
    """Carry the layout's ``unresolved`` lines about *item*'s record."""
    record = str(item.get("qualified_name") or "").split(".")[0]
    for entry in layout.get(_UNRESOLVED_KEY, []):
        line = str(entry["line"])
        if line.split(":", 1)[0].split(".")[0] == record:
            response.caveat(
                "incomplete-analysis", line, _unresolved_layout_effect(line)
            )


#: A cap no record reaches: :func:`_renames_records` filters first, caps after.
_UNCAPPED = 1 << 30


def _renames_records(
    unit: CobolProgram,
    wanted: str,
    parsed: ParsedProgram,
    response: Response,
    cap: int,
) -> list[dict[str, Any]]:
    """``record_layout`` answers for the level-66 RENAMES items named
    *wanted* (#563): the byte range ``data-items`` places each at, within
    the record it renames, with that record's fields lying in the range.
    """
    name = wanted.split(" OF ")[0].strip()
    layout = _layout_index(unit, response)
    records: list[dict[str, Any]] = []
    for index, entry in enumerate(
        e for e in layout.get(name, []) if e.get("level") == 66
    ):
        root_name = str(entry.get("parent_qualified_name") or "")
        roots = [f for f in _data_items_named(unit, root_name) if f.item is f.root]
        if len(roots) != 1:
            continue
        found = roots[0]
        # Every field of the record (no cap yet): the range picks from them.
        rows = _layout_answer(
            found,
            _record_layout(found.root, response),
            parsed,
            response,
            _UNCAPPED,
            index,
        )["fields"]
        start = int(entry["byte_offset"])
        end = start + int(entry["byte_length"])
        covered = [
            row
            for row in rows
            if row.get("byte_offset") is not None
            and start <= int(row["byte_offset"])
            and int(row["byte_offset"]) + int(row.get("byte_length") or 0) <= end
        ]
        location = _renames_location(unit, name)
        record: dict[str, Any] = {
            "name": entry["name"],
            "qualified_name": entry["name"],
            "section": found.section,
            "level": 66,
            "renames": found.root.name,
            "declared_at": (
                parsed.locate(location.line, location.column, response)
                if location is not None
                else None
            ),
            "byte_offset": start,
            "byte_length": int(entry["byte_length"]),
        }
        for key in ("picture", "usage"):
            if entry.get(key) and not entry.get("is_group"):
                record[key] = entry[key]
        if entry.get("offset_ambiguous"):
            record["offset_ambiguous"] = True
        record["field_count"] = len(covered)
        record["fields"] = response.cap(covered, cap, f"records[{index}].fields")
        records.append(record)
    return records


def _renames_location(unit: CobolProgram, name: str) -> Any:
    """Where the level-66 RENAMES item *name* is declared, or None."""
    node = _renames_node(unit, name)
    return node.location if node is not None else None


def _renames_node(unit: CobolProgram, name: str) -> RenamesItem | None:
    """The level-66 RENAMES item *name* of *unit*, or None."""
    data_div = unit.data_division
    if data_div is None:
        return None
    for section in data_div.sections:
        if not isinstance(section, CobolSection):
            continue
        for node in section.children:
            if isinstance(node, RenamesItem) and node.name.upper() == name:
                return node
    return None


def _layout_for(
    name: str,
    xref_qualified: str | None,
    layout: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    """The layout item an xref entry describes, or None when it is unclear.

    xref qualifies a duplicated name as ``AMT OF OUT-REC``; the layout as
    ``OUT-REC.AMT``. Every ``OF`` qualifier must be one of the item's
    ancestors.
    """
    candidates = layout.get(name.upper(), [])
    if xref_qualified:
        qualifiers = [
            q.strip().upper() for q in xref_qualified.upper().split(" OF ")[1:]
        ]
        candidates = [
            c
            for c in candidates
            if set(qualifiers)
            <= set(str(c.get("qualified_name", "")).upper().split(".")[:-1])
        ]
    return candidates[0] if len(candidates) == 1 else None


def _rule(
    rule: Any, index: int, parsed: ParsedProgram, response: Response, cap: int
) -> dict[str, Any]:
    """One business rule, cited on disk, with its empty fields left out."""
    branches = []
    for number, branch in enumerate(rule.branches):
        actions = response.cap(
            list(branch.actions),
            cap,
            f"rules[{index}].branches[{number}].actions",
        )
        branches.append(
            {
                "label": branch.label,
                "condition": branch.condition,
                "actions": [
                    {
                        key: value
                        for key, value in (
                            ("text", action.text),
                            (
                                "location",
                                parsed.locate(
                                    action.location.line,
                                    None,
                                    response,
                                    column_known=False,
                                ),
                            ),
                            ("rule_id", action.rule_id),
                        )
                        if value is not None
                    }
                    for action in actions
                ],
            }
        )
    result: dict[str, Any] = {
        "rule_id": rule.rule_id,
        "kind": rule.kind,
        "statement": rule.statement,
        "procedure": rule.procedure,
        "section": rule.section,
        "location": parsed.locate(
            rule.location.line, None, response, column_known=False
        ),
        "condition": rule.condition,
        "formula": rule.formula,
        "branches": branches,
        "guards": list(rule.guards),
        "reached_via": list(rule.reached_via),
        "inputs": list(rule.inputs),
        "outputs": list(rule.outputs),
        "classification": list(rule.classification),
        "technical": rule.technical,
        "in_dead_code": rule.in_dead_code,
    }
    # A calculation's condition repeats its formula.
    if rule.formula is not None and rule.condition == rule.formula:
        del result["condition"]
    return {key: value for key, value in result.items() if _worth_showing(value)}


def _change(
    change: Any, old: ParsedProgram, new: ParsedProgram, response: Response
) -> dict[str, Any]:
    """One structural difference, each side cited in its own file."""
    result: dict[str, Any] = {
        "kind": change.kind,
        "category": change.category,
        "symbol": change.symbol,
        "detail": change.detail,
        "old": change.old,
        "new": change.new,
        "old_location": (
            old.locate(change.old_location.line, None, response, column_known=False)
            if change.old_location
            else None
        ),
        "new_location": (
            new.locate(change.new_location.line, None, response, column_known=False)
            if change.new_location
            else None
        ),
    }
    return {key: value for key, value in result.items() if value is not None}


def _scenario(
    scenario: Any, index: int, parsed: ParsedProgram, response: Response, cap: int
) -> dict[str, Any]:
    """One fixture scenario: rows as lists aligned to ``columns`` (a dict
    per row would repeat every column name in every row)."""
    fixtures = []
    for number, fixture in enumerate(
        response.cap(list(scenario.fixtures), cap, f"scenarios[{index}].fixtures")
    ):
        ref = fixture.ref
        columns = [spec.column for spec in fixture.layout]
        if not columns and fixture.sequence:
            columns = list(fixture.sequence[0])
        entry: dict[str, Any] = {
            "boundary": f"{ref.category}:{ref.key}",
            "paragraph": ref.paragraph,
            "location": parsed.locate(ref.line, None, response, column_known=False),
            "direction": fixture.direction,
            "provenance": fixture.provenance,
            "columns": columns,
            "rows": [
                [row.get(column, "") for column in columns]
                for row in response.cap(
                    list(fixture.sequence),
                    cap,
                    f"scenarios[{index}].fixtures[{number}].rows",
                )
            ],
            "terminal": fixture.terminal,
            "status": fixture.status,
            "unresolved": list(fixture.unresolved),
        }
        fixtures.append(
            {key: value for key, value in entry.items() if _worth_showing(value)}
        )
    result: dict[str, Any] = {
        "name": scenario.name,
        "intent": scenario.intent,
        "entry": scenario.entry,
        "fixtures": fixtures,
        "expectations": [
            {
                key: value
                for key, value in expectation.to_dict().items()
                if value is not None
            }
            for expectation in response.cap(
                list(scenario.expectations), cap, f"scenarios[{index}].expectations"
            )
        ],
        "unconstrained": list(scenario.unconstrained),
    }
    if scenario.entry_parameters is not None:
        result["entry_parameters"] = scenario.entry_parameters.to_dict()
    verification = scenario.verification
    if verification is not None:
        result["verification"] = {
            "status": verification.get("status"),
            "reasons": [
                f"{entry['field']}: {entry['detail']}"
                for entry in verification.get("fields", [])
                if entry.get("status") != "satisfied"
            ]
            + list(verification.get("gaps", [])),
        }
    return {key: value for key, value in result.items() if _worth_showing(value)}


#: ``<procedure>@<line>:<column>/...``: where an arm key's branch sits, in
#: the parse's (copybook-expanded) lines.
_ARM_KEY = re.compile(r"^(?P<proc>.*)@(?P<line>\d+):\d+/")


def _arm_coverage(
    coverage: dict[str, Any], parsed: ParsedProgram, response: Response, cap: int
) -> dict[str, Any]:
    """The branch-arm accounting, every missed arm with its reason."""
    missed = [d for d in coverage.get("details", []) if d.get("status") == "missed"]
    rows = []
    for detail in response.cap(missed, cap, "arm_coverage.missed_arms"):
        match = _ARM_KEY.match(detail.get("arm_key") or "")
        rows.append(
            {
                "arm": detail.get("arm_key"),
                "procedure": detail.get("parent_proc"),
                "location": (
                    parsed.locate(
                        int(match.group("line")), None, response, column_known=False
                    )
                    if match
                    else None
                ),
                "reason": detail.get("reason"),
            }
        )
    return {
        "total_arms": coverage.get("total_arms"),
        "targeted": coverage.get("targeted"),
        "merged": coverage.get("merged"),
        "missed": coverage.get("missed"),
        "missed_arms": rows,
    }
