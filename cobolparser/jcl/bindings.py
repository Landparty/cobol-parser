"""
Dataset bindings: the answer to "which dataset is this DD name?".

A COBOL program names its files by DD name -- ``SELECT INV-FILE ASSIGN TO
INVFILE`` -- and nothing in the COBOL source says what ``INVFILE`` is.  The
answer lives in the JCL that runs the program.  This module flattens a parsed
:class:`~cobolparser.jcl.models.JclParseResult` into one
:class:`~cobolparser.jcl.models.DatasetBinding` per DD card, so a caller can
map a DD name straight to a real dataset, its disposition, and its RECFM/LRECL
when the JCL states them.

The flattening is exhaustive and ordered: job order, then step order, then
card order, with each concatenated member of a DD immediately after the card
that owns it, and job-level DD cards (JOBLIB and friends) ahead of the steps
with an empty ``step`` name.  Steps produced by expanding an in-stream
procedure are included like any other, under their ``invocation.procstep``
name, which is how a program run out of a procedure still resolves.

Each binding names the program its step runs (``program``; ``None`` for
job-level DDs and ``EXEC proc`` steps), so ``cobol-parser jcl --bindings``
output is directly usable as ``field-impact --bindings`` input.

A DD backed by SYSOUT, DUMMY or in-stream data yields a binding whose
``dataset`` is ``None``.  Those rows are kept rather than dropped -- knowing
that ``SYSPRINT`` is a SYSOUT DD is an answer, and silently omitting it would
be indistinguishable from the DD not being in the JCL at all.
"""

from __future__ import annotations

from .models import DatasetBinding, JclParseResult


def resolve_dd_bindings(result: JclParseResult) -> list[DatasetBinding]:
    """Every ``ddname -> dataset`` binding in ``result``, in JCL order."""
    bindings: list[DatasetBinding] = []
    for job, step, dd in result.all_dd_statements():
        bindings.append(
            DatasetBinding(
                ddname=dd.name,
                dataset=dd.dataset,
                step="" if step is None else step.name,
                job=job.name,
                disposition=dd.disposition,
                record_format=dd.record_format,
                record_length=dd.record_length,
                program=None if step is None else step.program,
            )
        )
    return bindings


def bindings_for_ddname(result: JclParseResult, ddname: str) -> list[DatasetBinding]:
    """Every binding of one DD name, case-insensitively, in JCL order."""
    target = ddname.strip().upper()
    return [
        binding
        for binding in resolve_dd_bindings(result)
        if binding.ddname.upper() == target
    ]
