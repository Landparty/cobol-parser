"""
SQL statement AST nodes for embedded SQL in COBOL programs.

This module provides comprehensive AST nodes for all types of SQL statements
embedded within COBOL EXEC SQL blocks, with structured output for analysis.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from .ast_base import SourceLocation
from .statements import CobolStatement

# Pre-compiled regex patterns for SQL statement parsing (avoids re-compilation per statement)
_SQL_HOST_VAR_RE = re.compile(r":([A-Za-z][A-Za-z0-9_-]*)")
_SQL_INDICATOR_RE = re.compile(
    r":([A-Za-z][A-Za-z0-9_-]*)\s*:\s*([A-Za-z][A-Za-z0-9_-]*)"
)
_SQL_INDICATOR_KW_RE = re.compile(
    r"INDICATOR\s+:([A-Za-z][A-Za-z0-9-]*)", re.IGNORECASE
)
# A table name may be qualified (schema.table, location.schema.table); matching
# only the first part used to report the schema itself (BANK) as a table.
_SQL_TABLE_NAME = r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
_SQL_FROM_TABLE_RE = re.compile(r"FROM\s+" + _SQL_TABLE_NAME, re.IGNORECASE)
_SQL_JOIN_TABLE_RE = re.compile(r"JOIN\s+" + _SQL_TABLE_NAME, re.IGNORECASE)
_SQL_INTO_TABLE_RE = re.compile(r"INTO\s+" + _SQL_TABLE_NAME, re.IGNORECASE)
_SQL_UPDATE_TABLE_RE = re.compile(r"UPDATE\s+" + _SQL_TABLE_NAME, re.IGNORECASE)
_SQL_INTO_VARS_RE = re.compile(r"INTO\s+(:[\w-]+(?:\s*,\s*:[\w-]+)*)", re.IGNORECASE)
_SQL_DECLARE_CURSOR_RE = re.compile(
    r"DECLARE\s+([A-Za-z_][A-Za-z0-9_-]*)\s+CURSOR", re.IGNORECASE
)
# The table may be qualified (``DECLARE SCHEMA.TABLE TABLE`` -- every DCLGEN
# member is), and the token-joined SQL text may carry spaces around the
# period (``BANK. ACCOUNT``); the name is normalized to ``SCHEMA.TABLE``.
_SQL_DECLARE_TABLE_RE = re.compile(
    r"DECLARE\s+([A-Za-z_][A-Za-z0-9_]*(?:\s*\.\s*[A-Za-z_][A-Za-z0-9_]*)*)\s+TABLE",
    re.IGNORECASE,
)
# Matches a single column definition: NAME  TYPE[(len[,scale])]  [NOT NULL]
_SQL_COLUMN_DEF_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)"  # column name
    r"\s+([A-Za-z][A-Za-z0-9]*)"  # DB2 type keyword
    r"(?:\s*\(\s*(\d+)(?:\s*,\s*(\d+))?\s*\))?"  # optional (len) or (prec,scale)
    r"(?:\s+(NOT\s+NULL))?",  # optional NOT NULL
    re.IGNORECASE,
)
_SQL_FETCH_RE = re.compile(
    r"FETCH\s+(?:NEXT\s+)?(?:FROM\s+)?([A-Za-z_][A-Za-z0-9_-]*)", re.IGNORECASE
)
_SQL_OPEN_RE = re.compile(r"OPEN\s+([A-Za-z_][A-Za-z0-9_-]*)", re.IGNORECASE)
_SQL_CLOSE_RE = re.compile(r"CLOSE\s+([A-Za-z_][A-Za-z0-9_-]*)", re.IGNORECASE)
_SQL_PREPARE_RE = re.compile(
    r"PREPARE\s+([A-Za-z_][A-Za-z0-9_-]*)\s+FROM", re.IGNORECASE
)
_SQL_EXECUTE_RE = re.compile(r"EXECUTE\s+([A-Za-z_][A-Za-z0-9_-]*)", re.IGNORECASE)
_SQL_FOR_SELECT_RE = re.compile(r"FOR\s+(SELECT.+)", re.IGNORECASE | re.DOTALL)
_SQL_USING_VARS_RE = re.compile(r"USING\s+(:[\w-]+(?:\s*,\s*:[\w-]+)*)", re.IGNORECASE)
_SQL_SAVEPOINT_RE = re.compile(
    r"TO\s+(?:SAVEPOINT\s+)?([A-Za-z_][A-Za-z0-9_-]*)", re.IGNORECASE
)

# SQL keyword filter set (used in table extraction)
_SQL_KEYWORDS = frozenset(
    [
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "WHERE",
        "INTO",
        "VALUES",
        "SET",
        "AND",
        "OR",
        "NULL",
        "NOT",
        "IN",
        "LIKE",
    ]
)

# Keywords that terminate a FROM table list or can never be a table name in
# the tokenizer-based extraction (see _extract_tables_tokenized).
_SQL_TABLE_STOP_KEYWORDS = frozenset(
    {
        "WHERE",
        "GROUP",
        "ORDER",
        "HAVING",
        "ON",
        "UNION",
        "EXCEPT",
        "INTERSECT",
        "FETCH",
        "FOR",
        "WITH",
        "SET",
        "VALUES",
        "INNER",
        "LEFT",
        "RIGHT",
        "FULL",
        "OUTER",
        "CROSS",
        "JOIN",
        "AS",
        "USING",
        "OPTIMIZE",
        "AT",
    }
    | _SQL_KEYWORDS
)


# ---------------------------------------------------------------------------
# Light SQL tokenizer (literal/comment aware) used to derive additional
# structure (select columns, WHERE presence, multi-table extraction) on top
# of the pre-existing regex extraction. Deliberately not a full grammar.
# ---------------------------------------------------------------------------


def _strip_sql_literals_and_comments(sql: str) -> str:
    """Blank out string literals and SQL comments from *sql*.

    Quoted literals (``'...'`` / ``"..."`` with doubled-quote escapes),
    ``--`` line comments, and ``/* ... */`` block comments are replaced by a
    single space so subsequent keyword/host-variable scans never match text
    inside them. A ``--`` immediately preceded by an identifier character is
    NOT treated as a comment (COBOL names may contain hyphens).
    """
    out: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            quote = ch
            i += 1
            while i < n:
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append(" ")
            continue
        if (
            ch == "-"
            and i + 1 < n
            and sql[i + 1] == "-"
            and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] in "_-:"))
        ):
            newline = sql.find("\n", i)
            i = n if newline == -1 else newline
            out.append(" ")
            continue
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _scan_sql_tokens(sql: str) -> list[tuple[str, int]]:
    """Tokenize literal/comment-scrubbed SQL into ``(token, paren_depth)``.

    Host variables keep their leading colon (``:WS-NAME``); an indicator form
    ``:WS-NAME:WS-IND`` yields two consecutive colon tokens. Identifier
    tokens may include dots and hyphens; other characters come out as
    single-character punctuation tokens. Whitespace is skipped.
    """
    tokens: list[tuple[str, int]] = []
    depth = 0
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch.isspace():
            i += 1
        elif ch == "(":
            tokens.append(("(", depth))
            depth += 1
            i += 1
        elif ch == ")":
            depth = max(0, depth - 1)
            tokens.append((")", depth))
            i += 1
        elif ch == ":":
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] in "_-"):
                j += 1
            tokens.append((sql[i:j], depth))
            i = j
        elif ch.isalnum() or ch in "_$#@":
            j = i
            while j < n and (sql[j].isalnum() or sql[j] in "_-$#@."):
                j += 1
            tokens.append((sql[i:j], depth))
            i = j
        else:
            tokens.append((ch, depth))
            i += 1
    return tokens


def _is_sql_word(token: str) -> bool:
    """Return True for identifier-shaped tokens (not punctuation/host vars)."""
    return (
        bool(token)
        and not token.startswith(":")
        and (token[0].isalnum() or token[0] in "_$#@")
    )


def _tidy_sql_fragment(parts: list[str]) -> str:
    """Join scan tokens back into readable SQL fragment text."""
    text = " ".join(parts)
    for src, dst in ((" (", "("), ("( ", "("), (" )", ")"), (". ", "."), (" .", ".")):
        text = text.replace(src, dst)
    return text.strip()


def _extract_select_columns(tokens: list[tuple[str, int]]) -> list[str]:
    """Return the SELECT-list items of a SELECT statement's token scan.

    Items are split on top-level commas between ``SELECT`` and the first
    top-level ``INTO``/``FROM``. A leading ``DISTINCT``/``ALL`` qualifier is
    dropped. Returns ``[]`` when the scan does not start with SELECT.
    """
    if not tokens or tokens[0][0].upper() != "SELECT":
        return []
    columns: list[str] = []
    current: list[str] = []
    start = 1
    if (
        len(tokens) > 1
        and tokens[1][1] == 0
        and tokens[1][0].upper() in ("DISTINCT", "ALL")
    ):
        start = 2
    for token, depth in tokens[start:]:
        upper = token.upper()
        if depth == 0 and upper in ("INTO", "FROM"):
            break
        if depth == 0 and token == ",":
            if current:
                columns.append(_tidy_sql_fragment(current))
                current = []
            continue
        current.append(token)
    if current:
        columns.append(_tidy_sql_fragment(current))
    return columns


def _read_qualified_name(tokens: list[tuple[str, int]], index: int) -> tuple[str, int]:
    """Read a (possibly qualified) table name at *index*; return (name, next)."""
    parts: list[str] = []
    n = len(tokens)
    while index < n:
        token, depth = tokens[index]
        if depth != 0 or not _is_sql_word(token):
            break
        parts.append(token)
        index += 1
        if not token.endswith("."):
            break
    return "".join(parts), index


_CTE_MAIN_VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE", "MERGE")


def _split_common_table_expressions(
    tokens: list[tuple[str, int]],
) -> tuple[list[str], int]:
    """Split a ``WITH name [(cols)] AS (...) [, ...] <statement>`` scan.

    Returns the CTE names and the index of the main statement's first token.
    A scan that does not start with ``WITH`` yields ``([], 0)``.
    """
    if not tokens or tokens[0][1] != 0 or tokens[0][0].upper() != "WITH":
        return [], 0
    names: list[str] = []
    n = len(tokens)
    i = 1
    while i < n:
        token, depth = tokens[i]
        if depth != 0 or not _is_sql_word(token):
            break
        if token.upper() in _CTE_MAIN_VERBS:
            return names, i
        names.append(token)
        i += 1
        # Optional column list, then AS, then the parenthesised body. Each
        # parenthesised group is its opening "(" at depth 0, the body at
        # depth >= 1 and its closing ")" back at depth 0.
        for _ in range(2):
            if i < n and tokens[i][0].upper() == "AS" and tokens[i][1] == 0:
                i += 1
            if i < n and tokens[i] == ("(", 0):
                i += 1
                while i < n and tokens[i] != (")", 0):
                    i += 1
                i += 1
        if i < n and tokens[i] == (",", 0):
            i += 1
            continue
        break
    return names, i


def _extract_tables_tokenized(
    tokens: list[tuple[str, int]], sql_type: str
) -> list[str]:
    """Tokenizer-based table extraction (multi-table FROM lists, JOINs).

    Complements the regex extraction: results are appended to
    ``ExecSQLStatement.tables`` only when not already present, so existing
    regex behaviour is preserved.
    """
    tables: list[str] = []

    def add(name: str) -> None:
        if name and name.upper() not in _SQL_TABLE_STOP_KEYWORDS and name not in tables:
            tables.append(name)

    def read_table_list(index: int) -> int:
        """Read ``table [AS alias][, table [AS alias]]...`` from *index*."""
        n = len(tokens)
        while True:
            name, index = _read_qualified_name(tokens, index)
            if not name or name.upper() in _SQL_TABLE_STOP_KEYWORDS:
                return index
            add(name)
            # Optional alias: AS alias | bare alias word.
            if index < n and tokens[index][1] == 0:
                token = tokens[index][0]
                upper = token.upper()
                if upper == "AS":
                    index += 1
                    if index < n and _is_sql_word(tokens[index][0]):
                        index += 1
                elif _is_sql_word(token) and upper not in _SQL_TABLE_STOP_KEYWORDS:
                    index += 1
            if index < n and tokens[index] == (",", 0):
                index += 1
                continue
            return index

    from_types = (
        SQLStatementType.SELECT,
        SQLStatementType.DELETE,
        SQLStatementType.DECLARE_CURSOR,
    )
    n = len(tokens)
    i = 0
    insert_into_pending = sql_type in (SQLStatementType.INSERT, SQLStatementType.MERGE)
    while i < n:
        token, depth = tokens[i]
        if depth == 0:
            upper = token.upper()
            if upper == "FROM" and sql_type in from_types:
                i = read_table_list(i + 1)
                continue
            if upper == "JOIN":
                name, j = _read_qualified_name(tokens, i + 1)
                add(name)
                i = max(j, i + 1)
                continue
            if upper == "INTO" and insert_into_pending:
                name, j = _read_qualified_name(tokens, i + 1)
                add(name)
                insert_into_pending = False
                i = max(j, i + 1)
                continue
            if upper == "USING" and sql_type == SQLStatementType.MERGE:
                # MERGE ... USING table: the source (a parenthesised
                # subquery or VALUES list has no name here).
                name, j = _read_qualified_name(tokens, i + 1)
                add(name)
                i = max(j, i + 1)
                continue
            if upper == "UPDATE" and sql_type == SQLStatementType.UPDATE and i == 0:
                name, j = _read_qualified_name(tokens, i + 1)
                add(name)
                i = max(j, i + 1)
                continue
        i += 1
    return tables


@dataclass
class SQLStatementInfo:
    """Structured information about a parsed SQL statement."""

    table: str | None = None
    query: str | None = None
    cursor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {"table": self.table, "query": self.query, "cursor": self.cursor}


class SQLStatementType:
    """SQL statement type constants."""

    SELECT: ClassVar[str] = "SELECT"
    INSERT: ClassVar[str] = "INSERT"
    UPDATE: ClassVar[str] = "UPDATE"
    DELETE: ClassVar[str] = "DELETE"
    MERGE: ClassVar[str] = "MERGE"
    DECLARE_CURSOR: ClassVar[str] = "DECLARE CURSOR"
    DECLARE_TABLE: ClassVar[str] = "DECLARE TABLE"
    OPEN_CURSOR: ClassVar[str] = "OPEN"
    FETCH: ClassVar[str] = "FETCH"
    CLOSE_CURSOR: ClassVar[str] = "CLOSE"
    COMMIT: ClassVar[str] = "COMMIT"
    ROLLBACK: ClassVar[str] = "ROLLBACK"
    PREPARE: ClassVar[str] = "PREPARE"
    EXECUTE: ClassVar[str] = "EXECUTE"
    INCLUDE: ClassVar[str] = "INCLUDE"
    WHENEVER: ClassVar[str] = "WHENEVER"
    UNKNOWN: ClassVar[str] = "UNKNOWN"


# ---------------------------------------------------------------------------
# DB2 column definition (produced by DCLGEN)
# ---------------------------------------------------------------------------


# Mapping from DB2 type name (upper-cased) to a function that returns the
# equivalent COBOL picture string given (length, precision, scale) parameters.
# Returns None for types that have no simple picture equivalent (e.g. BLOB).
def _db2_pic_char(length: int | None, _prec: int | None, _scale: int | None) -> str:
    n = length or 1
    return f"X({n})"


def _db2_pic_varchar(length: int | None, _prec: int | None, _scale: int | None) -> str:
    # VARCHAR is represented as a group with a 2-byte length prefix in DCLGEN
    n = length or 1
    return f"X({n})"  # simplified; full form is a 49-level group


def _db2_pic_integer(_l: int | None, _p: int | None, _s: int | None) -> str:
    return "S9(9)"


def _db2_pic_smallint(_l: int | None, _p: int | None, _s: int | None) -> str:
    return "S9(4)"


def _db2_pic_bigint(_l: int | None, _p: int | None, _s: int | None) -> str:
    return "S9(18)"


def _db2_pic_decimal(_l: int | None, precision: int | None, scale: int | None) -> str:
    p = precision or 9
    s = scale or 0
    if p <= 0:
        raise ValueError(f"Invalid DECIMAL precision: {p}")
    if s < 0:
        raise ValueError(f"Invalid DECIMAL scale: {s}")
    if s > p:
        raise ValueError(
            f"Invalid DECIMAL definition: scale ({s}) cannot exceed precision ({p})"
        )
    if s > 0:
        integer_digits = max(1, p - s)
        return f"S9({integer_digits})V9({s})"
    return f"S9({p})"


def _db2_pic_float(_l: int | None, _p: int | None, _s: int | None) -> str:
    return "COMP-1"  # single-precision — not a PIC, but conventional usage annotation


def _db2_pic_double(_l: int | None, _p: int | None, _s: int | None) -> str:
    return "COMP-2"  # double-precision


def _db2_pic_date(_l: int | None, _p: int | None, _s: int | None) -> str:
    return "X(10)"


def _db2_pic_time(_l: int | None, _p: int | None, _s: int | None) -> str:
    return "X(8)"


def _db2_pic_timestamp(_l: int | None, _p: int | None, _s: int | None) -> str:
    return "X(26)"


def _db2_pic_clob(length: int | None, _p: int | None, _s: int | None) -> str:
    n = length or 1
    return f"X({n})"


_Db2PicFn = Callable[[int | None, int | None, int | None], str]

_DB2_TYPE_MAP: dict[str, _Db2PicFn] = {
    "CHAR": _db2_pic_char,
    "CHARACTER": _db2_pic_char,
    "VARCHAR": _db2_pic_varchar,
    "INTEGER": _db2_pic_integer,
    "INT": _db2_pic_integer,
    "SMALLINT": _db2_pic_smallint,
    "BIGINT": _db2_pic_bigint,
    "DECIMAL": _db2_pic_decimal,
    "DEC": _db2_pic_decimal,
    "NUMERIC": _db2_pic_decimal,
    "NUM": _db2_pic_decimal,
    "FLOAT": _db2_pic_float,
    "REAL": _db2_pic_float,
    "DOUBLE": _db2_pic_double,
    "DATE": _db2_pic_date,
    "TIME": _db2_pic_time,
    "TIMESTAMP": _db2_pic_timestamp,
    "CLOB": _db2_pic_clob,
}

# DB2 numeric types that require COMP-3 storage in DCLGEN-generated copybooks
_DB2_COMP3_TYPES = frozenset({"DECIMAL", "DEC", "NUMERIC", "NUM"})
# DB2 numeric types that require COMP (binary) storage
_DB2_COMP_TYPES = frozenset({"INTEGER", "INT", "SMALLINT", "BIGINT"})
# DB2 float types (usage annotation rather than PIC)
_DB2_FLOAT_TYPES = frozenset({"FLOAT", "REAL", "DOUBLE"})
# DB2 character-like types
_DB2_CHAR_TYPES = frozenset(
    {"CHAR", "CHARACTER", "VARCHAR", "CLOB", "DATE", "TIME", "TIMESTAMP"}
)


def db2_type_to_cobol_pic(
    db2_type: str,
    length: int | None = None,
    precision: int | None = None,
    scale: int | None = None,
) -> str | None:
    """Map a DB2 column type to a COBOL PICTURE string.

    Args:
        db2_type: DB2 data type keyword (e.g. ``"CHAR"``, ``"DECIMAL"``).
        length: Length parameter for CHAR / VARCHAR columns.
        precision: Total digits for DECIMAL / NUMERIC columns.
        scale: Decimal digits for DECIMAL / NUMERIC columns.

    Returns:
        A COBOL picture string (e.g. ``"X(30)"``, ``"S9(7)V9(2)"``),
        or *None* for types without a direct picture equivalent (BLOB, etc.).
    """
    fn = _DB2_TYPE_MAP.get(db2_type.upper())
    if fn is None:
        return None
    return fn(length, precision, scale)


def db2_type_to_cobol_usage(db2_type: str) -> str:
    """Return the COBOL USAGE clause string for a DB2 column type.

    Returns ``"DISPLAY"`` for character types, ``"COMP-3"`` for packed decimal,
    ``"COMP"`` for binary integer types, ``"COMP-1"`` / ``"COMP-2"`` for floats.
    """
    upper = db2_type.upper()
    if upper in _DB2_COMP3_TYPES:
        return "COMP-3"
    if upper in _DB2_COMP_TYPES:
        return "COMP"
    if upper == "FLOAT" or upper == "REAL":
        return "COMP-1"
    if upper == "DOUBLE":
        return "COMP-2"
    return "DISPLAY"


@dataclass
class DB2ColumnDefinition:
    """A single column definition from a DB2 DECLARE TABLE (DCLGEN output).

    Attributes:
        name: Column name as it appears in the DB2 catalog.
        db2_type: DB2 data type keyword (upper-cased), e.g. ``"CHAR"``.
        length: Length for CHAR / VARCHAR columns; ``None`` otherwise.
        precision: Total digits for DECIMAL / NUMERIC; ``None`` otherwise.
        scale: Decimal places for DECIMAL / NUMERIC; ``None`` otherwise.
        nullable: ``True`` if the column accepts NULL (default); ``False``
            when ``NOT NULL`` is declared.
        cobol_picture: COBOL PICTURE string derived from the DB2 type,
            computed automatically on construction.
        cobol_usage: COBOL USAGE clause string (e.g. ``"COMP-3"``).
    """

    name: str
    db2_type: str
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    nullable: bool = True
    cobol_picture: str | None = field(init=False)
    cobol_usage: str = field(init=False)

    def __post_init__(self) -> None:
        self.cobol_picture = db2_type_to_cobol_pic(
            self.db2_type, self.length, self.precision, self.scale
        )
        self.cobol_usage = db2_type_to_cobol_usage(self.db2_type)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "name": self.name,
            "db2_type": self.db2_type,
            "length": self.length,
            "precision": self.precision,
            "scale": self.scale,
            "nullable": self.nullable,
            "cobol_picture": self.cobol_picture,
            "cobol_usage": self.cobol_usage,
        }


class ExecSQLStatement(CobolStatement):
    """AST node for EXEC SQL statements with enhanced parsing.

    Provides structured output with table, query, and cursor information
    as well as comprehensive host variable detection.
    """

    def __init__(self, location: SourceLocation):
        super().__init__("EXEC-SQL", location)
        self.sql_text: str = ""
        self._sql_type: str = SQLStatementType.UNKNOWN
        self.host_variables: list[str] = []
        self.null_indicators: list[str] = []
        self.tables: list[str] = []
        self.cursor_name: str | None = None
        self.prepared_statement_name: str | None = None
        self.into_variables: list[str] = []
        #: SELECT-list items (tokenizer-derived; populated for SELECT only).
        self.select_columns: list[str] = []
        #: True when a top-level WHERE clause is present.
        self.where_present: bool = False

    @property
    def sql_type(self) -> str:
        """Return SQL type (SELECT, INSERT, UPDATE, DELETE, etc.)."""
        return self._sql_type

    def set_sql_text(self, sql_text: str) -> None:
        """Set the SQL statement text and parse its components."""
        self.sql_text = sql_text.strip()
        self._parse_sql_statement()

    def _parse_sql_statement(self) -> None:
        """Parse the SQL statement to extract type, tables, host variables, etc."""
        if not self.sql_text:
            return

        # Normalize whitespace for easier parsing
        normalized = " ".join(self.sql_text.split())
        upper_sql = normalized.upper()

        # Determine SQL type
        self._sql_type = self._determine_sql_type(upper_sql)

        # Scans below must never match inside string literals or comments.
        scrubbed = _strip_sql_literals_and_comments(normalized)

        # Extract host variables (:variable_name)
        self._extract_host_variables(scrubbed)

        tokens = _scan_sql_tokens(scrubbed)

        # ``WITH cte AS (...) SELECT ...``: the statement is its main verb,
        # and the CTE names are not tables.
        cte_names, main_start = _split_common_table_expressions(tokens)
        if cte_names and self._sql_type == SQLStatementType.UNKNOWN:
            main = tokens[main_start][0].upper() if main_start < len(tokens) else ""
            self._sql_type = self._determine_sql_type(main)
        main_tokens = tokens[main_start:]

        # Extract table names (regex pass — preserved for compatibility)
        self._extract_tables(scrubbed)

        # Tokenizer pass: adds structure the regexes miss (multi-table FROM
        # lists, JOIN chains, SELECT columns, WHERE presence).
        tokenized = _extract_tables_tokenized(main_tokens, self._sql_type)
        for table in tokenized:
            if table not in self.tables:
                self.tables.append(table)
        if cte_names:
            ctes = {name.upper() for name in cte_names}
            self.tables = [t for t in self.tables if t.upper() not in ctes]
        if self._sql_type == SQLStatementType.MERGE and tokenized:
            # The MERGE target (read by the tokenizer from ``MERGE INTO``)
            # leads, ahead of the tables its USING subquery reads.
            target = tokenized[0]
            self.tables = [target] + [t for t in self.tables if t != target]
        self.select_columns = (
            _extract_select_columns(main_tokens)
            if self._sql_type == SQLStatementType.SELECT
            else []
        )
        self.where_present = any(
            depth == 0 and token.upper() == "WHERE" for token, depth in tokens
        )

        # Extract INTO variables
        self._extract_into_variables(scrubbed)

        # Extract cursor name if applicable
        self._extract_cursor_info(normalized)

    def _determine_sql_type(self, upper_sql: str) -> str:
        """Determine the type of SQL statement."""
        # Check for cursor operations first
        if upper_sql.startswith("DECLARE"):
            if "CURSOR" in upper_sql:
                return SQLStatementType.DECLARE_CURSOR
            if "TABLE" in upper_sql:
                return SQLStatementType.DECLARE_TABLE
        if upper_sql.startswith("FETCH"):
            return SQLStatementType.FETCH
        elif upper_sql.startswith("OPEN"):
            return SQLStatementType.OPEN_CURSOR
        elif upper_sql.startswith("CLOSE"):
            return SQLStatementType.CLOSE_CURSOR

        # DML statements
        if upper_sql.startswith("SELECT"):
            return SQLStatementType.SELECT
        elif upper_sql.startswith("INSERT"):
            return SQLStatementType.INSERT
        elif upper_sql.startswith("UPDATE"):
            return SQLStatementType.UPDATE
        elif upper_sql.startswith("DELETE"):
            return SQLStatementType.DELETE
        elif upper_sql.startswith("MERGE"):
            return SQLStatementType.MERGE

        # Transaction control
        if upper_sql.startswith("COMMIT"):
            return SQLStatementType.COMMIT
        elif upper_sql.startswith("ROLLBACK"):
            return SQLStatementType.ROLLBACK

        # Dynamic SQL
        if upper_sql.startswith("PREPARE"):
            return SQLStatementType.PREPARE
        elif upper_sql.startswith("EXECUTE"):
            return SQLStatementType.EXECUTE

        # Other
        if upper_sql.startswith("INCLUDE"):
            return SQLStatementType.INCLUDE
        elif upper_sql.startswith("WHENEVER"):
            return SQLStatementType.WHENEVER

        return SQLStatementType.UNKNOWN

    def _extract_host_variables(self, sql: str) -> None:
        """Extract host variables prefixed with colon."""
        matches = _SQL_HOST_VAR_RE.findall(sql)

        for var in matches:
            if var.upper() not in ["NULL", "INDICATOR"]:
                if var not in self.host_variables:
                    self.host_variables.append(var)

        # Extract null indicators (either :var:indicator or INDICATOR :var)
        indicator_matches = _SQL_INDICATOR_RE.findall(sql)
        for _var, indicator in indicator_matches:
            if indicator not in self.null_indicators:
                self.null_indicators.append(indicator)

        # Also check for INDICATOR keyword pattern
        indicator_keyword_matches = _SQL_INDICATOR_KW_RE.findall(sql)
        for indicator in indicator_keyword_matches:
            if indicator not in self.null_indicators:
                self.null_indicators.append(indicator)

    def _extract_tables(self, sql: str) -> None:
        """Extract table names from the SQL statement."""
        # Use pre-compiled patterns based on SQL type
        compiled_patterns = []

        if self._sql_type == SQLStatementType.SELECT:
            compiled_patterns.append(_SQL_FROM_TABLE_RE)
            compiled_patterns.append(_SQL_JOIN_TABLE_RE)

        elif self._sql_type == SQLStatementType.INSERT:
            compiled_patterns.append(_SQL_INTO_TABLE_RE)

        elif self._sql_type == SQLStatementType.UPDATE:
            compiled_patterns.append(_SQL_UPDATE_TABLE_RE)

        elif self._sql_type == SQLStatementType.DELETE:
            compiled_patterns.append(_SQL_FROM_TABLE_RE)

        elif self._sql_type == SQLStatementType.MERGE:
            # Tables read by a ``USING (SELECT ... FROM t)`` source.
            compiled_patterns.append(_SQL_FROM_TABLE_RE)
            compiled_patterns.append(_SQL_JOIN_TABLE_RE)

        elif self._sql_type == SQLStatementType.DECLARE_CURSOR:
            compiled_patterns.append(_SQL_FROM_TABLE_RE)
            compiled_patterns.append(_SQL_JOIN_TABLE_RE)

        elif self._sql_type == SQLStatementType.DECLARE_TABLE:
            # Table name is extracted by DeclareTableStatement directly
            pass

        elif self._sql_type == SQLStatementType.FETCH:
            pass

        for pattern in compiled_patterns:
            matches = pattern.findall(sql)
            for table in matches:
                if table.upper() not in _SQL_KEYWORDS:
                    if table not in self.tables:
                        self.tables.append(table)

    def _extract_into_variables(self, sql: str) -> None:
        """Extract variables from INTO clause."""
        match = _SQL_INTO_VARS_RE.search(sql)
        if match:
            into_clause = match.group(1)
            vars_matches = _SQL_HOST_VAR_RE.findall(into_clause)
            self.into_variables = vars_matches

    def _extract_cursor_info(self, sql: str) -> None:
        """Extract cursor name if this is a cursor-related statement."""
        if self._sql_type == SQLStatementType.DECLARE_CURSOR:
            match = _SQL_DECLARE_CURSOR_RE.search(sql)
            if match:
                self.cursor_name = match.group(1)

        elif self._sql_type == SQLStatementType.FETCH:
            match = _SQL_FETCH_RE.search(sql)
            if match:
                cursor_candidate = match.group(1)
                if cursor_candidate.upper() not in [
                    "INTO",
                    "NEXT",
                    "PRIOR",
                    "FIRST",
                    "LAST",
                ]:
                    self.cursor_name = cursor_candidate

        elif self._sql_type == SQLStatementType.OPEN_CURSOR:
            match = _SQL_OPEN_RE.search(sql)
            if match:
                self.cursor_name = match.group(1)

        elif self._sql_type == SQLStatementType.CLOSE_CURSOR:
            match = _SQL_CLOSE_RE.search(sql)
            if match:
                self.cursor_name = match.group(1)

        # Check for PREPARE statement
        if self._sql_type == SQLStatementType.PREPARE:
            match = _SQL_PREPARE_RE.search(sql)
            if match:
                self.prepared_statement_name = match.group(1)

        elif self._sql_type == SQLStatementType.EXECUTE:
            match = _SQL_EXECUTE_RE.search(sql)
            if match:
                self.prepared_statement_name = match.group(1)

    def add_host_variable(self, variable: str) -> None:
        """Add a host variable used in the SQL statement."""
        if variable not in self.host_variables:
            self.host_variables.append(variable)

    def get_structured_output(self) -> SQLStatementInfo:
        """Get structured output with table, query, and cursor fields."""
        result = SQLStatementInfo()

        # Set table (primary table for the operation)
        if self.tables:
            result.table = self.tables[0]

        # Set query or cursor based on statement type
        if self._sql_type in [
            SQLStatementType.FETCH,
            SQLStatementType.OPEN_CURSOR,
            SQLStatementType.CLOSE_CURSOR,
        ]:
            # For cursor operations, output goes to cursor field
            if self.cursor_name:
                result.cursor = f"{self._sql_type} {self.cursor_name}"
                if self._sql_type == SQLStatementType.FETCH and self.into_variables:
                    result.cursor = f"FETCH :{','.join(self.into_variables)} FROM {self.cursor_name}"
        elif self._sql_type == SQLStatementType.DECLARE_CURSOR:
            # For DECLARE CURSOR, both query and cursor are relevant
            result.cursor = f"DECLARE {self.cursor_name} CURSOR"
            # Extract the SELECT portion
            match = _SQL_FOR_SELECT_RE.search(self.sql_text)
            if match:
                result.query = match.group(1).strip()
        else:
            # For regular DML statements, output goes to query field
            result.query = self.sql_text

        return result

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = super().to_dict()
        structured = self.get_structured_output()
        result.update(
            {
                "sql_text": self.sql_text,
                "sql_type": self.sql_type,
                "host_variables": self.host_variables,
                "null_indicators": self.null_indicators,
                "tables": self.tables,
                "cursor_name": self.cursor_name,
                "prepared_statement_name": self.prepared_statement_name,
                "into_variables": self.into_variables,
                "select_columns": self.select_columns,
                "where_present": self.where_present,
                "structured_output": structured.to_dict(),
            }
        )
        return result


class DeclareCursorStatement(ExecSQLStatement):
    """AST node specifically for DECLARE CURSOR statements."""

    def __init__(self, location: SourceLocation):
        super().__init__(location)
        self.statement_type = "DECLARE-CURSOR"
        self.select_statement: str | None = None
        self.cursor_options: list[str] = []  # WITH HOLD, FOR UPDATE, etc.

    def set_select_statement(self, select_sql: str) -> None:
        """Set the SELECT statement for the cursor."""
        self.select_statement = select_sql.strip()
        # Parse tables from the SELECT
        self._extract_tables_from_select(select_sql)

    def _extract_tables_from_select(self, sql: str) -> None:
        """Extract tables from the cursor's SELECT statement."""
        compiled_patterns = [_SQL_FROM_TABLE_RE, _SQL_JOIN_TABLE_RE]
        for pattern in compiled_patterns:
            matches = pattern.findall(sql)
            for table in matches:
                if table.upper() not in ["SELECT", "WHERE", "AND", "OR", "NOT", "IN"]:
                    if table not in self.tables:
                        self.tables.append(table)

    def add_cursor_option(self, option: str) -> None:
        """Add a cursor option (WITH HOLD, FOR UPDATE, etc.)."""
        if option not in self.cursor_options:
            self.cursor_options.append(option)

    def get_structured_output(self) -> SQLStatementInfo:
        """Get structured output for DECLARE CURSOR."""
        result = SQLStatementInfo()
        result.cursor = f"DECLARE {self.cursor_name} CURSOR"
        if self.select_statement:
            result.query = self.select_statement
        if self.tables:
            result.table = self.tables[0]
        return result

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "select_statement": self.select_statement,
                "cursor_options": self.cursor_options,
            }
        )
        return result


class DeclareTableStatement(ExecSQLStatement):
    """AST node for EXEC SQL DECLARE tablename TABLE (...) END-EXEC.

    This is the output of the IBM DB2 DCLGEN utility, which generates a
    ``DECLARE TABLE`` SQL block together with a matching COBOL 01-level
    structure in the DATA DIVISION.  Parsing this block lets the host-variable
    resolver correlate :host-var references in DML statements with their DB2
    column type.

    Attributes:
        table_name: DB2 table name as declared (upper-cased).
        columns: Ordered list of :class:`DB2ColumnDefinition` objects.
    """

    def __init__(self, location: SourceLocation):
        super().__init__(location)
        self.statement_type = "DECLARE-TABLE"
        self.table_name: str | None = None
        self.columns: list[DB2ColumnDefinition] = []

    # ------------------------------------------------------------------
    # Column parsing
    # ------------------------------------------------------------------

    def _parse_columns(self, sql_text: str) -> None:
        """Extract column definitions from the SQL text.

        Expects the normalized SQL text of a DECLARE TABLE statement.
        The column block is the parenthesised list after TABLE.
        """
        # Extract everything inside the outermost parentheses
        paren_start = sql_text.find("(")
        paren_end = sql_text.rfind(")")
        if paren_start == -1 or paren_end == -1:
            return

        col_block = sql_text[paren_start + 1 : paren_end]

        # Split on commas that are *not* inside nested parens
        # (handles DECIMAL(10,2) correctly)
        col_defs: list[str] = []
        depth = 0
        current: list[str] = []
        for ch in col_block:
            if ch == "(":
                depth += 1
                current.append(ch)
            elif ch == ")":
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                col_defs.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        if current:
            col_defs.append("".join(current).strip())

        for col_text in col_defs:
            col_text = col_text.strip()
            if not col_text:
                continue
            m = _SQL_COLUMN_DEF_RE.match(col_text)
            if not m:
                continue
            col_name = m.group(1)
            db2_type = m.group(2).upper()
            raw_len = m.group(3)
            raw_scale = m.group(4)
            not_null_flag = m.group(5)

            length: int | None = None
            precision: int | None = None
            scale: int | None = None

            upper_type = db2_type
            if upper_type in _DB2_CHAR_TYPES:
                length = int(raw_len) if raw_len else None
            elif upper_type in _DB2_COMP3_TYPES:
                precision = int(raw_len) if raw_len else None
                scale = int(raw_scale) if raw_scale else None
            # For integer/float types length/precision/scale stay None

            nullable = not_null_flag is None or "NOT" not in not_null_flag.upper()

            self.columns.append(
                DB2ColumnDefinition(
                    name=col_name,
                    db2_type=db2_type,
                    length=length,
                    precision=precision,
                    scale=scale,
                    nullable=nullable,
                )
            )

    def set_sql_text(self, sql_text: str) -> None:
        """Override to also parse table name and column definitions."""
        # Reset state so re-invocations don't accumulate duplicates
        self.table_name = None
        self.columns = []
        super().set_sql_text(sql_text)
        # Extract table name
        m = _SQL_DECLARE_TABLE_RE.search(sql_text)
        if m:
            self.table_name = re.sub(r"\s*\.\s*", ".", m.group(1)).upper()
            if self.table_name not in self.tables:
                self.tables.append(self.table_name)
        # Parse columns
        self._parse_columns(sql_text)

    def get_structured_output(self) -> SQLStatementInfo:
        """Get structured output for DECLARE TABLE."""
        result = SQLStatementInfo()
        result.table = self.table_name
        result.query = self.sql_text
        return result

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "table_name": self.table_name,
                "columns": [c.to_dict() for c in self.columns],
            }
        )
        return result


class FetchStatement(ExecSQLStatement):
    """AST node specifically for FETCH statements."""

    def __init__(self, location: SourceLocation):
        super().__init__(location)
        self.statement_type = "FETCH"
        self.fetch_direction: str = "NEXT"  # NEXT, PRIOR, FIRST, LAST
        self.fetch_count: int | None = None

    def set_fetch_direction(self, direction: str) -> None:
        """Set fetch direction (NEXT, PRIOR, FIRST, LAST)."""
        self.fetch_direction = direction.upper()

    def get_structured_output(self) -> SQLStatementInfo:
        """Get structured output for FETCH."""
        result = SQLStatementInfo()
        if self.into_variables:
            result.cursor = f"FETCH :{','.join(self.into_variables)} FROM {self.cursor_name or 'UNKNOWN'}"
        else:
            result.cursor = f"FETCH FROM {self.cursor_name or 'UNKNOWN'}"
        return result

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = super().to_dict()
        result.update(
            {"fetch_direction": self.fetch_direction, "fetch_count": self.fetch_count}
        )
        return result


class DynamicSQLStatement(ExecSQLStatement):
    """AST node for dynamic SQL (PREPARE/EXECUTE)."""

    def __init__(self, location: SourceLocation):
        super().__init__(location)
        self.statement_type = "DYNAMIC-SQL"
        self.dynamic_sql_text: str | None = None
        self.using_variables: list[str] = []

    def set_dynamic_sql(self, sql: str) -> None:
        """Set the dynamic SQL text."""
        self.dynamic_sql_text = sql.strip()

    def add_using_variable(self, variable: str) -> None:
        """Add a variable to the USING clause."""
        if variable not in self.using_variables:
            self.using_variables.append(variable)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "dynamic_sql_text": self.dynamic_sql_text,
                "using_variables": self.using_variables,
            }
        )
        return result


class TransactionControlStatement(ExecSQLStatement):
    """AST node for transaction control statements (COMMIT, ROLLBACK)."""

    def __init__(self, location: SourceLocation):
        super().__init__(location)
        self.statement_type = "TRANSACTION-CONTROL"
        self.savepoint_name: str | None = None
        self.is_work: bool = False  # COMMIT WORK vs COMMIT

    def set_sql_text(self, sql: str) -> None:
        """Set the SQL text and detect WORK keyword."""
        super().set_sql_text(sql)
        upper_sql = sql.upper()
        if "WORK" in upper_sql:
            self.is_work = True
        # Auto-detect savepoint
        match = _SQL_SAVEPOINT_RE.search(sql)
        if match:
            self.savepoint_name = match.group(1)

    def set_savepoint(self, savepoint: str) -> None:
        """Set savepoint name for ROLLBACK TO SAVEPOINT."""
        self.savepoint_name = savepoint

    def get_structured_output(self) -> SQLStatementInfo:
        """Get structured output for transaction control."""
        result = SQLStatementInfo()
        result.query = self.sql_text
        return result

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = super().to_dict()
        result.update({"savepoint_name": self.savepoint_name, "is_work": self.is_work})
        return result


def parse_exec_sql(sql_text: str, location: SourceLocation) -> ExecSQLStatement:
    """Factory function to parse EXEC SQL and return the appropriate statement type.

    Args:
        sql_text: The SQL text (without EXEC SQL and END-EXEC)
        location: Source location for the statement

    Returns:
        Appropriate ExecSQLStatement subclass based on the SQL type
    """
    normalized = " ".join(sql_text.strip().split())
    upper_sql = normalized.upper()

    # Determine statement type and create appropriate node
    if upper_sql.startswith("DECLARE"):
        if "CURSOR" in upper_sql:
            declare_stmt = DeclareCursorStatement(location)
            declare_stmt.set_sql_text(sql_text)
            # Extract cursor name
            match = _SQL_DECLARE_CURSOR_RE.search(sql_text)
            if match:
                declare_stmt.cursor_name = match.group(1)
            # Extract SELECT statement
            match = _SQL_FOR_SELECT_RE.search(sql_text)
            if match:
                declare_stmt.set_select_statement(match.group(1))
            # Extract cursor options
            if "WITH HOLD" in upper_sql:
                declare_stmt.add_cursor_option("WITH HOLD")
            if "FOR UPDATE" in upper_sql:
                declare_stmt.add_cursor_option("FOR UPDATE")
            return declare_stmt

        if "TABLE" in upper_sql:
            # DCLGEN-generated DECLARE TABLE statement
            table_stmt = DeclareTableStatement(location)
            table_stmt.set_sql_text(sql_text)
            return table_stmt

    if upper_sql.startswith("FETCH"):
        fetch_stmt = FetchStatement(location)
        fetch_stmt.set_sql_text(sql_text)
        # Extract direction
        for direction in ["NEXT", "PRIOR", "FIRST", "LAST"]:
            if direction in upper_sql:
                fetch_stmt.set_fetch_direction(direction)
                break
        return fetch_stmt

    elif upper_sql.startswith("PREPARE") or upper_sql.startswith("EXECUTE"):
        dynamic_stmt = DynamicSQLStatement(location)
        dynamic_stmt.set_sql_text(sql_text)
        # Extract USING variables
        match = _SQL_USING_VARS_RE.search(sql_text)
        if match:
            using_clause = match.group(1)
            vars_matches = _SQL_HOST_VAR_RE.findall(using_clause)
            for var in vars_matches:
                dynamic_stmt.add_using_variable(var)
        return dynamic_stmt

    elif upper_sql.startswith("COMMIT") or upper_sql.startswith("ROLLBACK"):
        txn_stmt = TransactionControlStatement(location)
        txn_stmt.set_sql_text(sql_text)
        if "WORK" in upper_sql:
            txn_stmt.is_work = True
        # Check for savepoint
        match = _SQL_SAVEPOINT_RE.search(sql_text)
        if match:
            txn_stmt.set_savepoint(match.group(1))
        return txn_stmt

    else:
        # Default to generic ExecSQLStatement
        generic_stmt = ExecSQLStatement(location)
        generic_stmt.set_sql_text(sql_text)
        return generic_stmt


__all__ = [
    "DB2ColumnDefinition",
    "SQLStatementInfo",
    "SQLStatementType",
    "ExecSQLStatement",
    "DeclareCursorStatement",
    "DeclareTableStatement",
    "FetchStatement",
    "DynamicSQLStatement",
    "TransactionControlStatement",
    "db2_type_to_cobol_pic",
    "db2_type_to_cobol_usage",
    "parse_exec_sql",
]
