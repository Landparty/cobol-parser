"""The ``jcl_job`` tool: one JCL file's jobs, steps and DDs, the procedures
it expands, SORT control cards mapped onto record layouts (:class:`_Layouts`,
:func:`_sort_layout`)."""

from __future__ import annotations

from typing import Any

from ...jcl.models import JclJob, JobStep
from ..envelope import Response, ToolError, clamp_limit
from ..workspace import Workspace
from .jcl_common import (
    _MEMBER_RE,
    _SORT_PROGRAMS,
    _base,
    _cards,
    _carry_file,
    _carry_libraries,
    _control_lines,
    _ControlMembers,
    _dd_row,
    _other_language_source,
    _step_row,
    _utility_uses,
    run_order,
)
from .jcl_index import (
    JclFile,
    _Locator,
    _parse,
    _program_selects,
    _source_files,
    jcl_index,
)

#: Programs tried for the record layout of a SORT step input dataset.
SORT_LAYOUT_PROGRAMS = 6


#: Fields of the output layout a SORT step's ``output_read_as`` lists.
SORT_READ_BACK_FIELDS = 40


# ---------------------------------------------------------------------------
# jcl_job
# ---------------------------------------------------------------------------


def jcl_job(
    workspace: Workspace,
    file: str,
    job: str | None = None,
    step: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """One JCL file's jobs, steps and DD statements, cited on disk."""
    path = workspace.resolve(file)
    index = jcl_index(workspace)
    jfile = next((f for f in index.files if f.path == path), None)
    if jfile is None:  # JCL under another suffix (a member with none)
        jfile = _parse(index.libraries, workspace, path)
    if jfile.result is None:
        raise ToolError(f"cannot read {jfile.display}: {jfile.failure}")
    result = jfile.result
    response = Response()
    locator = _Locator(jfile, workspace)
    _carry_file(jfile, response)
    _carry_libraries(index.libraries, [jfile], response)

    jobs = result.jobs
    if job:
        jobs = [j for j in jobs if j.name.upper() == job.strip().upper()]
        if not jobs:
            raise ToolError(
                f"no job named {job!r} in {jfile.display} (found: "
                f"{', '.join(j.name for j in result.jobs) or 'none'})"
            )
    cap = clamp_limit(limit)
    sources = _source_files(workspace)
    members = _ControlMembers(workspace)
    layouts = _Layouts(workspace)
    programs: dict[str, str | None] = {}
    # Looked up once per program name: each lookup checks the languages
    # index's stamps, a walk of the root.
    others: dict[str, dict[str, Any] | None] = {}
    rows = []
    for each in jobs:
        steps = each.steps
        if step:
            wanted = step.strip().upper()
            steps = [
                s
                for s in steps
                if s.name.upper() == wanted or s.name.upper().endswith(f".{wanted}")
            ]
        shown = response.cap(steps, cap, f"{each.name}.steps")
        for s in shown:
            for name in s.effective_programs():
                found = sources.get(name)
                if found is None:
                    if name not in others:
                        others[name] = _other_language_source(workspace, name)
                    other = others[name]
                    found = other["file"] if other else None
                programs[name] = found
        rows.append(_job_row(each, shown, locator))
        for shown_step, step_row in zip(shown, rows[-1]["steps"], strict=True):
            laid = _sort_layout(
                shown_step, _sysin_lines(shown_step, members, jfile), layouts, each
            )
            if laid is not None:
                step_row["sort_layout"] = laid
    if step and not any(row["steps"] for row in rows):
        names = [s.name for j in jobs for s in j.steps]
        raise ToolError(
            f"no step named {step!r} in {jfile.display} (found: "
            f"{', '.join(names) or 'none'})"
        )
    answer: dict[str, Any] = {"file": jfile.display, "jobs": rows}
    if programs:
        answer["program_sources"] = programs
    procedures = _procedures(jobs, jfile, workspace)
    if procedures:
        answer["procedures"] = procedures
        answer["procedure_libraries"] = [workspace.display(d) for d in jfile.libraries]
    if result.symbols:
        answer["symbols"] = {k: result.symbols[k] for k in sorted(result.symbols)}
    if result.errors:
        answer["errors"] = [
            {
                "location": locator.at(jfile.path, int(e.get("line") or 0)),
                "message": e.get("message"),
            }
            for e in result.errors
        ]
    if not result.jobs:
        answer["note"] = "no JOB or EXEC statement in this file"
    return response.build(answer)


def _job_row(job: JclJob, steps: list[JobStep], locator: _Locator) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": job.name,
        "location": locator.at(locator.jfile.path, job.line),
    }
    parameters = {
        p.keyword: p.value for p in job.parameters if p.keyword and p.value is not None
    }
    if parameters:
        row["parameters"] = parameters
    if job.dd_statements:
        row["dds"] = [_dd_row(dd, None, locator) for dd in job.dd_statements]
    row["step_count"] = len(job.steps)
    row["run_order"] = run_order(job.steps)
    row["steps"] = [_step_row(s, locator, instream=True) for s in steps]
    return row


def _procedures(
    jobs: list[JclJob],
    jfile: JclFile,
    workspace: Workspace,
) -> list[dict[str, Any]]:
    """Every procedure the jobs invoke, and where its cards were read."""
    assert jfile.result is not None
    in_stream = {name.upper() for name in jfile.result.procedures}
    seen: dict[str, dict[str, Any]] = {}
    for job in jobs:
        for step in job.steps:
            name = (step.procedure or "").upper()
            if not name or name in seen:
                continue
            if name in in_stream:
                seen[name] = {"name": name, "source": "in-stream"}
            elif name in jfile.members:
                seen[name] = {
                    "name": name,
                    "source": workspace.display(jfile.members[name]),
                }
            elif name in jfile.result.template_procedures:
                seen[name] = {"name": name, "source": "jcl-parser template"}
            else:
                seen[name] = {"name": name, "source": None, "expanded": False}
    return list(seen.values())


class _Layouts:
    """The record layout a COBOL program reads a dataset through, by the
    dataset's base name, found once per tool call."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self._held: dict[str, dict[str, Any] | None] = {}

    def of(self, dataset: str) -> dict[str, Any] | None:
        base = _base(dataset).upper()
        if base not in self._held:
            self._held[base] = self._find(base)
        return self._held[base]

    def _find(self, base: str) -> dict[str, Any] | None:
        """The most detailed record a program opening a DD for *base* uses:
        the FD record, or what it READs INTO / WRITEs FROM."""
        index = jcl_index(self.workspace)
        seen: set[str] = set()
        best: dict[str, Any] | None = None
        for jfile in index.parsed():
            assert jfile.result is not None
            locator = _Locator(jfile, self.workspace)
            for _job, step, dd, _path in _cards(jfile.result, locator):
                if step is None or dd.dataset is None:
                    continue
                if _base(dd.dataset).upper() != base or _utility_uses(step):
                    continue
                for program in self._programs(step):
                    key = f"{program}:{(dd.name or '').upper()}"
                    if key in seen:
                        continue
                    seen.add(key)
                    found = self._record(program, (dd.name or "").upper())
                    if found and (
                        best is None or found["field_count"] > best["field_count"]
                    ):
                        best = found
                if len(seen) >= SORT_LAYOUT_PROGRAMS:
                    return best
        return best

    def _programs(self, step: JobStep) -> list[str]:
        """The step's programs and those they CALL: a called I/O routine
        opens the DD for its caller (CBSTM03B for CBSTM03A)."""
        from ..codebase_index import call_chain

        found = list(step.effective_programs())
        for program in list(found):
            rows, _notes = call_chain(self.workspace, program, 2)
            found += [
                str(r["program"]).upper()
                for r in rows
                if r.get("file") and r.get("language", "COBOL") == "COBOL"
            ]
        return list(dict.fromkeys(found))

    def _record(self, program: str, ddname: str) -> dict[str, Any] | None:
        from . import CobolTools
        from .common import _file_facts

        selects = _program_selects(self.workspace, program, Response())
        if selects is None:
            return None
        file_names = [
            row["file_name"].upper()
            for row in selects["files"]
            if (row.get("ddname") or "").upper() == ddname
        ]
        if not file_names:
            return None
        file = selects["source"]["file"]
        parsed = self.workspace.program(file)
        unit = parsed.ast.find_program_unit(program) or parsed.ast
        facts = _file_facts(parsed, unit)
        candidates: dict[str, str] = {}
        for file_name in file_names:
            fact = facts.get(file_name)
            records = {r.upper() for r in (fact.record_names if fact else [])}
            for record in sorted(records):
                candidates.setdefault(record, f"the FD record of {file_name}")
            for node in unit.find_all_by_type("IOReadStatement"):
                into = getattr(node, "into_target", None)
                read = (getattr(node, "file_name", None) or "").upper()
                if into and read == file_name:
                    candidates[into.upper()] = f"READ {file_name} INTO {into.upper()}"
            for kind, verb in (
                ("IOWriteStatement", "WRITE"),
                ("IORewriteStatement", "REWRITE"),
            ):
                for node in unit.find_all_by_type(kind):
                    source = getattr(node, "from_clause", None)
                    record = (getattr(node, "record_name", None) or "").upper()
                    if source and record in records:
                        candidates.setdefault(
                            source.upper(), f"{verb} {record} FROM {source.upper()}"
                        )
        tools = CobolTools(self.workspace)
        best: dict[str, Any] | None = None
        for record, how in candidates.items():
            try:
                answer = tools.record_layout(file, record, program, 500)["answer"]
            except ToolError:
                continue
            for laid in answer.get("records") or []:
                fields = _elementary(laid.get("fields") or [])
                if best is not None and len(fields) <= best["field_count"]:
                    continue
                best = {
                    "record": laid["name"],
                    "declared_at": laid.get("declared_at"),
                    "length": laid.get("byte_length"),
                    "field_count": len(fields),
                    "how": f"{how} in {program} ({file}), which opens the "
                    f"dataset as DD {ddname}",
                    "fields": fields,
                }
        return best


def _elementary(fields: list[dict[str, Any]]) -> list[tuple[str, int, int]]:
    """The elementary items of a record_layout field list, as (name,
    0-based offset, length)."""
    out = []
    for at, item in enumerate(fields):
        after = fields[at + 1] if at + 1 < len(fields) else None
        if after is not None and after.get("level", 0) > item.get("level", 0):
            continue
        if item.get("byte_offset") is None or item.get("byte_length") is None:
            continue
        out.append((str(item["name"]), item["byte_offset"], item["byte_length"]))
    return out


def _sysin_lines(step: JobStep, members: _ControlMembers, jfile: JclFile) -> list[str]:
    """A step's SYSIN control statements: in-stream, or the member under
    the root its ``DSN=LIB(MEMBER)`` names."""
    for dd in step.dd_statements:
        if (dd.name or "").upper() != "SYSIN":
            continue
        if dd.is_instream:
            return [ln.strip() for ln in dd.instream_lines if ln.strip()]
        found = _MEMBER_RE.search(dd.dataset or "")
        path = members.find(found.group(1), jfile.display) if found else None
        if path is not None:
            return _control_lines(Workspace.read_text(path))
    return []


def _sort_layout(
    step: JobStep, lines: list[str], layouts: _Layouts, job: JclJob | None = None
) -> dict[str, Any] | None:
    """A SORT / MERGE step's control cards in field names, when a COBOL
    program under the root reads its input dataset: which fields are the
    keys, what the reformatted record holds, what it leaves out."""
    from ..sort_layout import map_sort, parse_sort_control, read_back

    if (step.program or "").upper() not in _SORT_PROGRAMS or not lines:
        return None
    control = parse_sort_control(lines)
    if not (
        control.sort_keys
        or control.tests
        or control.inrec
        or control.outrec
        or control.not_mapped
    ):
        return None
    sortin = next(
        (
            dd
            for dd in step.dd_statements
            if (dd.name or "").upper().startswith(("SORTIN", "SORTJNF")) and dd.dataset
        ),
        None,
    )
    if sortin is None or sortin.dataset is None:
        return None
    layout = layouts.of(sortin.dataset)
    if layout is None:
        return {
            "input": sortin.dataset,
            "note": "no COBOL program under the root opens this dataset, so its "
            "record layout is unknown; read the positions against the "
            "layout's record_layout",
        }
    mapped = map_sort(control, layout["fields"], int(layout["length"] or 0))
    answer: dict[str, Any] = {
        "input": sortin.dataset,
        "input_layout": _layout_source(layout),
        **mapped,
    }
    output = _sort_output_layout(step, job, layouts)
    if output is not None:
        dataset, read_as = output
        rows = read_back(control, layout["fields"], read_as["fields"])
        if rows is not None:
            answer["output_read_as"] = {
                "dataset": dataset,
                **_layout_source(read_as),
                "fields": rows[:SORT_READ_BACK_FIELDS],
            }
    return answer


def _layout_source(layout: dict[str, Any]) -> dict[str, Any]:
    return {
        k: layout[k]
        for k in ("record", "declared_at", "length", "how")
        if layout.get(k) is not None
    }


def _sort_output_layout(
    step: JobStep, job: JclJob | None, layouts: _Layouts
) -> tuple[str, dict[str, Any]] | None:
    """The layout a program reads the SORTOUT dataset through: directly,
    or after a later IDCAMS REPRO of the same job copies it (a sorted
    sequential file loaded into a KSDS)."""
    out = next(
        (
            dd.dataset
            for dd in step.dd_statements
            if (dd.name or "").upper() == "SORTOUT" and dd.dataset
        ),
        None,
    )
    if out is None:
        return None
    datasets = [out]
    later = job.steps[job.steps.index(step) + 1 :] if job and step in job.steps else []
    for other in later:
        if (other.program or "").upper() != "IDCAMS":
            continue
        uses = _utility_uses(other) or {}
        cards = {(dd.name or "").upper(): dd.dataset for dd in other.dd_statements}
        named = {
            key: key[4:] if key.startswith("DSN:") else cards.get(key) for key in uses
        }
        if any(
            use == "read" and _base(named[key] or "").upper() == _base(out).upper()
            for key, use in uses.items()
        ):
            datasets += [
                found
                for key, use in uses.items()
                if use == "write" and (found := named[key])
            ]
    for dataset in datasets:
        layout = layouts.of(dataset)
        if layout is not None:
            return dataset, layout
    return None
