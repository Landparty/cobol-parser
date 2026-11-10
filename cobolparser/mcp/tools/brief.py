"""``program_brief``: one program's size, interface, files, calls, call tree,
the JCL that runs it, reachability and lint headline."""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

from ..._lines import split_source_lines
from ...models.program import CobolProgram
from ...models.walk import own_statements
from ..envelope import Response, ToolError, clamp_limit
from ..link_decks import bound_into, own_decks
from ..workspace import ParsedProgram, Workspace
from .analysis import _finding, _lint_summary, _run_lint
from .common import (
    _CONTROL_EDGES,
    BaseTools,
    _attempt,
    _carry_parse_caveats,
    _crud,
    _file_facts,
    _flow,
    _label_runs_as,
    _notes,
    _Reachability,
    _reachability,
    _worth_showing,
)

#: JCL steps a brief lists under run_by (jobs_running has them all).
BRIEF_RUN_BY = 10


#: Programs a brief's ``call_tree`` lists (``follow_calls``), each with the
#: files and tables it uses; ``jobs_running`` with follow_calls lists them all.
BRIEF_CALL_TREE = 25


#: Sources of one callee ``program_brief`` compares in ``implementations``.
BRIEF_IMPLEMENTATIONS = 4


#: Lint findings a program brief shows (worst first); ``lint`` has the rest.
BRIEF_LINT = 5


class BriefTools(BaseTools):
    """``program_brief``."""

    # -- program_brief -------------------------------------------------------

    def program_brief(
        self,
        file: str,
        program: str | None = None,
        limit: int | None = None,
        follow_calls: bool = False,
    ) -> dict[str, Any]:
        """What *file* (or one program unit in it) is, on one page; with
        *follow_calls*, also every program it runs in turn, each with the
        files and SQL tables it uses (``call_tree``)."""
        from ...analysis.lint import LintAnalyzer

        other = self._other_language_path(file)
        if other is not None:
            result = self._other_language_brief(other, clamp_limit(limit))
            if follow_calls:
                response = Response()
                self._brief_call_tree(
                    str(result["answer"].get("program_id") or other.stem),
                    result["answer"],
                    response,
                    clamp_limit(limit),
                )
                result["caveats"] += [c.to_dict() for c in response.caveats]
                result["truncated"] += response.truncated
            return result
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
                "statements": len(own_statements(unit)),
            }
            answer["entry_points"] = list(flow.entry_points)
            reach = _reachability(parsed, unit, response)
            answer["unreachable_procedures"] = (
                list(flow.unreachable_nodes) if reach is None else reach.unreachable
            )
            if reach is not None and reach.unreachable:
                answer["unreachable_reasons"] = response.cap(
                    _unreachable_reasons(flow, reach, parsed, response),
                    cap,
                    "unreachable_reasons",
                )
            answer["perform_cycles"] = len(flow.cycles)
            flow_notes = _control_flow_notes(nodes)
            if flow_notes:
                answer["control_flow_notes"] = flow_notes

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
            notes = _file_open_close_notes(crud.file_entries, facts or {}, unit)
            if notes:
                answer.setdefault("control_flow_notes", []).extend(notes)
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

        statements = own_statements(unit)
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
        self._brief_runs_as(unit.program_name or "", answer, response)
        _attempt(
            response,
            "other declarations",
            lambda: self._brief_also_declared(parsed, unit, answer),
        )
        name = (unit.program_name or "").upper()
        if name:
            decks = _attempt(
                response, "link-edit decks", lambda: own_decks(self.workspace, name)
            )
            if decks:
                answer["link_edit"] = decks
            bound = _attempt(
                response, "link-edit decks", lambda: bound_into(self.workspace, name)
            )
            if bound:
                answer["link_edited_into"] = bound
        if follow_calls:
            self._brief_call_tree(
                unit.program_name or "",
                answer,
                response,
                cap,
                {(unit.program_name or "").upper(), Path(str(parsed.path)).stem.upper()}
                - {""},
            )
        return response.build(answer, parsed.program_info(unit))

    def _brief_also_declared(
        self, parsed: ParsedProgram, unit: CobolProgram, answer: dict[str, Any]
    ) -> None:
        """``also_declared_in``: the other files whose PROGRAM-ID is this
        one's, each compared with this file line by line, so "is it the
        same program?" is answered rather than left to a diff."""
        from ..codebase_index import programs_index

        name = (unit.program_name or "").upper()
        mine = self.workspace.display(parsed.path)
        others = sorted(
            {
                self.workspace.display(node.path)
                for node in programs_index(self.workspace).graph.programs
                if node.program_id.upper() == name
            }
            - {mine}
        )
        if not others:
            return
        text = Workspace.read_text(parsed.path)
        rows = []
        for other in others[:BRIEF_ALSO_DECLARED]:
            try:
                theirs = Workspace.read_text(self.workspace.resolve(other))
            except (ToolError, OSError):
                rows.append({"file": other})
                continue
            rows.append({"file": other, **compare_sources(text, theirs)})
        answer["also_declared_in"] = rows

    def _brief_call_tree(
        self,
        name: str,
        answer: dict[str, Any],
        response: Response,
        cap: int,
        names: set[str] | None = None,
    ) -> None:
        """``answer["call_tree"]``: every program *name* runs through CALL /
        LINK / XCTL, breadth first, each COBOL one with its ``files`` and
        ``sql_tables`` (C/R/U/D) and CICS command counts, so a transaction's
        whole footprint is one answer instead of one brief per program."""
        from ..codebase_index import call_chain

        chain: tuple[list[dict[str, Any]], list[str]] | None = _attempt(
            response, "call tree", lambda: call_chain(self.workspace, name)
        )
        rows, notes = chain or ([], [])
        shown = response.cap(rows, min(cap, BRIEF_CALL_TREE), "call_tree")
        for row in shown:
            if row.get("language") != "COBOL" or not row.get("file"):
                continue
            file, callee = str(row["file"]), str(row["program"])
            uses = _attempt(
                response,
                f"file and table use of {callee}",
                functools.partial(self._program_uses, file, callee),
            )
            if uses:
                row.update(uses)
            if any(o.get("language") == "COBOL" for o in row.get("also_in") or []):
                _attempt(
                    response,
                    f"implementations of {callee}",
                    functools.partial(
                        self._implementations, row, names or {name.upper()}
                    ),
                )
        _label_runs_as(self.workspace, answer, shown, response)
        answer["call_tree"] = shown
        if shown:
            answer.setdefault("access_legend", "C=create R=read U=update D=delete")
        _notes(
            response,
            "incomplete-analysis",
            notes,
            "programs those dynamic CALLs reach are missing from call_tree",
            lead="the call chain could not be followed everywhere",
        )

    def _implementations(self, row: dict[str, Any], names: set[str]) -> None:
        """A callee with several COBOL sources (a VSAM and a DB2 version of
        one I/O module): each one's files, DD names and tables, and which
        of the JCL steps that run the caller code every DD it opens. The
        step decides which one it is set up for; the call tree alone
        cannot, since a CALL names a load module, not a source."""
        from .jcl_index import jcl_available, program_dds, step_dds

        program = str(row["program"])
        files = [str(row["file"])] + [
            str(o["file"])
            for o in row.get("also_in") or []
            if o.get("language") == "COBOL"
        ]
        steps = step_dds(self.workspace, names) if jcl_available() else []
        impls = []
        for file in files[:BRIEF_IMPLEMENTATIONS]:
            parsed = self.workspace.program(file)
            unit = parsed.ast.find_program_unit(program) or parsed.ast
            impl: dict[str, Any] = {"file": file, **self._program_uses(file, program)}
            dds = program_dds(parsed, unit)
            if dds:
                impl["dds"] = dds
                impl["dds_coded_by"] = [
                    {
                        "step": label,
                        "datasets": {dd: coded[dd] for dd in dds if coded[dd]},
                    }
                    for label, coded in steps
                    if set(dds) <= set(coded)
                ]
            impls.append(impl)
        row["implementations"] = impls
        set_up = [i for i in impls if i.get("dds_coded_by")]
        if steps and set_up:
            row["implementation_note"] = "; ".join(
                f"{', '.join(c['step'] for c in i['dds_coded_by'])} code(s) every "
                f"DD {i['file']} opens ({', '.join(i['dds'])}): that is the "
                "version those steps are set up to run"
                for i in set_up
            )
        elif steps:
            row["implementation_note"] = (
                "no JCL step that runs the caller codes the DDs any version "
                "opens; which one runs depends on which is linked"
            )

    def _brief_runs_as(
        self, program: str, answer: dict[str, Any], response: Response
    ) -> None:
        """``runs_as``: online (CICS), batch or IMS, and why."""
        from ..codebase_index import RunsAs

        if not program:
            return
        found = _attempt(
            response, "online or batch", lambda: RunsAs(self.workspace).of(program)
        )
        if found:
            answer["runs_as"] = found

    def _program_uses(self, file: str, program: str) -> dict[str, Any]:
        """The files and SQL tables one program uses (C/R/U/D) and its CICS
        command counts: the footprint part of its brief."""
        parsed = self.workspace.program(file)
        unit = parsed.ast.find_program_unit(program) or parsed.ast
        crud = _crud(parsed, unit)
        out: dict[str, Any] = {}
        files = [
            {"name": e.file_name, "access": e.crud.as_string()}
            for e in sorted(crud.file_entries, key=lambda e: e.file_name)
        ]
        tables = [
            {"name": e.table_name, "access": e.crud.as_string()}
            for e in sorted(crud.table_entries, key=lambda e: e.table_name)
        ]
        if files:
            out["files"] = files
        if tables:
            out["sql_tables"] = tables
        cics = _verb_counts(own_statements(unit), "EXEC_CICS", "cics_command")
        if cics:
            out["cics_commands"] = cics
        return out

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
        from .jcl_index import run_by

        steps = _attempt(response, "JCL steps", lambda: run_by(self.workspace, names))
        if steps is None:
            return
        answer["run_by"] = response.cap(steps, min(cap, BRIEF_RUN_BY), "run_by")

    def _other_language_brief(self, path: Path, cap: int) -> dict[str, Any]:
        """``program_brief`` of a PL/I or assembler source: its names, its
        procedures or sections, what it CALLs and includes, its CICS / SQL /
        MQ / IMS requests, who CALLs it and which JCL steps run it."""
        from ..codebase_index import programs_index
        from ..languages import LIMITS, facts_for

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


def _unreachable_reasons(
    flow: Any, reach: _Reachability, parsed: ParsedProgram, response: Response
) -> list[dict[str, Any]]:
    """Why each unreachable procedure is: what names it (nothing, or only
    unreachable code) and why control does not fall into it from the one
    before. So "why is this dead" is answered, not left to be argued from
    the source."""
    dead = {name.upper() for name in reach.unreachable}
    nodes = list(flow.nodes)
    order = {node.key.upper(): i for i, node in enumerate(nodes)}
    into: dict[str, list[Any]] = {}
    for edge in flow.edges:
        kind = edge.edge_type.value
        if kind not in _CONTROL_EDGES:
            continue
        targets = {edge.target.upper(), *(m.upper() for m in edge.range_members)}
        for target in targets:
            into.setdefault(target, []).append(edge)

    def where(edge: Any) -> str:
        located = parsed.locate(edge.location.line, edge.location.column, response)
        return f"{located['file']}:{located['line']}" if located else ""

    rows = []
    for name in reach.unreachable:
        key = name.upper()
        position = order.get(key)
        node = nodes[position] if position is not None else None
        named = [
            e
            for e in into.get(key, [])
            if not e.edge_type.value.endswith("_THRU")
            and e.edge_type.value != "FALL_THROUGH"
        ]
        if not named:
            why = ["no PERFORM, GO TO or other statement names it"]
        else:
            sources = sorted(
                {f"{e.edge_type.value} from {e.source} at {where(e)}" for e in named}
            )
            why = ["named only from unreachable code: " + "; ".join(sources[:3])]
        if position:
            before = nodes[position - 1]
            bkey = before.key.upper()
            if (bkey, key) in reach.fall_throughs:
                pass
            elif bkey in dead:
                why.append(f"the procedure before it, {before.key}, is unreachable too")
            elif any(e.edge_type.value.endswith("_THRU") for e in into.get(bkey, [])):
                why.append(
                    f"the procedure before it, {before.key}, is reached only as "
                    "the end of a PERFORM ... THRU range, whose end returns to "
                    "the PERFORM"
                )
            elif before.exit_statement_kind:
                ends = before.exit_statement_location
                line = ""
                if ends is not None:
                    located = parsed.locate(ends.line, ends.column, response)
                    line = f" ({located['file']}:{located['line']})" if located else ""
                why.append(
                    f"the procedure before it, {before.key}, ends with "
                    f"{before.exit_statement_kind}{line}, so control never "
                    "falls into it"
                )
            elif into.get(bkey):
                why.append(
                    f"the procedure before it, {before.key}, is only PERFORMed, "
                    "so its end returns to the PERFORM"
                )
            else:
                why.append(f"control does not fall into it from {before.key}")
        row: dict[str, Any] = {"procedure": name, "reason": "; ".join(why)}
        if node is not None:
            row["location"] = parsed.locate(
                node.location.line, node.location.column, response
            )
        rows.append(row)
    return rows


def _signature(parsed: ParsedProgram, unit: CobolProgram) -> Any:
    from ...analysis.program_signature import ProgramSignatureExtractor

    return parsed.report(
        "signature", unit, lambda: ProgramSignatureExtractor().analyze(unit)
    )


def _debt(parsed: ParsedProgram, unit: CobolProgram) -> Any:
    from ...analysis.technical_debt import TechnicalDebtAnalyzer

    return parsed.report(
        "debt", unit, lambda: TechnicalDebtAnalyzer().analyze(parsed.context(unit))
    )


def _call_targets(values: list[str]) -> list[str]:
    """Traced CALL / LINK / XCTL targets as the program names they reach:
    trailing blanks dropped (``MOVE 'SUBY    ' TO WS-P`` of a PIC X(8)
    calls SUBY, #754), duplicates after that merged."""
    return list(dict.fromkeys(v.rstrip() for v in values))


def _calls(
    parsed: ParsedProgram, unit: CobolProgram, flow: Any, response: Response
) -> list[dict[str, Any]]:
    """Every program *unit* CALLs (or LINKs/XCTLs to), one row per target."""
    from ...analysis.value_tracker import DynamicCallAnalyzer

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
                values = _call_targets(values)
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
    for statement in own_statements(unit):
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
                values = _call_targets(values)
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
        from ...analysis.language_env_analyzer import function_references

        for statement in own_statements(unit):
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


BRIEF_ALSO_DECLARED = 5


_DIFF_LINES_SHOWN = 10


def compare_sources(mine: str, theirs: str) -> dict[str, Any]:
    """How two source texts differ: ``identical``, else the line numbers
    (of *mine*) that differ, and whether every one of them is a comment
    line (column 7 ``*`` or ``/``) on both sides."""
    import difflib

    a, b = split_source_lines(mine), split_source_lines(theirs)
    if a == b:
        return {"identical": True, "comparison": "identical, line for line"}
    changed: list[int] = []
    comments_only = True
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed.extend(range(i1 + 1, i2 + 1) or [i1 + 1])
        for line in [*a[i1:i2], *b[j1:j2]]:
            if line[6:7] not in ("*", "/") and line.strip():
                comments_only = False
    if comments_only:
        what = "only comment lines differ"
    else:
        what = "code differs"
    shown = changed[:_DIFF_LINES_SHOWN]
    return {
        "identical": False,
        "comments_only": comments_only,
        "differing_lines": shown,
        "differing_line_count": len(changed),
        "comparison": f"{what}: {len(changed)} line(s), "
        f"at {', '.join(map(str, shown))}"
        + (" ..." if len(changed) > len(shown) else ""),
    }


def _control_flow_notes(nodes: list[Any]) -> list[str]:
    """What a reader of the PROCEDURE DIVISION easily misses: no statement
    that ends the program (control falls off the last paragraph), and
    paragraphs that run in order by falling through because nothing
    PERFORMs or GOes TO them."""
    if not nodes:
        return []
    notes: list[str] = []
    ends = [
        n
        for n in nodes
        if n.has_stop_run
        or n.has_goback
        or n.has_exit_program
        or n.has_cics_exit
        or n.has_abend_call
    ]
    if not ends:
        notes.append(
            "no GOBACK, STOP RUN, EXIT PROGRAM or EXEC CICS RETURN: control "
            f"falls off the end of the last procedure, {nodes[-1].name}"
        )
    named = [n for n in nodes if n.name != "PROCEDURE DIVISION"]
    jumps = sum(n.perform_count + n.goto_count for n in nodes)
    if len(named) > 1 and not jumps and (not ends or ends[0] is nodes[-1]):
        notes.append(
            "nothing is PERFORMed or GONE TO: the paragraphs run once each, "
            "in order, by falling through: " + " -> ".join(n.name for n in named)
        )
    return notes


def _file_open_close_notes(
    entries: Any, facts: dict[str, Any], unit: CobolProgram
) -> list[str]:
    """FD files that are never OPENed, or OPENed and never CLOSEd.

    An SD, an EXEC CICS file (no FD) and a SORT/MERGE USING or GIVING file
    are opened by something else, so none of them counts.
    """
    closed: set[str] = set()
    sorted_by: set[str] = set()
    for statement in own_statements(unit):
        kind = getattr(statement, "statement_type", "")
        if kind == "CLOSE":
            closed.update(n.upper() for n in getattr(statement, "file_names", []))
        elif kind in ("SORT", "MERGE"):
            for attr in ("using_files", "giving_files"):
                sorted_by.update(n.upper() for n in getattr(statement, attr, []))
    declared = [
        e
        for e in entries
        if getattr(facts.get(e.file_name.upper()), "record_type", None) == "FD"
        and e.file_name.upper() not in sorted_by
    ]
    unopened = sorted(e.file_name for e in declared if not e.open_modes)
    unclosed = sorted(
        e.file_name
        for e in declared
        if e.open_modes and e.file_name.upper() not in closed
    )
    notes = []
    if unopened:
        notes.append(f"declared but never OPENed: {', '.join(unopened)}")
    if unclosed:
        notes.append(f"OPENed but never CLOSEd: {', '.join(unclosed)}")
    return notes


def _verb_counts(
    statements: list[Any], node_type: str, attribute: str
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for statement in statements:
        if getattr(statement, "node_type", None) == node_type:
            verb = (getattr(statement, attribute, "") or "?").upper()
            counts[verb] = counts.get(verb, 0) + 1
    return dict(sorted(counts.items()))
