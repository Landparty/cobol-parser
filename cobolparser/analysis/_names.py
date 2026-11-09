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

#: A COBOL identifier-shaped token: letters/digits/hyphens holding at least
#: one letter. IBM lets a user word start with a digit (``1ST-NAME``,
#: ``2ND-REC``); a letter-led-only pattern bit the leading digit off, so
#: ``MOVE 1ST-NAME TO 2ND-NAME`` referenced ``ST-NAME`` / ``ND-NAME`` and
#: both declared items read as unused (2026-10-08). A token must not start
#: inside another word or right after a decimal point, so the ``5E`` of a
#: floating-point literal ``1.5E+3`` is never a word. The canonical
#: tokenizer for pulling identifier-shaped words out of a raw text blob that
#: has no AST-level operand list of its own to walk (a paragraph's source
#: text for clone-detection renaming, an unstructured EVALUATE selector).
#: Shared so a future fix to what counts as an identifier token does not
#: have to be made in more than one place.
#:
#: A token is a *whole* word: it may not start right after a hyphen either,
#: and digits may be followed by a hyphen. The old ``\d*[A-Za-z]...`` could
#: not match ``1000-INIT`` from its first character, so it matched the tail
#: ``INIT`` instead -- and ``PERFORM 1000-INIT`` referenced data item
#: ``INIT`` (#487). Such a word is now one token that names no data item.
IDENTIFIER_TOKEN_RE = re.compile(
    r"(?<![\w.-])(?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9][A-Za-z0-9-]*"
)

#: Same, but also matches a token that *starts* with a digit. Only where a
#: stray non-identifier match is harmless -- the caller looks every match up
#: against a name map, so a digit-led word (part of a numeric literal, say)
#: simply never matches anything real.
RELAXED_IDENTIFIER_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")


# Name normalization. Statement parsers fold a reference into one operand
# string (``"WS-NUM OF GRP-1"``, ``"WS-TAB OF GRP ( 3 )"``, a MOVE source as
# ``"T-E(2)"``). Each function below is one distinct reduction of such a
# string; analyzers use these rather than splitting the string themselves.

#: An identifier with its subscript / reference-modification group glued on
#: or spaced off: ``T-E(2)``, ``WS-A (1:3)``, ``T-E(IX)(1:2)``.
_SUBSCRIPTED_REFERENCE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9-]*)\s*\(")


def base_data_name(ref: str) -> str:
    """Return the referenced data item's own name from a folded reference,
    case kept.

    ``"WS-NUM OF GRP-1"`` / ``"WS-NUM IN GRP-1"`` / ``"WS-TAB ( 3 )"`` /
    ``"WS-TAB(3)"`` / ``"WS-TAB OF GRP ( IDX )"`` all yield the first word.
    Anything else -- a bare name, a quoted literal (even one containing
    spaces or parentheses), a figurative constant like ``ALL 'X'`` -- is
    returned unchanged: the first word is only split off when what follows
    is a recognized qualifier keyword or subscript group, so a literal's
    content is never truncated. (The glued ``WS-TAB(3)`` form, which the
    MOVE parser builds for a source, used to come back unchanged and miss
    every lookup keyed by the bare name.)
    """
    match = _SUBSCRIPTED_REFERENCE_RE.match(ref.strip())
    if match:
        return match.group(1)
    parts = ref.split()
    if len(parts) >= 2 and parts[1].upper() in ("OF", "IN"):
        return parts[0]
    return ref


def strip_subscripts(ref: str) -> str:
    """*ref* without its subscript / reference-modification suffix -- from
    the first ``(`` on -- with any ``OF``/``IN`` qualification kept and the
    case unchanged: ``"WS-T ( 1 )"`` -> ``"WS-T"``, ``"WS-B(1:1)"`` ->
    ``"WS-B"``, ``"A OF G (2)"`` -> ``"A OF G"``."""
    text = (ref or "").strip()
    cut = text.find("(")
    return text[:cut].strip() if cut >= 0 else text


def strip_qualification(ref: str) -> str:
    """*ref* without its ``OF``/``IN`` qualifier chain (``IN`` is a full
    synonym of ``OF``), case unchanged: ``"AMT IN OUT-GRP OF OUT-REC"`` ->
    ``"AMT"``."""
    return _QUALIFIER_SPLIT_RE.split((ref or "").strip(), maxsplit=1)[0].strip()


def bare_item_name(ref: str) -> str:
    """The upper-cased name of the item *ref* addresses, with subscripts,
    reference modification and qualification all stripped:
    ``"ws-stmt(1:80)"`` and ``"WS-STMT OF WS-REC"`` both give ``"WS-STMT"``.
    Unlike :func:`base_data_name` it does not protect literals; use it on
    something already known to be a data reference."""
    return strip_qualification(strip_subscripts(ref)).upper()


#: ``DFHRESP(cond)`` / ``DFHVALUE(cvda)``: the CICS translator replaces each
#: with a fullword binary constant. The argument is a CICS condition or CVDA
#: name (``NORMAL``, ``NOTFND``, ``ACQUIRED``), never a data name.
_TRANSLATOR_FUNCTION_RE = re.compile(
    r"(?<![\w-])(DFHRESP|DFHVALUE)\s*\([^()]*\)", re.IGNORECASE
)


def strip_translator_arguments(text: str) -> str:
    """*text* with the argument of every ``DFHRESP(...)`` / ``DFHVALUE(...)``
    removed, the function word kept: ``"DFHRESP ( NOTFND )"`` becomes
    ``"DFHRESP"``.

    The argument went through the subscript splitter as a data-item
    reference, so xref listed CICS conditions as undefined and a data item
    sharing a condition's name (a flag called ``NOTFND``) was credited with
    a use (#594). Every name extractor applies this before splitting.
    """
    if "(" not in text:
        return text
    return _TRANSLATOR_FUNCTION_RE.sub(r"\1", text)


def is_translator_function(text: str) -> bool:
    """Whether *text* is one ``DFHRESP(...)`` / ``DFHVALUE(...)`` call: a
    fullword binary numeric constant once translated."""
    return _TRANSLATOR_FUNCTION_RE.fullmatch(text.strip()) is not None


#: Separator of a qualified reference as :func:`qualified_references` spells
#: it: ``"AMT OF IN-REC"`` (an ``IN`` qualifier is normalized to ``OF``).
QUALIFIER_SEPARATOR = " OF "

_PAREN_GROUP_RE = re.compile(r"\(([^()]*)\)")

_QUALIFIER_SPLIT_RE = re.compile(r"\s+(?:OF|IN)\s+", re.IGNORECASE)


def split_qualified_name(text: str) -> list[str]:
    """``"AMT IN OUT-GRP OF OUT-REC"`` -> ``["AMT", "OUT-GRP", "OUT-REC"]``:
    the data name then its qualifiers, innermost first, upper-cased. ``IN``
    is a full synonym of ``OF`` (#541)."""
    return [p.upper() for p in _QUALIFIER_SPLIT_RE.split(text.strip()) if p.strip()]


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


#: What a dynamic CALL candidate is stripped of before it is read as a
#: program name: blanks, the LOW-VALUES / HIGH-VALUES bytes, and quotes.
_CALLEE_STRIP = " \x00\xff'\""


def callee_names(possible_values: list[str]) -> list[str]:
    """The program names among a dynamic CALL's ``possible_values``.

    ``DynamicCallAnalyzer`` records every value MOVEd to the CALL's
    identifier, figuratives included: SPACES / LOW-VALUES / HIGH-VALUES
    arrive as ``" "`` / ``"\\x00"`` / ``"\\xff"`` and ZERO as ``"0"``. Those
    are the "no program" sentinel a dispatcher tests before its CALL, never
    a callee, and an all-digit value is not a program name either. The
    one filter every consumer of the candidates shares, so lineage, the
    codebase call graph, recursion-check and gen-fixtures agree on what a
    dynamic CALL can reach. Uppercased, de-duplicated, in first-seen order.
    """
    names: list[str] = []
    for value in possible_values:
        name = value.strip(_CALLEE_STRIP).upper()
        if name and not name.isdigit() and name not in names:
            names.append(name)
    return names
