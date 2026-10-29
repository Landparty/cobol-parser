"""Fixed- vs. free-format source: deciding which, and normalizing.

* ``detect_fixed_format`` decides whether a COBOL source needs
  ``normalize_fixed_format`` before it is lexed, from the sequence area
  (columns 1-6) and the indicator column (7) of a sample of lines, with
  corroborating anchors for shops that stamp change tags into the sequence
  area.
* ``debug_line_numbers`` lists the debugging lines (``D`` in column 7) a
  fixed-format source holds -- the lines ``normalize_fixed_format`` drops
  as comments unless told otherwise.
* ``normalize_with_recovery`` runs that normalization with the one recovery
  every caller wants: an unterminated literal at EOF is reported, and the
  never-raising ``merge_continued_literals=False`` pass is used instead.

The single home of both decisions for ``CobolParser`` (and so
``parse_cobol``), the lexer's ``tokenize_cobol`` and the CLI.
"""

import re

from .._lines import split_source_lines
from .._source_directive import free_format_flags, source_format_directive
from ._normalize import (
    ALL_COMMENT_INDICATORS,
    DEBUG_INDICATORS,
    INDICATOR_COL,
    TEXT_END_COL,
    TEXT_START_COL,
)

#: A change-tracking tag as shops stamp it into the sequence area (columns
#: 1-6): a single unbroken token of letters/digits and the punctuation that
#: turns up in ticket ids (``SAPR24``, ``28486``, ``GART``, ``JSINT``,
#: ``ABC-12``, ``#00100``). It may open with one of the z/OS national
#: characters ``#``/``@``/``$``, which no free-form line can start with. The
#: "no internal whitespace" property is what keeps ordinary free-form
#: statement text (``MOVE A``, ``IF A =``) out -- see
#: :func:`_sequence_area_is_fixed_like`.
_CHANGE_TAG_RE = re.compile(r"^[A-Za-z0-9#@$][A-Za-z0-9_/#@$.-]*$")

#: Area A headers used to corroborate a *tagged* sequence area. Anchored at
#: the start of the code area (column 8+), which is exactly where free-form
#: source does not put them.
_AREA_A_HEADERS = (
    "IDENTIFICATION DIVISION",
    "ID DIVISION",
    "ENVIRONMENT DIVISION",
    "DATA DIVISION",
    "PROCEDURE DIVISION",
    "PROGRAM-ID",
)

#: A data-description entry in the code area: a level number, a data name
#: (or FILLER), then either the closing period of a group item or a clause
#: keyword. Corroborates a *tagged* sequence area in a copybook, which has no
#: division header to offer. The trailing period/clause requirement is what
#: keeps free-form statements that open with a six-letter verb and a number
#: (``DIVIDE 10 INTO X``) from matching.
_TAGGED_DATA_ENTRY_RE = re.compile(
    r"^(?:0?[1-9]|[1-4][0-9]|66|77|88)\s+[A-Za-z0-9][A-Za-z0-9-]*"
    r"(?:\s*\.|\s+(?:PIC|PICTURE|VALUE|VALUES|OCCURS|REDEFINES|RENAMES|USAGE"
    r"|COMP(?:UTATIONAL)?(?:-[1-5])?|BINARY|PACKED-DECIMAL|DISPLAY|INDEX"
    r"|POINTER|SIGN|JUST|JUSTIFIED|SYNC|SYNCHRONIZED|BLANK|EXTERNAL|GLOBAL)\b)",
    re.IGNORECASE,
)

#: How far into the file to look for the Area A anchor above. Division headers
#: cluster at the top of a program, so a bounded scan keeps this O(1)-ish on a
#: 28,000-line expanded source.
_HEADER_SCAN_LIMIT = 100


def _sequence_area_is_fixed_like(seq_area: str) -> tuple[bool, bool]:
    """Classify a line's columns 1-6 as fixed-format evidence.

    Returns ``(strict, relaxed)``:

    * ``strict`` -- blank or all-digits, the two conventional sequence-area
      fills. This is the historical rule and still decides on its own.
    * ``relaxed`` -- additionally allows a change-tracking *tag*
      (:data:`_CHANGE_TAG_RE`). Only ever consulted together with the Area A
      anchor in :func:`detect_fixed_format`, because a bare tag test alone
      would also match free-form lines whose first six characters happen to
      be a word followed by a blank column 7 (``ACCEPT X``, ``SEARCH T``).
    """
    stripped = seq_area.strip()
    if stripped == "" or seq_area.replace(" ", "").isdigit():
        return True, True
    if _CHANGE_TAG_RE.match(stripped):
        return False, True
    return False, False


def _is_numbered_blank_line(line: str) -> bool:
    """A blank fixed-format record that kept only its sequence number.

    A mainframe export that strips trailing blanks turns every empty line of
    a numbered member into ``000300``: six digits (or fewer, right-trimmed)
    and nothing else. Such a line is fixed-format evidence like any other
    numbered record. Skipping it but still counting it in the sample used to
    drag a copybook with a few blank lines in its banner under the 60% bar,
    so the member was judged free-form, its column-7 comment lines were
    spliced in raw, and a ``#`` in one failed the parse.
    """
    return len(line) <= 6 and line.strip().isdigit()


def _has_area_a_division_header(non_empty_lines: list[str]) -> bool:
    """True when a division/PROGRAM-ID header starts in the code area.

    Fixed-format source puts these in Area A (columns 8-11); free-form source
    puts them at column 1, where ``line[7:]`` slices into the middle of the
    word (``IDENTIFICATION DIVISION.`` -> ``ICATION DIVISION.``) and cannot
    match. That asymmetry is what makes this a safe corroborating signal for
    a sequence area holding something other than blanks or digits.

    A header only counts at a word boundary -- followed by a period, a
    space, or end of text -- so an identifier that merely starts with a
    header string (``PROGRAM-ID-VAL``, ``DATA-DIVISION-FLAG``) in free-form
    source indented past column 8 can never anchor rule 2 and drag a
    genuine free-form program into normalization.

    Only candidate lines consume the ``_HEADER_SCAN_LIMIT`` budget: comment
    lines (column 7 indicator) and too-short lines are skipped without
    counting, because the tag-stamping shops this rule exists for are the
    same shops that open every program with a 100+-line change-history
    banner block -- counting those against the window would push the
    IDENTIFICATION DIVISION header out of reach and re-introduce the very
    misclassification rule 2 fixes.
    """
    scanned = 0
    for line in non_empty_lines:
        if scanned >= _HEADER_SCAN_LIMIT:
            break
        if len(line) < 8 or line[6] in ALL_COMMENT_INDICATORS:
            continue
        scanned += 1
        text = line[TEXT_START_COL - 1 : TEXT_END_COL].lstrip().upper()
        for header in _AREA_A_HEADERS:
            if text.startswith(header) and (
                len(text) == len(header) or text[len(header)] in " ."
            ):
                return True
    return False


def _has_tagged_line_anchor(non_empty_lines: list[str]) -> bool:
    """True when a change-tagged line can only be fixed-format.

    The division-header anchor of :func:`_has_area_a_division_header` never
    fires for a copybook, which has no divisions. So a member whose columns
    1-6 carry change tags (``BNC#01``, ``CHG001``) was judged free-form, its
    column-7 comment lines were spliced in raw, and the first ``#`` in a
    comment banner surfaced as ``Lexer error: Invalid character: #``.

    Two shapes corroborate a tagged sequence area instead, both impossible in
    free-form source:

    * a column-7 comment indicator right after the tag (``CHG001*...``) --
      free-form never puts ``*`` or ``/`` straight after a six-character
      word;
    * a data-description entry in the code area (``CHG001     05  WS-A  PIC
      X.``), see :data:`_TAGGED_DATA_ENTRY_RE`.

    Only lines whose sequence area is a non-blank *tag* count: a blank or
    numeric one already decides through the strict rule.
    """
    scanned = 0
    for line in non_empty_lines:
        if scanned >= _HEADER_SCAN_LIMIT:
            break
        if len(line) < 8:
            continue
        strict, relaxed = _sequence_area_is_fixed_like(line[:6])
        if strict or not relaxed:
            continue
        scanned += 1
        if line[6] in ALL_COMMENT_INDICATORS:
            return True
        if line[6] == " " and _TAGGED_DATA_ENTRY_RE.match(
            line[TEXT_START_COL - 1 : TEXT_END_COL].lstrip()
        ):
            return True
    return False


def detect_fixed_format(source: str) -> bool:
    """Detect if source appears to be in fixed-format COBOL.

    Returns True if source appears to be fixed-format, False if free-form.

    Two rules, in order:

    1. **Strict** -- at least 60% of the sampled lines carry a blank or
       all-digit sequence area with a valid indicator column. Unchanged
       historical behavior; decides on its own.
    2. **Tagged sequence area** -- the same 60% bar, but also counting lines
       whose columns 1-6 hold a change-tracking tag (``SAPR24``, ``28486``),
       *and* requiring an Area A division header to corroborate. Shops that
       stamp ticket ids into the sequence area used to fail rule 1 outright,
       so the whole file was misclassified as free-form, normalization was
       skipped, and the tag text lexed as code -- surfacing as stray
       identifier/number tokens before the first division. The corroborating
       anchor is what keeps genuine free-form source (which never puts a
       division header at column 8) from being dragged in by rule 2. A
       copybook has no division header, so a comment indicator or a
       data-description entry right after a tag corroborates instead (see
       :func:`_has_tagged_line_anchor`).
    """
    lines = split_source_lines(source)
    non_empty_lines = [line for line in lines if line.strip()]

    if len(non_empty_lines) < 3:
        return False

    first = non_empty_lines[0]
    if (
        len(first) - len(first.lstrip()) < 6
        and source_format_directive(first) == "FREE"
    ):
        # A file that OPENS with ``>>SOURCE ... FREE`` in the sequence area
        # (columns 1-6; GnuCOBOL users write it in column 1) is free-form.
        # Read as fixed, such a directive was never seen and was sliced to
        # ``E FORMAT FREE``: the parse failed with "no division near 'E'"
        # (#502). From column 7 on the fixed reader sees it itself and
        # honours a later ``>>SOURCE FIXED`` with sequence numbers, which a
        # wholly free reading would lex as code.
        return False

    if any(">>" in line for line in lines):
        # Only lines written in fixed format count: after an early
        # ``>>SOURCE FORMAT IS FREE`` the free-format lines filled the sample
        # and a sequence-numbered fixed file was misclassified as free-form.
        flags = free_format_flags(lines)
        non_empty_lines = [
            line
            for line, free in zip(lines, flags, strict=True)
            if line.strip() and not free
        ]
        if all(line.lstrip().startswith(">>") for line in non_empty_lines):
            # Nothing but the directive itself precedes the switch: a
            # free-format file that opens with ``>>SOURCE FORMAT IS FREE``.
            return False

    sample_size = min(10, len(non_empty_lines))
    strict_hits = 0
    relaxed_hits = 0

    for line in non_empty_lines[:sample_size]:
        if len(line) < 7:
            if _is_numbered_blank_line(line):
                strict_hits += 1
                relaxed_hits += 1
            continue

        seq_area = line[:6]
        indicator = line[6]  # the len(line) < 7 guard above makes this safe

        valid_indicator = indicator in (" ", "-") or indicator in ALL_COMMENT_INDICATORS
        if not valid_indicator:
            continue

        strict, relaxed = _sequence_area_is_fixed_like(seq_area)
        strict_hits += strict
        relaxed_hits += relaxed

    threshold = sample_size * 0.6
    if strict_hits >= threshold:
        return True
    return relaxed_hits >= threshold and (
        _has_area_a_division_header(non_empty_lines)
        or _has_tagged_line_anchor(non_empty_lines)
    )


def normalize_with_recovery(
    source_lines: list[str],
    warnings: list[str],
    *,
    recover: bool = True,
    debug_lines_as_comments: bool = True,
) -> tuple[str | None, str | None]:
    """Normalize fixed-format *source_lines*; returns ``(text, error)``.

    *error* is the message of the ``ValueError`` an unterminated literal at
    EOF raises, else None. On that error, *recover* (the default) retries
    with ``merge_continued_literals=False``, which never raises, so *text*
    is always set; with ``recover=False`` *text* is None. Only the
    warnings of the pass whose text is returned reach *warnings* -- the
    failed pass stopped partway through, and its warnings would duplicate
    the retry's. *debug_lines_as_comments* is ``normalize_fixed_format``'s
    flag of the same name, passed to both passes.
    """
    # The package attribute, not ``_normalize``'s: ``preprocess/__init__``
    # swaps in the Cython-accelerated implementation when it is built.
    from . import normalize_fixed_format

    pass_warnings: list[str] = []
    try:
        text = normalize_fixed_format(
            source_lines,
            debug_lines_as_comments=debug_lines_as_comments,
            warnings=pass_warnings,
        )
        error = None
    except ValueError as exc:
        error = str(exc)
        if not recover:
            return None, error
        pass_warnings = []
        text = normalize_fixed_format(
            source_lines,
            merge_continued_literals=False,
            debug_lines_as_comments=debug_lines_as_comments,
            warnings=pass_warnings,
        )
    warnings.extend(pass_warnings)
    return text, error


def debug_line_numbers(source_lines: list[str]) -> list[int]:
    """1-based numbers of the fixed-format debugging lines in *source_lines*.

    A debugging line has ``D``/``d`` in the indicator column (7). Lines a
    ``>>SOURCE FORMAT IS FREE`` directive has switched to free format have
    no indicator column, so they are never counted -- an indented
    ``DISPLAY`` there starts with a ``D`` in column 7 and is code.
    """
    flags = free_format_flags(source_lines)
    numbers: list[int] = []
    for number, (line, free) in enumerate(zip(source_lines, flags, strict=True), 1):
        if free:
            continue
        expanded = line.expandtabs(8)
        if (
            len(expanded) >= INDICATOR_COL
            and expanded[INDICATOR_COL - 1] in DEBUG_INDICATORS
        ):
            numbers.append(number)
    return numbers
