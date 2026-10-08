"""
z/OS Job Control Language (JCL) parsing.

JCL is what binds a COBOL batch program to the world it runs in: which
datasets its DD names point at, which program each job step runs, what
``PARM=`` string it is passed, and in what order the steps go.  None of that
is in the COBOL source, so none of it is knowable from the rest of this
library -- a ``SELECT INV-FILE ASSIGN TO INVFILE`` says only ``INVFILE``.

The JCL itself is read by the ``jcl-parser`` package (``jclparser``),
installed with ``pip install 'cobol-parser[jcl]'``; this package converts its
model into the shapes below and adds the ``ddname -> dataset`` bindings.  The
models and bindings import without ``jcl-parser``; parsing needs it.

    >>> from cobolparser.jcl import parse_jcl, resolve_dd_bindings
    >>> result = parse_jcl(text, proc_paths=["proclib/"])
    >>> result.jobs[0].steps[0].program
    'INVUPDT'
    >>> result.dd_map()["INVFILE"]
    ['PROD.INVENTORY.MASTER']

Two properties hold throughout, and are as much of the contract as the shapes
themselves:

* **A quiet result is never a complete one by default.**  A job that
  ``jclparser`` rejects goes into ``JclParseResult.errors`` with its line and
  the reason (the other jobs in the deck are still read); a procedure or
  ``INCLUDE`` member found neither in the file nor on ``proc_paths``, and
  every warning ``jclparser`` raised (an unresolved symbol, a statement it
  does not model), go into ``JclParseResult.unresolved``.  No dataset name is
  guessed.
* **Determinism.**  The same input always produces a byte-identical
  ``to_dict()``.

Modules: :mod:`~cobolparser.jcl.parser` (the adapter over ``jclparser``),
:mod:`~cobolparser.jcl.models` (the dataclasses), and
:mod:`~cobolparser.jcl.bindings` (DD name to dataset).
"""

from __future__ import annotations

from .bindings import bindings_for_ddname, resolve_dd_bindings
from .models import (
    DatasetBinding,
    DDStatement,
    JclJob,
    JclParameter,
    JclParseResult,
    JobStep,
    unquote,
)
from .parser import JclParser, parse_jcl

__all__ = [
    # models
    "JclParameter",
    "DDStatement",
    "JobStep",
    "JclJob",
    "JclParseResult",
    "DatasetBinding",
    "unquote",
    # parsing
    "JclParser",
    "parse_jcl",
    # dataset bindings
    "resolve_dd_bindings",
    "bindings_for_ddname",
]
