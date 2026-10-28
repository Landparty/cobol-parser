"""The JCL tools: how the programs under the root are run.

A COBOL program names its files by DD name (``SELECT INV-FILE ASSIGN TO
INVFILE``); only the JCL that runs it says which dataset ``INVFILE`` is,
which step runs the program, with what ``PARM=`` and under what condition.
These tools read that JCL, through :mod:`cobolparser.jcl` and so the
``jcl-parser`` package (the optional ``[jcl]`` extra), and join it to the
COBOL source under the same root:

* :func:`jcl_job` -- one JCL file: its jobs, steps, DD statements, the
  procedures it expands and the COBOL source of each program it runs.
* :func:`jobs_running` -- every step under the root that runs a program,
  with each of the program's ``SELECT`` files bound to its DD and dataset,
  and the DDs the program needs that the step does not code.
* :func:`dataset_users` -- every job, step and program that touches a
  dataset, and how (``DISP=``).

Without ``jcl-parser`` each tool answers with a :class:`ToolError` naming the
install command, never with an empty answer that would read as "no JCL".

Like :mod:`.tools`, nothing here imports the MCP SDK. The JCL files under the
root (``.jcl`` / ``.job``) are parsed once into the ``jcl`` index
(:meth:`.Workspace.index`) and again only when one of them, or a procedure
member, changes. Cataloged procedures are looked up in every directory under
the root that holds a ``.prc`` / ``.proc`` member, one member per procedure,
named after it.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .._lines import split_source_lines
from ..jcl.models import DDStatement, JclJob, JclParseResult, JobStep
from ..models.program import CobolProgram
from .envelope import Response, ToolError, clamp_limit
from .workspace import ParsedProgram, Stamp, Workspace, _stamp

#: Suffixes of the JCL files the root-wide tools read.
JCL_SUFFIXES: tuple[str, ...] = (".jcl", ".job")

#: Suffixes of cataloged procedure members; their directories are the
#: procedure libraries.
PROC_SUFFIXES: tuple[str, ...] = (".prc", ".proc")

#: In-stream data lines ``jcl_job`` shows per DD (a SORT's control cards,
#: a TSO step's ``RUN PROGRAM``); the count is always given.
MAX_INSTREAM_LINES = 20

INSTALL_HINT = (
    "the JCL tools read JCL through jcl-parser, which is not installed: "
    "pip install 'cobol-parser[jcl]'"
)

#: An unnamed DD card: a concatenation member.
_UNNAMED_DD = re.compile(r"^//\s+DD(\s|$)")

#: ``DISP=`` status -> what the step does with the dataset.
_ACCESS = {"SHR": "read", "OLD": "exclusive", "NEW": "create", "MOD": "extend"}


def jcl_available() -> bool:
    """True when ``jcl-parser`` is installed, so the JCL tools can answer."""
    try:
        import jclparser  # noqa: F401
    except ImportError:
        return False
    return True


def require_jcl() -> None:
    if not jcl_available():
        raise ToolError(INSTALL_HINT)


# ---------------------------------------------------------------------------
# the index
# ---------------------------------------------------------------------------


@dataclass
class JclFile:
    """One JCL file under the root, parsed, or why it could not be."""

    path: Path
    display: str
    result: JclParseResult | None = None
    failure: str | None = None


@dataclass
class JclIndex:
    files: list[JclFile] = field(default_factory=list)
    #: Directories searched for cataloged procedures, in order.
    libraries: list[Path] = field(default_factory=list)
    #: Procedure name (upper-cased) -> the member file it was read from.
    members: dict[str, Path] = field(default_factory=dict)
    seconds: float = 0.0

    def parsed(self) -> list[JclFile]:
        return [f for f in self.files if f.result is not None]


def jcl_index(workspace: Workspace) -> JclIndex:
    """Every JCL file under the root, parsed; rebuilt when one changes."""

    def build() -> tuple[JclIndex, dict[str, Stamp]]:
        from ..jcl.parser import JclParser, _library_members

        started = time.monotonic()
        stamps = workspace.tree_stamps()
        libraries = sorted({p.parent for p in workspace.files_named(PROC_SUFFIXES)})
        members = _library_members(libraries, PROC_SUFFIXES)
        for member in members.values():
            stamps[str(member)] = _stamp(str(member))
        parser = JclParser(libraries, PROC_SUFFIXES)
        files = workspace.files_named(JCL_SUFFIXES)
        index = JclIndex(libraries=libraries, members=members)
        for done, path in enumerate(files):
            workspace.report_progress(done, len(files), "reading JCL")
            stamps[str(path)] = _stamp(str(path))
            index.files.append(_parse(parser, workspace, path))
        index.seconds = time.monotonic() - started
        return index, stamps

    require_jcl()
    result: JclIndex = workspace.index("jcl", build)
    return result


def _parse(parser: Any, workspace: Workspace, path: Path) -> JclFile:
    display = workspace.display(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return JclFile(path, display, failure=str(exc))
    try:
        return JclFile(path, display, parser.parse(text, filename=display))
    except ImportError as exc:
        raise ToolError(INSTALL_HINT) from exc
    except Exception as exc:  # noqa: BLE001 -- reported as the file's failure
        return JclFile(path, display, failure=f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# locations
# ---------------------------------------------------------------------------


class _Locator:
    """``{file, line}`` for the cards of one parsed JCL file.

    A step expanded from a cataloged procedure carries the line numbers of
    the procedure member, while an override coded on the invocation
    (``//STEP.DD DD ...``) carries the job file's: each DD card is placed by
    reading the line it claims and checking it is that card.
    """

    def __init__(self, jfile: JclFile, index: JclIndex, workspace: Workspace):
        assert jfile.result is not None
        self.jfile = jfile
        self.workspace = workspace
        self.members = index.members
        self.in_stream = {name.upper() for name in jfile.result.procedures}
        self._lines: dict[Path, list[str]] = {}

    def _text(self, path: Path, line: int) -> str:
        if path not in self._lines:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            self._lines[path] = split_source_lines(text)
        lines = self._lines[path]
        return lines[line - 1].upper() if 0 < line <= len(lines) else ""

    def member(self, step: JobStep) -> Path | None:
        """The procedure member *step* was expanded from, or None when its
        cards are in the JCL file itself."""
        procedure = (step.procedure or "").upper()
        if "." not in step.name or not procedure or procedure in self.in_stream:
            return None
        return self.members.get(procedure)

    def at(self, path: Path, line: int) -> dict[str, Any] | None:
        if line <= 0:
            return None
        return {"file": self.workspace.display(path), "line": line}

    def step(self, step: JobStep) -> dict[str, Any] | None:
        return self.at(self.member(step) or self.jfile.path, step.line)

    def dd(
        self,
        step: JobStep | None,
        dd: DDStatement,
        owner: Path | None = None,
    ) -> Path:
        """The file *dd*'s card is in.

        *owner* is the file of the card that heads *dd*'s concatenation, when
        *dd* is an unnamed member of one: a member that follows an override
        on the invocation is coded in the job file too, but only when the
        job file really has an unnamed DD card at its line.
        """
        member = None if step is None else self.member(step)
        if member is None or step is None:
            return self.jfile.path
        procstep = step.name.split(".", 1)[1].upper()
        text = self._text(self.jfile.path, dd.line)
        if text.startswith(f"//{procstep}.{dd.name.upper()} "):
            return self.jfile.path
        if owner == self.jfile.path and _UNNAMED_DD.match(text):
            # The two files share line numbers: a dataset name coded on only
            # one of the two cards settles which it is.
            dataset = (dd.dataset or "").upper()
            in_member = bool(dataset) and dataset in self._text(member, dd.line)
            if not in_member or dataset in text:
                return self.jfile.path
        return member

    def flattened(
        self, step: JobStep | None, dd: DDStatement
    ) -> list[tuple[DDStatement, Path]]:
        """*dd* and its concatenation members, each with its card's file."""
        head = self.dd(step, dd)
        return [(dd, head)] + [
            (member, self.dd(step, member, head)) for member in dd.flatten()[1:]
        ]


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------


def _kind(dd: DDStatement) -> str:
    if dd.sysout is not None:
        return "sysout"
    if dd.is_dummy:
        return "dummy"
    if dd.is_instream:
        return "instream"
    if dd.dataset is None:
        return "unnamed"
    if dd.dataset.startswith("&&"):
        return "temporary"
    return "dataset"


def _access(disposition: str | None) -> str:
    """What a ``DISP=`` says the step does: read, exclusive, create, extend.

    An omitted status (``DISP=(,CATLG)``, or no ``DISP`` at all) is NEW.
    """
    status = (disposition or "").strip("()").split(",")[0].strip().upper()
    return _ACCESS.get(status or "NEW", status.lower())


def _dd_row(
    dd: DDStatement,
    step: JobStep | None,
    locator: _Locator,
    *,
    instream: bool = False,
) -> dict[str, Any]:
    cards = locator.flattened(step, dd)
    path = cards[0][1]
    row: dict[str, Any] = {"ddname": dd.name, "kind": _kind(dd)}
    if dd.dataset is not None:
        row["dataset"] = dd.dataset
        row["disposition"] = dd.disposition
        row["access"] = _access(dd.disposition)
    if dd.sysout is not None:
        row["sysout_class"] = dd.sysout
    if dd.record_format:
        row["record_format"] = dd.record_format
    if dd.record_length is not None:
        row["record_length"] = dd.record_length
    if dd.procstep:
        # Left on the invocation: the override names no step of the PROC.
        row["unapplied_override"] = f"{dd.procstep}.{dd.name}"
    if dd.is_instream:
        row["instream_line_count"] = len(dd.instream_lines)
        if instream:
            row["instream_lines"] = dd.instream_lines[:MAX_INSTREAM_LINES]
    row["location"] = locator.at(path, dd.line)
    if dd.concatenated:
        row["concatenated"] = [
            {
                "dataset": member.dataset,
                "kind": _kind(member),
                "location": locator.at(member_path, member.line),
            }
            for member, member_path in cards[1:]
        ]
    return row


def _step_row(
    step: JobStep, locator: _Locator, *, instream: bool = False
) -> dict[str, Any]:
    row: dict[str, Any] = {"name": step.name, "location": locator.step(step)}
    if step.program:
        row["program"] = step.program
        runs = step.effective_programs()
        if runs != [step.program.upper()]:
            # A launcher: IKJEFT01's RUN PROGRAM, DFSRRC00's PARM program.
            row["runs"] = runs
    if step.procedure:
        key = "from_procedure" if "." in step.name else "invokes_procedure"
        row[key] = step.procedure
    if step.parm is not None:
        row["parm"] = step.parm
    if step.condition:
        row["condition"] = step.condition
    row["dds"] = [
        _dd_row(dd, step, locator, instream=instream) for dd in step.dd_statements
    ]
    return row


def _carry_file(jfile: JclFile, response: Response) -> None:
    """One file's parse errors and what it could not resolve, as caveats."""
    from .tools import _notes

    result = jfile.result
    assert result is not None
    if result.errors:
        lines = ", ".join(str(e.get("line")) for e in result.errors[:5])
        response.caveat(
            "partial-parse",
            f"{jfile.display}: {len(result.errors)} JCL statement(s) could not "
            f"be read (line {lines})",
            "the steps and DD statements coded there are missing",
        )
    _notes(
        response,
        "incomplete-analysis",
        list(result.unresolved),
        "a procedure or INCLUDE member not found, or a symbol left "
        "unsubstituted, may hide steps or change dataset names",
        lead=jfile.display,
    )


def _carry_index(index: JclIndex, response: Response) -> None:
    """The root's JCL gaps, summarized: one caveat per kind, not per file."""
    from .tools import _notes

    _notes(
        response,
        "incomplete-analysis",
        [f"{f.display}: {f.failure}" for f in index.files if f.failure],
        "the steps in those files are not in this answer",
        lead="JCL files that could not be read",
    )
    _notes(
        response,
        "partial-parse",
        [f.display for f in index.parsed() if f.result and f.result.errors],
        "statements that could not be read are missing; jcl_job on a file "
        "names the lines",
        lead="JCL files read with errors",
    )
    _notes(
        response,
        "incomplete-analysis",
        [f.display for f in index.parsed() if f.result and f.result.unresolved],
        "a procedure or symbol not found there may hide steps or change "
        "dataset names; jcl_job on a file says which",
        lead="JCL files with unresolved procedures or symbols",
    )


def _source_files(workspace: Workspace) -> dict[str, str]:
    """Upper-cased member name -> the COBOL source file of that name.

    ``PGM=`` names a load module, which on z/OS is named after the source
    member, not after its PROGRAM-ID; so the file stem is the match.
    """
    found: dict[str, str] = {}
    for path in workspace.program_files():
        found.setdefault(path.stem.upper(), workspace.display(path))
    return found


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
        from ..jcl.parser import JclParser

        jfile = _parse(JclParser(index.libraries, PROC_SUFFIXES), workspace, path)
    if jfile.result is None:
        raise ToolError(f"cannot read {jfile.display}: {jfile.failure}")
    result = jfile.result
    response = Response()
    locator = _Locator(jfile, index, workspace)
    _carry_file(jfile, response)

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
    programs: dict[str, str | None] = {}
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
                programs[name] = sources.get(name)
        rows.append(_job_row(each, shown, locator))
    if step and not any(row["steps"] for row in rows):
        names = [s.name for j in jobs for s in j.steps]
        raise ToolError(
            f"no step named {step!r} in {jfile.display} (found: "
            f"{', '.join(names) or 'none'})"
        )
    answer: dict[str, Any] = {"file": jfile.display, "jobs": rows}
    if programs:
        answer["program_sources"] = programs
    procedures = _procedures(jobs, result, index, workspace)
    if procedures:
        answer["procedures"] = procedures
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
    row["steps"] = [_step_row(s, locator, instream=True) for s in steps]
    return row


def _procedures(
    jobs: list[JclJob],
    result: JclParseResult,
    index: JclIndex,
    workspace: Workspace,
) -> list[dict[str, Any]]:
    """Every procedure the jobs invoke, and where its cards were read."""
    in_stream = {name.upper() for name in result.procedures}
    seen: dict[str, dict[str, Any]] = {}
    for job in jobs:
        for step in job.steps:
            name = (step.procedure or "").upper()
            if not name or name in seen:
                continue
            if name in in_stream:
                seen[name] = {"name": name, "source": "in-stream"}
            elif name in index.members:
                seen[name] = {
                    "name": name,
                    "source": workspace.display(index.members[name]),
                }
            else:
                seen[name] = {"name": name, "source": None, "expanded": False}
    return list(seen.values())


# ---------------------------------------------------------------------------
# jobs_running
# ---------------------------------------------------------------------------


def jobs_running(
    workspace: Workspace, program: str, limit: int | None = None
) -> dict[str, Any]:
    """Every JCL step under the root that runs *program*, joined to its
    COBOL source's ``SELECT`` files."""
    name = program.strip().upper()
    if not name:
        raise ToolError("no program given")
    index = jcl_index(workspace)
    response = Response()
    _carry_index(index, response)
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
    shown = response.cap(matches, clamp_limit(limit), "steps")
    locators: dict[Path, _Locator] = {}
    rows = []
    for jfile, job, step in shown:
        locator = locators.setdefault(jfile.path, _Locator(jfile, index, workspace))
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
    if not matches:
        answer["note"] = (
            f"no JCL step under the root runs {name}"
            + ("" if index.files else " (the root holds no .jcl / .job file)")
            + ": it may be CALLed by another program (callers_of), started "
            "by CICS or IMS, or run by JCL that is not under the root"
        )
    return response.build(answer)


def _program_selects(
    workspace: Workspace, name: str, response: Response
) -> dict[str, Any] | None:
    """The COBOL source of *name* and its ``SELECT``s, or None when the
    program is not under the root."""
    file = _source_files(workspace).get(name) or _declaring_file(workspace, name)
    if file is None:
        return None
    from .tools import _attempt

    try:
        parsed = workspace.program(file)
    except ToolError as exc:
        # The steps stand without the source; only the SELECT join is lost.
        response.caveat(
            "analyzer-failed",
            f"{file} (the source of {name}): {exc}",
            "its SELECT files are not bound to the steps' DDs",
        )
        return None
    unit = parsed.ast.find_program_unit(name) or parsed.ast
    files = _attempt(response, "SELECT files", lambda: _selects(parsed, unit, response))
    if files is None:
        return None
    return {"source": parsed.program_info(unit), "files": files}


def _declaring_file(workspace: Workspace, name: str) -> str | None:
    """The program file whose text declares ``PROGRAM-ID. name``, for a source
    not named after its load module. A text scan, not a parse: a utility
    such as SORT or IEFBR14 is in no file, and finding that out must not
    cost a parse of every program under the root."""
    declares = re.compile(
        rf"PROGRAM-ID\s*\.?\s*['\"]?{re.escape(name)}(?![\w-])", re.IGNORECASE
    )
    for path in workspace.program_files():
        try:
            text = path.read_text(encoding="latin-1")
        except OSError:
            continue
        if declares.search(text):
            return workspace.display(path)
    return None


def _selects(
    parsed: ParsedProgram, unit: CobolProgram, response: Response
) -> list[dict[str, Any]]:
    from ..analysis.field_lineage import normalize_ddname
    from ..analysis.xref import _contained_node_ids
    from ..models.statements.misc import SelectStatement
    from .tools import _file_facts

    facts = _file_facts(parsed, unit)
    inner = _contained_node_ids(unit)
    rows: list[dict[str, Any]] = []
    for node in unit.traverse_depth_first():
        if id(node) in inner or not isinstance(node, SelectStatement):
            continue
        if not node.file_name:
            continue
        row: dict[str, Any] = {"file_name": node.file_name}
        if node.assign_using:
            # The DD is a data item's value at run time.
            row["ddname"] = None
            row["assign_using"] = node.assign_using
        else:
            row["ddname"] = (
                normalize_ddname(node.assign_external_name or node.assign_to) or None
            )
        if node.is_optional:
            row["optional"] = True
        fact = facts.get(node.file_name.upper())
        if fact is not None and fact.record_type == "SD":
            row["sort_work_file"] = True
        row["declared_at"] = parsed.locate(
            node.location.line if node.location else None,
            None,
            response,
            column_known=False,
        )
        rows.append(row)
    return rows


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


# ---------------------------------------------------------------------------
# dataset_users
# ---------------------------------------------------------------------------


def _base(dataset: str) -> str:
    """*dataset* without a member or GDG generation: ``A.B(+1)`` -> ``A.B``."""
    return dataset.split("(", 1)[0]


def _filter_regex(pattern: str) -> re.Pattern[str]:
    """A z/OS dataset name filter as a regex: ``%`` is one character, ``*``
    any characters within one qualifier, ``**`` any number of qualifiers
    (``A.**`` is ``A`` and everything under it)."""
    out = ""
    qualifiers = pattern.split(".")
    for n, qualifier in enumerate(qualifiers):
        if qualifier == "**":
            if n == 0:
                out = r"(?:[^.]+\.)*" if len(qualifiers) > 1 else r".+"
            else:
                out = out[:-2] + r"(?:\.[^.]+)*\."
            continue
        out += "".join(
            "[^.]*" if c == "*" else "[^.]" if c == "%" else re.escape(c)
            for c in qualifier
        )
        out += r"\."
    if out.endswith(r"\."):
        out = out[:-2]
    return re.compile(out)


def _matcher(pattern: str) -> Callable[[str], bool]:
    wanted = pattern.strip().strip("'").upper()
    if not wanted:
        raise ToolError("no dataset given")
    if any(c in wanted for c in "*%"):
        regex = _filter_regex(wanted)
        return lambda ds: bool(regex.fullmatch(ds) or regex.fullmatch(_base(ds)))
    if "(" in wanted:
        return lambda ds: ds == wanted
    return lambda ds: _base(ds) == wanted


def _cards(
    result: JclParseResult, locator: _Locator
) -> list[tuple[JclJob, JobStep | None, DDStatement, Path]]:
    """Every DD card, as ``all_dd_statements()`` lists them, with its file."""
    out: list[tuple[JclJob, JobStep | None, DDStatement, Path]] = []
    for job in result.jobs:
        for dd in job.dd_statements:
            out += [(job, None, m, p) for m, p in locator.flattened(None, dd)]
        for step in job.steps:
            for dd in step.dd_statements:
                out += [(job, step, m, p) for m, p in locator.flattened(step, dd)]
    return out


def dataset_users(
    workspace: Workspace, dataset: str, limit: int | None = None
) -> dict[str, Any]:
    """Every DD under the root that names *dataset*, and what it does."""
    matches = _matcher(dataset)
    index = jcl_index(workspace)
    response = Response()
    _carry_index(index, response)

    found: list[dict[str, Any]] = []
    for jfile in index.parsed():
        assert jfile.result is not None
        locator = _Locator(jfile, index, workspace)
        for job, step, dd, path in _cards(jfile.result, locator):
            if dd.dataset is None or not matches(dd.dataset.upper()):
                continue
            row: dict[str, Any] = {
                "dataset": dd.dataset,
                "file": jfile.display,
                "job": job.name,
                "step": None if step is None else step.name,
                "programs": [] if step is None else step.effective_programs(),
                "ddname": dd.name,
                "disposition": dd.disposition,
                "access": _access(dd.disposition),
                "location": locator.at(path, dd.line),
            }
            if dd.dataset.startswith("&&"):
                row["temporary"] = True
            found.append(row)

    by_access: dict[str, list[str]] = {}
    for row in found:
        bucket = by_access.setdefault(row["access"], [])
        for name in row["programs"] or [f"{row['job']}.{row['step'] or 'JOB'}"]:
            if name not in bucket:
                bucket.append(name)
    answer: dict[str, Any] = {
        "dataset": dataset.strip().strip("'").upper(),
        "use_count": len(found),
        "by_access": by_access,
        "jobs": sorted({row["job"] for row in found}),
        "uses": response.cap(found, clamp_limit(limit), "uses"),
        "jcl_files": len(index.files),
    }
    if not found:
        answer["note"] = "no DD under the root names this dataset" + (
            "" if index.files else " (the root holds no .jcl / .job file)"
        )
    elif any(row.get("temporary") for row in found):
        answer["temporary_note"] = (
            "a && temporary dataset exists only within its job: uses in "
            "different jobs are different datasets"
        )
    return response.build(answer)
