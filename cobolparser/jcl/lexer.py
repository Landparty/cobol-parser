"""
Card-image scanning for z/OS Job Control Language.

JCL is not COBOL and this module shares nothing with the COBOL lexer: a JCL
statement lives on one or more 80-column card images with its own field
layout, its own continuation rule and its own comment convention.  Everything
downstream (:mod:`cobolparser.jcl.parser`) works from the :class:`JclCard`
records produced here, one per *logical* statement -- continuation already
joined, in-stream data already separated out.

Card layout
-----------

============  ==========================================================
Columns       Meaning
============  ==========================================================
1-2           ``//`` identifier field (``//*`` comment, ``/*`` delimiter)
3             first column of the name field; blank means "no name"
3-72          name, operation and parameter fields, blank-separated
73-80         identification/sequence field, ignored
============  ==========================================================

Columns 73-80 are discarded before anything else looks at the card, so a
sequence-numbered deck parses the same as an unnumbered one.

Continuation -- the rule that is usually got wrong
--------------------------------------------------

A statement continues onto the next card in exactly two situations, and the
*current* card decides which:

1. Its parameter field ends with a comma.  The next card must have ``//`` in
   columns 1-2, a blank in column 3, and its continued text must begin
   somewhere in columns 4-16.
2. An apostrophe-quoted string is still open when the card ends.  The next
   card must have ``//`` in columns 1-2, blanks through column 15, and the
   string resumes at column 16 -- verbatim, blanks included, because those
   blanks are inside the quoted string.

Anything else ends the statement.  A card that promises continuation but is
not followed by a valid continuation card is reported as an error and the
statement is closed where it stands, so the following card is still parsed
rather than swallowed.

The parameter field ends at the first blank that is outside both quotes and
parentheses; the remainder of the card is a comment.  Blanks *inside*
parentheses are kept.  ``IF``/``ELSE``/``ENDIF`` follow their own rule
because their operand is a relational expression rather than a parameter
list: ``IF``'s expression runs, blanks included, up to ``THEN`` -- continued
onto following cards (text in columns 4-16) until ``THEN`` is found -- and
whatever follows ``THEN`` is a comment; ``ELSE`` and ``ENDIF`` take no
operand, so the rest of their card is a comment.

In-stream data
--------------

``DD *`` and ``DD DATA`` are followed by data, not by JCL, and the scanner
switches modes so that data is never parsed as JCL.  ``DD *`` data ends at a
delimiter card or at the first card starting with ``//``; ``DD DATA`` data
ends only at the delimiter, which is ``/*`` unless the DD card coded
``DLM=xx``.  The data lines are attached to the DD card that introduced them
and are kept exactly as written, full width, not truncated at column 72.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .._lines import split_source_lines

#: Columns 73-80 are the identification field and are discarded.
CARD_WIDTH = 72

#: A continued parameter field must resume within these columns (1-based).
CONTINUATION_MIN_COLUMN = 4
CONTINUATION_MAX_COLUMN = 16

#: A continued quoted string must resume in exactly this column (1-based).
STRING_CONTINUATION_COLUMN = 16
#: A quoted string that is continued is coded through this column.
STRING_LAST_COLUMN = 71

#: Default in-stream data delimiter; overridable per DD card with ``DLM=``.
DEFAULT_DELIMITER = "/*"

#: Operations whose operand is a relational expression, not a parameter list.
_EXPRESSION_OPERATIONS = frozenset({"IF", "ELSE", "ENDIF"})

#: Operation words: a card opening with one of these starts a new statement,
#: so it never continues an ``IF`` relational expression.
_OPERATION_WORDS = frozenset(
    {
        "JOB",
        "EXEC",
        "DD",
        "PROC",
        "PEND",
        "SET",
        "IF",
        "ELSE",
        "ENDIF",
        "INCLUDE",
        "JCLLIB",
        "OUTPUT",
        "CNTL",
        "ENDCNTL",
        "COMMAND",
        "XMIT",
        "NOTIFY",
    }
)

_THEN_RE = re.compile(r"\bTHEN\b", re.IGNORECASE)

#: ``JclCard.kind`` values.
KIND_STATEMENT = "statement"
KIND_COMMENT = "comment"
KIND_NULL = "null"
KIND_JES = "jes"


@dataclass
class JclCard:
    """One logical JCL card image, continuation already joined.

    ``kind`` is ``"statement"`` for a real JCL statement, ``"comment"`` for a
    ``//*`` card, ``"null"`` for the bare ``//`` that ends a job, and ``"jes"``
    for a ``/*``-prefixed JES control card such as ``/*JOBPARM``.

    ``parameters`` is the raw parameter field with continuation joined and
    comments removed; splitting it into parameters is the parser's job.
    ``instream_lines`` is non-``None`` only on a ``DD *`` / ``DD DATA`` card.
    """

    kind: str
    name: str
    operation: str
    parameters: str
    comment: str = ""
    line: int = 0
    end_line: int = 0
    raw: list[str] = field(default_factory=list)
    instream_lines: list[str] | None = None
    instream_terminated: bool = True
    delimiter: str = DEFAULT_DELIMITER

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "operation": self.operation,
            "parameters": self.parameters,
            "comment": self.comment,
            "line": self.line,
            "end_line": self.end_line,
            "instream_lines": (
                None if self.instream_lines is None else list(self.instream_lines)
            ),
        }


@dataclass
class ScanResult:
    """The cards read from one JCL member, plus the cards that would not read."""

    cards: list[JclCard]
    errors: list[dict[str, Any]] = field(default_factory=list)


def split_top_level(text: str) -> list[str]:
    """Split a JCL parameter field on its top-level commas.

    Commas inside apostrophes or parentheses do not split, so
    ``DISP=(NEW,CATLG),PARM='A,B'`` yields two parts.  An empty part is
    preserved (``DISP=(NEW,,DELETE)`` has a genuinely omitted middle
    sub-parameter), and empty input yields an empty list rather than one empty
    part.
    """
    if not text:
        return []
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_quote = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_quote:
            if char == "'":
                if text[index + 1 : index + 2] == "'":
                    current.append("''")
                    index += 2
                    continue
                in_quote = False
            current.append(char)
        elif char == "'":
            in_quote = True
            current.append(char)
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    parts.append("".join(current))
    return parts


def find_top_level_equals(text: str) -> int:
    """Index of the first ``=`` outside quotes and parentheses, or ``-1``."""
    depth = 0
    in_quote = False
    for index, char in enumerate(text):
        if in_quote:
            if char == "'":
                in_quote = False
            continue
        if char == "'":
            in_quote = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "=" and depth == 0:
            return index
    return -1


def _token_end(text: str, start: int) -> int:
    index = start
    while index < len(text) and text[index] != " ":
        index += 1
    return index


def _skip_blanks(text: str, start: int) -> int:
    index = start
    while index < len(text) and text[index] == " ":
        index += 1
    return index


def _scan_parameter_segment(
    text: str, start: int, *, in_quote: bool, stop_on_blank: bool
) -> tuple[str, str, bool, int]:
    """Read one card's worth of parameter text.

    Returns ``(segment, comment, in_quote_at_end, paren_depth_at_end)``.  The
    segment stops at the first blank outside quotes and parentheses when
    ``stop_on_blank`` is set; everything after that blank is the comment.
    """
    out: list[str] = []
    comment = ""
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if in_quote:
            if char == "'":
                if text[index + 1 : index + 2] == "'":
                    out.append("''")
                    index += 2
                    continue
                in_quote = False
            out.append(char)
            index += 1
            continue
        if char == "'":
            in_quote = True
            out.append(char)
        elif char == "(":
            depth += 1
            out.append(char)
        elif char == ")":
            depth = max(0, depth - 1)
            out.append(char)
        elif char == " " and depth == 0 and stop_on_blank:
            comment = text[index:].strip()
            break
        else:
            out.append(char)
        index += 1
    return "".join(out), comment, in_quote, depth


def _card_text(line: str) -> str:
    """Columns 1-72 of a card image, trailing blanks removed."""
    return line.rstrip()[:CARD_WIDTH]


def _open_quote_padding(card_text: str, in_quote: bool) -> str:
    """The blanks a quoted string continued past this card still holds.

    A continued string runs through column 71; `_card_text` has already
    stripped trailing blanks, but blanks inside the open quote are part of
    the string's value, not padding.
    """
    if not in_quote:
        return ""
    return " " * max(0, STRING_LAST_COLUMN - len(card_text))


def _is_continuation_card(text: str) -> bool:
    return text.startswith("//") and text[2:3] == " " and bool(text[2:].strip())


class _Scanner:
    """Single-use scanner over the lines of one JCL member."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.index = 0
        self.cards: list[JclCard] = []
        self.errors: list[dict[str, Any]] = []

    # -- helpers ---------------------------------------------------------
    def _error(self, line: int, message: str) -> None:
        self.errors.append({"line": line, "message": message})

    # -- driver ----------------------------------------------------------
    def scan(self) -> ScanResult:
        while self.index < len(self.lines):
            raw = self.lines[self.index]
            lineno = self.index + 1
            text = _card_text(raw)
            if not text.strip():
                self.index += 1
                continue
            if not text.startswith("//"):
                self._handle_non_jcl_card(text, raw, lineno)
                continue
            if text[2:3] == "*":
                self.cards.append(
                    JclCard(
                        kind=KIND_COMMENT,
                        name="",
                        operation="",
                        parameters="",
                        comment=text[3:].strip(),
                        line=lineno,
                        end_line=lineno,
                        raw=[raw],
                    )
                )
                self.index += 1
                continue
            if text.strip() == "//":
                self.cards.append(
                    JclCard(
                        kind=KIND_NULL,
                        name="",
                        operation="",
                        parameters="",
                        line=lineno,
                        end_line=lineno,
                        raw=[raw],
                    )
                )
                self.index += 1
                continue
            self._read_statement()
        return ScanResult(cards=self.cards, errors=self.errors)

    def _handle_non_jcl_card(self, text: str, raw: str, lineno: int) -> None:
        if text.startswith("/*"):
            rest = text[2:].strip()
            if rest:
                self.cards.append(
                    JclCard(
                        kind=KIND_JES,
                        name="",
                        operation=rest.split()[0].upper(),
                        parameters=rest,
                        line=lineno,
                        end_line=lineno,
                        raw=[raw],
                    )
                )
            # A bare `/*` outside in-stream data delimits nothing; drop it.
        else:
            self._error(
                lineno,
                "card does not begin with // or /*: " + repr(text.strip()[:40]),
            )
        self.index += 1

    # -- one logical statement -------------------------------------------
    def _read_statement(self) -> None:
        start = self.index
        lineno = start + 1
        raw_first = self.lines[start]
        text = _card_text(raw_first)
        body = text[2:]

        name = ""
        position = 0
        if body[:1] not in ("", " "):
            position = _token_end(body, 0)
            name = body[:position]

        position = _skip_blanks(body, position)
        if position >= len(body):
            self._error(lineno, f"statement {name!r} has no operation field")
            self.index = start + 1
            return
        operation_end = _token_end(body, position)
        operation = body[position:operation_end].upper()
        position = _skip_blanks(body, operation_end)

        if operation in _EXPRESSION_OPERATIONS:
            self._read_expression_statement(name, operation, body[position:])
            return
        stop_on_blank = True
        segment, comment, in_quote, _depth = _scan_parameter_segment(
            body, position, in_quote=False, stop_on_blank=stop_on_blank
        )
        segment += _open_quote_padding(text, in_quote)
        parts = [segment]
        comments = [comment] if comment else []
        raw_lines = [raw_first]
        cursor = start

        while True:
            joined = "".join(parts)
            if in_quote:
                continuation = "string"
            elif joined.endswith(","):
                continuation = "parameter"
            else:
                break

            if cursor + 1 >= len(self.lines):
                self._error(
                    lineno,
                    "statement is continued but the file ends after line "
                    f"{cursor + 1}",
                )
                break
            next_raw = self.lines[cursor + 1]
            next_text = _card_text(next_raw)
            if not _is_continuation_card(next_text) or next_text[2:3] == "*":
                self._error(
                    cursor + 2,
                    "continuation card expected (// in columns 1-2, blank in "
                    "column 3) for the statement starting on line "
                    f"{lineno}",
                )
                break

            cursor += 1
            raw_lines.append(next_raw)
            if continuation == "string":
                before = next_text[2 : STRING_CONTINUATION_COLUMN - 1]
                if before.strip():
                    self._error(
                        cursor + 1,
                        "a continued quoted string must resume in column "
                        f"{STRING_CONTINUATION_COLUMN}; found text in column "
                        f"{2 + len(before) - len(before.lstrip()) + 1}",
                    )
                    break
                segment, comment, in_quote, _depth = _scan_parameter_segment(
                    next_text,
                    STRING_CONTINUATION_COLUMN - 1,
                    in_quote=True,
                    stop_on_blank=stop_on_blank,
                )
            else:
                begin = _skip_blanks(next_text, 2)
                column = begin + 1
                if column < CONTINUATION_MIN_COLUMN or column > CONTINUATION_MAX_COLUMN:
                    self._error(
                        cursor + 1,
                        "continued text must begin in columns "
                        f"{CONTINUATION_MIN_COLUMN}-{CONTINUATION_MAX_COLUMN}; "
                        f"found column {column}",
                    )
                segment, comment, in_quote, _depth = _scan_parameter_segment(
                    next_text, begin, in_quote=False, stop_on_blank=stop_on_blank
                )
            segment += _open_quote_padding(next_text, in_quote)
            parts.append(segment)
            if comment:
                comments.append(comment)

        card = JclCard(
            kind=KIND_STATEMENT,
            name=name,
            operation=operation,
            parameters="".join(parts).strip(),
            comment=" ".join(comments),
            line=lineno,
            end_line=cursor + 1,
            raw=raw_lines,
        )
        self.cards.append(card)
        self.index = cursor + 1
        if operation == "DD":
            self._maybe_read_instream(card)

    # -- IF / ELSE / ENDIF -------------------------------------------------
    def _read_expression_statement(self, name: str, operation: str, rest: str) -> None:
        """Read an ``IF``/``ELSE``/``ENDIF`` statement.

        ``ELSE`` and ``ENDIF`` take no operand, so everything after the
        operation is a comment.  ``IF``'s relational expression runs up to
        ``THEN`` -- blanks and all, and continued onto following cards
        (``//``, blank column 3, text in columns 4-16) until ``THEN`` is
        found; whatever follows ``THEN`` is a comment.
        """
        start = self.index
        lineno = start + 1
        raw_lines = [self.lines[start]]
        cursor = start
        if operation != "IF":
            parameters, comment = "", rest.strip()
        else:
            pieces = [rest.strip()]
            while _THEN_RE.search(" ".join(pieces)) is None:
                if cursor + 1 >= len(self.lines):
                    break
                next_raw = self.lines[cursor + 1]
                next_text = _card_text(next_raw)
                if not _is_continuation_card(next_text) or next_text[2:3] == "*":
                    break
                begin = _skip_blanks(next_text, 2)
                word = next_text[begin : _token_end(next_text, begin)].upper()
                if word in _OPERATION_WORDS:
                    break
                cursor += 1
                raw_lines.append(next_raw)
                column = begin + 1
                if column < CONTINUATION_MIN_COLUMN or column > CONTINUATION_MAX_COLUMN:
                    self._error(
                        cursor + 1,
                        "continued text must begin in columns "
                        f"{CONTINUATION_MIN_COLUMN}-{CONTINUATION_MAX_COLUMN}; "
                        f"found column {column}",
                    )
                pieces.append(next_text[begin:].strip())
            joined = " ".join(piece for piece in pieces if piece)
            match = _THEN_RE.search(joined)
            if match is None:
                parameters, comment = joined, ""
            else:
                parameters = joined[: match.end()]
                comment = joined[match.end() :].strip()
        self.cards.append(
            JclCard(
                kind=KIND_STATEMENT,
                name=name,
                operation=operation,
                parameters=parameters,
                comment=comment,
                line=lineno,
                end_line=cursor + 1,
                raw=raw_lines,
            )
        )
        self.index = cursor + 1

    # -- in-stream data ---------------------------------------------------
    def _maybe_read_instream(self, card: JclCard) -> None:
        parts = split_top_level(card.parameters)
        if not parts:
            return
        first = parts[0].strip().upper()
        if first not in ("*", "DATA"):
            return
        delimiter = DEFAULT_DELIMITER
        dlm_coded = False
        for part in parts[1:]:
            stripped = part.strip()
            if stripped.upper().startswith("DLM="):
                dlm_coded = True
                delimiter = stripped[4:].strip()
                if delimiter.startswith("'") and delimiter.endswith("'"):
                    delimiter = delimiter[1:-1]
        # Once DLM names another delimiter, the data may itself hold "//"
        # and "/*" cards: only the coded delimiter ends it.
        stop_on_jcl = first == "*" and not dlm_coded
        data: list[str] = []
        terminated = False
        while self.index < len(self.lines):
            line = self.lines[self.index]
            if delimiter and line.startswith(delimiter):
                self.index += 1
                terminated = True
                break
            if stop_on_jcl and line.startswith("//"):
                terminated = True
                break
            data.append(line)
            self.index += 1
        if not terminated:
            self._error(
                card.line,
                f"in-stream data for DD {card.name or '(unnamed)'} is not "
                f"terminated by {delimiter!r} before the end of the file",
            )
        card.instream_lines = data
        card.instream_terminated = terminated
        card.delimiter = delimiter


def scan_cards(text: str) -> ScanResult:
    """Scan JCL source text into logical cards.

    Continuation is joined, ``//*`` comment cards are kept as comment cards,
    and ``DD *`` / ``DD DATA`` content is attached to its DD card instead of
    being parsed as JCL.
    """
    return _Scanner(split_source_lines(text)).scan()
