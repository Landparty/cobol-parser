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


def unquote_literal(text: str) -> str:
    """The inverse of :func:`quote_literal`: a quoted COBOL literal's content.

    Strips the delimiters and collapses each doubled delimiter to one, so
    ``"A""B"`` reads back as ``A"B`` and ``'IT''S'`` as ``IT'S``. Text that is
    not a quoted literal comes back stripped but otherwise unchanged.
    Stripping the delimiters alone read ``quote_literal('"')`` -- the one
    character ``"`` -- back as two.
    """
    stripped = text.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "\"'":
        quote = stripped[0]
        return stripped[1:-1].replace(quote * 2, quote)
    return stripped


_TYPED_PREFIXES = ("NX", "UX", "X", "N", "G", "Z", "U")


def typed_literal_content(text: str) -> str | None:
    """The characters a typed literal (``X"4142"``, ``Z"AB"``, ...) stands for.

    Returns ``None`` when *text* is not a typed literal, so callers fall back
    to :func:`unquote_literal`. Hex forms decode to the code points of their
    bytes -- ``X"4142"`` is ``AB``, as an ASCII or Latin-1 host reads those
    bytes -- ``NX`` as UTF-16BE and ``UX`` as UTF-8. ``Z"..."`` gains its
    terminating NUL. ``N``/``G``/``U`` literals are their content. Hex that
    does not decode (odd length, a non-hex digit) comes back as the digits
    themselves; the lexer has already warned about it.
    """
    stripped = text.strip()
    upper = stripped.upper()
    for prefix in _TYPED_PREFIXES:
        if upper.startswith(prefix) and stripped[len(prefix) : len(prefix) + 1] in (
            '"',
            "'",
        ):
            content = unquote_literal(stripped[len(prefix) :])
            if prefix in ("X", "NX", "UX"):
                try:
                    data = bytes.fromhex(content)
                    return data.decode(
                        {"X": "latin-1", "NX": "utf-16-be", "UX": "utf-8"}[prefix]
                    )
                except (ValueError, UnicodeDecodeError):
                    return content
            if prefix == "Z":
                return content + "\x00"
            return content
    return None
