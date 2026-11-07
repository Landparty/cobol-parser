"""What the JCL tools share: DD and step rows (:func:`_dd_row`,
:func:`_step_row`), COND explained, caveats carried from the index, the
control-statement members, utility (SORT / IDCAMS / copy) dataset uses and
how a program's OPENs decide a DD's access (:class:`_ProgramUses`)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..._lines import split_source_lines
from ...jcl.models import DDStatement, JclJob, JclParseResult, JobStep
from ..envelope import Response
from ..workspace import ParsedProgram, Workspace
from .jcl_index import (
    JclFile,
    JclIndex,
    Libraries,
    _declaring_file,
    _Locator,
    _program_selects,
    _source_files,
)

#: In-stream data lines ``jcl_job`` shows per DD (a SORT's control cards,
#: a TSO step's ``RUN PROGRAM``); the count is always given.
MAX_INSTREAM_LINES = 20


#: Steps of one job ``jobs_running`` lays out in its ``jobs`` flow.
JOB_FLOW_STEPS = 40


#: Suffixes of a control-card member a SYSIN ``DD DSN=LIB(MEMBER)`` may name
#: under the root (a PDS member downloaded as ``ctl/MEMBER.ctl``).
CONTROL_SUFFIXES: frozenset[str] = frozenset(
    {"", ".ctl", ".cntl", ".ctlcard", ".card", ".sysin", ".srt", ".sort", ".txt"}
)


#: What counts as writing a dataset in a job flow.
_WRITES = frozenset({"create", "write", "extend", "update", "exclusive", "delete"})


#: ``DISP=`` status -> what the step does with the dataset.
_ACCESS = {"SHR": "read", "OLD": "exclusive", "NEW": "create", "MOD": "extend"}


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
    from .common import _notes

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
    from .common import _notes

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
    from .common import _notes

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


def _other_language_source(workspace: Workspace, name: str) -> dict[str, Any] | None:
    """The PL/I or assembler program *name* under the root (by its program
    name, else an entry name or the file stem), when its parser is
    installed: ``{program_id, file, language}``."""
    from ..languages import languages_index, source_files

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


# ---------------------------------------------------------------------------
# dataset_users
# ---------------------------------------------------------------------------


def _base(dataset: str) -> str:
    """*dataset* without a member or GDG generation: ``A.B(+1)`` -> ``A.B``."""
    return dataset.split("(", 1)[0]


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
    from ...analysis.lineage_jcl import _REPRO_IN_RE, _REPRO_OUT_RE, _repro_commands

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
        # program -> DD -> (file name, source file, OPEN line) per open mode
        self._opens: dict[str, dict[str, list[tuple[str, str, str, int | None]]]] = {}

    def of(self, program: str) -> dict[str, set[str]] | None:
        name = program.upper()
        if name not in self._held:
            self._held[name] = self._read(name)
        return self._held[name]

    def _read(self, name: str) -> dict[str, set[str]] | None:
        from .common import _attempt, _crud

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
        lines = _open_lines(parsed, unit)
        by_dd: dict[str, set[str]] = {}
        opens = self._opens.setdefault(name, {})
        for row in selects["files"]:
            if row.get("ddname"):
                ddname = row["ddname"].upper()
                file_name = row["file_name"].upper()
                by_dd.setdefault(ddname, set()).update(modes.get(file_name, set()))
                for mode in sorted(modes.get(file_name, set())):
                    opens.setdefault(ddname, []).append(
                        (mode, file_name, *lines.get((file_name, mode), (file, None)))
                    )
        return by_dd

    def because(self, step: JobStep, ddname: str, disposition: str | None) -> str:
        """The OPEN that says what *step*'s programs do with *ddname*, in
        words with its line, and what DISP= alone would have said."""
        said = []
        for program in step.effective_programs():
            if self.of(program) is None:
                continue
            for mode, file_name, file, line in self._opens.get(program.upper(), {}).get(
                ddname.upper(), []
            ):
                where = f"{file}:{line}" if line else file
                said.append(f"{program} opens {file_name} {mode} ({where})")
        text = "; ".join(said)
        status = (disposition or "").strip("()").split(",")[0].strip().upper()
        if status in ("SHR", "OLD"):
            text += (
                f"; DISP={disposition} only says how the dataset is shared, "
                "not whether it is read or written"
            )
        return text


def _open_lines(
    parsed: ParsedProgram, unit: Any
) -> dict[tuple[str, str], tuple[str, int]]:
    """(file, OPEN mode) -> where on disk its first OPEN in *unit* is."""
    from ...models.statements import IOOpenStatement

    lines: dict[tuple[str, str], tuple[str, int]] = {}
    for stmt in unit.find_all_by_type("IOOpenStatement"):
        if not isinstance(stmt, IOOpenStatement) or stmt.location is None:
            continue
        file_modes = getattr(stmt, "file_modes", None) or {}
        for file_name in stmt.file_names:
            mode = (file_modes.get(file_name) or stmt.open_mode or "").upper()
            if not mode or (file_name.upper(), mode) in lines:
                continue
            at = parsed.locate(stmt.location.line, None, Response())
            if at is not None:
                lines[(file_name.upper(), mode)] = (at["file"], at["line"])
    return lines


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
