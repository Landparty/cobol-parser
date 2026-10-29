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


#: In-stream data lines ``jcl_job`` shows per DD (a SORT's control cards,
#: a TSO step's ``RUN PROGRAM``); the count is always given.
MAX_INSTREAM_LINES = 20

#: Jobs ``jobs_running`` lays out step by step (``jobs``); ``steps`` lists
#: every step that runs the program whatever this says.
JOB_FLOWS_SHOWN = 5

#: Steps of one job ``jobs_running`` lays out in its ``jobs`` flow.
JOB_FLOW_STEPS = 40

#: Control-card lines a job flow shows per DD (SYSIN, SYMNAMES, ...).
FLOW_CONTROL_LINES = 12

#: Programs tried for the record layout of a SORT step input dataset.
SORT_LAYOUT_PROGRAMS = 6

#: Fields of the output layout a SORT step's ``output_read_as`` lists.
SORT_READ_BACK_FIELDS = 40

#: Suffixes of a control-card member a SYSIN ``DD DSN=LIB(MEMBER)`` may name
#: under the root (a PDS member downloaded as ``ctl/MEMBER.ctl``).
CONTROL_SUFFIXES: frozenset[str] = frozenset(
    {"", ".ctl", ".cntl", ".ctlcard", ".card", ".sysin", ".srt", ".sort", ".txt"}
)

#: DD names a job flow leaves out: libraries and print, not data.
_FLOW_SKIPPED_DDS = frozenset({"STEPLIB", "JOBLIB", "SYSLIB", "SYSUDUMP", "SYSABEND"})

#: What counts as writing a dataset in a job flow.
_WRITES = frozenset({"create", "write", "extend", "update", "exclusive", "delete"})

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
        from ..jcl.parser import _library_members

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
    from ..jcl.parser import JclParser

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


def _normal_disposition(disposition: str | None) -> str:
    """The normal-termination part of ``DISP=(status,normal,abnormal)``."""
    parts = (disposition or "").strip("()").split(",")
    return parts[1].strip().upper() if len(parts) > 1 else ""


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
        utility = None if step is None else _utility_uses(step)
        use = (utility or {}).get((dd.name or "").upper()) or (utility or {}).get(
            f"DSN:{dd.dataset.upper()}"
        )
        if use:
            # What SORT, IEBGENER, IDCAMS REPRO or IEFBR14 does with the DD,
            # not what DISP=SHR on a REPRO OUTFILE seems to say.
            row["access"] = _combine(use, row["access"])
            row["access_from"] = "utility"
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


#: ``COND=(code,op)``: the step is bypassed when ``code op RC`` holds, i.e.
#: when the return code stands in this relation to *code* ...
_COND_BYPASS = {
    "GT": "is less than",
    "GE": "is less than or equal to",
    "EQ": "is",
    "NE": "is not",
    "LT": "is greater than",
    "LE": "is greater than or equal to",
}
#: ... and so the step runs only when it stands in this one.
_COND_RUNS = {
    "GT": "is at least",
    "GE": "is greater than",
    "EQ": "is not",
    "NE": "is",
    "LT": "is at most",
    "LE": "is less than",
}
_COND_TEST = re.compile(r"(\d+)\s*,\s*(GT|GE|EQ|NE|LT|LE)(?:\s*,\s*([A-Z0-9@#$.]+))?")


def explain_condition(condition: str) -> str | None:
    """``COND=`` in plain words, since its sense is the reverse of how it
    reads: ``(0,NE)`` bypasses the step when 0 is not equal to a return
    code, so the step runs only if every earlier step returned 0. None for
    a form this does not read."""
    text = condition.strip().upper()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    parts: list[str] = []
    runs: list[str] = []
    special = None
    for word in ("EVEN", "ONLY"):
        if re.search(rf"(^|,)\s*{word}\s*(,|$)", text):
            special = word
    tests = _COND_TEST.findall(text)
    if not tests and special is None:
        return None
    for code, op, step in tests:
        whose = (
            f"step {step}'s return code" if step else "any earlier step's return code"
        )
        every = (
            f"step {step}'s return code" if step else "every earlier step's return code"
        )
        parts.append(f"{whose} {_COND_BYPASS[op]} {code}")
        runs.append(f"{every} {_COND_RUNS[op]} {code}")
    words = []
    if parts:
        words.append("bypassed if " + ", or if ".join(parts))
        words.append("so it runs only if " + " and ".join(runs))
    if special == "EVEN":
        words.append("it runs even after an earlier step abends")
    elif special == "ONLY":
        words.append("it runs only after an earlier step abends")
    return "; ".join(words)


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
        meaning = explain_condition(step.condition)
        if meaning:
            row["condition_means"] = meaning
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
        [n for n in result.unresolved if not _is_template_note(n)],
        "a procedure or INCLUDE member not found, or a symbol left "
        "unsubstituted, may hide steps or change dataset names; a cataloged "
        "procedure is found in a .prc / .proc file, a folder named like a "
        "PROCLIB, or a folder cobol.yml lists as project.proc_path",
        lead=jfile.display,
    )
    _notes(
        response,
        "incomplete-analysis",
        [n for n in result.unresolved if _is_template_note(n)],
        "its steps and DD names are IBM's defaults, not your PROCLIB's; put "
        "the procedure member under the root for an exact answer",
        lead=jfile.display,
    )


def _carry_libraries(
    libraries: Libraries, files: list[JclFile], response: Response
) -> None:
    """Procedure libraries that could not be searched: a ``proc_path`` folder
    outside the root, a ``JCLLIB`` library no directory is named for."""
    from .tools import _notes

    effect = (
        "a procedure only that library holds is left unexpanded, or one of "
        "the same name from another library is used instead"
    )
    if libraries.skipped:
        response.caveat(
            "incomplete-analysis",
            "cobol.yml proc_path folders outside the workspace were not "
            f"searched: {', '.join(libraries.skipped)}",
            effect,
        )
    _notes(
        response,
        "incomplete-analysis",
        [
            f"{f.display} ({', '.join(f.missing_libraries)})"
            for f in files
            if f.missing_libraries
        ],
        effect + "; put each library's members in a folder of the library's "
        "name under the root",
        lead="JCLLIB ORDER libraries with no folder under the root",
    )


def _carry_index(
    index: JclIndex,
    response: Response,
    needle: str | None = None,
    answer_files: set[str] | None = None,
) -> None:
    """The root's JCL gaps, summarized: one caveat per kind, not per file.

    With *needle* (the program or dataset asked about), only the gaps that
    could change this answer are spelled out: those in the files the answer
    came from (*answer_files*) and in files whose text names *needle*. A gap
    in any other file is counted in one caveat, so the answer to a question
    about one application is not buried in the JCL gaps of every other one.
    """
    from .tools import _notes

    files = index.files
    others: list[JclFile] = []
    if needle:
        near = answer_files or set()
        relevant = [
            f
            for f in files
            if _has_gap(f) and (f.display in near or _mentions(f, needle))
        ]
        others = [f for f in files if _has_gap(f) and f not in relevant]
        files = relevant
    parsed = [f for f in files if f.result is not None]
    _carry_libraries(index.libraries, parsed, response)
    _notes(
        response,
        "incomplete-analysis",
        [f"{f.display}: {f.failure}" for f in files if f.failure],
        "the steps in those files are not in this answer",
        lead="JCL files that could not be read",
    )
    _notes(
        response,
        "partial-parse",
        [f.display for f in parsed if f.result and f.result.errors],
        "statements that could not be read are missing; jcl_job on a file "
        "names the lines",
        lead="JCL files read with errors",
    )
    _notes(
        response,
        "incomplete-analysis",
        [
            f.display
            for f in parsed
            if f.result and any(not _is_template_note(n) for n in f.result.unresolved)
        ],
        "a procedure or symbol not found there may hide steps or change "
        "dataset names; jcl_job on a file says which",
        lead="JCL files with unresolved procedures or symbols",
    )
    _notes(
        response,
        "incomplete-analysis",
        [
            f"{f.display} ({', '.join(f.result.template_procedures)})"
            for f in parsed
            if f.result and f.result.template_procedures
        ],
        "their steps and DD names are IBM's defaults, not your PROCLIB's; put "
        "the procedure member under the root for an exact answer",
        lead="JCL files whose IBM-supplied procedures were expanded from "
        "jcl-parser's generic templates",
    )
    if others:
        response.caveat(
            "incomplete-analysis",
            f"{len(others)} other JCL file(s) under the root have gaps "
            "(statements that could not be read, procedures, symbols or "
            f"JCLLIB libraries not found) but do not name {needle}",
            f"a step there reaches {needle} only through a procedure or "
            "symbol that is not under the root; jcl_job on a file lists its "
            "gaps",
        )


def _has_gap(jfile: JclFile) -> bool:
    """Whether *jfile* could not be read whole, or left something unresolved."""
    result = jfile.result
    if result is None:
        return True
    return bool(
        jfile.missing_libraries
        or result.errors
        or result.unresolved
        or result.template_procedures
    )


def _mentions(jfile: JclFile, needle: str) -> bool:
    """Whether the text of *jfile*, or of a procedure member it EXECs, names
    *needle* as a whole word (a dataset name: as a whole qualifier run)."""

    def word(text: str) -> re.Pattern[str]:
        return re.compile(rf"(?<![\w@#$.]){re.escape(text)}(?![\w@#$])", re.IGNORECASE)

    def text_of(path: Path) -> str | None:
        try:
            return path.read_text(encoding="latin-1")
        except OSError:
            return None

    wanted = word(needle)
    text = text_of(jfile.path)
    if text is None or wanted.search(text):
        return True  # unreadable: it may well name it
    for procedure, member in jfile.members.items():
        if not word(procedure).search(text):
            continue
        body = text_of(member)
        if body is None or wanted.search(body):
            return True
    return False


def _is_template_note(note: str) -> bool:
    """An ``unresolved`` note saying a procedure came from a template, which
    the template caveat already covers."""
    return "expanded from jcl-parser's template" in note


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


def run_order(steps: list[JobStep]) -> str:
    """The steps in the order they run, each with its program and when it
    runs: ``A (IDCAMS) -> B (SORT, only if every earlier step's return code
    is 0)``. The one line a flow description should not leave out."""
    parts = []
    for step in steps[:JOB_FLOW_STEPS]:
        what = step.program or (
            f"procedure {step.procedure}" if step.procedure else "?"
        )
        when = explain_condition(step.condition) if step.condition else None
        if when:
            when = when.split("so it ", 1)[-1]
            parts.append(f"{step.name} ({what}, {when})")
        else:
            parts.append(f"{step.name} ({what})")
    if len(steps) > JOB_FLOW_STEPS:
        parts.append(f"... {len(steps) - JOB_FLOW_STEPS} more")
    return " -> ".join(parts)


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


class _ControlMembers:
    """Control-card members under the root by name (``ctl/REPROCT.ctl`` for
    ``DSN=AWS.CNTL(REPROCT)``), walked once per call when first needed."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self._by_name: dict[str, list[Path]] | None = None

    def find(self, member: str, near: str) -> Path | None:
        if self._by_name is None:
            self._by_name = {}
            for directory, names in self.workspace._walk():
                for entry in names:
                    path = Path(directory, entry)
                    if path.suffix.lower() not in CONTROL_SUFFIXES:
                        continue
                    try:
                        path = path.resolve()
                    except (OSError, RuntimeError):
                        continue
                    if not self.workspace._within(path):
                        continue
                    self._by_name.setdefault(path.stem.upper(), []).append(path)
        found = self._by_name.get(member.upper(), [])
        if not found:
            return None
        # The member nearest the job wins (the most leading folders in
        # common, then the shallowest): two applications under one root may
        # each have a REPROCT.
        here = near.split("/")[:-1]

        def distance(path: Path) -> tuple[int, int, str]:
            parts = self.workspace.display(path).split("/")
            shared = 0
            for mine, theirs in zip(here, parts[:-1], strict=False):
                if mine != theirs:
                    break
                shared += 1
            return (-shared, len(parts), str(path))

        found = sorted(found, key=distance)
        return found[0]


#: ``LIB(MEMBER)``: a PDS member, not a GDG generation such as ``(+1)``.
_MEMBER_RE = re.compile(r"\(([A-Z@#$][A-Z0-9@#$]{0,7})\)$", re.IGNORECASE)


def _control_lines(text: str) -> list[str]:
    """The control statements of a SYSIN member: blank lines and ``/* */``
    comment lines dropped, the sequence area (73-80) cut."""
    out = []
    for line in split_source_lines(text):
        card = line[:72].rstrip()
        stripped = card.strip()
        if not stripped or stripped.startswith("/*") or stripped.startswith("*"):
            continue
        out.append(stripped)
    return out


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
        from .codebase_index import call_chain

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
        from .tools import CobolTools, _file_facts

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
    from .sort_layout import map_sort, parse_sort_control, read_back

    if (step.program or "").upper() not in _SORT_PROGRAMS or not lines:
        return None
    control = parse_sort_control(lines)
    if not (control.sort_keys or control.tests or control.inrec or control.outrec):
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
    flow: dict[str, Any] = {"file": jfile.display, "job": job.name, "steps": steps}
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
    from .codebase_index import call_chain
    from .tools import _notes

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
    from .codebase_index import programs_index

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


def _other_language_source(workspace: Workspace, name: str) -> dict[str, Any] | None:
    """The PL/I or assembler program *name* under the root (by its program
    name, else an entry name or the file stem), when its parser is
    installed: ``{program_id, file, language}``."""
    from .languages import languages_index, source_files

    if not source_files(workspace):
        return None
    found = languages_index(workspace).named(name)
    if not found:
        return None
    return {
        "program_id": found[0].program_id,
        "file": found[0].display,
        "language": found[0].language,
    }


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


#: Open mode -> what the program does with the file, before DISP says
#: whether the dataset was new.
_OPEN_USE = {"INPUT": "read", "OUTPUT": "write", "I-O": "update", "EXTEND": "extend"}

_SORT_PROGRAMS = frozenset({"SORT", "ICEMAN", "DFSORT", "SYNCSORT", "SORTD"})
_COPY_PROGRAMS = frozenset({"IEBGENER", "ICEGENER", "IEBCOPY", "IEBPTPCH"})
_OUTFIL_FNAMES_RE = re.compile(r"\bFNAMES\s*=\s*\(?([A-Z0-9@#$, ]+)\)?")
_ICETOOL_FROM_RE = re.compile(r"\bFROM\s*\(\s*([A-Z0-9@#$]+)\s*\)")
_ICETOOL_TO_RE = re.compile(r"\bTO\s*\(\s*([A-Z0-9@#$, ]+)\s*\)")


def _instream(step: JobStep, ddname: str) -> str:
    return "\n".join(
        line
        for dd in step.dd_statements
        if dd.name and dd.name.upper() == ddname
        for line in dd.instream_lines
    ).upper()


def _utility_uses(step: JobStep) -> dict[str, str] | None:
    """For a utility step, DD name (or ``DSN:`` + dataset name) -> read or
    write, from what the utility does with each DD; None for a program
    that is no utility this knows."""
    from ..analysis.lineage_jcl import _REPRO_IN_RE, _REPRO_OUT_RE, _repro_commands

    program = (step.program or "").upper()
    uses: dict[str, str] = {}
    if program in _SORT_PROGRAMS:
        for dd in step.dd_statements:
            name = (dd.name or "").upper()
            if name.startswith(("SORTIN", "SORTJNF")):
                uses[name] = "read"
            elif name == "SORTOUT" or name.startswith("SORTOF"):
                uses[name] = "write"
        for match in _OUTFIL_FNAMES_RE.finditer(_instream(step, "SYSIN")):
            for name in match.group(1).replace(",", " ").split():
                uses[name] = "write"
        return uses
    if program in _COPY_PROGRAMS:
        return {"SYSUT1": "read", "SYSUT2": "write"}
    if program == "IEFBR14":
        # It opens nothing: DISP alone acts, so (MOD,DELETE) deletes.
        for dd in step.dd_statements:
            if _normal_disposition(dd.disposition) == "DELETE":
                uses[(dd.name or "").upper()] = "delete"
        return uses
    if program == "ICETOOL":
        toolin = _instream(step, "TOOLIN")
        for match in _ICETOOL_FROM_RE.finditer(toolin):
            uses[match.group(1)] = "read"
        for match in _ICETOOL_TO_RE.finditer(toolin):
            for name in match.group(1).replace(",", " ").split():
                uses[name] = "write"
        return uses
    if program == "IDCAMS":
        for command in _repro_commands(_instream(step, "SYSIN")):
            for regex, use in ((_REPRO_IN_RE, "read"), (_REPRO_OUT_RE, "write")):
                found = regex.search(command)
                if found is None:
                    continue
                if found.group(1) in ("INFILE", "IFILE", "OUTFILE", "OFILE"):
                    uses[found.group(2)] = use
                else:
                    uses["DSN:" + found.group(2)] = use
        return uses
    return None


_DSN = r"'?([A-Z0-9@#$&][A-Z0-9@#$&.\-]*(?:\([+-]?[A-Z0-9@#$]+\))?)'?"
#: IDCAMS commands that name a dataset in SYSIN rather than through a DD:
#: (regex, access, command). DEFINE ... NAME(X) is the cluster / index /
#: GDG base itself, never its DATA or INDEX component.
_IDCAMS_NAMED = (
    (re.compile(rf"\bDELETE\s+\(?\s*{_DSN}"), "delete", "DELETE"),
    (
        re.compile(
            rf"\bDEFINE\s+(?:CLUSTER|AIX|ALTERNATEINDEX|GDG|GENERATIONDATAGROUP|"
            rf"NONVSAM|PATH)\s*\(\s*NAME\s*\(\s*{_DSN}"
        ),
        "define",
        "DEFINE",
    ),
    (re.compile(rf"\bRELATE\s*\(\s*{_DSN}"), "read", "DEFINE AIX RELATE"),
    (
        re.compile(
            rf"\b(?:REPRO|BLDINDEX|PRINT)\b[^;]*?\b(?:INDATASET|IDS)\s*\(\s*{_DSN}"
        ),
        "read",
        "REPRO/BLDINDEX INDATASET",
    ),
    (
        re.compile(rf"\b(?:REPRO|BLDINDEX)\b[^;]*?\b(?:OUTDATASET|ODS)\s*\(\s*{_DSN}"),
        "write",
        "REPRO/BLDINDEX OUTDATASET",
    ),
)


def _idcams_named(step: JobStep) -> list[tuple[str, str, str]]:
    """``(dataset, access, command)`` for every dataset an IDCAMS step's
    in-stream SYSIN names directly: DELETE, DEFINE, a REPRO or BLDINDEX
    INDATASET / OUTDATASET, an AIX's RELATE. A DD-named file is not here
    (``_utility_uses`` has those)."""
    if (step.program or "").upper() != "IDCAMS":
        return []
    text = re.sub(r"/\*.*?\*/", " ", _instream(step, "SYSIN"), flags=re.DOTALL)
    # One IDCAMS command per statement: continuations (a trailing - or +)
    # joined, a new command at each line that does not continue.
    text = re.sub(r"[-+][ \t]*\n", " ", text).replace("\n", ";")
    found: list[tuple[str, str, str]] = []
    for regex, access, command in _IDCAMS_NAMED:
        for match in regex.finditer(text):
            entry = (match.group(1), access, command)
            if entry not in found:
                found.append(entry)
    return found


def _combine(use: str, disposition_access: str) -> str:
    """A program's *use* of a file, said with what DISP adds: a written
    dataset DISP=NEW is created; DISP=MOD with OUTPUT or EXTEND extends."""
    if use in ("write", "extend") and disposition_access == "create":
        return "create"
    if use == "write" and disposition_access == "extend":
        return "extend"
    return use


class _ProgramUses:
    """Per COBOL program under the root: DD name -> open modes, read once."""

    def __init__(self, workspace: Workspace, response: Response) -> None:
        self.workspace = workspace
        self.response = response
        self._held: dict[str, dict[str, set[str]] | None] = {}

    def of(self, program: str) -> dict[str, set[str]] | None:
        name = program.upper()
        if name not in self._held:
            self._held[name] = self._read(name)
        return self._held[name]

    def _read(self, name: str) -> dict[str, set[str]] | None:
        from .tools import _attempt, _crud

        selects = _program_selects(self.workspace, name, Response())
        if selects is None:
            return None
        file = _source_files(self.workspace).get(name) or _declaring_file(
            self.workspace, name
        )
        if file is None:
            return None
        parsed = self.workspace.program(file)
        unit = parsed.ast.find_program_unit(name) or parsed.ast
        crud = _attempt(self.response, "file use", lambda: _crud(parsed, unit))
        if crud is None:
            return None
        modes = {
            e.file_name.upper(): {str(m).upper() for m in e.open_modes}
            for e in crud.file_entries
        }
        by_dd: dict[str, set[str]] = {}
        for row in selects["files"]:
            if row.get("ddname"):
                by_dd.setdefault(row["ddname"].upper(), set()).update(
                    modes.get(row["file_name"].upper(), set())
                )
        return by_dd


class _NoProgramUses(_ProgramUses):
    """No program's open modes: every step falls back to DISP."""

    def of(self, program: str) -> dict[str, set[str]] | None:
        return None


def _step_access(
    step: JobStep | None,
    dd: DDStatement,
    by_disp: str,
    programs: _ProgramUses,
) -> tuple[str, str]:
    """(access, what it was read from: program / utility / disp) of *dd*
    in *step*."""
    if step is None:
        return by_disp, "disp"
    ddname = (dd.name or "").upper()
    utility = _utility_uses(step)
    if utility is not None:
        use = utility.get(ddname) or utility.get(f"DSN:{(dd.dataset or '').upper()}")
        if use:
            return _combine(use, by_disp), "utility"
        return by_disp, "disp"
    uses: set[str] = set()
    for program in step.effective_programs():
        modes = programs.of(program)
        if modes is None or ddname not in modes:
            continue
        uses.update(_OPEN_USE.get(m, m.lower()) for m in modes[ddname])
    if not uses:
        return by_disp, "disp"
    # Several open modes in one run: the strongest says what can happen.
    for strongest in ("update", "write", "extend", "read"):
        if strongest in uses:
            return _combine(strongest, by_disp), "program"
    return by_disp, "disp"


def dataset_users(
    workspace: Workspace, dataset: str, limit: int | None = None
) -> dict[str, Any]:
    """Every DD under the root that names *dataset*, and what it does."""
    matches = _matcher(dataset)
    index = jcl_index(workspace)
    response = Response()

    found: list[dict[str, Any]] = []
    programs = _ProgramUses(workspace, response)
    for jfile in index.parsed():
        assert jfile.result is not None
        locator = _Locator(jfile, workspace)
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
                "location": locator.at(path, dd.line),
            }
            access, source = _step_access(step, dd, _access(dd.disposition), programs)
            row["access"] = access
            row["access_from"] = source
            if source != "disp":
                row["disposition_access"] = _access(dd.disposition)
            if dd.dataset.startswith("&&"):
                row["temporary"] = True
            found.append(row)

        for job in jfile.result.jobs:
            for step in job.steps:
                for named, access, command in _idcams_named(step):
                    if not matches(named.upper()):
                        continue
                    found.append(
                        {
                            "dataset": named,
                            "file": jfile.display,
                            "job": job.name,
                            "step": step.name,
                            "programs": ["IDCAMS"],
                            "ddname": None,
                            "command": command,
                            "access": access,
                            "access_from": "idcams command",
                            "location": locator.step(step),
                        }
                    )

    wanted = dataset.strip().strip("'").upper()
    _carry_index(
        index,
        response,
        None if any(c in wanted for c in "*%") else _base(wanted),
        {row["file"] for row in found},
    )
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
        "access_legend": "access_from program: the COBOL program's OPEN mode "
        "for the DD (read, write, update, extend; create when DISP=NEW); "
        "utility: what SORT, IEBGENER, IDCAMS REPRO or ICETOOL do with the "
        "DD; idcams command: an IDCAMS DELETE, DEFINE, REPRO / BLDINDEX "
        "INDATASET / OUTDATASET or AIX RELATE in SYSIN names the dataset "
        "itself; disp: only DISP= was known (SHR/OLD say nothing about "
        "reading or writing)",
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
