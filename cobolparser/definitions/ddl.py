"""DB2 for z/OS data definitions: tables, columns, keys, indexes, views, aliases, comments.

``parse_ddl(source)`` reads the ``CREATE`` / ``ALTER`` / ``COMMENT ON`` /
``LABEL ON`` statements of a DDL member (SPUFI or DSNTEP2 input, or a plain
``.sql`` script). Statements it does not model (GRANT, INSERT, SET, ...) are
counted under ``ignored_statements`` rather than dropped silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .._lines import split_source_lines

#: ``WITH DEFAULT`` / ``DEFAULT`` with no value: DB2 supplies the type's default.
SYSTEM_DEFAULT = "(type default)"


@dataclass
class DdlColumn:
    name: str
    data_type: str
    nullable: bool = True
    default: str | None = None
    comment: str | None = None
    label: str | None = None
    position: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.data_type,
            "nullable": self.nullable,
            "default": self.default,
            "comment": self.comment,
            "label": self.label,
            "position": self.position,
        }


@dataclass
class DdlTable:
    name: str
    line: int
    columns: list[DdlColumn] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    unique_keys: list[list[str]] = field(default_factory=list)
    foreign_keys: list[dict[str, Any]] = field(default_factory=list)
    indexes: list[dict[str, Any]] = field(default_factory=list)
    tablespace: str | None = None
    like: str | None = None
    comment: str | None = None
    label: str | None = None

    def column(self, name: str) -> DdlColumn | None:
        for col in self.columns:
            if col.name == name:
                return col
        return None

    def to_dict(self) -> dict[str, Any]:
        schema, _, table = self.name.rpartition(".")
        return {
            "name": self.name,
            "schema": schema or None,
            "table": table,
            "line": self.line,
            "columns": [c.to_dict() for c in self.columns],
            "primary_key": self.primary_key,
            "unique_keys": self.unique_keys,
            "foreign_keys": self.foreign_keys,
            "indexes": self.indexes,
            "tablespace": self.tablespace,
            "like": self.like,
            "comment": self.comment,
            "label": self.label,
        }


@dataclass
class DdlDefinitions:
    tables: list[DdlTable] = field(default_factory=list)
    views: list[dict[str, Any]] = field(default_factory=list)
    aliases: list[dict[str, Any]] = field(default_factory=list)
    indexes: list[dict[str, Any]] = field(default_factory=list)
    other_objects: list[dict[str, Any]] = field(default_factory=list)
    ignored_statements: dict[str, int] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def table(self, name: str) -> DdlTable | None:
        for tbl in self.tables:
            if tbl.name == name:
                return tbl
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "DDL",
            "tables": [t.to_dict() for t in self.tables],
            "views": self.views,
            "aliases": self.aliases,
            "indexes": self.indexes,
            "other_objects": self.other_objects,
            "ignored_statements": self.ignored_statements,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Lexing
# ---------------------------------------------------------------------------

_SEQUENCE_FIELD = re.compile(r"^(.{72})\s*\d{1,8}\s*$")
_TERMINATOR_DIRECTIVE = re.compile(r"^\s*--#SET\s+TERMINATOR\s+(\S)", re.IGNORECASE)
_TOKEN = re.compile(
    r"""
    (?P<string>'(?:[^']|'')*')
  | (?P<quoted>"(?:[^"]|"")*")
  | (?P<word>[A-Za-z0-9_@#$]+)
  | (?P<punct>[(),.=])
  | (?P<other>\S)
    """,
    re.VERBOSE,
)


@dataclass
class _Tok:
    text: str
    kind: str
    line: int

    @property
    def upper(self) -> str:
        return self.text.upper() if self.kind == "word" else self.text


def _statements(source: str) -> list[list[_Tok]]:
    """The token lists of every statement, split on the terminator outside quotes."""
    statements: list[list[_Tok]] = []
    current: list[_Tok] = []
    terminator = ";"
    in_block_comment = False
    for line_no, raw in enumerate(split_source_lines(source), start=1):
        directive = _TERMINATOR_DIRECTIVE.match(raw)
        if directive:
            terminator = directive.group(1)
            continue
        match = _SEQUENCE_FIELD.match(raw)
        text = match.group(1) if match else raw
        position = 0
        while position < len(text):
            if in_block_comment:
                end = text.find("*/", position)
                if end < 0:
                    position = len(text)
                    continue
                in_block_comment = False
                position = end + 2
                continue
            if text.startswith("--", position):
                break
            if text.startswith("/*", position):
                in_block_comment = True
                position += 2
                continue
            if text[position] == terminator:
                if current:
                    statements.append(current)
                current = []
                position += 1
                continue
            if text[position].isspace():
                position += 1
                continue
            token = _TOKEN.match(text, position)
            if (
                token is None
            ):  # pragma: no cover - _TOKEN matches any non-blank character
                position += 1
                continue
            kind = token.lastgroup or "other"
            current.append(_Tok(token.group(0), kind, line_no))
            position = token.end()
    if current:
        statements.append(current)
    return statements


def _name_text(tok: _Tok) -> str:
    if tok.kind == "quoted":
        return tok.text[1:-1].replace('""', '"')
    return tok.text.upper()


def _string_text(tok: _Tok) -> str:
    return tok.text[1:-1].replace("''", "'") if tok.kind == "string" else tok.text


class _Cursor:
    def __init__(self, tokens: list[_Tok]) -> None:
        self.tokens = tokens
        self.index = 0

    def peek(self, offset: int = 0) -> _Tok | None:
        position = self.index + offset
        return self.tokens[position] if position < len(self.tokens) else None

    def peek_upper(self, offset: int = 0) -> str:
        tok = self.peek(offset)
        return tok.upper if tok else ""

    def next(self) -> _Tok | None:
        tok = self.peek()
        if tok is not None:
            self.index += 1
        return tok

    def accept(self, *words: str) -> bool:
        if self.peek_upper() in words:
            self.index += 1
            return True
        return False

    def qualified_name(self) -> str | None:
        """``A.B.C`` -> ``A.B.C`` (unquoted parts upper-cased)."""
        tok = self.next()
        if tok is None or tok.kind not in ("word", "quoted"):
            return None
        parts = [_name_text(tok)]
        while self.peek_upper() == "." and self.peek(1) is not None:
            self.index += 1
            nxt = self.next()
            if nxt is None:  # pragma: no cover - guarded by peek(1)
                break
            parts.append(_name_text(nxt))
        return ".".join(parts)

    def paren_group(self) -> list[_Tok]:
        """The tokens inside the parenthesised group at the cursor (cursor moves past it)."""
        if self.peek_upper() != "(":
            return []
        self.index += 1
        depth = 1
        inner: list[_Tok] = []
        while (tok := self.next()) is not None:
            if tok.text == "(":
                depth += 1
            elif tok.text == ")":
                depth -= 1
                if depth == 0:
                    break
            inner.append(tok)
        return inner


def _split_commas(tokens: list[_Tok]) -> list[list[_Tok]]:
    parts: list[list[_Tok]] = [[]]
    depth = 0
    for tok in tokens:
        if tok.text == "(":
            depth += 1
        elif tok.text == ")":
            depth -= 1
        elif tok.text == "," and depth == 0:
            parts.append([])
            continue
        parts[-1].append(tok)
    return [p for p in parts if p]


def _column_names(tokens: list[_Tok]) -> list[str]:
    """Names of a column list ``(A ASC, B DESC)`` (order keywords dropped)."""
    names = []
    for part in _split_commas(tokens):
        if part and part[0].kind in ("word", "quoted"):
            names.append(_name_text(part[0]))
    return names


def _join(tokens: list[_Tok]) -> str:
    out = ""
    for tok in tokens:
        text = tok.upper if tok.kind == "word" else tok.text
        if out and not (text in "(),." or out.endswith("(") or out.endswith(".")):
            out += " "
        out += text
    return out


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------

_COLUMN_STOP = frozenset(
    {
        "NOT",
        "NULL",
        "DEFAULT",
        "PRIMARY",
        "UNIQUE",
        "REFERENCES",
        "GENERATED",
        "CONSTRAINT",
        "CHECK",
        "AS",
        "IMPLICITLY",
        "INLINE",
        "FIELDPROC",
    }
)


def _column(
    part: list[_Tok], position: int
) -> tuple[DdlColumn, dict[str, Any] | None, bool, bool]:
    """A column definition: the column, an inline foreign key, and whether it is
    the primary key and whether it is declared UNIQUE."""
    name = _name_text(part[0])
    type_tokens: list[_Tok] = []
    index = 1
    while index < len(part):
        tok = part[index]
        word = tok.upper
        if word in _COLUMN_STOP:
            break
        if (
            word == "WITH"
            and index + 1 < len(part)
            and part[index + 1].upper == "DEFAULT"
        ):
            break
        type_tokens.append(tok)
        index += 1
    column = DdlColumn(name=name, data_type=_join(type_tokens), position=position)
    foreign_key: dict[str, Any] | None = None
    primary = False
    unique = False
    rest = part[index:]
    words = [t.upper for t in rest]
    for offset, word in enumerate(words):
        if word == "NOT" and offset + 1 < len(words) and words[offset + 1] == "NULL":
            column.nullable = False
        elif word == "PRIMARY":
            primary = True
            column.nullable = False
        elif word == "UNIQUE":
            unique = True
        elif word == "DEFAULT":
            column.default = _default_value(rest[offset + 1 :])
        elif word == "REFERENCES" and offset + 1 < len(rest):
            cursor = _Cursor(rest[offset + 1 :])
            target = cursor.qualified_name()
            foreign_key = {
                "columns": [name],
                "references": target,
                "referenced_columns": _column_names(cursor.paren_group()),
                "name": None,
                "on_delete": _on_delete(cursor),
            }
    return column, foreign_key, primary, unique


def _default_value(tokens: list[_Tok]) -> str:
    """The value after DEFAULT: ``NULL``, a constant, or the type's default."""
    if tokens and tokens[0].upper == "NULL":
        return "NULL"
    value: list[_Tok] = []
    for nxt in tokens:
        if nxt.upper in _COLUMN_STOP:
            break
        value.append(nxt)
    if not value:
        return SYSTEM_DEFAULT
    if len(value) == 1:
        return _string_text(value[0])
    if len(value) == 2 and value[0].text in ("-", "+"):
        return value[0].text + _string_text(value[1])
    return _join(value)


_DELETE_RULE_WORDS = frozenset({"CASCADE", "RESTRICT", "NO", "ACTION", "SET", "NULL"})


def _on_delete(cursor: _Cursor) -> str | None:
    """The ``ON DELETE`` rule (``CASCADE``, ``SET NULL``, ...) from *cursor* on."""
    while cursor.peek() is not None:
        if cursor.accept("ON") and cursor.accept("DELETE"):
            rule: list[str] = []
            while cursor.peek_upper() in _DELETE_RULE_WORDS:
                cursor.next()
                rule.append(cursor.tokens[cursor.index - 1].upper)
            return " ".join(rule) or None
        cursor.next()
    return None


def _constraint(part: list[_Tok], table: DdlTable) -> bool:
    """Apply a table constraint; False when *part* is not one."""
    cursor = _Cursor(part)
    name: str | None = None
    if cursor.accept("CONSTRAINT"):
        tok = cursor.next()
        name = _name_text(tok) if tok else None
    if cursor.accept("PRIMARY"):
        cursor.accept("KEY")
        table.primary_key = _column_names(cursor.paren_group())
        for col_name in table.primary_key:
            col = table.column(col_name)
            if col is not None:
                col.nullable = False
        return True
    if cursor.accept("UNIQUE"):
        table.unique_keys.append(_column_names(cursor.paren_group()))
        return True
    if cursor.accept("FOREIGN"):
        cursor.accept("KEY")
        if cursor.peek_upper() != "(":
            tok = cursor.next()
            name = name or (_name_text(tok) if tok else None)
        columns = _column_names(cursor.paren_group())
        target = None
        referenced: list[str] = []
        if cursor.accept("REFERENCES"):
            target = cursor.qualified_name()
            referenced = _column_names(cursor.paren_group())
        on_delete = _on_delete(cursor)
        table.foreign_keys.append(
            {
                "name": name,
                "columns": columns,
                "references": target,
                "referenced_columns": referenced,
                "on_delete": on_delete,
            }
        )
        return True
    if cursor.accept("CHECK"):
        return True
    return name is not None


class _DdlBuilder:
    def __init__(self) -> None:
        self.result = DdlDefinitions()

    def ignore(self, words: list[str]) -> None:
        key = (
            " ".join(words[:2])
            if words[:1] in (["CREATE"], ["DROP"], ["ALTER"])
            else words[0]
        )
        self.result.ignored_statements[key] = (
            self.result.ignored_statements.get(key, 0) + 1
        )

    def warn(self, line: int, message: str) -> None:
        self.result.warnings.append({"line": line, "message": message})

    def statement(self, tokens: list[_Tok]) -> None:
        cursor = _Cursor(tokens)
        words = [t.upper for t in tokens[:4]]
        if cursor.accept("CREATE"):
            if cursor.accept("OR"):
                cursor.accept("REPLACE")
            self.create(cursor, tokens[0].line, words)
        elif cursor.accept("ALTER") and cursor.accept("TABLE"):
            self.alter_table(cursor, tokens[0].line)
        elif (
            cursor.peek_upper() in ("COMMENT", "LABEL") and cursor.peek_upper(1) == "ON"
        ):
            kind = cursor.next()
            cursor.next()
            self.comment(
                cursor, "comment" if kind and kind.upper == "COMMENT" else "label"
            )
        else:
            self.ignore(words)

    def create(self, cursor: _Cursor, line: int, words: list[str]) -> None:
        unique = cursor.accept("UNIQUE")
        cursor.accept("GLOBAL", "AUXILIARY", "LOB")
        cursor.accept("TEMPORARY")
        kind = cursor.next()
        kind_word = kind.upper if kind else ""
        if kind_word == "TABLE":
            self.create_table(cursor, line)
        elif kind_word == "INDEX":
            self.create_index(cursor, line, unique)
        elif kind_word == "VIEW":
            self.create_view(cursor, line)
        elif kind_word in ("ALIAS", "SYNONYM"):
            name = cursor.qualified_name()
            target = cursor.qualified_name() if cursor.accept("FOR") else None
            self.result.aliases.append(
                {"name": name, "kind": kind_word, "target": target, "line": line}
            )
        elif kind_word in (
            "TABLESPACE",
            "DATABASE",
            "STOGROUP",
            "SEQUENCE",
            "PROCEDURE",
        ):
            name = cursor.qualified_name()
            database = cursor.qualified_name() if cursor.accept("IN") else None
            self.result.other_objects.append(
                {"kind": kind_word, "name": name, "database": database, "line": line}
            )
        else:
            self.ignore(words)

    def create_table(self, cursor: _Cursor, line: int) -> None:
        name = cursor.qualified_name()
        if not name:
            self.warn(line, "CREATE TABLE without a name")
            return
        table = DdlTable(name=name, line=line)
        if cursor.accept("LIKE"):
            table.like = cursor.qualified_name()
        else:
            for part in _split_commas(cursor.paren_group()):
                self.table_element(table, part)
        while cursor.peek() is not None:
            if cursor.accept("IN"):
                table.tablespace = cursor.qualified_name()
                continue
            cursor.next()
        self.result.tables.append(table)

    def table_element(self, table: DdlTable, part: list[_Tok]) -> None:
        if part[0].upper in ("CONSTRAINT", "PRIMARY", "UNIQUE", "FOREIGN", "CHECK"):
            _constraint(part, table)
            return
        column, foreign_key, primary, unique = _column(part, len(table.columns) + 1)
        table.columns.append(column)
        if foreign_key:
            table.foreign_keys.append(foreign_key)
        if primary:
            table.primary_key = [column.name]
        elif unique:
            table.unique_keys.append([column.name])

    def create_index(self, cursor: _Cursor, line: int, unique: bool) -> None:
        name = cursor.qualified_name()
        table_name = cursor.qualified_name() if cursor.accept("ON") else None
        columns = _column_names(cursor.paren_group())
        clustered = any(t.upper == "CLUSTER" for t in cursor.tokens[cursor.index :])
        index = {
            "name": name,
            "table": table_name,
            "columns": columns,
            "unique": unique,
            "cluster": clustered,
            "line": line,
        }
        self.result.indexes.append(index)
        table = self.result.table(table_name) if table_name else None
        if table is not None:
            table.indexes.append({k: v for k, v in index.items() if k != "table"})

    def create_view(self, cursor: _Cursor, line: int) -> None:
        name = cursor.qualified_name()
        columns = _column_names(cursor.paren_group())
        cursor.accept("AS")
        body = cursor.tokens[cursor.index :]
        self.result.views.append(
            {
                "name": name,
                "columns": columns,
                "base_tables": _from_tables(body),
                "line": line,
            }
        )

    def alter_table(self, cursor: _Cursor, line: int) -> None:
        name = cursor.qualified_name()
        table = self.result.table(name) if name else None
        if table is None:
            self.warn(line, f"ALTER TABLE {name}, which this member does not create")
            return
        while cursor.peek() is not None:
            if not cursor.accept("ADD"):
                cursor.next()
                continue
            cursor.accept("COLUMN")
            remainder = []
            while cursor.peek() is not None and cursor.peek_upper() != "ADD":
                tok = cursor.next()
                if tok is not None:
                    remainder.append(tok)
            if remainder:
                self.table_element(table, remainder)

    def comment(self, cursor: _Cursor, attr: str) -> None:
        target_kind = cursor.peek_upper()
        if target_kind in ("TABLE", "COLUMN", "ALIAS", "INDEX", "VIEW"):
            cursor.next()
            name = cursor.qualified_name() or ""
            text = self.is_text(cursor)
            if target_kind == "COLUMN":
                table_name, _, column_name = name.rpartition(".")
                self.set_column_text(table_name, column_name, attr, text)
            elif target_kind == "TABLE":
                table = self.result.table(name)
                if table is not None:
                    setattr(table, attr, text)
            return
        # COMMENT ON tbl (col IS 'x', col2 IS 'y')
        name = cursor.qualified_name() or ""
        for part in _split_commas(cursor.paren_group()):
            sub = _Cursor(part)
            column_name = sub.qualified_name() or ""
            self.set_column_text(name, column_name, attr, self.is_text(sub))

    @staticmethod
    def is_text(cursor: _Cursor) -> str | None:
        cursor.accept("IS")
        tok = cursor.next()
        return _string_text(tok) if tok and tok.kind == "string" else None

    def set_column_text(
        self, table_name: str, column_name: str, attr: str, text: str | None
    ) -> None:
        table = self.result.table(table_name)
        column = table.column(column_name) if table else None
        if column is not None:
            setattr(column, attr, text)


_FROM_STOP = frozenset(
    {
        "WHERE",
        "GROUP",
        "ORDER",
        "HAVING",
        "UNION",
        "EXCEPT",
        "INTERSECT",
        "FETCH",
        "WITH",
        "ON",
        "FOR",
        "OPTIMIZE",
    }
)
_JOIN_WORDS = frozenset({"JOIN", "INNER", "LEFT", "RIGHT", "FULL", "OUTER", "CROSS"})


def _from_tables(tokens: list[_Tok]) -> list[str]:
    """Tables named after FROM and JOIN in a view's SELECT (nested selects included).

    A ``FROM`` inside a function call (``EXTRACT(YEAR FROM D)``,
    ``SUBSTR(X FROM 1)``, ``TRIM(... FROM X)``) is not a FROM clause, a table
    function (``TABLE(F(1))``) names no table, and the view's own common table
    expressions (``WITH CTE AS (...)``) are not base tables.
    """
    tables: list[str] = []
    expecting = False
    index = 0
    while index < len(tokens):
        tok = tokens[index]
        word = tok.upper
        if word == "FROM" and _is_from_clause(tokens, index):
            expecting = True
        elif word == "JOIN":
            expecting = True
        elif word == "," and expecting is False and _in_from_list(tokens, index):
            expecting = True
        elif expecting and tok.kind in ("word", "quoted") and word not in _JOIN_WORDS:
            if word == "SELECT":
                expecting = False
            elif word in ("TABLE", "LATERAL") and _next_upper(tokens, index) == "(":
                expecting = False
            else:
                cursor = _Cursor(tokens[index:])
                name = cursor.qualified_name()
                if name and name not in tables:
                    tables.append(name)
                index += cursor.index
                expecting = False
                continue
        elif word in _FROM_STOP or word == "(":
            expecting = False
        index += 1
    common = set(_common_table_names(tokens))
    return [name for name in tables if name not in common]


def _next_upper(tokens: list[_Tok], index: int) -> str:
    return tokens[index + 1].upper if index + 1 < len(tokens) else ""


def _is_from_clause(tokens: list[_Tok], index: int) -> bool:
    """True when the FROM at *index* follows a SELECT at the same depth.

    A FROM that only has an unmatched ``(`` before it (the argument list of
    ``EXTRACT``, ``SUBSTR``, ``TRIM``, ...) is a function's keyword.
    """
    depth = 0
    for back in range(index - 1, -1, -1):
        text = tokens[back].upper
        if text == ")":
            depth += 1
        elif text == "(":
            if depth == 0:
                return False
            depth -= 1
        elif depth == 0 and text == "SELECT":
            return True
    return False


def _common_table_names(tokens: list[_Tok]) -> list[str]:
    """The names a ``WITH name [(cols)] AS (...) [, ...]`` prefix defines."""
    cursor = _Cursor(tokens)
    if not cursor.accept("WITH"):
        return []
    names: list[str] = []
    while True:
        name = cursor.qualified_name()
        if name is None:
            return names
        names.append(name)
        if cursor.peek_upper() == "(":
            cursor.paren_group()
        if not cursor.accept("AS"):
            return names
        cursor.paren_group()
        if not cursor.accept(","):
            return names


def _in_from_list(tokens: list[_Tok], index: int) -> bool:
    """True when the comma at *index* separates FROM-list entries (same depth as a FROM)."""
    depth = 0
    for back in range(index - 1, -1, -1):
        text = tokens[back].upper
        if text == ")":
            depth += 1
        elif text == "(":
            if depth == 0:
                return False
            depth -= 1
        elif depth == 0 and text == "FROM":
            return True
        elif depth == 0 and (text in _FROM_STOP or text == "SELECT"):
            return False
    return False


def parse_ddl(source: str) -> DdlDefinitions:
    """The tables, views, indexes and aliases a DDL member defines."""
    builder = _DdlBuilder()
    for tokens in _statements(source):
        builder.statement(tokens)
    return builder.result
