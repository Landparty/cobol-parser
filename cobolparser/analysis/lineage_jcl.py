"""Dataset bindings and utility pass-throughs for field lineage, read off
jobs parsed by **jcl-parser** (``pip install jcl-parser``).

``lineage_graph.LineageGraph`` joins programs through datasets, so it needs
to know which dataset each program's DD names are bound to, and which
utility steps copy one dataset into another. This module turns jcl-parser
``Job`` objects into exactly those two lists. It is duck-typed over
jcl-parser's model (``job.name``, ``job.steps``, ``step.program``,
``step.dd_statements``, ``dd.name``, ``dd.dataset_name``,
``dd.inline_data``, IF/THEN ``ConditionalBlock`` ``then_steps`` /
``else_steps``) and imports jcl-parser only in :func:`load_jobs`, so
cobol-parser keeps no runtime dependency on it.

Utility steps understood:

- DFSORT / ICEMAN / SYNCSORT: ``SORTIN`` (and ``SORTINnn``) to ``SORTOUT``,
  every ``OUTFIL FNAMES=`` and every ``OUTFIL FILES=`` (``SORTOFnn`` /
  ``SORTOFd``). A ``JOINKEYS`` step reads ``SORTJNF1`` / ``SORTJNF2`` (or
  the DDs its ``F1=`` / ``F2=`` name) and is always a ``reformat``: a join
  builds new records. ``SORT``/``MERGE FIELDS``, ``INCLUDE``,
  ``OMIT`` keep bytes in place; ``SUM FIELDS=(p,l,f,...)`` rewrites the
  ranges it names (``kind="aggregate"`` there); ``INREC``, ``OUTREC``,
  ``BUILD``, ``OVERLAY``, ``FINDREP`` and ``IFTHEN`` move bytes, so the step
  is a ``reformat`` and the flow stops with a caveat. A sort step whose
  inputs or outputs are not recognised adds a caveat instead of vanishing.
- ICETOOL: every ``COPY`` / ``SORT`` / ``MERGE`` / ``SELECT`` / ``SUBSET`` /
  ``DATASORT`` operator in ``TOOLIN`` carries ``FROM(dd)`` to ``TO(dd...)``
  (and ``DISCARD(dd)``), read as a DFSORT step through its ``USING(xxxx)``
  ``xxxxCNTL`` statements; ``SPLICE`` / ``RESIZE`` are reformats.
- IEBGENER / ICEGENER: ``SYSUT1`` to ``SYSUT2`` (a ``GENERATE``/``RECORD``
  control statement makes it a reformat).
- IDCAMS ``REPRO`` with ``INFILE``/``OUTFILE`` DD names or
  ``INDATASET``/``OUTDATASET`` names, in either order.

Control statements read from a dataset (``//SYSIN DD DSN=PROD.CNTL(X)``, a
``DFSPARM`` dataset) cannot be seen, so the step is never assumed to be a
byte-for-byte copy: it is a ``reformat`` (the flow stops there) and a caveat
names the control dataset.

A concatenated DD (a DD statement with a blank name after a named one) is
part of the DD before it: every dataset of ``//SORTIN DD DSN=A`` /
``//  DD DSN=B`` is an input. ``DD DUMMY`` and ``DSN=NULLFILE`` bind nothing.
A ``DSN=*.STEP.DD`` referback is replaced by the dataset it names.
Quoted literals in utility control statements (``INCLUDE COND=(...,
C'BUILD')``) are blanked before keywords are looked for.
- IKJEFT01 / IKJEFT1A / IKJEFT1B: the program named by ``RUN PROGRAM(x)``
  in ``SYSTSIN`` is bound to the step's DDs (the DB2 batch pattern).
- DFSRRC00 (the IMS region controller): for a ``DLI`` / ``DBB`` / ``BMP``
  region, the program named by the second ``PARM`` positional
  (``PARM='BMP,LOANPMT,LOANPSB,...'``) is bound to the step's DDs (the IMS
  batch pattern, ``DLIBATCH`` / ``DBBBATCH`` / ``IMSBATCH`` PROCs).
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .lineage_graph import DatasetBinding, Passthrough

_SORT_PROGRAMS = frozenset({"SORT", "DFSORT", "ICEMAN", "SYNCSORT"})
_ICETOOL = "ICETOOL"
#: ICETOOL operators that write records ``FROM(dd...)`` ``TO(dd...)``; the
#: value says whether the records keep their bytes (``copy``) or not.
_ICETOOL_OPERATORS = {
    "COPY": "copy",
    "SORT": "copy",
    "MERGE": "copy",
    "SELECT": "copy",
    "SUBSET": "copy",
    "DATASORT": "copy",
    "SPLICE": "reformat",
    "RESIZE": "reformat",
}
_COPY_PROGRAMS = frozenset({"IEBGENER", "ICEGENER"})
_TSO_PROGRAMS = frozenset({"IKJEFT01", "IKJEFT1A", "IKJEFT1B"})
_IMS_CONTROLLER = "DFSRRC00"
#: IMS region types whose ``PARM`` names the application program second.
_IMS_BATCH_REGIONS = frozenset({"DLI", "DBB", "BMP"})
_REFORMAT_RE = re.compile(
    r"\b(INREC|OUTREC|BUILD|OVERLAY|FINDREP|IFTHEN|PARSE|REFORMAT|JOINKEYS)\b"
)
_SUM_RE = re.compile(r"\bSUM\s+FIELDS\s*=\s*\(([^)]*)\)")
_FNAMES_RE = re.compile(r"\bFNAMES\s*=\s*\(?([A-Z0-9@#$,\s]+)\)?")
#: ``OUTFIL FILES=01`` / ``FILES=(01,A)``: output DDs ``SORTOF01`` / ``SORTOFA``.
_FILES_RE = re.compile(r"\bFILES\s*=\s*\(?([A-Z0-9@#$,\s]+)\)?")
#: ``JOINKEYS F1=ddname`` / ``F2=ddname``: the join's input DDs, renamed.
_JOIN_DD_RE = re.compile(r"\bF([12])\s*=\s*([A-Z@#$][A-Z0-9@#$]{0,7})\b")
_RUN_PROGRAM_RE = re.compile(r"\bRUN\s+PROGRAM\s*\(\s*([A-Z0-9@#$]+)\s*\)")
_REPRO_IN_RE = re.compile(
    r"\b(INFILE|INDATASET|IFILE|IDS)\s*\(\s*'?([A-Z0-9@#$.()+-]+?)'?\s*\)"
)
_REPRO_OUT_RE = re.compile(
    r"\b(OUTFILE|OUTDATASET|OFILE|ODS)\s*\(\s*'?([A-Z0-9@#$.()+-]+?)'?\s*\)"
)
#: IDCAMS commands: where one REPRO's operands end.
_IDCAMS_COMMAND_RE = re.compile(
    r"\b(REPRO|DEFINE|DELETE|PRINT|LISTCAT|ALTER|VERIFY|EXPORT|IMPORT|SET|IF"
    r"|BLDINDEX|EXAMINE|DIAGNOSE)\b"
)
#: A quoted literal (``C'...'``, ``X'...'``, ``'...'``) in a control statement.
_LITERAL_RE = re.compile(r"(?:\b[CXZ])?'(?:[^']|'')*'")
_NULL_DSNS = frozenset({"NULLFILE"})


def _flat_steps(steps: Iterable[Any]) -> Iterable[Any]:
    for step in steps:
        if hasattr(step, "then_steps"):
            yield from _flat_steps(getattr(step, "then_steps", None) or [])
            yield from _flat_steps(getattr(step, "else_steps", None) or [])
        else:
            yield step


def _named(dds: list[Any]) -> list[tuple[str, Any]]:
    """Each DD with the name it belongs to: a blank-named DD continues the
    concatenation of the one before it."""
    out: list[tuple[str, Any]] = []
    current = ""
    for dd in dds:
        name = (getattr(dd, "name", None) or "").strip().upper()
        if name:
            current = name
        out.append((current, dd))
    return out


def _dataset(dd: Any) -> str | None:
    """The dataset a DD statement names; None for none, ``DUMMY`` or
    ``NULLFILE`` (nothing is read or kept there)."""
    dsn = getattr(dd, "dataset_name", None)
    if not dsn or str(dsn).strip().strip("'").upper() in _NULL_DSNS:
        return None
    parameters = getattr(dd, "parameters", None) or {}
    if isinstance(parameters, dict) and any(
        str(value).upper() == "DUMMY"
        for key, value in parameters.items()
        if str(key).startswith("_pos")
    ):
        return None
    return str(dsn)


def _inline(dds: list[Any], name: str) -> str:
    for dd_name, dd in _named(dds):
        if dd_name == name and isinstance(dd.inline_data, str):
            return dd.inline_data.upper()
    return ""


def _control(dds: list[Any], name: str) -> str:
    """A utility's control statements, quoted literals blanked."""
    return _LITERAL_RE.sub(" ", _inline(dds, name))


def _dsns(dds: list[Any], name: str) -> list[str]:
    """Every dataset of DD *name*, concatenation included."""
    out: list[str] = []
    for dd_name, dd in _named(dds):
        dsn = _dataset(dd) if dd_name == name else None
        if dsn and dsn not in out:
            out.append(dsn)
    return out


def _dsn(dds: list[Any], name: str) -> str | None:
    found = _dsns(dds, name)
    return found[0] if found else None


def _repro_commands(control: str) -> list[str]:
    """The operand text of every IDCAMS ``REPRO`` command, continuation
    (``-`` at the end of a line) joined."""
    joined = re.sub(r"[-+]\s*\n", " ", control)
    commands: list[str] = []
    for line in joined.splitlines():
        marks = list(_IDCAMS_COMMAND_RE.finditer(line))
        for index, mark in enumerate(marks):
            if mark.group(1) != "REPRO":
                continue
            end = marks[index + 1].start() if index + 1 < len(marks) else len(line)
            commands.append(line[mark.end() : end])
    return commands


def _sum_ranges(control: str) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    for match in _SUM_RE.finditer(control):
        parts = [p.strip() for p in match.group(1).split(",") if p.strip()]
        if parts and parts[0] == "NONE":
            continue
        i = 0
        while i + 1 < len(parts):
            if parts[i].isdigit() and parts[i + 1].isdigit():
                ranges.append((int(parts[i]) - 1, int(parts[i + 1])))
                i += 3 if i + 2 < len(parts) and not parts[i + 2].isdigit() else 2
            else:
                i += 1
    return tuple(ranges)


def bindings_from_jobs(
    jobs: Iterable[Any],
    caveats: list[str] | None = None,
) -> tuple[list[DatasetBinding], list[Passthrough]]:
    """DD -> dataset bindings per program, and utility pass-throughs, for
    every step of every (already PROC-expanded) jcl-parser ``Job``.

    ``caveats``, when given, receives one line per step whose flow could not
    be read (pass them on as ``LineageGraph(join_caveats=...)``), so a step
    left out is never mistaken for a step that moves nothing.
    """
    notes: list[str] = caveats if caveats is not None else []
    bindings: list[DatasetBinding] = []
    passthroughs: list[Passthrough] = []
    for job in jobs:
        job_name = (getattr(job, "name", None) or "").upper() or None
        earlier: dict[str, str] = {}
        for step in _flat_steps(getattr(job, "steps", None) or []):
            program = (getattr(step, "program", None) or "").upper()
            step_name = (getattr(step, "name", None) or "").upper() or None
            dds = _resolve_referbacks(
                list(getattr(step, "dd_statements", None) or []), step_name, earlier
            )
            if not program:
                continue
            if program == _ICETOOL:
                passthroughs += _icetool_passthroughs(dds, job_name, step_name, notes)
                continue
            if program in _SORT_PROGRAMS:
                passthroughs += _sort_passthroughs(
                    dds, job_name, step_name, program, notes
                )
                continue
            if program in _COPY_PROGRAMS:
                dst = _dsn(dds, "SYSUT2")
                control = _control(dds, "SYSIN")
                kind = (
                    "reformat"
                    if re.search(r"\b(GENERATE|RECORD)\b", control)
                    or (
                        dst is not None
                        and _unread_control(
                            dds, ("SYSIN",), program, step_name, job_name, notes
                        )
                    )
                    else "copy"
                )
                passthroughs += [
                    Passthrough(src, dst, kind, (), job_name, step_name, program)
                    for src in _dsns(dds, "SYSUT1")
                    if dst
                ]
                continue
            if program == "IDCAMS":
                passthroughs += _repro_passthroughs(dds, job_name, step_name)
                continue
            if program in _TSO_PROGRAMS:
                run = _RUN_PROGRAM_RE.search(_inline(dds, "SYSTSIN"))
                if not run:
                    systsin = _dsn(dds, "SYSTSIN")
                    if systsin:
                        notes.append(
                            f"{_step_label(program, step_name, job_name)}: "
                            f"SYSTSIN is not in-stream ({systsin}); the programs "
                            "it runs are not known, so its DDs are not bound"
                        )
                    continue
                program = run.group(1)
            elif program == _IMS_CONTROLLER:
                program = _ims_program(step) or program
            for dd_name, dd in _named(dds):
                dsn = _dataset(dd)
                if dd_name and dsn:
                    bindings.append(
                        DatasetBinding(
                            program=program,
                            ddname=dd_name,
                            dataset=dsn,
                            job=job_name,
                            step=step_name,
                        )
                    )
    return bindings, passthroughs


def _ims_program(step: Any) -> str | None:
    """The application program of an IMS batch region step: the second
    ``PARM`` positional when the first is ``DLI`` / ``DBB`` / ``BMP``."""
    parameters = getattr(step, "parameters", None) or {}
    parm = parameters.get("PARM") if isinstance(parameters, dict) else None
    if isinstance(parm, (list, tuple)):
        parts = [str(p) for p in parm]
    elif parm is not None:
        parts = str(parm).strip().strip("()'").split(",")
    else:
        return None
    parts = [p.strip().strip("'").upper() for p in parts]
    if len(parts) > 1 and parts[0] in _IMS_BATCH_REGIONS and parts[1]:
        return parts[1]
    return None


def _resolve_referbacks(
    dds: list[Any], step: str | None, earlier: dict[str, str]
) -> list[Any]:
    """Replace ``DSN=*.STEP.DD`` / ``DSN=*.DD`` referbacks with the dataset
    they name, and remember this step's DDs for the steps after it."""
    out: list[Any] = []
    for dd_name, dd in _named(dds):
        dsn = str(getattr(dd, "dataset_name", None) or "")
        if dsn.startswith("*."):
            parts = dsn[2:].upper().split(".")
            key = ".".join(parts[-2:]) if len(parts) > 1 else f"{step}.{parts[0]}"
            resolved = earlier.get(key)
            if resolved is not None:
                dd = SimpleNamespace(
                    name=getattr(dd, "name", None),
                    dataset_name=resolved,
                    inline_data=getattr(dd, "inline_data", None),
                    parameters=getattr(dd, "parameters", None),
                )
        out.append(dd)
        found = _dataset(dd)
        if dd_name and found and f"{step}.{dd_name}" not in earlier:
            earlier[f"{step}.{dd_name}"] = found
    return out


def _repro_passthroughs(
    dds: list[Any], job: str | None, step: str | None
) -> list[Passthrough]:
    out: list[Passthrough] = []
    for command in _repro_commands(_inline(dds, "SYSIN")):
        source, target = _REPRO_IN_RE.search(command), _REPRO_OUT_RE.search(command)
        if source is None or target is None:
            continue
        if source.group(1) in ("INFILE", "IFILE"):
            inputs = _dsns(dds, source.group(2))
        else:
            inputs = [source.group(2)]
        if target.group(1) in ("OUTFILE", "OFILE"):
            outputs = _dsns(dds, target.group(2))[:1]
        else:
            outputs = [target.group(2)]
        out += [
            Passthrough(src, dst, "copy", (), job, step, "IDCAMS")
            for src in inputs
            for dst in outputs
        ]
    return out


def _step_label(program: str, step: str | None, job: str | None) -> str:
    return f"{program} step {step or '?'}" + (f" in job {job}" if job else "")


def _unread_control(
    dds: list[Any],
    names: tuple[str, ...],
    program: str,
    step: str | None,
    job: str | None,
    notes: list[str],
) -> bool:
    """True (and a caveat) when a control DD of ``names`` is a dataset: its
    statements are not read, so the step cannot be taken for a copy."""
    unread = [dsn for name in names for dsn in _dsns(dds, name)]
    if unread:
        notes.append(
            f"{_step_label(program, step, job)}: control statements are read "
            f"from {', '.join(unread)}, which is not in-stream; the step is "
            "treated as a reformat and values are not traced through it"
        )
    return bool(unread)


def _sort_passthroughs(
    dds: list[Any],
    job: str | None,
    step: str | None,
    program: str,
    notes: list[str],
) -> list[Passthrough]:
    control = _control(dds, "SYSIN") + "\n" + _control(dds, "DFSPARM")
    input_dds = {"SORTJNF1", "SORTJNF2"} if "JOINKEYS" in control else set()
    input_dds |= {m.group(2) for m in _JOIN_DD_RE.finditer(control)}
    inputs: list[str] = []
    for dd_name, dd in _named(dds):
        dsn = _dataset(dd)
        if (
            dsn
            and dsn not in inputs
            and (re.fullmatch(r"SORTIN(\d\d)?", dd_name) or dd_name in input_dds)
        ):
            inputs.append(dsn)
    outputs = [d for d in [_dsn(dds, "SORTOUT")] if d]
    names = [
        name
        for match in _FNAMES_RE.finditer(control)
        for name in re.split(r"[,\s]+", match.group(1).strip())
    ] + [
        f"SORTOF{name}"
        for match in _FILES_RE.finditer(control)
        for name in re.split(r"[,\s]+", match.group(1).strip())
        if name
    ]
    for name in names:
        dsn = _dsn(dds, name) if name else None
        if dsn and dsn not in outputs:
            outputs.append(dsn)
    if not inputs or not outputs:
        missing = " and ".join(
            what
            for what, found in (("inputs", inputs), ("outputs", outputs))
            if not found
        )
        notes.append(
            f"{_step_label(program, step, job)}: {missing} not recognised; "
            "the flow through it is not traced"
        )
    kind = "reformat" if _REFORMAT_RE.search(control) else "copy"
    if (
        inputs
        and outputs
        and _unread_control(dds, ("SYSIN", "DFSPARM"), program, step, job, notes)
    ):
        kind = "reformat"
    ranges = _sum_ranges(control) if kind == "copy" else ()
    return [
        Passthrough(src, dst, kind, ranges, job, step, program)
        for src in inputs
        for dst in outputs
    ]


def _icetool_operands(text: str, keyword: str) -> list[str]:
    match = re.search(rf"\b{keyword}\s*\(([^)]*)\)", text)
    return [n for n in re.split(r"[,\s]+", match.group(1)) if n] if match else []


def _icetool_passthroughs(
    dds: list[Any], job: str | None, step: str | None, notes: list[str]
) -> list[Passthrough]:
    """ICETOOL's record-moving operators, each read as a DFSORT step."""
    label = _step_label(_ICETOOL, step, job)
    if not _inline(dds, "TOOLIN"):
        where = _dsn(dds, "TOOLIN")
        notes.append(
            f"{label}: TOOLIN is not in-stream"
            + (f" ({where})" if where else "")
            + "; the flow through it is not traced"
        )
        return []
    # ``-`` at the end of a line continues the operator; ``*`` starts a comment.
    joined = re.sub(r"-[ \t]*\n", " ", _control(dds, "TOOLIN"))
    out: list[Passthrough] = []
    for line in joined.splitlines():
        words = line.split()
        if not words or words[0].startswith("*"):
            continue
        operator = words[0]
        kind = _ICETOOL_OPERATORS.get(operator)
        if kind is None:
            continue  # COUNT, DISPLAY, OCCUR, STATS, ...: no records written
        inputs = [d for n in _icetool_operands(line, "FROM") for d in _dsns(dds, n)]
        outputs: list[str] = []
        for name in _icetool_operands(line, "TO") + _icetool_operands(line, "DISCARD"):
            outputs += [d for d in _dsns(dds, name) if d not in outputs]
        control = ""
        for prefix in _icetool_operands(line, "USING")[:1]:
            control = _control(dds, f"{prefix}CNTL")
            if not control and _dsn(dds, f"{prefix}CNTL"):
                notes.append(
                    f"{label}: {operator} USING({prefix}) reads its control "
                    f"statements from {_dsn(dds, f'{prefix}CNTL')}, which is not "
                    "in-stream; the step is treated as a reformat"
                )
                kind = "reformat"
            for match in _FNAMES_RE.finditer(control):
                for name in re.split(r"[,\s]+", match.group(1).strip()):
                    outputs += [d for d in _dsns(dds, name) if d not in outputs]
        if not inputs or not outputs:
            notes.append(
                f"{label}: {operator} operator's FROM/TO datasets not "
                "recognised; the flow through it is not traced"
            )
            continue
        if _REFORMAT_RE.search(control):
            kind = "reformat"
        ranges = _sum_ranges(control) if kind == "copy" else ()
        out += [
            Passthrough(src, dst, kind, ranges, job, step, _ICETOOL)
            for src in inputs
            for dst in outputs
        ]
    return out


_PROC_SUFFIXES = frozenset({".prc", ".proc", ".jcl", ".cntl", ""})


def _flat_procs(base: Path | None) -> dict[str, str]:
    """PROC members sitting directly in ``base`` (``SORTPROC.prc``, ...).

    jcl-parser's JCLLIB loader only searches the ``base/<library>/`` folders a
    job's ``JCLLIB ORDER=`` names; a source tree usually keeps its PROCs in one
    flat folder and has no JCLLIB statement at all, so those are read here.
    """
    if base is None or not base.is_dir():
        return {}
    return {
        p.stem.upper(): p.read_text(errors="replace")
        for p in sorted(base.iterdir())
        if p.is_file() and p.suffix.lower() in _PROC_SUFFIXES
    }


def load_jobs(
    paths: Iterable[str | Path], proc_path: str | Path | None = None
) -> tuple[list[Any], list[str]]:
    """Parse and PROC-expand JCL files with jcl-parser.

    ``proc_path`` is either a folder of PROC members (``NAME.prc`` /
    ``NAME.jcl`` / no suffix) or a JCLLIB base holding one sub-folder per
    library; both are searched. Returns the jobs and one message per file that
    could not be read or expanded. Raises ``ImportError`` when jcl-parser is
    not installed.
    """
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files += sorted(
                p
                for p in path.rglob("*")
                if p.is_file() and p.suffix.lower() in (".jcl", ".job", "")
            )
        else:
            files.append(path)
    sources: dict[str, str] = {}
    problems: list[str] = []
    for path in files:
        try:
            sources[str(path)] = path.read_text(errors="replace")
        except OSError as exc:
            problems.append(f"{path}: {exc}")
    base = Path(proc_path) if proc_path else None
    jobs, parse_problems = jobs_from_sources(sources, _flat_procs(base), base)
    return jobs, problems + parse_problems


def jobs_from_sources(
    jcl: Mapping[str, str],
    procs: Mapping[str, str] | None = None,
    jcllib_base: Path | None = None,
) -> tuple[list[Any], list[str]]:
    """Parse and PROC-expand JCL held in memory (the backend keeps every
    uploaded member's text in its database, not on disk).

    ``jcl`` maps a name used in messages to a job's text; ``procs`` maps a
    PROC name to its text. Returns the jobs and one message per job that
    could not be parsed or expanded. Raises ``ImportError`` when jcl-parser
    is not installed.
    """
    # Through importlib so mypy does not need jcl-parser installed to check
    # this module; it is an optional dependency, needed only here.
    lib = importlib.import_module("jclparser")
    flat = lib.DictProcedureLoader(dict(procs or {}))
    jobs: list[Any] = []
    problems: list[str] = []
    for name, text in jcl.items():
        try:
            job = lib.parse_jcl(text, proc_base_path=jcllib_base)
        except Exception as exc:  # noqa: BLE001 -- one bad job must not stop the rest
            problems.append(f"{name}: {exc}")
            continue
        try:
            default = lib.create_default_loader(job.procedures, base_path=jcllib_base)
            loader = lib.CompositeProcedureLoader([flat, default])
            job = lib.explode_job(job, proc_loader=loader)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{name}: PROCs not expanded ({exc})")
        jobs.append(job)
    return jobs, problems
