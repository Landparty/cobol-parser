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
  ``INDATASET``/``OUTDATASET`` names.
- IKJEFT01 / IKJEFT1A / IKJEFT1B: the program named by ``RUN PROGRAM(x)``
  in ``SYSTSIN`` is bound to the step's DDs (the DB2 batch pattern).
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .lineage_graph import DatasetBinding, Passthrough

_SORT_PROGRAMS = frozenset({"SORT", "DFSORT", "ICEMAN", "SYNCSORT", "ICETOOL"})
_COPY_PROGRAMS = frozenset({"IEBGENER", "ICEGENER"})
_TSO_PROGRAMS = frozenset({"IKJEFT01", "IKJEFT1A", "IKJEFT1B"})
_REFORMAT_RE = re.compile(r"\b(INREC|OUTREC|BUILD|OVERLAY|FINDREP|IFTHEN|PARSE)\b")
_SUM_RE = re.compile(r"\bSUM\s+FIELDS\s*=\s*\(([^)]*)\)")
_FNAMES_RE = re.compile(r"\bFNAMES\s*=\s*\(?([A-Z0-9@#$,\s]+)\)?")
_RUN_PROGRAM_RE = re.compile(r"\bRUN\s+PROGRAM\s*\(\s*([A-Z0-9@#$]+)\s*\)")
_REPRO_RE = re.compile(
    r"\bREPRO\b.*?\b(INFILE|INDATASET|IFILE|IDS)\s*\(\s*'?([A-Z0-9@#$.()+-]+?)'?\s*\)"
    r".*?\b(OUTFILE|OUTDATASET|OFILE|ODS)\s*\(\s*'?([A-Z0-9@#$.()+-]+?)'?\s*\)",
    re.S,
)


def _flat_steps(steps: Iterable[Any]) -> Iterable[Any]:
    for step in steps:
        if hasattr(step, "then_steps"):
            yield from _flat_steps(getattr(step, "then_steps", None) or [])
            yield from _flat_steps(getattr(step, "else_steps", None) or [])
        else:
            yield step


def _inline(dds: list[Any], name: str) -> str:
    for dd in dds:
        if (dd.name or "").upper() == name and isinstance(dd.inline_data, str):
            return dd.inline_data.upper()
    return ""


def _dsn(dds: list[Any], name: str) -> str | None:
    for dd in dds:
        if (dd.name or "").upper() == name and dd.dataset_name:
            return str(dd.dataset_name)
    return None


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
        for step in _flat_steps(getattr(job, "steps", None) or []):
            program = (getattr(step, "program", None) or "").upper()
            step_name = (getattr(step, "name", None) or "").upper() or None
            dds = list(getattr(step, "dd_statements", None) or [])
            if not program:
                continue
            if program in _SORT_PROGRAMS:
                passthroughs += _sort_passthroughs(dds, job_name, step_name, program)
                continue
            if program in _COPY_PROGRAMS:
                src, dst = _dsn(dds, "SYSUT1"), _dsn(dds, "SYSUT2")
                if src and dst:
                    control = _inline(dds, "SYSIN")
                    kind = (
                        "reformat"
                        if re.search(r"\b(GENERATE|RECORD)\b", control)
                        else "copy"
                    )
                    passthroughs.append(
                        Passthrough(src, dst, kind, (), job_name, step_name, program)
                    )
                continue
            if program == "IDCAMS":
                control = _inline(dds, "SYSIN")
                for match in _REPRO_RE.finditer(control):
                    src_kw, src, dst_kw, dst = match.groups()
                    if src_kw in ("INFILE", "IFILE"):
                        src = _dsn(dds, src) or ""
                    if dst_kw in ("OUTFILE", "OFILE"):
                        dst = _dsn(dds, dst) or ""
                    if src and dst:
                        passthroughs.append(
                            Passthrough(
                                src, dst, "copy", (), job_name, step_name, program
                            )
                        )
                continue
            if program in _TSO_PROGRAMS:
                run = _RUN_PROGRAM_RE.search(_inline(dds, "SYSTSIN"))
                if not run:
                    continue
                program = run.group(1)
            for dd in dds:
                if dd.name and dd.dataset_name:
                    bindings.append(
                        DatasetBinding(
                            program=program,
                            ddname=str(dd.name).upper(),
                            dataset=str(dd.dataset_name),
                            job=job_name,
                            step=step_name,
                        )
                    )
    return bindings, passthroughs


def _sort_passthroughs(
    dds: list[Any], job: str | None, step: str | None, program: str
) -> list[Passthrough]:
    control = _inline(dds, "SYSIN")
    inputs = [
        str(dd.dataset_name)
        for dd in dds
        if dd.dataset_name and re.fullmatch(r"SORTIN(\d\d)?", (dd.name or "").upper())
    ]
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
    # Through importlib so mypy does not need jcl-parser installed to check
    # this module; it is an optional dependency, needed only here.
    jcl = importlib.import_module("jclparser")
    parse_jcl = jcl.parse_jcl
    explode_job = jcl.explode_job
    create_default_loader = jcl.create_default_loader
    composite = jcl.CompositeProcedureLoader

    jobs: list[Any] = []
    problems: list[str] = []
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
    base = Path(proc_path) if proc_path else None
    flat = jcl.DictProcedureLoader(_flat_procs(base))
    for path in files:
        try:
            job = parse_jcl(path.read_text(errors="replace"), proc_base_path=base)
        except Exception as exc:  # noqa: BLE001 -- one bad job must not stop the rest
            problems.append(f"{path}: {exc}")
            continue
        try:
            default = create_default_loader(job.procedures, base_path=base)
            loader = composite([flat, default])
            job = explode_job(job, proc_loader=loader)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{path}: PROCs not expanded ({exc})")
        jobs.append(job)
    return jobs, problems
