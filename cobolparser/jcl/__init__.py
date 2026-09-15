"""
z/OS Job Control Language (JCL) parsing.

JCL is what binds a COBOL batch program to the world it runs in: which
datasets its DD names point at, which program each job step runs, what
``PARM=`` string it is passed, and in what order the steps go.  None of that
is in the COBOL source, so none of it is knowable from the rest of this
library -- a ``SELECT INV-FILE ASSIGN TO INVFILE`` says only ``INVFILE``.

This package stands alone: it shares no code with the COBOL lexer or parser
(JCL is a different language with its own 80-column card format) and adds no
runtime dependency.

    >>> from cobolparser.jcl import parse_jcl, resolve_dd_bindings
    >>> result = parse_jcl(text)
    >>> result.jobs[0].steps[0].program
    'INVUPDT'
    >>> result.dd_map()["INVFILE"]
    ['PROD.INVENTORY.MASTER']
    >>> [b.disposition for b in resolve_dd_bindings(result) if b.ddname == "INVFILE"]
    ['SHR']

Two properties hold throughout, and are as much of the contract as the shapes
themselves:

* **A quiet result is never a complete one by default.**  A card that cannot
  be parsed goes into ``JclParseResult.errors`` with its line and a reason; a
  symbolic parameter with no value, a procedure not defined in the file, an
  ``INCLUDE`` that would need library access, and a statement kind that is
  recognised but not modelled all go into ``JclParseResult.unresolved``.  No
  card is dropped and no dataset name is guessed.
* **Determinism.**  The same input always produces a byte-identical
  ``to_dict()``.

Modules: :mod:`~cobolparser.jcl.lexer` (card images, continuation, in-stream
data), :mod:`~cobolparser.jcl.parser` (statements, symbols, procedures),
:mod:`~cobolparser.jcl.models` (the dataclasses), and
:mod:`~cobolparser.jcl.bindings` (DD name to dataset).
"""

from __future__ import annotations

from .bindings import bindings_for_ddname, resolve_dd_bindings
from .lexer import (
    CARD_WIDTH,
    CONTINUATION_MAX_COLUMN,
    CONTINUATION_MIN_COLUMN,
    DEFAULT_DELIMITER,
    STRING_CONTINUATION_COLUMN,
    JclCard,
    ScanResult,
    find_top_level_equals,
    scan_cards,
    split_top_level,
)
from .models import (
    DatasetBinding,
    DDStatement,
    JclJob,
    JclParameter,
    JclParseResult,
    JobStep,
    unquote,
)
from .parser import EXEC_KEYWORDS, JclParser, parse_jcl

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
    "EXEC_KEYWORDS",
    # dataset bindings
    "resolve_dd_bindings",
    "bindings_for_ddname",
    # card-level scanning
    "JclCard",
    "ScanResult",
    "scan_cards",
    "split_top_level",
    "find_top_level_equals",
    "CARD_WIDTH",
    "CONTINUATION_MIN_COLUMN",
    "CONTINUATION_MAX_COLUMN",
    "STRING_CONTINUATION_COLUMN",
    "DEFAULT_DELIMITER",
]
