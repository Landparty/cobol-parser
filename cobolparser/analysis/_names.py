"""Shared reference-string normalization for analyzers.

Statement parsers fold ``OF``/``IN`` qualifier chains and ``( subscript )``
groups into a single operand string (``"WS-NUM OF GRP-1"``,
``"WS-TAB OF GRP ( 3 )"``) so no reference tokens are dropped from the AST.
Analyzers that key data items by bare name (a MOVE-target catalog lookup, a
tracked-variable table matched against a bare ``CALL identifier``) must
recover the referenced item's own name from that folded string -- otherwise
a qualified reference silently misses every lookup keyed by the bare name.
"""

from __future__ import annotations

import re

#: A COBOL identifier-shaped token: a letter, then letters/digits/hyphens.
#: The canonical tokenizer for pulling identifier-shaped words out of a raw
#: text blob that has no AST-level operand list of its own to walk (a
#: paragraph's source text for clone-detection renaming, an unstructured
#: EVALUATE selector). Shared so a future fix to what counts as an
#: identifier token does not have to be made in more than one place.
IDENTIFIER_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]*")

#: Same, but also matches a token that *starts* with a digit. Only where a
#: stray non-identifier match is harmless -- the caller looks every match up
#: against a name map, so a digit-led word (part of a numeric literal, say)
#: simply never matches anything real.
RELAXED_IDENTIFIER_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")


def base_data_name(ref: str) -> str:
    """Return the referenced data item's own name from a folded reference.

    ``"WS-NUM OF GRP-1"`` / ``"WS-NUM IN GRP-1"`` / ``"WS-TAB ( 3 )"`` /
    ``"WS-TAB OF GRP ( IDX )"`` all yield the first word. Anything else --
    a bare name, a quoted literal (even one containing spaces), a
    figurative constant like ``ALL 'X'`` -- is returned unchanged: the
    first word is only split off when what follows is a recognized
    qualifier keyword or subscript group, so a literal's content is never
    truncated.
    """
    parts = ref.split()
    if len(parts) >= 2 and (parts[1].upper() in ("OF", "IN") or parts[1] == "("):
        return parts[0]
    return ref


#: Separator of a qualified reference as :func:`qualified_references` spells
#: it: ``"AMT OF IN-REC"`` (an ``IN`` qualifier is normalized to ``OF``).
QUALIFIER_SEPARATOR = " OF "

_PAREN_GROUP_RE = re.compile(r"\(([^()]*)\)")


def qualified_references(text: str, skip_words: frozenset[str]) -> set[str]:
    """Every data-name reference in *text*, keeping its qualifiers.

    ``"CUST-ID OF IN-REC"`` yields ``"CUST-ID OF IN-REC"`` and ``"IN-REC"``:
    the qualified reference, and each qualifier as a reference of its own
    (``"A OF B OF C"`` also yields ``"B OF C"`` and ``"C"``). An unqualified
    token yields itself. Parenthesised groups (subscripts, reference
    modifiers, function arguments) are references in their own right and
    never qualify the name before them. Words in *skip_words* (figurative
    constants, ``OF``/``IN``, ``LENGTH``, ...) are never references, and
    one never takes a qualifier: ``LENGTH OF X`` yields just ``"X"``.

    The first part of each element is the bare name, so
    ``{r.split(QUALIFIER_SEPARATOR, 1)[0] for r in refs}`` is the plain
    token set.
    """
    refs: set[str] = set()
    remaining = text
    while True:
        match = _PAREN_GROUP_RE.search(remaining)
        if match is None:
            break
        refs |= qualified_references(match.group(1), skip_words)
        remaining = f"{remaining[: match.start()]} {remaining[match.end():]}"

    tokens = [t.upper() for t in IDENTIFIER_TOKEN_RE.findall(remaining)]
    for i, token in enumerate(tokens):
        if token in skip_words:
            continue
        chain = [token]
        j = i + 1
        while (
            j + 1 < len(tokens)
            and tokens[j] in ("OF", "IN")
            and tokens[j + 1] not in skip_words
        ):
            chain.append(tokens[j + 1])
            j += 2
        refs.add(QUALIFIER_SEPARATOR.join(chain))
    return refs


def bare_names(refs: set[str]) -> set[str]:
    """The plain names of :func:`qualified_references` output."""
    return {ref.split(QUALIFIER_SEPARATOR, 1)[0] for ref in refs}
