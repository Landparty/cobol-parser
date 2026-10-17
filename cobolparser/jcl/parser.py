"""
Read JCL through the ``jcl-parser`` package and shape it for this toolchain.

``cobolparser.jcl`` used to carry its own card scanner and statement parser.
It now delegates every JCL decision -- continuation, in-stream data, symbolic
parameters, procedure expansion, overrides -- to ``jclparser`` (the sibling
``jcl-parser`` package, installed with ``pip install 'cobol-parser[jcl]'``),
and only converts its ``Job`` model into the
:class:`~cobolparser.jcl.models.JclParseResult` shape the rest of this library
and the ``cobol-parser jcl`` subcommand consume.

What this module adds on top of ``jclparser``:

* **Several jobs per file.**  ``jclparser.parse_jcl`` reads one job; a deck
  with several ``JOB`` cards is split at each one (a ``JOB`` card inside
  in-stream data is data, not a boundary) and every job is parsed on its own,
  so one job's syntax error costs only that job.
* **Procedure libraries without guessing.**  Procedures are found in-stream
  first, then in the directories passed as ``proc_paths`` (one member per
  file, named after the procedure, any extension).  ``jclparser``'s bundled
  IBM utility templates and the ``JCL_PROCLIB_PATH`` environment variable are
  deliberately *not* consulted: a template's dataset names are not this
  shop's, and a result must not depend on the caller's environment.
* **Nothing dropped silently.**  A procedure found nowhere keeps its
  invocation step and is reported in ``unresolved``; a job ``jclparser``
  rejects lands in ``errors`` with its line; ``jclparser``'s own warnings are
  carried into ``unresolved``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .models import (
    DDStatement,
    JclJob,
    JclParameter,
    JclParseResult,
    JobStep,
    unquote,
)
from .programs import TSO_PROGRAMS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from jclparser.model import DDStatement as _JDD
    from jclparser.model import Job as _JJob
    from jclparser.model import Procedure as _JProc
    from jclparser.model import Step as _JStep

_INSTALL_HINT = (
    "cobolparser.jcl reads JCL through the jcl-parser package; install it with "
    "pip install 'cobol-parser[jcl]'"
)

#: A JOB card: ``//name JOB`` (or a nameless ``// JOB``, which is an error
#: but still starts a job) with the operation as its own word.
_JOB_CARD = re.compile(r"^//([A-Z@#$][A-Z0-9@#$]{0,7})?\s+JOB(?:\s|$)", re.IGNORECASE)

#: Keys ``jclparser`` uses for its own bookkeeping, not coded parameters.
_INTERNAL_KEYS = frozenset({"_records"})


def _require_jclparser() -> None:
    try:
        import jclparser  # noqa: F401
    except ImportError as exc:
        raise ImportError(_INSTALL_HINT) from exc


# -- Procedure libraries ----------------------------------------------------


def _library_members(proc_paths: Sequence[str | os.PathLike[str]]) -> dict[str, Path]:
    """Member name -> file, first directory wins, as a PROCLIB concatenation."""
    members: dict[str, Path] = {}
    for directory in proc_paths:
        base = Path(directory)
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if entry.is_file():
                members.setdefault(entry.stem.upper(), entry)
    return members


def _make_loaders(
    proc_paths: Sequence[str | os.PathLike[str]],
) -> tuple[Any, Any]:
    """(procedure loader, INCLUDE member loader) over ``proc_paths``; one pair
    per parse, so each member is read and parsed once."""
    from jclparser.include_loader import IncludeMemberLoader
    from jclparser.proc_loader import ProcedureLoader

    members = _library_members(proc_paths)

    def _read(name: str) -> str | None:
        path = members.get(name.upper())
        if path is None:
            return None
        return path.read_text(encoding="utf-8", errors="replace")

    class _LibraryProcedureLoader(ProcedureLoader):
        def __init__(self) -> None:
            self._cache: dict[str, _JProc | None] = {}

        def load_procedure(
            self, name: str, libraries: Sequence[str] | None = None
        ) -> _JProc | None:
            key = name.upper()
            if key not in self._cache:
                text = _read(key)
                self._cache[key] = None if text is None else _library_proc(text, key)
            return self._cache[key]

    class _LibraryMemberLoader(IncludeMemberLoader):
        def load_member(
            self, member_name: str, libraries: list[str] | None = None
        ) -> str | None:
            return _read(member_name)

    return _LibraryProcedureLoader(), _LibraryMemberLoader()


def _library_proc(text: str, name: str) -> _JProc | None:
    """The procedure a library member defines, with the member's own line
    numbers (``jclparser``'s file loader wraps the member in a JOB card first,
    which shifts every line by one).

    ``EXEC name`` resolves by *member* name, so the member's PROC is used
    whatever its label says (one named like the member wins if there are
    several).  A member with no PROC statement at all is its own body.
    """
    from jclparser import parse_jcl as _jcl_parse
    from jclparser.errors import JCLParseError

    try:
        member = _jcl_parse(text, enable_external_procs=False)
    except (JCLParseError, ValueError):
        member = None
    if member is not None and member.procedures:
        procs = member.procedures
        proc = next((p for p in procs if p.name.upper() == name), procs[0])
        proc.name = name
        proc.is_external = True
        return proc
    # No PROC statement: jclparser refuses an EXEC ahead of any JOB or PROC
    # card, so read the member as the body of a PROC coded on a line of its
    # own and move every line number back by that one line.
    try:
        wrapped = _jcl_parse(
            f"//{name} PROC\n{text.rstrip()}\n//         PEND\n",
            enable_external_procs=False,
        )
    except (JCLParseError, ValueError):
        return None
    if not wrapped.procedures or not wrapped.procedures[0].steps:
        return None
    proc = wrapped.procedures[0]
    _shift_lines(proc.steps, -1)
    proc.name = name
    proc.is_external = True
    return proc


def _shift_lines(items: Iterable[Any], delta: int) -> None:
    """Move the line numbers of steps (and their DDs) by ``delta``."""
    from jclparser.model import ConditionalBlock

    for item in items:
        if isinstance(item, ConditionalBlock):
            if item.line_number:
                item.line_number += delta
            _shift_lines(item.then_steps, delta)
            _shift_lines(item.else_steps, delta)
            continue
        if item.line_number:
            item.line_number += delta
        for dd in item.dd_statements:
            if dd.line_number:
                dd.line_number += delta


class _Missing:
    """Last loader in the chain: records the name and yields an empty body,
    so one missing procedure does not abort the expansion of every other."""

    def __init__(self) -> None:
        self.names: list[str] = []

    def loader(self) -> Any:
        from jclparser.model import Procedure
        from jclparser.proc_loader import ProcedureLoader

        names = self.names

        class _MissingLoader(ProcedureLoader):
            def load_procedure(
                self, name: str, libraries: Sequence[str] | None = None
            ) -> _JProc | None:
                if name.upper() not in names:
                    names.append(name.upper())
                return Procedure(name=name.upper(), steps=[], is_external=True)

        return _MissingLoader()


# -- Splitting a deck into jobs --------------------------------------------


def _split_jobs(text: str) -> list[tuple[int, str]]:
    """``(line offset, text)`` per job; lines before the first JOB card go
    with the first job (a PROC coded ahead of it is still that job's)."""
    from jclparser.parser import _merge_source_lines, split_source_lines

    lines = split_source_lines(text)
    from jclparser.errors import JCLParseError

    try:
        scanned = _merge_source_lines(text)
    except (JCLParseError, ValueError):
        # The per-job parse reports it; split at every JOB card meanwhile.
        data: set[int] = set()
    else:
        data = scanned.inline_data_indices | scanned.control_data_indices
    starts = [
        index
        for index, line in enumerate(lines)
        if index not in data and _JOB_CARD.match(line)
    ]
    if len(starts) <= 1:
        return [(0, text)]
    bounds = [0, *starts[1:], len(lines)]
    return [
        (bounds[i], "\n".join(lines[bounds[i] : bounds[i + 1]]) + "\n")
        for i in range(len(bounds) - 1)
    ]


# -- Model conversion --------------------------------------------------------


def _raw(value: Any) -> str | None:
    """A ``jclparser`` parameter value back as coded text."""
    if value is None or value is True:
        return None
    if isinstance(value, dict):
        return "(" + ",".join(f"{k}={v}" for k, v in value.items()) + ")"
    if isinstance(value, list | tuple):
        return "(" + ",".join("" if v is None else str(v) for v in value) + ")"
    return str(value)


def _split_commas(text: str) -> list[str]:
    """Split on commas outside apostrophe quotes."""
    items: list[str] = []
    current: list[str] = []
    quoted = False
    for char in text:
        if char == "'":
            quoted = not quoted
        if char == "," and not quoted:
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    items.append("".join(current))
    return items


def _parameter(key: str, value: Any, *, job_card: bool = False) -> JclParameter:
    if key.startswith("_pos_") and job_card:
        # JOB positionals: accounting information and programmer name.
        param = JclParameter(keyword="", value=_raw(value))
        if isinstance(value, list | tuple):
            param.positional = ["" if v is None else str(v) for v in value]
        return param
    if key.startswith("_pos_"):
        # A bare positional word (DUMMY, DATA, a procedure name) or a quoted /
        # parenthesised positional (JOB accounting information).
        text = _raw(value) or ""
        if text and text[0] not in "('":
            return JclParameter(keyword=text, value=None)
        return JclParameter(keyword="", value=text)
    if value is True:
        return JclParameter(keyword=key, value=None)
    param = JclParameter(keyword=key, value=_raw(value))
    items: Iterable[Any] = ()
    if isinstance(value, dict):
        param.subparameters = {str(k): str(v) for k, v in value.items()}
    elif isinstance(value, list | tuple):
        items = value
    for item in items:
        text = "" if item is None else str(item)
        sub_key, sep, sub_value = text.partition("=")
        if sep and sub_key and "(" not in sub_key and "'" not in sub_key:
            param.subparameters[sub_key.strip().upper()] = sub_value
        else:
            param.positional.append(text)
    return param


def _parameters(
    params: dict[str, Any], *, job_card: bool = False
) -> list[JclParameter]:
    return [
        _parameter(key, value, job_card=job_card)
        for key, value in params.items()
        if key not in _INTERNAL_KEYS
    ]


def _statement_text(chunk: str, line_number: int | None) -> str | None:
    """The JOB statement starting on ``line_number`` of ``chunk``, its
    continuations merged and its comment field dropped, as ``jclparser``
    reads it."""
    from jclparser.parser import _merge_source_lines

    if not line_number:
        return None
    try:
        merged = _merge_source_lines(chunk).merged_lines
    except ValueError:
        return None
    return next((text for text, number in merged if number == line_number), None)


def _top_level_items(operands: str) -> list[str]:
    """Split on commas outside apostrophe quotes and parentheses."""
    items: list[str] = []
    current: list[str] = []
    depth = 0
    quoted = False
    for char in operands:
        if char == "'":
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
        if char == "," and not quoted and depth == 0:
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    items.append("".join(current))
    return items


def _coded_positionals(job_card: str | None) -> list[str] | None:
    """The JOB card's positional operands (accounting information, programmer
    name) exactly as coded, quotes included; ``jclparser`` drops the quotes."""
    if job_card is None:
        return None
    match = re.match(r"//\S*\s+JOB(?:\s+(.*))?$", job_card, re.IGNORECASE)
    if match is None:
        return None
    operands = (match.group(1) or "").strip()
    items = _top_level_items(operands) if operands else []
    out: list[str] = []
    for item in items:
        if "=" in item.split("'")[0].split("(")[0]:
            break
        out.append(item)
    return out


def _job_parameters(job: _JJob, job_card: str | None = None) -> list[JclParameter]:
    params = {k: v for k, v in job.parameters.items() if not k.startswith("_pos_")}
    coded = _coded_positionals(job_card)
    if coded is None:
        # No card text to read: fall back on jclparser's (unquoted) values.
        fallback: dict[str, Any] = {}
        if job.accounting_info is not None:
            fallback["_pos_0"] = _split_commas(job.accounting_info)
        fallback.update(job.parameters)
        return _parameters(fallback, job_card=True)
    positionals: list[JclParameter] = []
    for text in coded:
        param = JclParameter(keyword="", value=text)
        if text.startswith("(") and text.endswith(")"):
            param.positional = _top_level_items(text[1:-1])
        positionals.append(param)
    return positionals + _parameters(params, job_card=True)


def _dd(dd: _JDD, offset: int, procstep: str | None = None) -> DDStatement:
    params = dd.parameters
    positional = {str(v).upper() for k, v in params.items() if k.startswith("_pos_")}
    dataset = dd.dataset_name
    if dataset is not None:
        dataset = unquote(dataset)
    is_dummy = "DUMMY" in positional or (
        dataset is not None and dataset.upper() == "NULLFILE"
    )
    is_instream = "*" in params or "DATA" in positional or dd.inline_data is not None
    sysout = _raw(params.get("SYSOUT")) if "SYSOUT" in params else None
    dcb = dd.dcb
    disposition = dd.disposition
    return DDStatement(
        name=dd.name,
        dataset=None if is_dummy else dataset,
        disposition=_raw(disposition) if disposition is not None else None,
        sysout=sysout,
        is_dummy=is_dummy,
        is_instream=is_instream,
        instream_lines=dd.inline_data.split("\n") if dd.inline_data else [],
        record_format=dcb.recfm if dcb is not None else None,
        record_length=dcb.lrecl if dcb is not None else None,
        parameters=_parameters(params),
        line=dd.line_number + offset if dd.line_number else 0,
        procstep=procstep,
    )


def _dds(
    statements: Iterable[_JDD], offset: int, procstep: str | None = None
) -> list[DDStatement]:
    """Convert DD cards, folding each unnamed card into the concatenation of
    the named one ahead of it (repeating its name, so a lookup finds both)."""
    out: list[DDStatement] = []
    for statement in statements:
        dd = _dd(statement, offset, procstep)
        if not dd.name and out:
            dd.name = out[-1].name
            out[-1].concatenated.append(dd)
        else:
            out.append(dd)
    return out


def _grouped(condition: str) -> str:
    """``condition`` wrapped in parentheses unless one pair already encloses
    all of it, so ``NOT`` / ``AND`` apply to the whole expression."""
    text = condition.strip()
    if text.startswith("(") and text.endswith(")"):
        depth = 0
        for index, char in enumerate(text):
            depth += char == "("
            depth -= char == ")"
            if depth == 0:
                if index == len(text) - 1:
                    return text
                break
    return f"({text})"


def _negated(condition: str) -> str:
    return f"NOT {_grouped(condition)}"


def _condition(params: dict[str, Any], enclosing: list[str]) -> str | None:
    if "COND" in params:
        return _raw(params["COND"])
    if not enclosing:
        return None
    if len(enclosing) == 1:
        return enclosing[0]
    return " AND ".join(_grouped(condition) for condition in enclosing)


def _step(
    step: _JStep,
    offset: int,
    enclosing: list[str],
    *,
    name: str | None = None,
    procedure: str | None = None,
) -> JobStep:
    params = step.parameters
    parm = params.get("PARM")
    dds = _dds(step.dd_statements, offset)
    for key, override in step.dd_overrides.items():
        procstep, _, ddname = key.rpartition(".")
        converted = _dds(
            [override, *step.dd_override_concatenations.get(key, [])],
            offset,
            procstep or None,
        )
        for head in converted:
            for member in head.flatten():
                member.name = ddname
        dds.extend(converted)
    return JobStep(
        name=name if name is not None else (step.name or ""),
        program=step.program,
        procedure=procedure if procedure is not None else step.procedure,
        parm=None if parm is None else unquote(_raw(parm) or ""),
        dd_statements=dds,
        condition=_condition(params, enclosing),
        line=step.line_number + offset if step.line_number else 0,
        parameters=_parameters(params),
    )


class _JobConverter:
    def __init__(
        self,
        job: _JJob,
        offset: int,
        library_loader: Any,
        unresolved: list[str],
        errors: list[dict[str, Any]],
        preamble: Iterable[str] = (),
    ) -> None:
        self.job = job
        self.offset = offset
        self.library_loader = library_loader
        self.unresolved = unresolved
        self.errors = errors
        #: Procedures coded ahead of the first JOB card: in-stream, but their
        #: line numbers count from the top of the file, not from this job.
        self.preamble = set(preamble)
        self.job_card: str | None = None

    def convert(self) -> JclJob:
        job = self.job
        steps: list[JobStep] = []
        self._walk(job.steps, [], steps)
        return JclJob(
            name=job.name,
            steps=steps,
            parameters=_job_parameters(job, self.job_card),
            line=job.line_number + self.offset if job.line_number else 0,
            dd_statements=_dds(job.joblib_dds, self.offset),
        )

    def _walk(self, items: list[Any], enclosing: list[str], out: list[JobStep]) -> None:
        from jclparser.model import ConditionalBlock

        for item in items:
            if isinstance(item, ConditionalBlock):
                self._walk(item.then_steps, [*enclosing, item.condition], out)
                self._walk(item.else_steps, [*enclosing, _negated(item.condition)], out)
                continue
            out.append(_step(item, self.offset, enclosing))
            if item.procedure:
                out.extend(self._expand(item, enclosing))

    def procedures(self) -> dict[str, list[JobStep]]:
        """Each in-stream procedure's steps, expanded with its own defaults."""
        from jclparser.model import Step

        out: dict[str, list[JobStep]] = {}
        for proc in self.job.procedures:
            name = proc.name.upper()
            probe = Step(name=name, procedure=name, line_number=proc.line_number)
            steps = self._expand(probe, [], quiet=True)
            for body_step in steps:
                body_step.name = body_step.name.removeprefix(name + ".")
            out[name] = steps
        return out

    def _expand(
        self, step: _JStep, enclosing: list[str], *, quiet: bool = False
    ) -> list[JobStep]:
        """The steps an ``EXEC proc`` expands to, one per procedure step."""
        from jclparser import explode_job
        from jclparser.errors import JCLParseError
        from jclparser.model import ConditionalBlock, Job
        from jclparser.proc_loader import (
            CompositeProcedureLoader,
            InlineProcedureLoader,
        )

        missing = _Missing()
        loader = CompositeProcedureLoader(
            [
                InlineProcedureLoader(self.job.procedures),
                self.library_loader,
                missing.loader(),
            ]
        )
        single = Job(
            name=self.job.name,
            steps=[step],
            procedures=self.job.procedures,
            set_statements=dict(self.job.set_statements),
        )
        try:
            exploded = explode_job(single, proc_loader=loader, audit=True)
        except (JCLParseError, ValueError, RecursionError) as exc:
            if quiet:
                return []
            self.errors.append(
                {
                    "line": step.line_number + self.offset,
                    "message": f"EXEC {step.procedure}: {exc}",
                }
            )
            return []
        for name in [] if quiet else missing.names:
            self.unresolved.append(
                f"PROC {name} (line {step.line_number + self.offset}): the "
                "procedure is neither defined in this file nor found on the "
                "procedure path, so its steps and DD statements could not be "
                "expanded"
            )
        for warning in [] if quiet else exploded.warnings:
            if warning not in self.unresolved:
                self.unresolved.append(warning)

        out: list[JobStep] = []
        explosion_map = exploded.explosion_map or {}

        def walk(items: list[Any], conds: list[str]) -> None:
            for item in items:
                if isinstance(item, ConditionalBlock):
                    walk(item.then_steps, [*conds, item.condition])
                    walk(item.else_steps, [*conds, _negated(item.condition)])
                    continue
                info = explosion_map.get(item.original_proc_call or "")
                procedure = getattr(info, "proc_definition", None) or step.procedure
                # Line numbers of a library procedure are its own member's,
                # not this file's.
                name = str(procedure).upper()
                inline = name in self._inline_names() and name not in self.preamble
                origin = self.offset if inline else 0
                out.append(_step(item, origin, conds, procedure=name))

        walk(exploded.steps, list(enclosing))
        return out

    def _inline_names(self) -> set[str]:
        return {proc.name.upper() for proc in self.job.procedures}


_SYMBOL = re.compile(r"(?<!&)&([A-Z@#$][A-Z0-9@#$]{0,7})", re.IGNORECASE)


def _diagnose(job: JclJob, unresolved: list[str]) -> None:
    """Report what ``jclparser`` read but could not resolve, rather than let
    an unresolved name pass for a real one."""

    def note(message: str) -> None:
        if message not in unresolved:
            unresolved.append(message)

    dds: list[tuple[JobStep | None, DDStatement]] = [
        (None, dd) for top in job.dd_statements for dd in top.flatten()
    ]
    dds += [
        (step, dd)
        for step in job.steps
        for top in step.dd_statements
        for dd in top.flatten()
    ]
    for step, dd in dds:
        where = f"DD {dd.name}" + (f" of step {step.name}" if step else "")
        where += f" (line {dd.line})"
        dataset = dd.dataset
        if dataset is not None and not dataset.startswith("&&"):
            symbols = sorted({m.group(1).upper() for m in _SYMBOL.finditer(dataset)})
            if symbols:
                note(
                    f"{where}: DSN={dataset} keeps "
                    + ", ".join(f"&{name}" for name in symbols)
                    + " as coded; no SET, procedure default or EXEC override "
                    "gives it a value"
                )
        if dataset is not None and dataset.startswith("*."):
            note(
                f"{where}: DSN={dataset} is a backward reference; the dataset "
                "it names is not resolved"
            )
        dcb = dd.parameter("DCB")
        lrecl = dd.parameter("LRECL")
        coded = (dcb.subparameters.get("LRECL") if dcb else None) or (
            lrecl.value if lrecl else None
        )
        if coded is not None and dd.record_length is None:
            note(f"{where}: LRECL={coded} is not a number; record length unknown")
        if (
            step is not None
            and (step.program or "").upper() in TSO_PROGRAMS
            and dd.name.upper() == "SYSTSIN"
            and dd.dataset is not None
        ):
            note(
                f"{where}: {step.program} reads SYSTSIN from {dd.dataset}, "
                "which is not read, so the programs it runs (RUN PROGRAM) are "
                "not known"
            )


def _names(procedures: Iterable[_JProc]) -> set[str]:
    return {proc.name.upper() for proc in procedures}


def _note_duplicate_procedures(job: _JJob, offset: int, unresolved: list[str]) -> None:
    seen: set[str] = set()
    for proc in job.procedures:
        name = proc.name.upper()
        if name in seen:
            unresolved.append(
                f"PROC {name} (line {proc.line_number + offset}) is defined "
                "more than once in this job; an EXEC of it runs the last "
                "definition"
            )
        seen.add(name)


# -- Entry points ------------------------------------------------------------


class JclParser:
    """Parses z/OS JCL into a :class:`~cobolparser.jcl.models.JclParseResult`.

    ``proc_paths`` are directories searched, in order, for cataloged
    procedures (``EXEC name`` with no in-stream ``PROC name``) and ``INCLUDE``
    members: one member per file, named after the member, any extension.
    The parser is stateless between calls.
    """

    #: How many unreadable cards one job may have before it is given up on.
    MAX_RECOVERIES = 50

    def __init__(
        self, proc_paths: Sequence[str | os.PathLike[str]] | None = None
    ) -> None:
        self.proc_paths = list(proc_paths or [])

    def parse(self, text: str, *, filename: str = "<jcl>") -> JclParseResult:
        """Parse JCL source ``text``."""
        _require_jclparser()

        library_loader, member_loader = _make_loaders(self.proc_paths)
        jobs: list[JclJob] = []
        procedures: dict[str, list[JobStep]] = {}
        symbols: dict[str, str] = {}
        errors: list[dict[str, Any]] = []
        unresolved: list[str] = []

        chunks = _split_jobs(text)
        preamble = self._preamble_procedures(chunks, member_loader)
        for offset, chunk in chunks:
            job = self._parse_job(chunk, offset, member_loader, errors)
            if job is None:
                continue
            borrowed = [
                proc for proc in preamble if proc.name not in _names(job.procedures)
            ]
            job.procedures[:0] = borrowed
            for warning in job.warnings:
                if warning not in unresolved:
                    unresolved.append(warning)
            _note_duplicate_procedures(job, offset, unresolved)
            converter = _JobConverter(
                job, offset, library_loader, unresolved, errors, _names(borrowed)
            )
            converter.job_card = _statement_text(chunk, job.line_number)
            converted = converter.convert()
            has_job_card = converter.job_card is not None and bool(
                _JOB_CARD.match(converter.job_card)
            )
            if not has_job_card:
                unresolved.append(
                    "no JOB card: read as a cataloged procedure member, whose "
                    "steps run only when a job invokes it"
                )
            elif not job.name:
                errors.append(
                    {
                        "line": offset + (job.line_number or 1),
                        "message": "JOB statement has no job name",
                    }
                )
            _diagnose(converted, unresolved)
            if has_job_card or converted.steps:
                jobs.append(converted)
            for name, steps in converter.procedures().items():
                procedures.setdefault(name, steps)
            symbols.update(job.set_statements)

        return JclParseResult(
            jobs=jobs,
            procedures=procedures,
            symbols=symbols,
            errors=errors,
            unresolved=unresolved,
            filename=filename,
        )

    def _parse_job(
        self,
        chunk: str,
        offset: int,
        member_loader: Any,
        errors: list[dict[str, Any]],
    ) -> _JJob | None:
        """``jclparser`` stops at the first card it cannot read; record that
        card as an error, blank it out, and read the rest of the job."""
        from jclparser import parse_jcl as _jcl_parse
        from jclparser.errors import JCLParseError
        from jclparser.parser import split_source_lines

        lines = split_source_lines(chunk)
        for _ in range(self.MAX_RECOVERIES):
            try:
                job: _JJob = _jcl_parse(
                    "\n".join(lines),
                    enable_external_procs=False,
                    include_loader=member_loader,
                )
                return job
            except (JCLParseError, ValueError) as exc:
                line = getattr(exc, "line_number", 0) or 0
                errors.append(
                    {
                        "line": line + offset if line else offset + 1,
                        "message": getattr(exc, "message", None) or str(exc),
                    }
                )
                if not 0 < line <= len(lines) or lines[line - 1] == "//*":
                    return None
                lines[line - 1] = "//*"
        return None

    def _preamble_procedures(
        self, chunks: list[tuple[int, str]], member_loader: Any
    ) -> list[_JProc]:
        """In-stream procedures coded ahead of the first JOB card, which
        ``jclparser`` would otherwise not see from inside the job."""
        from jclparser import parse_jcl as _jcl_parse
        from jclparser.errors import JCLParseError

        if not chunks:
            return []
        from jclparser.parser import split_source_lines

        lines = split_source_lines(chunks[0][1])
        first = next((i for i, line in enumerate(lines) if _JOB_CARD.match(line)), None)
        if not first:
            return []
        try:
            head = _jcl_parse(
                "\n".join(lines[:first]),
                enable_external_procs=False,
                include_loader=member_loader,
            )
        except (JCLParseError, ValueError):
            return []
        return list(head.procedures)

    def parse_file(self, path: str | os.PathLike[str]) -> JclParseResult:
        """Parse the JCL file at ``path`` (UTF-8, undecodable bytes replaced)."""
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        return self.parse(text, filename=str(path))


def parse_jcl(
    text: str,
    *,
    filename: str = "<jcl>",
    proc_paths: Sequence[str | os.PathLike[str]] | None = None,
) -> JclParseResult:
    """Parse JCL source ``text``.  Convenience wrapper around :class:`JclParser`."""
    return JclParser(proc_paths).parse(text, filename=filename)
