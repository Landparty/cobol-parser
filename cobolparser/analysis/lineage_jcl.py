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

- DFSORT / ICEMAN / SYNCSORT: ``SORTIN`` (and ``SORTINnn``) to ``SORTOUT``
  and every ``OUTFIL FNAMES=``. ``SORT``/``MERGE FIELDS``, ``INCLUDE``,
  ``OMIT`` keep bytes in place; ``SUM FIELDS=(p,l,f,...)`` rewrites the
  ranges it names (``kind="aggregate"`` there); ``INREC``, ``OUTREC``,
  ``BUILD``, ``OVERLAY``, ``FINDREP`` and ``IFTHEN`` move bytes, so the step
  is a ``reformat`` and the flow stops with a caveat.
- IEBGENER / ICEGENER: ``SYSUT1`` to ``SYSUT2`` (a ``GENERATE``/``RECORD``
  control statement makes it a reformat).
- IDCAMS ``REPRO`` with ``INFILE``/``OUTFILE`` DD names or
  ``INDATASET``/``OUTDATASET`` names, in either order.

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

_SORT_PROGRAMS = frozenset({"SORT", "DFSORT", "ICEMAN", "SYNCSORT", "ICETOOL"})
_COPY_PROGRAMS = frozenset({"IEBGENER", "ICEGENER"})
_TSO_PROGRAMS = frozenset({"IKJEFT01", "IKJEFT1A", "IKJEFT1B"})
_IMS_CONTROLLER = "DFSRRC00"
#: IMS region types whose ``PARM`` names the application program second.
_IMS_BATCH_REGIONS = frozenset({"DLI", "DBB", "BMP"})
_REFORMAT_RE = re.compile(r"\b(INREC|OUTREC|BUILD|OVERLAY|FINDREP|IFTHEN|PARSE)\b")
_SUM_RE = re.compile(r"\bSUM\s+FIELDS\s*=\s*\(([^)]*)\)")
_FNAMES_RE = re.compile(r"\bFNAMES\s*=\s*\(?([A-Z0-9@#$,\s]+)\)?")
_RUN_PROGRAM_RE = re.compile(r"\bRUN\s+PROGRAM\s*\(\s*([A-Z0-9@#$]+)\s*\)")
_REPRO_IN_RE = re.compile(
    r"\b(INFILE|INDATASET|IFILE|IDS)\s*\(\s*'?([A-Z0-9@#$.()+-]+?)'?\s*\)"
)
_REPRO_OUT_RE = re.compile(
    r"\b(OUTFILE|OUTDATASET|OFILE|ODS)\s*\(\s*'?([A-Z0-9@#$.()+-]+?)'?\s*\)"
)
#: IDCAMS commands: where one REPRO's operands end. A command word starts a
#: command only at the start of a statement (after a newline or ``;``, or
#: after ``IF ... THEN`` / ``ELSE`` / ``DO``), outside parentheses and not
#: inside a dataset name: ``PROD.DELETE.MASTER`` holds no DELETE (#338).
_IDCAMS_COMMAND_RE = re.compile(
    r"(?<![\w.@#$])(REPRO|DEFINE|DELETE|PRINT|LISTCAT|ALTER|VERIFY|EXPORT|IMPORT"
    r"|SET|IF|BLDINDEX|EXAMINE|DIAGNOSE)(?![\w.@#$])"
)
_IDCAMS_LEAD_RE = re.compile(r"(?:^|\b(?:THEN|ELSE|DO))\s*$")
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
    for statement in re.split(r"[\n;]", joined):
        marks = [
            mark
            for mark in _IDCAMS_COMMAND_RE.finditer(statement)
            if _paren_depth(statement, mark.start()) == 0
            and _IDCAMS_LEAD_RE.search(statement[: mark.start()])
        ]
        for index, mark in enumerate(marks):
            if mark.group(1) != "REPRO":
                continue
            end = marks[index + 1].start() if index + 1 < len(marks) else None
            commands.append(statement[mark.end() : end])
    return commands


def _paren_depth(text: str, index: int) -> int:
    return text.count("(", 0, index) - text.count(")", 0, index)


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
) -> tuple[list[DatasetBinding], list[Passthrough]]:
    """DD -> dataset bindings per program, and utility pass-throughs, for
    every step of every (already PROC-expanded) jcl-parser ``Job``."""
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
            if program in _SORT_PROGRAMS:
                passthroughs += _sort_passthroughs(dds, job_name, step_name, program)
                continue
            if program in _COPY_PROGRAMS:
                dst = _dsn(dds, "SYSUT2")
                control = _control(dds, "SYSIN")
                kind = (
                    "reformat"
                    if re.search(r"\b(GENERATE|RECORD)\b", control)
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


def _sort_passthroughs(
    dds: list[Any], job: str | None, step: str | None, program: str
) -> list[Passthrough]:
    control = _control(dds, "SYSIN")
    inputs: list[str] = []
    for dd_name, dd in _named(dds):
        dsn = _dataset(dd)
        if dsn and dsn not in inputs and re.fullmatch(r"SORTIN(\d\d)?", dd_name):
            inputs.append(dsn)
    outputs = [d for d in [_dsn(dds, "SORTOUT")] if d]
    for match in _FNAMES_RE.finditer(control):
        for name in re.split(r"[,\s]+", match.group(1).strip()):
            dsn = _dsn(dds, name) if name else None
            if dsn and dsn not in outputs:
                outputs.append(dsn)
    kind = "reformat" if _REFORMAT_RE.search(control) else "copy"
    ranges = _sum_ranges(control) if kind == "copy" else ()
    return [
        Passthrough(src, dst, kind, ranges, job, step, program)
        for src in inputs
        for dst in outputs
    ]


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
