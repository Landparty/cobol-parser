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
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, TypeVar

from ..models.data_items import CobolDataItem, ConditionNameItem
from ..models.program import CobolProgram, CobolSection
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

#: Lint findings a program brief shows (worst first); ``lint`` has the rest.
BRIEF_LINT = 5

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
        start = max(1, line - before)
        # At most MAX_SOURCE_LINES are kept while the file streams past; the
        # rest is only counted, so a huge file under the root costs no memory.
        last_kept = min(line + after, start + MAX_SOURCE_LINES - 1)
        window: list[str] = []
        total = 0
        try:
            # newline="" splits on \n, \r\n and \r only, as
            # split_source_lines does: never on a form feed inside a record.
            with path.open(encoding="utf-8", newline="") as handle:
                for total, text in enumerate(handle, start=1):
                    if start <= total <= last_kept:
                        window.append(text.rstrip("\r\n"))
        except UnicodeDecodeError as exc:
            raise ToolError(f"{path.name} is not valid UTF-8 text") from exc
        except OSError as exc:
            raise ToolError(f"cannot read {path.name}: {exc}") from exc
        if line < 1 or (total and line > total):
            raise ToolError(f"line {line} is outside {file} (1-{total})")
        end = min(total, line + after)
        response = Response()
        if end - start + 1 > MAX_SOURCE_LINES:
            response.truncated.append(
                {
                    "field": "lines",
                    "shown": MAX_SOURCE_LINES,
                    "total": end - start + 1,
                }
            )
            end = start + MAX_SOURCE_LINES - 1
        return response.build(
            {
                "file": self.workspace.display(path),
                "start_line": start,
                "end_line": end,
                "total_lines": total,
                "lines": [
                    {"line": n, "text": window[n - start]}
                    for n in range(start, end + 1)
                ],
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
        selected = rules or list(config.rules) or None
        severity = min_severity or config.min_severity or "info"
        if severity not in SEVERITIES:
            raise ToolError(
                f"unknown severity {severity!r} (expected one of "
                f"{', '.join(SEVERITIES)})"
            )
        try:
            analyzer = LintAnalyzer(selected)
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

        qualified = " OF " in wanted or " IN " in wanted
        if qualified:
            entry = report.entry_for(wanted.replace(" IN ", " OF "))
            matches = [entry] if entry is not None else []
        else:
            matches = [e for e in report.entries if e.name.upper() == wanted]

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
            item = _layout_for(entry.name, entry.qualified_name, layout)
            if item is not None:
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
            answer["unreachable_procedures"] = list(flow.unreachable_nodes)
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
        return response.build(answer, parsed.program_info(unit))

    # -- callers_of ----------------------------------------------------------

    def callers_of(
        self,
        file: str,
        name: str,
        program: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Who transfers control to paragraph or section *name*, and from where.

        A program name that *file* CALLs answers with those CALL sites.
        """
        wanted = " ".join(name.split()).upper()
        if not wanted:
            raise ToolError("no paragraph, section or program name given")
        parsed = self.workspace.program(file)
        response = Response()
        _carry_parse_caveats(parsed, response)
        unit = parsed.unit(program, response)
        program_info = parsed.program_info(unit)
        flow = _flow(parsed, unit)
        cap = clamp_limit(limit)

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
            sites = [
                e
                for e in flow.edges
                if e.edge_type.value in _CALL_EDGES and e.target.upper() == wanted
            ]
            if sites:
                callers = [_edge_caller(e, parsed, response) for e in sites]
                return response.build(
                    {
                        "name": wanted,
                        "found": True,
                        "kind": "program",
                        "scope": "this file only",
                        "caller_count": len(callers),
                        "callers": response.cap(callers, cap, "callers"),
                    },
                    program_info,
                )
            names = sorted({n.key.upper() for n in flow.nodes})
            not_found: dict[str, Any] = {
                "name": wanted,
                "found": False,
                "suggestions": difflib.get_close_matches(wanted, names, n=5),
            }
            if unit.program_name and wanted == unit.program_name.upper():
                not_found["note"] = (
                    f"{wanted} is this program: which other programs CALL it "
                    "needs a cross-program index, which this server does not "
                    "build yet"
                )
            return response.build(not_found, program_info)

        unreachable = {u.upper() for u in flow.unreachable_nodes}
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
                response, "byte layout", functools.partial(_record_layout, found.root)
            )
            if layout is not None:
                records.append(
                    _layout_answer(found, layout, parsed, response, cap, index)
                )
        answer["found"] = True
        answer["records"] = records
        answer["offsets_from"] = "the start of each record's 01/77 item"
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
        row = rows.setdefault(
            (linked.upper(), command),
            {
                "program": linked,
                "via": f"EXEC CICS {command}",
                "dynamic": not literal,
                "sites": [],
            },
        )
        row["sites"].append(
            {"location": parsed.locate(cics.location.line, None, response)}
        )
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


def _record_layout(root: CobolDataItem) -> list[dict[str, Any]]:
    from ..generators.data.layout_offsets import compute_record_layout

    return [item.to_dict() for item in compute_record_layout(root)]


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


def _carry_parse_caveats(parsed: ParsedProgram, response: Response) -> None:
    for caveat in parsed.caveats:
        response.caveat(caveat.kind, caveat.detail, caveat.effect)


def _layout_index(
    unit: CobolProgram, response: Response
) -> dict[str, list[dict[str, Any]]]:
    """Every data item's byte layout, by upper-cased name."""
    from ..generators.data.layout_offsets import compute_program_data_items

    try:
        with stdout_to_stderr():
            items = compute_program_data_items(unit)["items"]
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
    return index


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
