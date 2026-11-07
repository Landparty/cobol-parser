"""The ``jobs_running`` tool: every step that runs a program, its ``SELECT``
files bound to DDs, the job flow around it and, optionally, the programs it
CALLs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...jcl.models import JclJob, JobStep
from ..envelope import Response, ToolError, clamp_limit
from ..workspace import Workspace
from .jcl_common import (
    _MEMBER_RE,
    _WRITES,
    JOB_FLOW_STEPS,
    _access,
    _base,
    _carry_index,
    _control_lines,
    _ControlMembers,
    _idcams_named,
    _NoProgramUses,
    _other_language_source,
    _ProgramUses,
    _step_access,
    _step_row,
    explain_condition,
    run_order,
)
from .jcl_index import JclFile, _Locator, _program_selects, jcl_index
from .jcl_job import _Layouts, _sort_layout

#: Jobs ``jobs_running`` lays out step by step (``jobs``); ``steps`` lists
#: every step that runs the program whatever this says.
JOB_FLOWS_SHOWN = 5


#: Control-card lines a job flow shows per DD (SYSIN, SYMNAMES, ...).
FLOW_CONTROL_LINES = 12


#: DD names a job flow leaves out: libraries and print, not data.
_FLOW_SKIPPED_DDS = frozenset({"STEPLIB", "JOBLIB", "SYSLIB", "SYSUDUMP", "SYSABEND"})


# ---------------------------------------------------------------------------
# jobs_running
# ---------------------------------------------------------------------------


def jobs_running(
    workspace: Workspace,
    program: str,
    limit: int | None = None,
    follow_calls: bool = False,
) -> dict[str, Any]:
    """Every JCL step under the root that runs *program*, joined to its
    COBOL source's ``SELECT`` files; with *follow_calls*, also every program
    it runs in turn through CALL / LINK / XCTL, in any language."""
    name = program.strip().upper()
    if not name:
        raise ToolError("no program given")
    index = jcl_index(workspace)
    response = Response()
    selects = _program_selects(workspace, name, response)

    matches: list[tuple[JclFile, JclJob, JobStep]] = []
    for jfile in index.parsed():
        assert jfile.result is not None
        running = {id(step) for step in jfile.result.steps_running(name)}
        matches += [
            (jfile, job, step)
            for job in jfile.result.jobs
            for step in job.steps
            if id(step) in running
        ]
    _carry_index(index, response, name, {jfile.display for jfile, _, _ in matches})
    shown = response.cap(matches, clamp_limit(limit), "steps")
    locators: dict[Path, _Locator] = {}
    rows = []
    for jfile, job, step in shown:
        locator = locators.setdefault(jfile.path, _Locator(jfile, workspace))
        row: dict[str, Any] = {"file": jfile.display, "job": job.name}
        row.update(_step_row(step, locator))
        if selects is not None:
            _join_selects(row, selects["files"])
        rows.append(row)

    answer: dict[str, Any] = {
        "program": name,
        "jcl_files": len(index.files),
        "step_count": len(matches),
        "steps": rows,
    }
    if selects is not None:
        answer["source"] = selects["source"]
        answer["files"] = selects["files"]
    else:
        other = _other_language_source(workspace, name)
        if other is not None:
            answer["source"] = other
            response.caveat(
                "incomplete-analysis",
                f"{name} is {other['language']} source ({other['file']}), whose "
                "parser reads no file declarations",
                "its DDs are not bound to the files it opens; dataset access "
                "comes from DISP alone",
            )
    jobs: dict[tuple[str, str], tuple[JclFile, JclJob, set[int]]] = {}
    for jfile, job, step in matches:
        held = jobs.setdefault((jfile.display, job.name or ""), (jfile, job, set()))
        held[2].add(id(step))
    flows = response.cap(
        list(jobs.values()), min(clamp_limit(limit), JOB_FLOWS_SHOWN), "jobs"
    )
    if flows:
        # A utility's jobs (SORT runs in hundreds) are laid out from DISP
        # and the utilities' own DD roles: no COBOL program is parsed for
        # them, as for the rest of this answer.
        programs = (
            _ProgramUses(workspace, response)
            if selects is not None
            else _NoProgramUses(workspace, response)
        )
        members = _ControlMembers(workspace)
        layouts = _Layouts(workspace) if selects is not None else None
        answer["jobs"] = [
            _job_flow(
                jfile,
                job,
                locators.setdefault(jfile.path, _Locator(jfile, workspace)),
                programs,
                members,
                running,
                response,
                layouts,
            )
            for jfile, job, running in flows
        ]
    _also_named(workspace, name, answer, response)
    if follow_calls:
        _follow_calls(workspace, name, answer, response, clamp_limit(limit))
    if not matches:
        answer["note"] = (
            f"no JCL step under the root runs {name}"
            + ("" if index.files else " (the root holds no .jcl / .job file)")
            + ": it may be CALLed by another program (callers_of), started "
            "by CICS or IMS, or run by JCL that is not under the root"
        )
    return response.build(answer)


def _job_flow(
    jfile: JclFile,
    job: JclJob,
    locator: _Locator,
    programs: _ProgramUses,
    members: _ControlMembers,
    running: set[int],
    response: Response,
    layouts: _Layouts | None = None,
) -> dict[str, Any]:
    """One job, step by step: what each step runs, the datasets it reads and
    writes (by what the program or utility does with each DD, else DISP),
    the control cards it is given (in-stream, or the SYSIN member under the
    root), and ``fed_by``: the earlier step that wrote what this one reads.
    So "where does this report's data come from" is one answer, not a read
    of the JCL and every procedure it expands."""
    written_by: dict[str, str] = {}
    steps: list[dict[str, Any]] = []
    for step in job.steps[:JOB_FLOW_STEPS]:
        row: dict[str, Any] = {"step": step.name}
        if step.program:
            row["program"] = step.program
            runs = step.effective_programs()
            if runs != [step.program.upper()]:
                row["runs"] = runs
        if step.procedure:
            key = "from_procedure" if "." in (step.name or "") else "invokes_procedure"
            row[key] = step.procedure
        if step.condition:
            row["condition"] = step.condition
            meaning = explain_condition(step.condition)
            if meaning:
                row["condition_means"] = meaning
        if id(step) in running:
            row["runs_the_program"] = True
        reads: list[str] = []
        writes: list[str] = []
        fed_by: dict[str, str] = {}
        control: list[dict[str, Any]] = []
        for dd in step.dd_statements:
            ddname = (dd.name or "").upper()
            if ddname in _FLOW_SKIPPED_DDS:
                continue
            if dd.is_instream:
                lines = [ln.strip() for ln in dd.instream_lines if ln.strip()]
                if lines:
                    entry: dict[str, Any] = {
                        "dd": dd.name,
                        "lines": lines[:FLOW_CONTROL_LINES],
                    }
                    if len(lines) > FLOW_CONTROL_LINES:
                        entry["line_count"] = len(lines)
                    control.append(entry)
                continue
            for member_dd, _path in locator.flattened(step, dd):
                dataset = member_dd.dataset
                if not dataset or member_dd.sysout is not None or member_dd.is_dummy:
                    continue
                if dataset.upper() == "NULLFILE":
                    continue
                if ddname in ("SYSIN", "SYMNAMES", "TOOLIN", "DFSPARM", "CTLCARD"):
                    found = _MEMBER_RE.search(dataset)
                    path = (
                        members.find(found.group(1), jfile.display) if found else None
                    )
                    if path is not None:
                        lines = _control_lines(Workspace.read_text(path))
                        control.append(
                            {
                                "dd": dd.name,
                                "member": dataset,
                                "file": locator.workspace.display(path),
                                "lines": lines[:FLOW_CONTROL_LINES],
                            }
                        )
                        continue
                access, _from = _step_access(
                    step, member_dd, _access(member_dd.disposition), programs
                )
                label = f"{dd.name}={dataset}"
                base = _base(dataset).upper()
                if access in _WRITES:
                    writes.append(f"{label} ({access})")
                else:
                    reads.append(label)
                    if base in written_by:
                        fed_by[dataset] = written_by[base]
                if access in _WRITES:
                    written_by[base] = step.name or ""
        for named, access, command in _idcams_named(step):
            label = f"{command} {named}"
            if access == "read":
                reads.append(label)
            else:
                writes.append(f"{label} ({access})")
                written_by[_base(named).upper()] = step.name or ""
        if reads:
            row["reads"] = reads
        if writes:
            row["writes"] = writes
        if fed_by:
            row["fed_by"] = fed_by
        if control:
            row["control"] = control
        if layouts is not None:
            sysin: list[str] = next(
                (c["lines"] for c in control if c["dd"] == "SYSIN"), []
            )
            laid = _sort_layout(step, sysin, layouts, job)
            if laid is not None:
                row["sort_layout"] = laid
        steps.append(row)
    flow: dict[str, Any] = {
        "file": jfile.display,
        "job": job.name,
        "step_count": len(job.steps),
        "run_order": run_order(job.steps),
        "steps": steps,
    }
    if len(job.steps) > JOB_FLOW_STEPS:
        response.truncated.append(
            {
                "field": f"jobs[{job.name}].steps",
                "shown": JOB_FLOW_STEPS,
                "total": len(job.steps),
            }
        )
    return flow


def _follow_calls(
    workspace: Workspace,
    name: str,
    answer: dict[str, Any],
    response: Response,
    cap: int,
) -> None:
    """What a step running *name* executes beyond it: ``answer["calls"]``,
    the call chain in any language, and ``answer["languages_run"]``."""
    from ..codebase_index import call_chain
    from .common import _notes

    rows, notes = call_chain(workspace, name)
    languages = {
        str(s.get("language"))
        for s in [answer.get("source") or {}, *answer.get("sources", [])]
        if s.get("language")
    }
    if answer.get("source") and "language" not in answer["source"]:
        languages.add("COBOL")
    languages |= {str(r["language"]) for r in rows if r.get("language")}
    # A program found in two languages runs as one of them: both are named,
    # the duplicate-declaration caveat (or the row's also_in) says which.
    languages |= {str(alt["language"]) for r in rows for alt in r.get("also_in", [])}
    answer["calls"] = response.cap(rows, cap, "calls")
    answer["languages_run"] = sorted(languages)
    _notes(
        response,
        "incomplete-analysis",
        notes,
        "programs those dynamic CALLs reach are missing from calls",
        lead="the call chain could not be followed everywhere",
    )


def _named_sources(workspace: Workspace, name: str) -> list[dict[str, str]]:
    """Every source under the root that could be load module *name*, in any
    language: an outermost program unit of that name (COBOL, PL/I or
    assembler), a program file of that stem, and a source of that name these
    tools do not parse. ``{file, language}`` each, in a stable order."""
    from ..codebase_index import programs_index

    found: dict[str, str] = {}
    for unit in programs_index(workspace).units_named(name):
        if not unit.depth:
            found.setdefault(unit.file, unit.language)
    for path in workspace.program_files():
        if path.stem.upper() == name:
            found.setdefault(workspace.display(path), "COBOL")
    for path, language in workspace.other_sources().get(name, []):
        found.setdefault(workspace.display(path), language)
    return [{"file": f, "language": lang} for f, lang in sorted(found.items())]


def _also_named(
    workspace: Workspace, name: str, answer: dict[str, Any], response: Response
) -> None:
    """When more than one source could be *name*, list them all in
    ``answer["sources"]``: the JCL names a load module, and which source it
    was built from is up to the load library, not the JCL."""
    try:
        sources = _named_sources(workspace, name)
    except Exception:  # noqa: BLE001 -- the steps stand without this
        return
    if len(sources) < 2:
        return
    answer["sources"] = sources
    response.caveat(
        "duplicate-declaration",
        f"{len(sources)} sources under the root could be program {name}: "
        + ", ".join(f"{s['file']} ({s['language']})" for s in sources),
        "which one a step runs depends on the STEPLIB / JOBLIB load library, "
        "which the source does not say; the files bound to DDs here come from "
        "source",
    )


def _join_selects(row: dict[str, Any], files: list[dict[str, Any]]) -> None:
    """Mark each DD row with the COBOL file it backs, and list the files whose
    DD the step does not code."""
    by_dd: dict[str, list[str]] = {}
    for f in files:
        if f["ddname"]:
            by_dd.setdefault(f["ddname"].upper(), []).append(f["file_name"])
    for dd in row["dds"]:
        names = by_dd.get(dd["ddname"].upper())
        if names:
            dd["cobol_files"] = names
    coded = {dd["ddname"].upper() for dd in row["dds"]}
    missing = [
        {"file_name": f["file_name"], "ddname": f["ddname"]}
        for f in files
        if f["ddname"]
        and f["ddname"].upper() not in coded
        and not f.get("optional")
        and not f.get("sort_work_file")
    ]
    if missing:
        # An OPEN of a non-OPTIONAL file with no DD fails (status 35 / an
        # abend) -- unless this run never opens it, which only the program
        # flow can tell.
        row["dds_not_coded"] = missing
