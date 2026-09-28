"""A deliberately small YAML reader for project config files.

This package has **no runtime dependencies** (see CLAUDE.md), so PyYAML is
not available to it. Rather than take one on for a file that is at most a
few dozen lines of mappings and lists, this module implements the strict
subset a config file actually needs:

* block mappings (``key: value``) nested by indentation
* block sequences (``- item``), including sequences of mappings
* flow sequences (``[a, b]``) and flow mappings (``{a: 1}``)
* scalars: single/double-quoted strings, integers, floats, booleans, null
* ``#`` comments, blank lines, and one optional leading ``---``

Everything outside that subset is **rejected with a line number**, never
guessed at: anchors and aliases, tags, block scalars (``|``/``>``), merge
keys (``<<``), multiple documents, tabs used for indentation, and duplicate
keys. A config file that this module cannot read is an error naming the
line, not a silent fallback to defaults -- the same fail-closed posture the
rest of the CLI's input validation takes. The alternative, quietly ignoring
a construct, produces a config the user believes is in effect and isn't.

Two deliberate departures from what a full YAML 1.1 parser would do, both
chosen because the surprising behavior is worse than the missing feature:

* ``yes``/``no``/``on``/``off`` stay **strings**, not booleans (the YAML 1.2
  core schema's rule). Only ``true``/``false`` are booleans.
* A duplicate key is an error rather than last-one-wins.
"""

from __future__ import annotations

import re
from typing import Any

from cobolparser._lines import split_source_lines

__all__ = ["YamlError", "parse_yaml"]


class YamlError(Exception):
    """The config file is not readable as the supported YAML subset."""


# Constructs this reader deliberately does not implement. Each maps to the
# message shown when a value starts with it, so the error says what to write
# instead rather than just "unexpected character".
_REJECTED_VALUE_PREFIXES = {
    "&": "YAML anchors (&name) are not supported",
    "*": "YAML aliases (*name) are not supported",
    "!": "YAML tags (!name) are not supported",
    "|": "block scalars (|) are not supported; use a quoted string",
    ">": "folded scalars (>) are not supported; use a quoted string",
    "?": "explicit keys (? key) are not supported",
    "%": "YAML directives (%YAML, %TAG) are not supported",
}

_DOUBLE_QUOTE_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "b": "\b",
    "f": "\f",
    "0": "\0",
    "\\": "\\",
    '"': '"',
    "/": "/",
    "'": "'",
    " ": " ",
    # The rest of YAML 1.2's double-quoted escape set (spec 5.7). Rejecting
    # them refused a valid file with "unsupported escape".
    "\t": "\t",
    "a": "\a",
    "v": "\v",
    "e": "\x1b",
    "N": "\x85",
    "_": "\xa0",
    "L": " ",
    "P": " ",
}

# `\xXX`, `\uXXXX`, `\UXXXXXXXX`: exactly that many hex digits, as YAML says.
_HEX_ESCAPE_WIDTHS = {"x": 2, "u": 4, "U": 8}
_HEX_DIGITS_RE = re.compile(r"[0-9A-Fa-f]+", re.ASCII)


class _Line:
    """One significant source line: its indent, its content, its number."""

    __slots__ = ("indent", "text", "number")

    def __init__(self, indent: int, text: str, number: int) -> None:
        self.indent = indent
        self.text = text
        self.number = number


def parse_yaml(text: str, filename: str = "<config>") -> Any:
    """Parse ``text`` as the supported YAML subset.

    Returns the document's top-level value (normally a ``dict``), or ``None``
    for an empty/comment-only file. Raises `YamlError` naming ``filename``
    and the offending line for anything unsupported or malformed.
    """
    # A byte-order mark (what some Windows editors put at the top of a UTF-8
    # file) is an encoding artefact, not part of the first key.
    parser = _Parser(text.removeprefix("﻿"), filename)
    return parser.parse()


class _Parser:
    def __init__(self, text: str, filename: str) -> None:
        self.filename = filename
        self.lines = self._scan(text)
        self.index = 0

    # -- error reporting ---------------------------------------------------

    def _error(self, message: str, line: _Line | None = None) -> YamlError:
        where = f"{self.filename}:{line.number}" if line else self.filename
        return YamlError(f"{where}: {message}")

    # -- scanning ----------------------------------------------------------

    def _scan(self, text: str) -> list[_Line]:
        """Strip comments and blank lines, and turn what is left into
        (indent, text, line number) triples. Document markers are handled
        here because they are the one construct that is neither a mapping
        entry nor a sequence entry."""
        lines: list[_Line] = []
        seen_document_start = False
        seen_document_end = False
        for number, raw in enumerate(split_source_lines(text), start=1):
            stripped = _strip_comment(raw)
            if not stripped.strip():
                continue

            leading = raw[: len(raw) - len(raw.lstrip())]
            if "\t" in leading:
                raise YamlError(
                    f"{self.filename}:{number}: tab character in indentation; "
                    f"YAML requires spaces"
                )

            indent = len(stripped) - len(stripped.lstrip(" "))
            content = stripped.strip()

            if content.startswith("%"):
                raise YamlError(
                    f"{self.filename}:{number}: "
                    f"YAML directives (%YAML, %TAG) are not supported"
                )
            if content.startswith("-\t"):
                raise YamlError(
                    f"{self.filename}:{number}: tab after '-'; a sequence "
                    f"entry needs a space after the dash"
                )
            if content == "?" or content.startswith("? "):
                raise YamlError(
                    f"{self.filename}:{number}: "
                    f"explicit keys (? key) are not supported"
                )

            if content == "---":
                if seen_document_start or lines:
                    raise YamlError(
                        f"{self.filename}:{number}: multiple YAML documents are "
                        f"not supported in a config file"
                    )
                seen_document_start = True
                continue
            if content == "...":
                # The end-of-document marker. Anything significant after it
                # would be a further document -- rejected, like a second
                # `---`, rather than silently dropped.
                seen_document_end = True
                continue
            if seen_document_end:
                raise YamlError(
                    f"{self.filename}:{number}: multiple YAML documents are "
                    f"not supported in a config file"
                )

            lines.append(_Line(indent, content, number))
        return lines

    # -- block parsing -----------------------------------------------------

    def parse(self) -> Any:
        if not self.lines:
            return None
        first = self.lines[0]
        if first.indent != 0:
            raise self._error("top-level content must not be indented", first)
        value = self._parse_block(0)
        if self.index < len(self.lines):
            raise self._error(
                "unexpected content (inconsistent indentation?)", self.lines[self.index]
            )
        return value

    def _peek(self) -> _Line | None:
        return self.lines[self.index] if self.index < len(self.lines) else None

    def _parse_block(self, indent: int) -> Any:
        line = self._peek()
        assert line is not None  # callers check
        if line.text == "-" or line.text.startswith("- "):
            return self._parse_sequence(indent)
        return self._parse_mapping(indent)

    def _parse_mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while True:
            line = self._peek()
            if line is None or line.indent < indent:
                break
            if line.indent > indent:
                raise self._error("unexpected indentation", line)
            if line.text == "-" or line.text.startswith("- "):
                raise self._error(
                    "sequence entry where a 'key: value' mapping was expected", line
                )

            key, rest = self._split_key(line)
            if key in result:
                raise self._error(f"duplicate key {key!r}", line)
            self.index += 1
            result[key] = self._parse_value_for(rest, line, indent)
        return result

    def _parse_sequence(self, indent: int, indentless: bool = False) -> list[Any]:
        """A block sequence at ``indent``. An ``indentless`` one is a mapping
        value sharing its key's column, so it ends at the parent mapping's
        next key rather than treating that key as an error."""
        result: list[Any] = []
        while True:
            line = self._peek()
            if line is None or line.indent < indent:
                break
            if line.indent > indent:
                raise self._error("unexpected indentation", line)
            if line.text != "-" and not line.text.startswith("- "):
                if indentless:
                    break
                raise self._error(
                    "mapping entry where a '- ' sequence entry was expected", line
                )

            rest = line.text[1:].strip()
            self.index += 1
            if not rest:
                result.append(self._parse_nested_block(line, indent))
                continue

            # `- key: value` opens a mapping whose remaining keys line up
            # with the column the key itself starts at, which is what
            # `indent + dash offset` computes.
            # `- - x` likewise opens a nested sequence at that column. Read
            # as a scalar it became the string "- x" -- a list the user
            # wrote, silently turned into text.
            if rest == "-" or rest.startswith("- ") or _is_mapping_entry(rest):
                inline_indent = indent + (len(line.text) - len(line.text[1:].lstrip()))
                nested = _Line(inline_indent, rest, line.number)
                self.lines.insert(self.index, nested)
                result.append(self._parse_block(inline_indent))
            else:
                result.append(self._scalar(rest, line))
        return result

    def _parse_value_for(self, rest: str, line: _Line, indent: int) -> Any:
        """The value of `key:` -- either written inline after the colon, or
        as an indented block on the following lines."""
        if rest:
            return self._scalar(rest, line)
        # A mapping value may also be a sequence written at the key's own
        # indentation -- the "indentless" form YAML allows and many
        # formatters emit:
        #
        #     copybook_paths:
        #     - ./copy
        #
        # Only a sequence may sit at the key's column; a mapping there is
        # the parent's next key, handled by the caller.
        nxt = self._peek()
        if (
            nxt is not None
            and nxt.indent == indent
            and (nxt.text == "-" or nxt.text.startswith("- "))
        ):
            return self._parse_sequence(indent, indentless=True)
        return self._parse_nested_block(line, indent)

    def _parse_nested_block(self, line: _Line, indent: int) -> Any:
        """A `key:` or bare `-` with nothing after it: the value is the
        indented block that follows, or null if nothing is more indented."""
        nxt = self._peek()
        if nxt is None or nxt.indent <= indent:
            return None
        return self._parse_block(nxt.indent)

    def _split_key(self, line: _Line) -> tuple[str, str]:
        """Split `key: value` at the first colon that actually separates a
        key from a value -- one followed by whitespace or at end of line,
        and outside any quoted span. `url: http://x` keeps its value whole."""
        text = line.text
        if text.startswith("<<"):
            raise self._error("YAML merge keys (<<) are not supported", line)

        quote: str | None = None
        i = 0
        while i < len(text):
            char = text[i]
            if quote:
                i, quote = _step_in_quote(text, i, quote)
                continue
            if char in "\"'" and _opens_quote(text, i):
                quote = char
                i += 1
                continue
            if char == ":" and (i + 1 == len(text) or text[i + 1] in " \t"):
                key_text = text[:i].strip()
                if not key_text:
                    raise self._error("mapping entry with an empty key", line)
                return self._scalar_key(key_text, line), text[i + 1 :].strip()
            i += 1
        raise self._error(
            "expected 'key: value' (a colon followed by a space)",
            line,
        )

    def _scalar_key(self, text: str, line: _Line) -> str:
        value = self._scalar(text, line)
        if not isinstance(value, str):
            # `1: x` / `true: x` -- legal YAML, but a config file key that is
            # not a string is always a mistake, and silently stringifying it
            # would make `"1"` and `1` two different keys downstream.
            raise self._error(f"mapping key must be a string (got {text!r})", line)
        return value

    # -- scalars and flow collections --------------------------------------

    def _scalar(self, text: str, line: _Line) -> Any:
        if text and text[0] in _REJECTED_VALUE_PREFIXES:
            # A quoted string starting with one of these is fine; only a
            # bare one is the unsupported construct.
            raise self._error(_REJECTED_VALUE_PREFIXES[text[0]], line)
        if text.startswith("["):
            value, consumed = self._parse_flow(text, 0, line)
            self._require_flow_end(text, consumed, line)
            return value
        if text.startswith("{"):
            value, consumed = self._parse_flow(text, 0, line)
            self._require_flow_end(text, consumed, line)
            return value
        if text.startswith(('"', "'")):
            value, consumed = self._parse_quoted(text, 0, line)
            self._require_flow_end(text, consumed, line)
            return value
        if _is_sequence_indicator(text):
            # `key: - x` -- a block sequence cannot start on its key's line
            # (YAML: "sequence entries are not allowed here"). Read as a plain
            # scalar it became the string "- x": a list the user wrote,
            # silently turned into one text value (a copybook directory
            # literally named "- copybooks").
            raise self._error(
                f"a '- ' sequence entry cannot follow 'key:' on the same line "
                f"({text!r}); put each entry on its own line below the key, "
                f"or quote the value",
                line,
            )
        if _is_mapping_entry(text):
            # `key: a: b` -- YAML rejects a plain scalar holding `: ` ("mapping
            # values are not allowed here"); taking it as the string "a: b"
            # hides what is usually a lost newline or missing quotes.
            raise self._error(
                f"unexpected ': ' inside plain value {text!r}; quote the value",
                line,
            )
        return _plain_scalar(text)

    def _require_flow_end(self, text: str, consumed: int, line: _Line) -> None:
        if text[consumed:].strip():
            raise self._error(
                f"trailing content after value: {text[consumed:]!r}", line
            )

    def _parse_flow(self, text: str, start: int, line: _Line) -> tuple[Any, int]:
        """Parse a flow collection or scalar beginning at ``text[start]``.
        Returns the value and the index just past it."""
        if text[start] == "[":
            return self._parse_flow_collection(text, start, line, "]", is_map=False)
        if text[start] == "{":
            return self._parse_flow_collection(text, start, line, "}", is_map=True)
        if text[start] in "\"'":
            return self._parse_quoted(text, start, line)
        end = start
        while end < len(text):
            char = text[end]
            if char in ",]}":
                break
            # In flow context a colon ends a plain scalar when what follows
            # it is a separator -- that is what makes `{DEBUG: TRUE}` two
            # tokens rather than one scalar spelled "DEBUG: TRUE".
            if char == ":" and (end + 1 == len(text) or text[end + 1] in " \t,]}"):
                break
            end += 1
        raw = text[start:end].strip()
        if raw and raw[0] in _REJECTED_VALUE_PREFIXES:
            raise self._error(_REJECTED_VALUE_PREFIXES[raw[0]], line)
        if _is_sequence_indicator(raw):
            raise self._error(
                f"a '- ' sequence entry is not allowed inside a flow collection "
                f"({raw!r}); quote the value",
                line,
            )
        return _plain_scalar(raw), end

    def _parse_flow_collection(
        self, text: str, start: int, line: _Line, closer: str, is_map: bool
    ) -> tuple[Any, int]:
        items: list[Any] = []
        pairs: dict[str, Any] = {}
        i = start + 1
        while True:
            while i < len(text) and text[i] in " \t":
                i += 1
            if i >= len(text):
                raise self._error(
                    f"unterminated flow collection (missing {closer})", line
                )
            if text[i] == closer:
                return (pairs if is_map else items), i + 1
            if text[i] == ",":
                raise self._error("empty entry in flow collection", line)

            value, i = self._parse_flow(text, i, line)
            if is_map:
                while i < len(text) and text[i] in " \t":
                    i += 1
                if i >= len(text) or text[i] != ":":
                    raise self._error("expected 'key: value' in flow mapping", line)
                if not isinstance(value, str):
                    raise self._error("flow mapping key must be a string", line)
                if value in pairs:
                    raise self._error(f"duplicate key {value!r}", line)
                i += 1
                while i < len(text) and text[i] in " \t":
                    i += 1
                entry, i = self._parse_flow(text, i, line)
                pairs[value] = entry
            else:
                items.append(value)

            while i < len(text) and text[i] in " \t":
                i += 1
            if i >= len(text):
                raise self._error(
                    f"unterminated flow collection (missing {closer})", line
                )
            if text[i] == ",":
                i += 1
                continue
            if text[i] == closer:
                return (pairs if is_map else items), i + 1
            raise self._error(f"expected ',' or '{closer}' in flow collection", line)

    def _parse_quoted(self, text: str, start: int, line: _Line) -> tuple[str, int]:
        quote = text[start]
        i = start + 1
        out: list[str] = []
        while i < len(text):
            char = text[i]
            if char == quote:
                if quote == "'" and i + 1 < len(text) and text[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                return "".join(out), i + 1
            if char == "\\" and quote == '"':
                i += 1
                if i >= len(text):
                    break
                esc = text[i]
                width = _HEX_ESCAPE_WIDTHS.get(esc)
                if width is not None:
                    if i + width >= len(text):
                        raise self._error(f"truncated \\{esc} escape", line)
                    hex_digits = text[i + 1 : i + 1 + width]
                    # A regex, not bare int(..., 16): that also takes a sign,
                    # underscores and surrounding spaces (`\u+0e9`, `\u1_23`).
                    code = (
                        int(hex_digits, 16)
                        if _HEX_DIGITS_RE.fullmatch(hex_digits)
                        else None
                    )
                    if code is None or code > 0x10FFFF:
                        raise self._error(
                            f"invalid \\{esc} escape: \\{esc}{hex_digits}", line
                        )
                    out.append(chr(code))
                    i += 1 + width
                    continue
                if esc not in _DOUBLE_QUOTE_ESCAPES:
                    raise self._error(f"unsupported escape: \\{esc}", line)
                out.append(_DOUBLE_QUOTE_ESCAPES[esc])
                i += 1
                continue
            out.append(char)
            i += 1
        raise self._error("unterminated quoted string", line)


def _step_in_quote(text: str, i: int, quote: str) -> tuple[int, str | None]:
    """Advance past ``text[i]`` inside a quoted span opened by *quote*.

    Returns the next index and the quote still open (``None`` once the span
    closes). ``''`` inside single quotes and a backslash escape inside double
    quotes are the escaped forms of a character, not the end of the span:
    ``'it''s # x'`` and ``"a\\": b"`` are each one scalar.
    """
    char = text[i]
    if quote == '"' and char == "\\":
        return i + 2, quote
    if char == quote:
        if quote == "'" and i + 1 < len(text) and text[i + 1] == "'":
            return i + 2, quote
        return i + 1, None
    return i + 1, quote


def _is_sequence_indicator(text: str) -> bool:
    """Whether a plain value starts with the block-sequence indicator: a
    ``-`` followed by whitespace or nothing. ``-x`` and ``-1`` are ordinary
    plain scalars; ``-`` and ``- x`` are not scalars at all."""
    return text == "-" or text.startswith(("- ", "-\t"))


def _is_mapping_entry(text: str) -> bool:
    """Whether `text` looks like `key: value` rather than a bare scalar.
    Only used to decide how to read a `- ...` sequence entry."""
    quote: str | None = None
    depth = 0
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            i, quote = _step_in_quote(text, i, quote)
            continue
        if char in "\"'" and _opens_quote(text, i):
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif (
            char == ":" and depth == 0 and (i + 1 == len(text) or text[i + 1] in " \t")
        ):
            return True
        i += 1
    return False


def _opens_quote(text: str, i: int) -> bool:
    """Whether the quote character at ``text[i]`` starts a quoted scalar.

    A quote only opens a quoted span at the *start* of a scalar -- the first
    thing on the line, or right after the ``:``, ``- ``, ``[``, ``{`` or
    ``,`` that introduces a value. Anywhere else it is an ordinary character
    of a plain scalar: the apostrophe in ``owner: Sam's shop  # note`` must
    not hide the comment after it (or, in a key, the colon after it).
    """
    before = text[:i].rstrip(" \t")
    if not before:
        return True
    if before[-1] == "-":
        # `- 'x'` is a sequence entry; `-'x'` is a plain scalar.
        return len(before) < i
    return before[-1] in ":[{,"


def _strip_comment(raw: str) -> str:
    """Drop a trailing `#` comment, leaving `#` inside quotes alone.

    A `#` only starts a comment when it is at the start of the line or
    preceded by whitespace -- so `PIC X#Y` and `--flag=a#b` survive, which
    matters for a file full of COBOL-ish literals.
    """
    quote: str | None = None
    i = 0
    while i < len(raw):
        char = raw[i]
        if quote:
            # A backslash escape inside a double-quoted scalar consumes the
            # NEXT character, so it has to advance the cursor by two. As a
            # `continue` in a `for` loop it advanced by one and left the
            # escaped character to be read on its own -- which made `\"`
            # close the string it was meant to sit inside. An even number of
            # escaped quotes then re-opened it and hid the damage; an odd
            # number left a later `#` looking unquoted, so
            # `msg: "a \" # b"` lost its tail and failed to parse at all.
            i, quote = _step_in_quote(raw, i, quote)
            continue
        if char in "\"'" and _opens_quote(raw, i):
            quote = char
            i += 1
            continue
        if char == "#" and (i == 0 or raw[i - 1] in " \t"):
            return raw[:i]
        i += 1
    return raw


def _plain_scalar(text: str) -> Any:
    """Resolve an unquoted scalar to bool / int / float / None / str.

    `yes`/`no`/`on`/`off` stay strings (YAML 1.2 core schema) -- a COBOL
    shop writing `charset: no` means the string, and YAML 1.1's rule here is
    the single most notorious source of silent config bugs.
    """
    if text in ("", "null", "Null", "NULL", "~"):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    # Python's int()/float() are far looser than YAML's core schema: they
    # take `1_000`, surrounding whitespace, non-ASCII digits (`٣`) and
    # `inf`/`nan`. Only the YAML 1.2 core spellings resolve to numbers;
    # anything else stays the string the user wrote.
    if _INT_RE.fullmatch(text):
        return int(text)
    if _FLOAT_RE.fullmatch(text):
        return float(text)
    return text


_INT_RE = re.compile(r"[-+]?[0-9]+", re.ASCII)
_FLOAT_RE = re.compile(
    r"[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?", re.ASCII
)
