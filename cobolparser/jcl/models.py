"""
Data model for parsed z/OS Job Control Language (JCL).

A JCL job is a sequence of job steps; each step names either a program
(``EXEC PGM=``) or a procedure (``EXEC PROC=`` / ``EXEC procname``) and owns a
set of DD statements.  A DD statement binds a *DD name* -- the name a COBOL
program sees in ``SELECT ... ASSIGN TO ddname`` -- to a real z/OS dataset, a
SYSOUT class, a DUMMY placeholder, or in-stream data.  Resolving that binding
is the whole point of reading JCL from a COBOL toolchain: nothing in the COBOL
source says which dataset ``INVFILE`` actually is.

Every node here is a plain dataclass with a ``to_dict()`` whose key order is
fixed by the literal that builds it, so ``json.dumps(result.to_dict())`` is
byte-identical for byte-identical input.

Two house rules run through the whole package and show up in this module as
:class:`JclParseResult`'s last two fields:

* ``errors`` -- one entry per card that could not be parsed, with the line
  number and the reason.  A card is never silently dropped.
* ``unresolved`` -- one entry per thing that was read but could not be fully
  resolved or modelled: a symbolic parameter with no value, an ``EXEC`` of a
  procedure that is not defined in this file, an ``INCLUDE`` that would need
  library access, a statement kind this package does not model.  A dataset
  name is never guessed; an unsubstituted ``&SYM`` stays in the text exactly
  as coded and is reported here instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def unquote(text: str) -> str:
    """Remove JCL apostrophe quoting from ``text``.

    ``'PARM STRING'`` becomes ``PARM STRING`` and the doubled apostrophes JCL
    uses to escape a literal one (``'IT''S'``) collapse to single ones.  Text
    that is not apostrophe-quoted is returned unchanged.
    """
    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    return text


@dataclass
class JclParameter:
    """One item of a JCL parameter field.

    Three shapes are represented, and which one applies is readable off the
    fields without re-parsing anything:

    * ``DSN=MY.DATA.SET`` -- ``keyword="DSN"``, ``value="MY.DATA.SET"``.
    * ``DISP=(NEW,CATLG,DELETE)`` -- ``keyword="DISP"``, ``value`` the raw
      parenthesised text, ``positional=["NEW", "CATLG", "DELETE"]``.
    * ``DCB=(RECFM=FB,LRECL=80)`` -- ``keyword="DCB"``, ``value`` the raw text,
      ``subparameters={"RECFM": "FB", "LRECL": "80"}``.  A mixed sub-list such
      as ``DCB=(MODEL.DSCB,RECFM=FB)`` fills both ``positional`` and
      ``subparameters``.

    A parameter coded without ``=`` is either a bare word (``DUMMY``, ``DATA``,
    ``*``, a procedure name on ``EXEC``), which lands in ``keyword`` with
    ``value=None``, or a quoted / parenthesised positional (the accounting
    information and programmer name on a JOB card), which lands in ``value``
    with an empty ``keyword``.

    ``value`` is always the text exactly as coded, apostrophes included; use
    :func:`unquote` to read the content of a quoted string.
    """

    keyword: str
    value: str | None
    subparameters: dict[str, str] = field(default_factory=dict)
    positional: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "keyword": self.keyword,
            "value": self.value,
            "subparameters": dict(self.subparameters),
            "positional": list(self.positional),
        }


@dataclass
class DDStatement:
    """A single DD card: the binding of a DD name to what backs it.

    ``dataset`` is the ``DSN=`` / ``DSNAME=`` value as coded, apostrophe
    quoting removed -- including any member (``PDS(MEMBER)``) or relative
    generation (``GDG(+1)``) qualifier, and including a leading ``&&`` for a
    temporary dataset.  It is ``None`` whenever no DSN was coded, which is the
    normal case for SYSOUT, DUMMY and in-stream data; those are flagged by
    ``sysout`` / ``is_dummy`` / ``is_instream`` instead.  It is never inferred.

    ``concatenated`` holds the unnamed DD cards that follow this one (a JCL
    dataset concatenation, e.g. a multi-library STEPLIB).  Each member repeats
    the owning card's ``name`` so that a binding lookup on the DD name finds
    every dataset in the concatenation.

    ``procstep`` is set only for a ``procstep.ddname`` override coded on the
    invocation of a procedure; ``name`` then holds just the ``ddname`` half.
    """

    name: str
    dataset: str | None
    disposition: str | None
    sysout: str | None = None
    is_dummy: bool = False
    is_instream: bool = False
    instream_lines: list[str] = field(default_factory=list)
    concatenated: list[DDStatement] = field(default_factory=list)
    record_format: str | None = None
    record_length: int | None = None
    parameters: list[JclParameter] = field(default_factory=list)
    line: int = 0
    procstep: str | None = None

    def flatten(self) -> list[DDStatement]:
        """This DD followed by every concatenated member, in card order."""
        out = [self]
        for member in self.concatenated:
            out.extend(member.flatten())
        return out

    def parameter(self, keyword: str) -> JclParameter | None:
        """The parameter coded with ``keyword``, or ``None``."""
        target = keyword.upper()
        for param in self.parameters:
            if param.keyword.upper() == target:
                return param
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dataset": self.dataset,
            "disposition": self.disposition,
            "sysout": self.sysout,
            "is_dummy": self.is_dummy,
            "is_instream": self.is_instream,
            "instream_lines": list(self.instream_lines),
            "record_format": self.record_format,
            "record_length": self.record_length,
            "procstep": self.procstep,
            "parameters": [p.to_dict() for p in self.parameters],
            "concatenated": [d.to_dict() for d in self.concatenated],
            "line": self.line,
        }


@dataclass
class JobStep:
    """One ``EXEC`` statement and the DD statements coded under it.

    Exactly one of ``program`` / ``procedure`` is normally set: ``PGM=`` gives
    a program step, ``PROC=name`` or a positional procedure name gives a
    procedure step.  A step produced by expanding an in-stream procedure has
    *both* -- ``program`` from the procedure's own ``EXEC PGM=`` and
    ``procedure`` naming the procedure it came from -- and its ``name`` is
    ``invocation.procstep``, the same qualified form z/OS itself reports.

    ``condition`` carries ``COND=`` when coded, otherwise the text of the
    enclosing ``IF``/``ELSE`` (``NOT (...)`` inside an ``ELSE``, several
    nested conditions joined with ``AND``), otherwise ``None``.

    A step inside an ``IF`` that also codes ``COND=`` runs only when both
    allow it, and ``condition`` holds only the ``COND=``. ``if_condition``
    (the enclosing ``IF``/``ELSE`` text, as above) and ``cond`` (the raw
    ``COND=``) keep the two apart; each is ``None`` when absent (#896).
    """

    name: str
    program: str | None
    procedure: str | None
    parm: str | None
    dd_statements: list[DDStatement]
    condition: str | None = None
    line: int = 0
    parameters: list[JclParameter] = field(default_factory=list)
    if_condition: str | None = None
    cond: str | None = None

    def effective_programs(self) -> list[str]:
        """The programs this step runs: ``PGM=``, or, for a launcher, what it
        launches -- every ``RUN PROGRAM(x)`` of an IKJEFT01/1A/1B step's
        in-stream ``SYSTSIN``, the application program of a DFSRRC00
        ``PARM='DLI|DBB|BMP,x,...'``. Empty for a procedure invocation, and
        for a TSO step whose ``SYSTSIN`` is not in-stream (the parser notes
        that in ``unresolved``)."""
        from .programs import IMS_CONTROLLER, TSO_PROGRAMS, ims_program, run_programs

        program = (self.program or "").upper()
        if program in TSO_PROGRAMS:
            systsin = self.dd("SYSTSIN")
            lines = [
                line
                for top in ([systsin] if systsin else [])
                for member in top.flatten()
                for line in member.instream_lines
            ]
            return run_programs("\n".join(lines))
        if program == IMS_CONTROLLER:
            launched = ims_program(self.parm)
            return [launched] if launched else [program]
        return [program] if program else []

    def dd(self, name: str) -> DDStatement | None:
        """The DD statement named ``name`` (case-insensitive), or ``None``."""
        target = name.strip().upper()
        for statement in self.dd_statements:
            if statement.name.upper() == target:
                return statement
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "program": self.program,
            "procedure": self.procedure,
            "parm": self.parm,
            "condition": self.condition,
            "if_condition": self.if_condition,
            "cond": self.cond,
            "parameters": [p.to_dict() for p in self.parameters],
            "dd_statements": [d.to_dict() for d in self.dd_statements],
            "line": self.line,
        }


@dataclass
class JclJob:
    """One ``JOB`` statement and everything coded under it.

    ``dd_statements`` holds job-level DD cards -- ``JOBLIB``, ``JOBCAT`` --
    which are coded before the first ``EXEC`` and belong to the job rather
    than to any step.
    """

    name: str
    steps: list[JobStep]
    parameters: list[JclParameter] = field(default_factory=list)
    line: int = 0
    dd_statements: list[DDStatement] = field(default_factory=list)

    def step(self, name: str) -> JobStep | None:
        """The step named ``name`` (case-insensitive), or ``None``."""
        target = name.strip().upper()
        for job_step in self.steps:
            if job_step.name.upper() == target:
                return job_step
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "parameters": [p.to_dict() for p in self.parameters],
            "dd_statements": [d.to_dict() for d in self.dd_statements],
            "steps": [s.to_dict() for s in self.steps],
            "line": self.line,
        }


@dataclass
class JclParseResult:
    """Everything one JCL member yielded, including what it did not yield.

    ``procedures`` maps the name of each in-stream ``PROC`` to the steps of
    its body, parsed once with the procedure's own default symbol values.
    ``symbols`` holds the values established by ``SET`` statements (procedure
    defaults and ``EXEC`` symbolic overrides are applied while expanding a
    procedure invocation and are deliberately not merged into this global
    table).  ``template_procedures`` names each procedure expanded from
    ``jclparser``'s template of an IBM-supplied procedure (``DLIBATCH``, ...)
    because neither this file nor the procedure path defines it.
    """

    jobs: list[JclJob]
    procedures: dict[str, list[JobStep]]
    symbols: dict[str, str]
    errors: list[dict[str, Any]]
    unresolved: list[str]
    filename: str = "<jcl>"
    template_procedures: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """True when every card parsed.  Says nothing about ``unresolved``."""
        return not self.errors

    def steps_running(self, program: str) -> list[JobStep]:
        """Every step that runs ``program``, across all jobs: its ``PGM=``,
        or the program a launcher step runs (``RUN PROGRAM(x)`` under
        IKJEFT01, the ``PARM`` program of DFSRRC00; see
        :meth:`JobStep.effective_programs`).

        Steps produced by expanding an in-stream procedure are included, so a
        program run only from inside a procedure is still found.
        """
        target = program.strip().upper()
        return [
            step
            for job in self.jobs
            for step in job.steps
            if (step.program is not None and step.program.upper() == target)
            or target in step.effective_programs()
        ]

    def all_dd_statements(self) -> list[tuple[JclJob, JobStep | None, DDStatement]]:
        """Every DD card in the result, paired with where it was coded.

        Job-level DD cards (JOBLIB and friends) come back with a ``None``
        step.  Concatenated members follow the card that owns them.  The order
        is job order, then step order, then card order.
        """
        out: list[tuple[JclJob, JobStep | None, DDStatement]] = []
        for job in self.jobs:
            for job_dd in job.dd_statements:
                out.extend((job, None, member) for member in job_dd.flatten())
            for step in job.steps:
                for step_dd in step.dd_statements:
                    out.extend((job, step, member) for member in step_dd.flatten())
        return out

    def dd_map(self) -> dict[str, list[str]]:
        """DD name -> every dataset it is bound to, across every step.

        Every DD name that appears anywhere is a key, even when nothing backs
        it with a dataset (SYSOUT, DUMMY, in-stream), in which case its list is
        empty -- an empty list means "seen, but not a dataset", while a missing
        key means "this DD name is not in the JCL at all".  Datasets are listed
        in the order they were encountered, without repeats.
        """
        out: dict[str, list[str]] = {}
        for _job, _step, dd in self.all_dd_statements():
            bucket = out.setdefault(dd.name.upper(), [])
            if dd.dataset is not None and dd.dataset not in bucket:
                bucket.append(dd.dataset)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "jobs": [job.to_dict() for job in self.jobs],
            "procedures": {
                name: [step.to_dict() for step in self.procedures[name]]
                for name in sorted(self.procedures)
            },
            "symbols": {name: self.symbols[name] for name in sorted(self.symbols)},
            "errors": [dict(error) for error in self.errors],
            "unresolved": list(self.unresolved),
            "template_procedures": list(self.template_procedures),
        }


@dataclass
class DatasetBinding:
    """One resolved ``ddname -> dataset`` pair, with the DCB facts a reader needs.

    This is the shape the rest of the toolchain consumes: given a COBOL
    ``SELECT INV-FILE ASSIGN TO INVFILE``, look ``INVFILE`` up here and get the
    dataset it is bound to in this job, which step binds it, how it is
    disposed, and (when the JCL says so) its RECFM and LRECL.

    ``program`` is the ``PGM=`` the binding step runs (``None`` for a
    job-level DD and for an ``EXEC proc`` step, which runs no program
    itself), so ``to_dict()`` rows feed ``field-impact --bindings`` as-is.
    """

    ddname: str
    dataset: str | None
    step: str
    job: str
    disposition: str | None = None
    record_format: str | None = None
    record_length: int | None = None
    program: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ddname": self.ddname,
            "dataset": self.dataset,
            "step": self.step,
            "job": self.job,
            "disposition": self.disposition,
            "record_format": self.record_format,
            "record_length": self.record_length,
            "program": self.program,
        }
