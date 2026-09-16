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

from typing import Any

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
}


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
    parser = _Parser(text, filename)
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
        for number, raw in enumerate(text.splitlines(), start=1):
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
                break

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

    def _parse_sequence(self, indent: int) -> list[Any]:
        result: list[Any] = []
        while True:
            line = self._peek()
            if line is None or line.indent < indent:
                break
            if line.indent > indent:
                raise self._error("unexpected indentation", line)
            if line.text != "-" and not line.text.startswith("- "):
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
            if _is_mapping_entry(rest):
                inline_indent = indent + (len(line.text) - len(line.text[1:].lstrip()))
                nested = _Line(inline_indent, rest, line.number)
                self.lines.insert(self.index, nested)
                result.append(self._parse_mapping(inline_indent))
            else:
                result.append(self._scalar(rest, line))
        return result

    def _parse_value_for(self, rest: str, line: _Line, indent: int) -> Any:
        """The value of `key:` -- either written inline after the colon, or
        as an indented block on the following lines."""
        if rest:
            return self._scalar(rest, line)
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
        for i, char in enumerate(text):
            if quote:
                if char == quote:
                    quote = None
                continue
            if char in "\"'":
                quote = char
                continue
            if char == ":" and (i + 1 == len(text) or text[i + 1] in " \t"):
                key_text = text[:i].strip()
                if not key_text:
                    raise self._error("mapping entry with an empty key", line)
                return self._scalar_key(key_text, line), text[i + 1 :].strip()
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
                if esc == "u":
                    if i + 4 >= len(text):
                        raise self._error("truncated \\u escape", line)
                    hex_digits = text[i + 1 : i + 5]
                    try:
                        out.append(chr(int(hex_digits, 16)))
                    except ValueError:
                        raise self._error(
                            f"invalid \\u escape: \\u{hex_digits}", line
                        ) from None
                    i += 5
                    continue
                if esc not in _DOUBLE_QUOTE_ESCAPES:
                    raise self._error(f"unsupported escape: \\{esc}", line)
                out.append(_DOUBLE_QUOTE_ESCAPES[esc])
                i += 1
                continue
            out.append(char)
            i += 1
        raise self._error("unterminated quoted string", line)


def _is_mapping_entry(text: str) -> bool:
    """Whether `text` looks like `key: value` rather than a bare scalar.
    Only used to decide how to read a `- ...` sequence entry."""
    quote: str | None = None
    depth = 0
    for i, char in enumerate(text):
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif (
            char == ":" and depth == 0 and (i + 1 == len(text) or text[i + 1] in " \t")
        ):
            return True
    return False


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
            if char == "\\" and quote == '"':
                i += 2
                continue
            if char == quote:
                quote = None
            i += 1
            continue
        if char in "\"'":
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
    try:
        return int(text)
    except ValueError:
        pass
    try:
        # Guard against float() accepting "inf"/"nan"/"infinity", which in a
        # config file are far more likely to be a string someone meant.
        if text.lstrip("+-").lower() not in ("inf", "infinity", "nan"):
            return float(text)
    except ValueError:
        pass
    return text
