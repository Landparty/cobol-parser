"""Rendering a decoded COBOL alphanumeric literal back as COBOL source text.

Zero internal dependencies (same rationale as ``_errors.py``): the parsers
that need it live in both ``parsers/divisions/`` and ``parsers/statements/``.

The lexer hands every ``STRING_LITERAL`` token over **decoded** -- delimiters
stripped and any doubled delimiter collapsed to one character, so both
``'IT''S'`` and ``"IT'S"`` arrive as ``IT'S``. Anything that re-emits such
a value as COBOL source therefore has to re-apply COBOL's only escape for the
delimiter inside a literal: repeating it.
"""

from __future__ import annotations


def quote_literal(value: str | None) -> str:
    """Render `value` (a decoded literal's content) as a double-quote-
    delimited COBOL literal, doubling every embedded double quote.

    Without the doubling, a copybook's legitimate single-quote-delimited
    ``PIC X VALUE IS '"'`` -- content: one ``"`` character -- round-tripped
    to \"\"\": three quote characters, an unterminated literal. Downstream
    consumers that re-emit the clause (mockymock's generated
    ``UT-RESET-WORKING-STORAGE`` paragraph is the case that surfaced this)
    then emitted an unterminated ``MOVE`` operand, which desynchronizes a
    compiler's tokenizer for the rest of the program -- GnuCOBOL reported it
    as a bogus ``invalid symbol '%'`` two lines further on.
    """
    return '"' + (value or "").replace('"', '""') + '"'
