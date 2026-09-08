"""
Parser for z/OS Job Control Language.

Turns the card images scanned by :mod:`cobolparser.jcl.lexer` into the model
in :mod:`cobolparser.jcl.models`: jobs, steps, DD statements and the symbolic
parameter values that produced them.  It shares nothing with the COBOL parser
-- JCL is a different language with its own card format -- and adds no runtime
dependency.

What it understands
-------------------

``JOB``, ``EXEC``, ``DD``, ``PROC``, ``PEND``, ``SET``, ``INCLUDE``,
``IF``/``THEN``/``ELSE``/``ENDIF``, ``JCLLIB`` and ``OUTPUT``, plus ``//*``
comment cards, the null ``//`` end-of-job card and ``/*``-prefixed JES control
cards.

* ``EXEC PGM=name`` is a program step; ``EXEC procname`` and
  ``EXEC PROC=procname`` are procedure steps.  Both set ``JobStep.procedure``,
  and when the procedure is defined in-stream in the same file its body is
  *expanded*: one extra :class:`~cobolparser.jcl.models.JobStep` per procedure
  step is appended to the job, named ``invocation.procstep`` the way z/OS
  itself names it, carrying the procedure's own ``PGM=`` and DD statements
  with this invocation's symbol values substituted.  That is what makes a
  ``ddname -> dataset`` lookup work for programs run out of a procedure.
* ``procstep.ddname`` DD cards coded on the invocation override the matching
  DD of that procedure step, parameter by parameter; a DD name the procedure
  step does not have is an addition.  The invocation keeps its own copy of
  every override card, so nothing is moved out of sight.
* Symbolic parameters (``&SYM``, ``&SYM.``) are substituted from ``SET``
  values, procedure defaults and ``EXEC`` overrides, in that order of
  increasing precedence.  ``&&`` is left alone: it introduces a temporary
  dataset name, not a symbol.  Substitution is *not* performed on the ``JOB``
  card, matching z/OS, so a ``NOTIFY=&SYSUID`` does not read as an unresolved
  user symbol.

What it deliberately does not do
--------------------------------

Nothing here reaches outside the file it was handed.  A procedure that is not
defined in-stream is not searched for in a PROCLIB, an ``INCLUDE`` group is
not expanded, and ``JCLLIB ORDER=`` is recorded but not honoured -- each of
those lands in ``JclParseResult.unresolved`` instead, naming what could not be
resolved and why.  ``OUTPUT``, ``CNTL``/``ENDCNTL``, ``COMMAND``, ``XMIT`` and
JES control cards are recognised, kept out of the error list, and reported as
not modelled.  Dataset names are never invented: a DSN whose symbols could not
all be resolved is stored exactly as coded and reported in ``unresolved``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from .lexer import (
    KIND_COMMENT,
    KIND_JES,
    KIND_NULL,
    KIND_STATEMENT,
    JclCard,
    find_top_level_equals,
    scan_cards,
    split_top_level,
)
from .models import (
    DDStatement,
    JclJob,
    JclParameter,
    JclParseResult,
    JobStep,
    unquote,
)

#: ``EXEC`` keywords that are parameters of the step itself.  Anything else
#: coded with a value on an ``EXEC`` is a symbolic parameter override for the
#: procedure being invoked.
EXEC_KEYWORDS = frozenset(
    {
        "PGM",
        "PROC",
        "PARM",
        "PARMDD",
        "COND",
        "REGION",
        "REGIONX",
        "TIME",
        "ACCT",
        "ADDRSPC",
        "DYNAMNBR",
        "PERFORM",
        "RD",
        "CCSID",
        "MEMLIMIT",
        "RLSTMOUT",
    }
)

#: Statements that are recognised, kept, but not modelled as job structure.
_UNMODELLED_OPERATIONS = {
    "OUTPUT": "JES output descriptor",
    "CNTL": "program control statement group",
    "ENDCNTL": "program control statement group",
    "COMMAND": "operator command",
    "XMIT": "transmission statement",
    "NOTIFY": "notify statement",
}

_MAX_SYMBOL_LENGTH = 8
_MAX_SUBSTITUTION_PASSES = 5
_THEN_RE = re.compile(r"\bTHEN\b", re.IGNORECASE)


@dataclass
class _IfFrame:
    """One open ``IF`` block."""

    condition: str
    line: int
    in_else: bool = False


@dataclass
class _Sink:
    """Where the steps of one job -- or of one procedure body -- accumulate."""

    steps: list[JobStep]
    job_dds: list[DDStatement]
    symbols: dict[str, str]
    expand_procs: bool
    context: str
    current_step: JobStep | None = None
    current_overrides: dict[str, str] = field(default_factory=dict)
    last_dd: DDStatement | None = None
    if_stack: list[_IfFrame] = field(default_factory=list)


def _clone_dd(dd: DDStatement, *, procstep: str | None = None) -> DDStatement:
    """A deep-enough copy of ``dd`` so callers can mutate it independently."""
    return DDStatement(
        name=dd.name,
        dataset=dd.dataset,
        disposition=dd.disposition,
        sysout=dd.sysout,
        is_dummy=dd.is_dummy,
        is_instream=dd.is_instream,
        instream_lines=list(dd.instream_lines),
        concatenated=[_clone_dd(member) for member in dd.concatenated],
        record_format=dd.record_format,
        record_length=dd.record_length,
        parameters=[
            JclParameter(
                keyword=p.keyword,
                value=p.value,
                subparameters=dict(p.subparameters),
                positional=list(p.positional),
            )
            for p in dd.parameters
        ],
        line=dd.line,
        procstep=procstep,
    )


class _Builder:
    """Single-use parse state.  One instance per :meth:`JclParser.parse` call."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.jobs: list[JclJob] = []
        self.symbols: dict[str, str] = {}
        self.errors: list[dict[str, Any]] = []
        self.unresolved: list[str] = []
        self.proc_bodies: dict[str, tuple[str, list[JclCard], dict[str, str]]] = {}
        self._seen_errors: set[tuple[int, str]] = set()
        self._seen_unresolved: set[str] = set()
        self._implicit_job_reported = False

    # -- diagnostics -----------------------------------------------------
    def _error(self, line: int, message: str) -> None:
        key = (line, message)
        if key in self._seen_errors:
            return
        self._seen_errors.add(key)
        self.errors.append({"line": line, "message": message})

    def _note(self, message: str) -> None:
        if message in self._seen_unresolved:
            return
        self._seen_unresolved.add(message)
        self.unresolved.append(message)

    # -- entry point -----------------------------------------------------
    def build(self, text: str) -> JclParseResult:
        scan = scan_cards(text)
        for error in scan.errors:
            self._error(int(error["line"]), str(error["message"]))
        top_level = self._collect_procedures(scan.cards)
        self._process_top_level(top_level)
        procedures = self._parse_declared_procedures()
        self.errors.sort(key=lambda entry: entry["line"])
        return JclParseResult(
            jobs=self.jobs,
            procedures=procedures,
            symbols=self.symbols,
            errors=self.errors,
            unresolved=self.unresolved,
            filename=self.filename,
        )

    # -- pass 1: lift in-stream procedure bodies out of the deck ---------
    def _collect_procedures(self, cards: list[JclCard]) -> list[JclCard]:
        top_level: list[JclCard] = []
        name: str | None = None
        coded_name = ""
        body: list[JclCard] = []
        defaults: dict[str, str] = {}
        start_line = 0
        for card in cards:
            is_statement = card.kind == KIND_STATEMENT
            if is_statement and card.operation == "PROC":
                if name is not None:
                    self._error(
                        card.line,
                        f"PROC {card.name or '(unnamed)'} appears inside procedure "
                        f"{coded_name}; nested procedures are not supported",
                    )
                    continue
                if not card.name:
                    self._note(
                        f"PROC statement (line {card.line}): no procedure name, so "
                        "this is a cataloged-procedure header rather than an "
                        "in-stream procedure; its body is read as ordinary JCL"
                    )
                    top_level.append(card)
                    continue
                name = card.name.upper()
                coded_name = card.name
                body = []
                defaults = self._procedure_defaults(card)
                start_line = card.line
                continue
            if is_statement and card.operation == "PEND":
                if name is None:
                    top_level.append(card)
                    continue
                self._store_procedure(name, coded_name, body, defaults, start_line)
                name = None
                continue
            if name is not None:
                body.append(card)
            else:
                top_level.append(card)
        if name is not None:
            self._error(
                start_line,
                f"PROC {coded_name} is never ended by a PEND statement",
            )
            self._store_procedure(name, coded_name, body, defaults, start_line)
        return top_level

    def _store_procedure(
        self,
        key: str,
        coded_name: str,
        body: list[JclCard],
        defaults: dict[str, str],
        line: int,
    ) -> None:
        if key in self.proc_bodies:
            self._error(
                line,
                f"PROC {coded_name} is defined more than once; the first "
                "definition is used",
            )
            return
        self.proc_bodies[key] = (coded_name, list(body), defaults)

    def _procedure_defaults(self, card: JclCard) -> dict[str, str]:
        defaults: dict[str, str] = {}
        for param in self._parse_parameters(card.parameters):
            if not param.keyword:
                self._error(
                    card.line,
                    f"PROC {card.name}: positional parameter {param.value!r} is "
                    "not a symbolic parameter default",
                )
                continue
            defaults[param.keyword.upper()] = unquote(param.value or "")
        return defaults

    def _parse_declared_procedures(self) -> dict[str, list[JobStep]]:
        """Parse each in-stream procedure body once, with its own defaults."""
        procedures: dict[str, list[JobStep]] = {}
        for key, (coded_name, body, defaults) in self.proc_bodies.items():
            symbols = dict(self.symbols)
            symbols.update(defaults)
            procedures[coded_name] = self._parse_procedure_body(key, body, symbols)
        return procedures

    # -- pass 2: jobs, steps, DD statements ------------------------------
    def _process_top_level(self, cards: list[JclCard]) -> None:
        sink: _Sink | None = None
        job: JclJob | None = None
        for card in cards:
            if card.kind == KIND_COMMENT:
                continue
            if card.kind == KIND_JES:
                self._note(
                    f"{card.parameters.split()[0]} (line {card.line}): JES control "
                    "statement is recognised but not modelled"
                )
                continue
            if card.kind == KIND_NULL:
                if sink is not None:
                    self._close_sink(sink)
                sink = None
                job = None
                continue
            if card.kind != KIND_STATEMENT:  # pragma: no cover - defensive
                continue
            if card.operation == "JOB":
                if sink is not None:
                    self._close_sink(sink)
                job = self._make_job(card)
                self.jobs.append(job)
                sink = _Sink(
                    steps=job.steps,
                    job_dds=job.dd_statements,
                    symbols=self.symbols,
                    expand_procs=True,
                    context=f"job {job.name or '(unnamed)'}",
                )
                continue
            if card.operation == "PEND":
                self._error(
                    card.line, "PEND statement without a matching PROC statement"
                )
                continue
            if job is None and card.operation in ("EXEC", "DD"):
                job = self._implicit_job(card)
                self.jobs.append(job)
                sink = _Sink(
                    steps=job.steps,
                    job_dds=job.dd_statements,
                    symbols=self.symbols,
                    expand_procs=True,
                    context="implicit job",
                    if_stack=sink.if_stack if sink is not None else [],
                )
            elif sink is None:
                sink = _Sink(
                    steps=[],
                    job_dds=[],
                    symbols=self.symbols,
                    expand_procs=False,
                    context="before the first JOB statement",
                )
            self._dispatch(card, sink)
        if sink is not None:
            self._close_sink(sink)

    def _make_job(self, card: JclCard) -> JclJob:
        # Symbolic substitution is not performed on the JOB statement, so its
        # parameters are recorded exactly as coded.
        if not card.name:
            self._error(card.line, "JOB statement has no job name")
        return JclJob(
            name=card.name,
            steps=[],
            parameters=self._parse_parameters(card.parameters),
            line=card.line,
        )

    def _implicit_job(self, card: JclCard) -> JclJob:
        if not self._implicit_job_reported:
            self._implicit_job_reported = True
            self._error(
                card.line,
                f"{card.operation} statement appears before any JOB statement; "
                "its steps are attached to an unnamed job",
            )
        return JclJob(name="", steps=[], parameters=[], line=card.line)

    def _close_sink(self, sink: _Sink) -> None:
        self._finish_step(sink)
        for frame in sink.if_stack:
            self._error(
                frame.line,
                f"IF statement in {sink.context} is never closed by an ENDIF",
            )
        sink.if_stack.clear()

    # -- statement dispatch ----------------------------------------------
    def _dispatch(self, card: JclCard, sink: _Sink) -> None:
        operation = card.operation
        if operation == "EXEC":
            self._handle_exec(card, sink)
        elif operation == "DD":
            self._handle_dd(card, sink)
        elif operation == "SET":
            self._handle_set(card, sink)
        elif operation == "IF":
            self._handle_if(card, sink)
        elif operation == "ELSE":
            self._handle_else(card, sink)
        elif operation == "ENDIF":
            self._handle_endif(card, sink)
        elif operation == "INCLUDE":
            member = self._include_member(card, sink)
            self._note(
                f"INCLUDE {member} (line {card.line}): the group was not expanded; "
                "this parser reads only the file it was given"
            )
        elif operation == "JCLLIB":
            self._note(
                f"JCLLIB (line {card.line}): procedure libraries are not searched, "
                "so procedures not defined in this file stay unresolved"
            )
        elif operation in _UNMODELLED_OPERATIONS:
            named = f"{operation} {card.name}" if card.name else operation
            self._note(
                f"{named} (line {card.line}): "
                f"{_UNMODELLED_OPERATIONS[operation]} is recognised but not "
                "modelled"
            )
        else:
            self._error(
                card.line,
                f"unknown JCL operation {operation!r} on statement "
                f"{card.name or '(unnamed)'}",
            )

    def _include_member(self, card: JclCard, sink: _Sink) -> str:
        for param in self._parameters(card, sink):
            if param.keyword.upper() == "MEMBER":
                return param.value or "(unnamed)"
        return "(no MEMBER= parameter)"

    # -- EXEC -------------------------------------------------------------
    def _handle_exec(self, card: JclCard, sink: _Sink) -> None:
        self._finish_step(sink)
        params = self._parameters(card, sink)
        program: str | None = None
        procedure: str | None = None
        parm: str | None = None
        condition: str | None = None
        overrides: dict[str, str] = {}
        for index, param in enumerate(params):
            keyword = param.keyword.upper()
            if keyword == "PGM":
                program = unquote(param.value or "")
            elif keyword == "PROC":
                procedure = unquote(param.value or "")
            elif keyword == "PARM":
                parm = unquote(param.value) if param.value is not None else ""
            elif keyword == "COND":
                condition = param.value
            elif keyword in EXEC_KEYWORDS:
                continue
            elif param.value is None and keyword:
                if index == 0 and procedure is None and program is None:
                    procedure = param.keyword
                else:
                    self._error(
                        card.line,
                        f"EXEC statement {card.name or '(unnamed)'}: unexpected "
                        f"positional parameter {param.keyword!r}",
                    )
            elif not keyword:
                self._error(
                    card.line,
                    f"EXEC statement {card.name or '(unnamed)'}: unexpected "
                    f"positional parameter {param.value!r}",
                )
            else:
                overrides[keyword] = unquote(param.value or "")
        if program is None and procedure is None:
            self._error(
                card.line,
                f"EXEC statement {card.name or '(unnamed)'} names neither PGM= "
                "nor a procedure",
            )
        step = JobStep(
            name=card.name,
            program=program,
            procedure=procedure,
            parm=parm,
            dd_statements=[],
            condition=condition or self._if_condition(sink),
            line=card.line,
            parameters=params,
        )
        sink.steps.append(step)
        sink.current_step = step
        sink.current_overrides = overrides
        sink.last_dd = None

    def _finish_step(self, sink: _Sink) -> None:
        step = sink.current_step
        sink.current_step = None
        sink.last_dd = None
        overrides = sink.current_overrides
        sink.current_overrides = {}
        if step is None:
            return
        if step.procedure and sink.expand_procs:
            self._expand_procedure(sink, step, overrides)
        elif step.procedure:
            self._note(
                f"EXEC {step.procedure} (line {step.line}): a procedure invoked "
                "from inside another procedure is not expanded"
            )

    # -- DD ---------------------------------------------------------------
    def _handle_dd(self, card: JclCard, sink: _Sink) -> None:
        params = self._parameters(card, sink)
        coded_name = card.name
        procstep: str | None = None
        name = coded_name
        if "." in coded_name:
            procstep, _, name = coded_name.partition(".")
        dd = self._dd_from_parameters(name, params, card.line, procstep)
        if card.instream_lines is not None:
            dd.is_instream = True
            dd.instream_lines = list(card.instream_lines)
        if not coded_name:
            owner = sink.last_dd
            if owner is None:
                self._error(
                    card.line,
                    "unnamed DD statement does not follow a named DD statement, "
                    "so there is nothing for it to be concatenated to",
                )
                self._append_dd(sink, dd)
                return
            dd.name = owner.name
            dd.procstep = owner.procstep
            owner.concatenated.append(dd)
            return
        self._append_dd(sink, dd)
        sink.last_dd = dd

    def _append_dd(self, sink: _Sink, dd: DDStatement) -> None:
        if sink.current_step is None:
            sink.job_dds.append(dd)
        else:
            sink.current_step.dd_statements.append(dd)

    def _dd_from_parameters(
        self,
        name: str,
        params: list[JclParameter],
        line: int,
        procstep: str | None,
    ) -> DDStatement:
        dataset: str | None = None
        disposition: str | None = None
        sysout: str | None = None
        is_dummy = False
        record_format: str | None = None
        record_length: int | None = None
        for param in params:
            keyword = param.keyword.upper()
            # A parameter coded with an empty value (`SYSOUT=`) is JCL's way of
            # nullifying it on an overriding DD statement, so it reads as absent.
            if keyword in ("DSN", "DSNAME"):
                dataset = unquote(param.value) if param.value else None
            elif keyword == "DISP":
                disposition = param.value or None
            elif keyword == "SYSOUT":
                sysout = param.value or None
            elif keyword == "DUMMY" and param.value is None:
                is_dummy = True
            elif keyword == "RECFM":
                record_format = param.value or None
            elif keyword == "LRECL":
                record_length = (
                    self._as_length(param.value, name, line) if param.value else None
                )
            elif keyword == "DCB":
                if "RECFM" in param.subparameters:
                    record_format = param.subparameters["RECFM"]
                if "LRECL" in param.subparameters:
                    record_length = self._as_length(
                        param.subparameters["LRECL"], name, line
                    )
        if dataset is not None and "&" in dataset and not dataset.startswith("&&"):
            self._note(
                f"DD {name or '(unnamed)'} (line {line}): dataset name "
                f"{dataset!r} still contains an unresolved symbolic parameter and "
                "is reported exactly as coded"
            )
        return DDStatement(
            name=name,
            dataset=dataset,
            disposition=disposition,
            sysout=sysout,
            is_dummy=is_dummy,
            is_instream=False,
            instream_lines=[],
            concatenated=[],
            record_format=record_format,
            record_length=record_length,
            parameters=params,
            line=line,
            procstep=procstep,
        )

    def _as_length(self, value: str | None, name: str, line: int) -> int | None:
        if value is not None and value.isdigit():
            return int(value)
        self._note(
            f"DD {name or '(unnamed)'} (line {line}): LRECL={value} is not a "
            "number, so the record length is unknown"
        )
        return None

    # -- SET / IF / ELSE / ENDIF -----------------------------------------
    def _handle_set(self, card: JclCard, sink: _Sink) -> None:
        text = self._substitute(card.parameters, sink.symbols, card.line)
        items = [item.strip() for item in split_top_level(text)]
        if not any(items):
            self._error(card.line, "SET statement has no symbolic parameters")
            return
        for item in items:
            if not item:
                continue
            equals = find_top_level_equals(item)
            if equals < 0:
                self._error(
                    card.line,
                    f"SET parameter {item!r} is not of the form name=value",
                )
                continue
            sink.symbols[item[:equals].strip().upper()] = unquote(
                item[equals + 1 :].strip()
            )

    def _handle_if(self, card: JclCard, sink: _Sink) -> None:
        text = self._substitute(card.parameters, sink.symbols, card.line).strip()
        match = _THEN_RE.search(text)
        if match is None:
            self._error(card.line, "IF statement is missing the THEN keyword")
            condition = text
        else:
            condition = text[: match.start()].strip()
        if not condition:
            self._error(card.line, "IF statement has no relational expression")
        sink.if_stack.append(_IfFrame(condition=condition, line=card.line))

    def _handle_else(self, card: JclCard, sink: _Sink) -> None:
        if not sink.if_stack:
            self._error(card.line, "ELSE statement without a matching IF statement")
            return
        frame = sink.if_stack[-1]
        if frame.in_else:
            self._error(card.line, "second ELSE statement for the same IF statement")
            return
        frame.in_else = True

    def _handle_endif(self, card: JclCard, sink: _Sink) -> None:
        if not sink.if_stack:
            self._error(card.line, "ENDIF statement without a matching IF statement")
            return
        sink.if_stack.pop()

    def _if_condition(self, sink: _Sink) -> str | None:
        if not sink.if_stack:
            return None
        parts = [
            f"NOT ({frame.condition})" if frame.in_else else frame.condition
            for frame in sink.if_stack
        ]
        return " AND ".join(parts)

    # -- procedures -------------------------------------------------------
    def _expand_procedure(
        self, sink: _Sink, step: JobStep, overrides: dict[str, str]
    ) -> None:
        key = (step.procedure or "").upper()
        entry = self.proc_bodies.get(key)
        if entry is None:
            self._note(
                f"PROC {step.procedure} (line {step.line}): the procedure is not "
                "defined in this file, so its steps and DD statements could not "
                "be expanded"
            )
            return
        coded_name, body, defaults = entry
        symbols = dict(self.symbols)
        symbols.update(defaults)
        symbols.update(overrides)
        proc_steps = self._parse_procedure_body(key, body, symbols)
        self._apply_dd_overrides(step, coded_name, proc_steps)
        prefix = f"{step.name}." if step.name else ""
        for proc_step in proc_steps:
            proc_step.name = f"{prefix}{proc_step.name}"
            if proc_step.procedure is None:
                # A step of the procedure body itself; a step that invokes a
                # further procedure keeps the name it invoked.
                proc_step.procedure = coded_name
            if proc_step.condition is None:
                proc_step.condition = step.condition
            sink.steps.append(proc_step)

    def _parse_procedure_body(
        self, key: str, body: list[JclCard], symbols: dict[str, str]
    ) -> list[JobStep]:
        coded_name = self.proc_bodies[key][0] if key in self.proc_bodies else key
        sink = _Sink(
            steps=[],
            job_dds=[],
            symbols=dict(symbols),
            expand_procs=False,
            context=f"procedure {coded_name}",
        )
        for card in body:
            if card.kind == KIND_COMMENT:
                continue
            if card.kind == KIND_JES:
                self._note(
                    f"{card.parameters.split()[0]} (line {card.line}): JES control "
                    "statement is recognised but not modelled"
                )
                continue
            if card.kind == KIND_NULL:
                self._error(
                    card.line,
                    f"null statement inside procedure {coded_name}",
                )
                continue
            if card.operation in ("JOB", "PROC", "PEND"):
                self._error(
                    card.line,
                    f"{card.operation} statement is not allowed inside "
                    f"procedure {coded_name}",
                )
                continue
            self._dispatch(card, sink)
        self._close_sink(sink)
        for dd in sink.job_dds:
            self._error(
                dd.line,
                f"DD {dd.name or '(unnamed)'} precedes the first EXEC statement "
                f"of procedure {coded_name}",
            )
        return sink.steps

    def _apply_dd_overrides(
        self, invocation: JobStep, proc_name: str, proc_steps: list[JobStep]
    ) -> None:
        for dd in invocation.dd_statements:
            target: JobStep | None = None
            if dd.procstep:
                for candidate in proc_steps:
                    if candidate.name.upper() == dd.procstep.upper():
                        target = candidate
                        break
                if target is None:
                    self._note(
                        f"DD {dd.procstep}.{dd.name} (line {dd.line}): procedure "
                        f"{proc_name} has no step named {dd.procstep}, so the "
                        "override was not applied"
                    )
                    continue
            elif len(proc_steps) == 1:
                target = proc_steps[0]
            else:
                self._note(
                    f"DD {dd.name} (line {dd.line}): coded on an EXEC of "
                    f"procedure {proc_name}, which has {len(proc_steps)} steps, "
                    "without a procstep qualifier, so the override was not applied"
                )
                continue
            existing = target.dd(dd.name)
            if existing is None:
                target.dd_statements.append(_clone_dd(dd))
                continue
            merged = self._merge_dd(existing, dd)
            target.dd_statements[target.dd_statements.index(existing)] = merged

    def _merge_dd(self, base: DDStatement, override: DDStatement) -> DDStatement:
        params: list[JclParameter] = [
            JclParameter(
                keyword=p.keyword,
                value=p.value,
                subparameters=dict(p.subparameters),
                positional=list(p.positional),
            )
            for p in base.parameters
        ]
        for param in override.parameters:
            keyword = param.keyword.upper()
            replaced = False
            if keyword:
                for index, existing in enumerate(params):
                    if existing.keyword.upper() == keyword:
                        params[index] = param
                        replaced = True
                        break
            if not replaced:
                params.append(param)
        merged = self._dd_from_parameters(base.name, params, override.line, None)
        if override.is_instream:
            merged.is_instream = True
            merged.instream_lines = list(override.instream_lines)
        elif base.is_instream:
            merged.is_instream = True
            merged.instream_lines = list(base.instream_lines)
        source = override.concatenated or base.concatenated
        merged.concatenated = [_clone_dd(member) for member in source]
        for member in merged.concatenated:
            member.name = merged.name
        return merged

    # -- parameters and symbols ------------------------------------------
    def _parameters(self, card: JclCard, sink: _Sink) -> list[JclParameter]:
        text = self._substitute(card.parameters, sink.symbols, card.line)
        return self._parse_parameters(text)

    def _parse_parameters(self, text: str) -> list[JclParameter]:
        params: list[JclParameter] = []
        for raw in split_top_level(text):
            item = raw.strip()
            if not item:
                continue
            params.append(self._parse_parameter(item))
        return params

    def _parse_parameter(self, item: str) -> JclParameter:
        equals = find_top_level_equals(item)
        if equals >= 0:
            param = JclParameter(
                keyword=item[:equals].strip(), value=item[equals + 1 :].strip()
            )
            value = param.value or ""
            if value.startswith("(") and value.endswith(")"):
                for raw_sub in split_top_level(value[1:-1]):
                    sub = raw_sub.strip()
                    if not sub:
                        continue
                    sub_equals = find_top_level_equals(sub)
                    if sub_equals >= 0:
                        param.subparameters[sub[:sub_equals].strip().upper()] = sub[
                            sub_equals + 1 :
                        ].strip()
                    else:
                        param.positional.append(sub)
            return param
        if item.startswith("(") or item.startswith("'"):
            param = JclParameter(keyword="", value=item)
            if item.startswith("(") and item.endswith(")"):
                param.positional = [
                    sub.strip() for sub in split_top_level(item[1:-1]) if sub.strip()
                ]
            return param
        return JclParameter(keyword=item, value=None)

    def _substitute(
        self, text: str, symbols: dict[str, str], line: int, depth: int = 0
    ) -> str:
        if "&" not in text:
            return text
        out: list[str] = []
        index = 0
        changed = False
        while index < len(text):
            char = text[index]
            if char != "&":
                out.append(char)
                index += 1
                continue
            if text[index + 1 : index + 2] == "&":
                # `&&` introduces a temporary dataset name, not a symbol.
                out.append("&&")
                index += 2
                continue
            end = index + 1
            while (
                end < len(text)
                and (end - index - 1) < _MAX_SYMBOL_LENGTH
                and (text[end].isalnum() or text[end] in "@#$")
            ):
                end += 1
            name = text[index + 1 : end]
            if not name or not (name[0].isalpha() or name[0] in "@#$"):
                out.append("&")
                index += 1
                continue
            key = name.upper()
            if key in symbols:
                out.append(symbols[key])
                changed = True
                index = end
                if text[index : index + 1] == ".":
                    index += 1
                continue
            out.append("&" + name)
            index = end
            self._note(
                f"&{name} (line {line}): symbolic parameter has no value here, so "
                "the text is left exactly as coded"
            )
        result = "".join(out)
        if changed and "&" in result and depth + 1 < _MAX_SUBSTITUTION_PASSES:
            return self._substitute(result, symbols, line, depth + 1)
        return result


class JclParser:
    """Parses z/OS JCL into a :class:`~cobolparser.jcl.models.JclParseResult`.

    The parser is stateless between calls: every :meth:`parse` builds its own
    state, so the same instance can be reused and the same text always yields
    the same result.
    """

    def parse(self, text: str, *, filename: str = "<jcl>") -> JclParseResult:
        """Parse JCL source ``text``."""
        return _Builder(filename).build(text)

    def parse_file(self, path: str | os.PathLike[str]) -> JclParseResult:
        """Parse the JCL file at ``path``.

        The file is read as UTF-8 with undecodable bytes replaced, so a deck
        transferred from EBCDIC without conversion produces errors rather than
        an exception.
        """
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        return self.parse(text, filename=str(path))


def parse_jcl(text: str, *, filename: str = "<jcl>") -> JclParseResult:
    """Parse JCL source ``text``.  Convenience wrapper around :class:`JclParser`."""
    return JclParser().parse(text, filename=filename)
