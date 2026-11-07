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

Like the other tool modules, nothing here imports the MCP SDK. The JCL files under the
root (``.jcl`` / ``.job``) are parsed once into the ``jcl`` index
(:meth:`.Workspace.index`) and again only when one of them, or a procedure
member, changes. Cataloged procedures are looked up in every directory under
the root that holds a ``.prc`` / ``.proc`` member, one member per procedure,
named after it.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..._lines import split_source_lines
from ...jcl.models import DDStatement, JclParseResult, JobStep
from ...models.program import CobolProgram
from ..envelope import Response, ToolError
from ..workspace import ParsedProgram, Stamp, Workspace, _stamp

#: Suffixes of the JCL files the root-wide tools read.
JCL_SUFFIXES: tuple[str, ...] = (".jcl", ".job")


#: Suffixes of cataloged procedure members; a directory under the root
#: holding one is a procedure library, whose members are only files so named
#: (a program source of the same name beside them is never read as one).
PROC_SUFFIXES: tuple[str, ...] = (".prc", ".proc")


#: Members of a directory named as a procedure library -- ``cobol.yml``'s
#: ``project.proc_path``, or a ``JCLLIB ORDER=`` library -- may also be
#: ``.jcl`` / ``.cntl`` files or have no suffix at all, as members
#: downloaded from a PDS usually do.
LIBRARY_SUFFIXES: tuple[str, ...] = (".prc", ".proc", ".jcl", ".cntl", "")


#: ``// JCLLIB ORDER=(A.B,C.D)`` or ``ORDER=A.B``: the libraries a job's
#: procedures are searched in first. A parenthesized list may be continued
#: over several cards.
#: A ``//*`` comment card never matches: commenting out a JCLLIB line is how
#: a job is switched back from a test library (#749).
_JCLLIB = re.compile(
    r"^//(?!\*)\S*\s+JCLLIB\s+ORDER=(\([^)]*\)|[^\s,]+)",
    re.IGNORECASE | re.MULTILINE,
)


#: A DD card that starts in-stream data: ``DD *`` or ``DD DATA``, with the
#: ``DLM=`` that ends it when it has one.
_INSTREAM_DD = re.compile(
    r"^//(?!\*)\S*\s+DD\s+(\*|DATA)(?=[\s,]|$)(?:.*?\bDLM=(?:'([^']{2})'|(\S{2})))?",
    re.IGNORECASE,
)


def _job_cards(text: str) -> str:
    """*text* without its in-stream data: the records after a ``DD *`` /
    ``DD DATA`` card up to the ``/*`` (or ``DLM=``) that ends them. A
    ``DD *`` also ends at the next ``//`` card; ``DD DATA`` does not. A job
    submitted through INTRDR has its own JCLLIB, which is not the outer
    job's (#749)."""
    kept: list[str] = []
    delimiter: str | None = None
    ends_at_card = False
    for line in split_source_lines(text):
        if delimiter is not None:
            if line.startswith(delimiter):
                delimiter = None
                continue
            if not (ends_at_card and line.startswith("//")):
                kept.append("")
                continue
            delimiter = None
        kept.append(line)
        match = _INSTREAM_DD.match(line)
        if match:
            delimiter = match.group(2) or match.group(3) or "/*"
            ends_at_card = match.group(1) == "*" and delimiter == "/*"
    return "\n".join(kept)


def _jcllib_names(text: str) -> list[str]:
    """The libraries every ``JCLLIB ORDER=`` of *text* names, upper-cased,
    in order, each once. Comment cards and in-stream data are not looked
    at."""
    names: list[str] = []
    for match in _JCLLIB.finditer(_job_cards(text)):
        operand = re.sub(r"^//", " ", match.group(1), flags=re.MULTILINE)
        for raw in re.split(r"[,\s()]+", operand):
            name = raw.strip("'").upper()
            if name and name not in names:
                names.append(name)
    return names


INSTALL_HINT = (
    "the JCL tools read JCL through jcl-parser, which is not installed: "
    "pip install 'cobol-parser[jcl]'"
)


#: An unnamed DD card: a concatenation member.
_UNNAMED_DD = re.compile(r"^//\s+DD(\s|$)")


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
    #: Procedure name (upper-cased) -> the member its expansion read.
    members: dict[str, Path] = field(default_factory=dict)
    #: ``JCLLIB ORDER=`` libraries no directory under the root is named for.
    missing_libraries: list[str] = field(default_factory=list)
    #: The procedure libraries searched for this file, in order.
    libraries: list[Path] = field(default_factory=list)


@dataclass
class Libraries:
    """Where the root's cataloged procedures are, in search order.

    A job's ``JCLLIB ORDER=`` libraries come first (a directory under the
    root named exactly as the library, ``SYS1.PROCLIB/``), then ``cobol.yml``'s
    ``project.proc_path`` folders and any directory whose name contains
    ``PROCLIB`` (members with any of :data:`LIBRARY_SUFFIXES`), then every
    other directory holding a ``.prc`` / ``.proc`` member. The first member of
    a name wins, as in a PROCLIB concatenation.
    """

    #: ``proc_path`` folders, then folders named like a PROCLIB.
    configured: list[Path] = field(default_factory=list)
    #: ``proc_path`` entries outside the root, never opened.
    skipped: list[str] = field(default_factory=list)
    discovered: list[Path] = field(default_factory=list)
    #: Upper-cased directory name -> the directory, for ``JCLLIB ORDER=``.
    by_name: dict[str, Path] = field(default_factory=dict)

    def for_text(self, text: str) -> tuple[dict[str, Path], list[str], list[Path]]:
        """The members a JCL file's procedures resolve to, the ``JCLLIB``
        libraries of it no directory is named for, and the directories
        searched, in order."""
        from ...jcl.parser import _library_members

        order: list[tuple[Path, tuple[str, ...]]] = []
        missing: list[str] = []
        for name in _jcllib_names(text):
            directory = self.by_name.get(name)
            if directory is None:
                missing.append(name)
            else:
                order.append((directory, LIBRARY_SUFFIXES))
        order += [(d, LIBRARY_SUFFIXES) for d in self.configured]
        order += [(d, PROC_SUFFIXES) for d in self.discovered]
        members: dict[str, Path] = {}
        for directory, suffixes in order:
            for name, path in _library_members([directory], suffixes).items():
                members.setdefault(name, path)
        searched = list(dict.fromkeys(d for d, _ in order))
        return members, missing, searched


def jcllib_directories(libraries: Libraries, files: list[Path]) -> list[Path]:
    """The directories the ``JCLLIB ORDER=`` statements of *files* name."""
    found: list[Path] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name in _jcllib_names(text):
            directory = libraries.by_name.get(name)
            if directory is not None and directory not in found:
                found.append(directory)
    return found


def procedure_libraries(workspace: Workspace) -> Libraries:
    """The root's procedure libraries (see :class:`Libraries`)."""
    configured, skipped = workspace.proc_directories()
    discovered = sorted(
        {p.parent for p in workspace.files_named(PROC_SUFFIXES)} - set(configured)
    )
    by_name: dict[str, Path] = {}
    for directory, _names in workspace._walk():
        path = Path(directory).resolve()
        by_name.setdefault(path.name.upper(), path)
        if "PROCLIB" in path.name.upper() and path not in configured:
            configured.append(path)
    discovered = [d for d in discovered if d not in configured]
    return Libraries(configured, skipped, discovered, by_name)


@dataclass
class JclIndex:
    files: list[JclFile] = field(default_factory=list)
    libraries: Libraries = field(default_factory=Libraries)
    seconds: float = 0.0

    def parsed(self) -> list[JclFile]:
        return [f for f in self.files if f.result is not None]


def jcl_index(workspace: Workspace) -> JclIndex:
    """Every JCL file under the root, parsed; rebuilt when one changes."""

    def build() -> tuple[JclIndex, dict[str, Stamp]]:
        started = time.monotonic()
        stamps = workspace.tree_stamps()
        libraries = procedure_libraries(workspace)
        for directory in libraries.configured:
            # A proc_path folder may sit where the tree walk does not look.
            stamps[str(directory)] = _stamp(str(directory))
        # A .jcl member of a procedure library is a procedure, not a job.
        files = [
            p
            for p in workspace.files_named(JCL_SUFFIXES)
            if p.parent not in libraries.configured
        ]
        index = JclIndex(libraries=libraries)
        for done, path in enumerate(files):
            workspace.report_progress(done, len(files), "reading JCL")
            stamps[str(path)] = _stamp(str(path))
            jfile = _parse(libraries, workspace, path)
            for member in jfile.members.values():
                stamps[str(member)] = _stamp(str(member))
            index.files.append(jfile)
        index.seconds = time.monotonic() - started
        return index, stamps

    require_jcl()
    result: JclIndex = workspace.index("jcl", build)
    return result


def _parse(libraries: Libraries, workspace: Workspace, path: Path) -> JclFile:
    """*path* parsed with the procedure members its own ``JCLLIB`` and the
    root's libraries resolve to."""
    from ...jcl.parser import JclParser

    display = workspace.display(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return JclFile(path, display, failure=str(exc))
    members, missing, searched = libraries.for_text(text)
    jfile = JclFile(
        path,
        display,
        members=members,
        missing_libraries=missing,
        libraries=searched,
    )
    try:
        jfile.result = JclParser(library=members).parse(text, filename=display)
        return jfile
    except ImportError as exc:
        raise ToolError(INSTALL_HINT) from exc
    except Exception as exc:  # noqa: BLE001 -- reported as the file's failure
        jfile.failure = f"{type(exc).__name__}: {exc}"
        return jfile


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

    def __init__(self, jfile: JclFile, workspace: Workspace):
        assert jfile.result is not None
        self.jfile = jfile
        self.workspace = workspace
        self.members = jfile.members
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


def _source_files(workspace: Workspace) -> dict[str, str]:
    """Upper-cased member name -> the COBOL source file of that name.

    ``PGM=`` names a load module, which on z/OS is named after the source
    member, not after its PROGRAM-ID; so the file stem is the match.
    """
    found: dict[str, str] = {}
    for path in workspace.program_files():
        found.setdefault(path.stem.upper(), workspace.display(path))
    return found


def run_by(workspace: Workspace, names: set[str]) -> list[dict[str, Any]] | None:
    """The JCL steps under the root that run a program called any of
    *names* (its PROGRAM-ID, its member name): ``{job, step, file,
    location}`` each, for a brief; None when the ``[jcl]`` extra is missing
    or the root holds no JCL."""
    if not jcl_available():
        return None
    index = jcl_index(workspace)
    if not index.files:
        return None
    rows: list[dict[str, Any]] = []
    for jfile in index.parsed():
        assert jfile.result is not None
        locator: _Locator | None = None
        for name in sorted(names):
            for step in jfile.result.steps_running(name):
                job = next((j for j in jfile.result.jobs if step in j.steps), None)
                locator = locator or _Locator(jfile, workspace)
                rows.append(
                    {
                        "job": job.name if job else None,
                        "step": step.name,
                        "file": jfile.display,
                        "location": locator.step(step),
                    }
                )
    return rows


def programs_run_by_jcl(workspace: Workspace) -> set[str]:
    """Every program name a JCL step under the root runs (``PGM=``, or a
    launcher's ``RUN PROGRAM`` / ``PARM``), procedures expanded; empty
    without the ``[jcl]`` extra."""
    if not jcl_available():
        return set()
    names: set[str] = set()
    for jfile in jcl_index(workspace).parsed():
        assert jfile.result is not None
        for job in jfile.result.jobs:
            for step in job.steps:
                names.update(p.upper() for p in step.effective_programs())
    return names


def step_dds(
    workspace: Workspace, names: set[str]
) -> list[tuple[str, dict[str, str | None]]]:
    """Each JCL step that runs a program called any of *names*, as
    ``"FILE JOB.STEP"`` and the DDs it codes, name -> dataset (procedures
    expanded); empty when the ``[jcl]`` extra is missing or the root holds
    no JCL."""
    if not jcl_available():
        return []
    index = jcl_index(workspace)
    found: list[tuple[str, dict[str, str | None]]] = []
    for jfile in index.parsed():
        assert jfile.result is not None
        for name in sorted(names):
            for step in jfile.result.steps_running(name):
                job = next((j for j in jfile.result.jobs if step in j.steps), None)
                label = f"{jfile.display} {job.name if job else '?'}.{step.name}"
                dds = {
                    (dd.name or "").upper(): dd.dataset
                    for dd in step.dd_statements
                    if dd.name
                }
                found.append((label, dds))
    return found


def program_dds(parsed: ParsedProgram, unit: CobolProgram) -> list[str]:
    """The DD names a program's SELECTs need: not OPTIONAL, not a sort work
    file, not a run-time ASSIGN USING."""
    rows = _selects(parsed, unit, Response())
    return sorted(
        {
            str(r["ddname"]).upper()
            for r in rows
            if r.get("ddname") and not r.get("optional") and not r.get("sort_work_file")
        }
    )


def _program_selects(
    workspace: Workspace, name: str, response: Response
) -> dict[str, Any] | None:
    """The COBOL source of *name* and its ``SELECT``s, or None when the
    program is not under the root."""
    file = _source_files(workspace).get(name) or _declaring_file(workspace, name)
    if file is None:
        return None
    from .common import _attempt

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
    from ...analysis.field_lineage import normalize_ddname
    from ...analysis.xref import _contained_node_ids
    from ...models.statements.misc import SelectStatement
    from .common import _file_facts

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
