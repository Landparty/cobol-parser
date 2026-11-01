"""Assembler macro statements, as BMS, DBDGEN, PSBGEN and the old CICS tables write them.

Only what a macro *call* needs: the name field (column 1), the operation, and
the operand field split into keyword and positional operands. Column 72 marks
a continuation (the next record resumes at column 16), columns 73-80 are a
sequence field, and a ``*`` (or ``.*``) in column 1 is a comment line.

Members are often cut down to their text (no sequence field, no column-72
marker): an operand field that ends with a comma continues on the next record
when that record holds only operands (its first word has an ``=``, or starts
with ``(`` or a quote), which is how such members still read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .._lines import split_source_lines

#: An operand value: a plain string, or a parenthesised list of values.
OperandValue = str | list[Any]

_CONTINUATION_COLUMN = 71  # 0-based index of column 72
_CONTINUE_FROM = 15  # 0-based index of column 16


@dataclass
class AsmStatement:
    """One macro statement after continuation lines are joined."""

    line: int
    name: str | None
    operation: str
    operand_text: str
    keywords: dict[str, OperandValue] = field(default_factory=dict)
    positional: list[OperandValue] = field(default_factory=list)

    def keyword(self, key: str) -> OperandValue | None:
        """The value of keyword operand *key* (upper case), or None."""
        return self.keywords.get(key)

    def text(self, key: str) -> str | None:
        """Keyword *key* as one string; a list value is joined with commas."""
        value = self.keywords.get(key)
        if value is None:
            return None
        return value if isinstance(value, str) else ",".join(flatten(value))


def flatten(value: OperandValue) -> list[str]:
    """Every string inside *value*, in order."""
    if isinstance(value, str):
        return [value]
    out: list[str] = []
    for item in value:
        out.extend(flatten(item))
    return out


def as_list(value: OperandValue | None) -> list[OperandValue]:
    """*value* as a list: ``A`` -> ``[A]``, ``(A,B)`` -> ``[A, B]``, None -> ``[]``."""
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def as_int(value: OperandValue | None) -> int | None:
    """*value* as an int, or None when it is not a plain number."""
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _is_comment(raw: str) -> bool:
    return raw.startswith("*") or raw.startswith(".*")


def _record_body(raw: str, nxt: str | None) -> tuple[str, bool]:
    """``(columns 1-71, continued)`` of *raw*; the whole record when it overflows.

    Column 72 continues a statement only when the next record is a real
    continuation (columns 1-15 blank). A hand-written record that simply runs
    past column 71, with no sequence field, keeps its text: cutting it would
    read its last character as a continuation mark and swallow the next
    statement.
    """
    if len(raw) <= _CONTINUATION_COLUMN:
        return raw, False
    mark = raw[_CONTINUATION_COLUMN] != " "
    if mark and nxt is not None and nxt.strip() and not nxt[:_CONTINUE_FROM].strip():
        return raw[:_CONTINUATION_COLUMN], True
    tail = raw[_CONTINUATION_COLUMN + 1 :].strip()
    if not mark or (tail and tail.isdigit()):
        return raw[:_CONTINUATION_COLUMN], False
    return raw.rstrip(), False


_OPERAND_LINE = re.compile(r"^\s+(?:[A-Za-z0-9@#$_]+=|\(|')")


class _OperandScanner:
    """Collects the operand field across records, tracking quotes and parentheses."""

    def __init__(self) -> None:
        self.buffer: list[str] = []
        self.in_quote = False
        self.done_for_record = False

    def feed(self, segment: str) -> None:
        """Add one record's operand text; a blank outside quotes ends it."""
        self.done_for_record = False
        for char in segment:
            if char == "'":
                self.in_quote = not self.in_quote
            elif char == " " and not self.in_quote:
                if self.buffer:
                    self.done_for_record = True
                    return
                continue
            self.buffer.append(char)

    @property
    def text(self) -> str:
        return "".join(self.buffer)


def _split_fields(record: str) -> tuple[str | None, str, str]:
    """``(name, operation, rest)`` of a statement's first record (columns 1-71)."""
    name: str | None = None
    rest = record
    if record and record[0] != " ":
        parts = record.split(None, 1)
        name = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
    rest = rest.lstrip()
    parts = rest.split(None, 1)
    operation = parts[0] if parts else ""
    remainder = rest[len(operation) :].lstrip(" ") if parts else ""
    return name, operation, remainder


def read_statements(source: str) -> list[AsmStatement]:
    """Every macro statement of *source*, continuation records joined."""
    records = [raw.expandtabs(8) for raw in split_source_lines(source)]

    def following(position: int) -> str | None:
        return records[position + 1] if position + 1 < len(records) else None

    statements: list[AsmStatement] = []
    index = 0
    while index < len(records):
        raw = records[index]
        line_no = index + 1
        if not raw.strip() or _is_comment(raw):
            index += 1
            continue
        body, continued = _record_body(raw, following(index))
        index += 1
        name, operation, remainder = _split_fields(body)
        if not operation:
            continue
        scanner = _OperandScanner()
        scanner.feed(remainder)
        while index < len(records):
            nxt = records[index]
            if continued:
                nxt_body, continued = _record_body(nxt, following(index))
                segment = nxt_body[_CONTINUE_FROM:]
                scanner.feed(segment if scanner.in_quote else segment.lstrip(" "))
                index += 1
                continue
            if scanner.text.endswith(",") and _OPERAND_LINE.match(nxt):
                nxt_body, continued = _record_body(nxt, following(index))
                scanner.feed(nxt_body.lstrip(" "))
                index += 1
                continue
            break
        operand_text = scanner.text
        keywords, positional = parse_operands(operand_text)
        statements.append(
            AsmStatement(
                line=line_no,
                name=name,
                operation=operation.upper(),
                operand_text=operand_text,
                keywords=keywords,
                positional=positional,
            )
        )
    return statements


def _split_top_level(text: str) -> list[str]:
    """*text* split on commas outside quotes and parentheses."""
    parts: list[str] = []
    depth = 0
    in_quote = False
    current: list[str] = []
    for char in text:
        if char == "'":
            in_quote = not in_quote
        elif not in_quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(depth - 1, 0)
            elif char == "," and depth == 0:
                parts.append("".join(current))
                current = []
                continue
        current.append(char)
    parts.append("".join(current))
    return parts


def _unquote(text: str) -> str:
    """A quoted assembler string without its quotes, ``''`` and ``&&`` undoubled."""
    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'").replace("&&", "&")
    return text


def parse_value(text: str) -> OperandValue:
    """One operand value: ``(A,(B,C))`` -> ``['A', ['B', 'C']]``; quotes are removed."""
    stripped = text.strip()
    if stripped.startswith("(") and stripped.endswith(")") and _balanced(stripped):
        inner = stripped[1:-1]
        if not inner.strip():
            return []
        return [parse_value(part) for part in _split_top_level(inner)]
    return _unquote(stripped)


def _balanced(text: str) -> bool:
    """True when the opening parenthesis of *text* closes at its last character."""
    depth = 0
    in_quote = False
    for position, char in enumerate(text):
        if char == "'":
            in_quote = not in_quote
        elif not in_quote and char == "(":
            depth += 1
        elif not in_quote and char == ")":
            depth -= 1
            if depth == 0 and position != len(text) - 1:
                return False
    return depth == 0


_KEYWORD = re.compile(r"^([A-Za-z0-9@#$_]+)=(.*)$", re.DOTALL)


def parse_operands(text: str) -> tuple[dict[str, OperandValue], list[OperandValue]]:
    """Keyword (``KEY=value``, key upper-cased) and positional operands of *text*."""
    keywords: dict[str, OperandValue] = {}
    positional: list[OperandValue] = []
    if not text.strip():
        return keywords, positional
    for part in _split_top_level(text):
        if not part.strip():
            continue
        match = _KEYWORD.match(part.strip())
        if match and not part.strip().startswith("'"):
            keywords[match.group(1).upper()] = parse_value(match.group(2))
        else:
            positional.append(parse_value(part))
    return keywords, positional
