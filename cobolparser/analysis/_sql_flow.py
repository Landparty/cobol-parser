"""Which host variable feeds which DB2 column, and the reverse, for one
EXEC SQL statement.

A small, deliberately shallow reader of the SQL text an ``ExecSQLStatement``
carries. It answers exactly three questions, which is all field lineage
(``field_lineage.py``) needs from SQL:

- which ``table.column`` each host variable is written into
  (``INSERT ... VALUES``, ``UPDATE ... SET``);
- which ``table.column`` expressions each host variable is read from
  (``SELECT ... INTO``, and ``FETCH ... INTO`` through the cursor's
  ``DECLARE ... CURSOR FOR SELECT``);
- which host variables select rows by a column (``WHERE col = :hv``), the
  key uses that ``key_relationships`` is built from.

It is not an SQL parser. Anything it cannot map with certainty -- an
``INSERT`` with no column list, a sub-select in ``FROM``, an unqualified
column in a join -- is either reported in ``caveats`` or marked
``exact=False``; it is never silently guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Aggregate functions: a value that flows through one is a sum/count/...
#: of many rows, not a copy of one.
_AGGREGATES = frozenset({"SUM", "AVG", "COUNT", "MIN", "MAX", "COUNT_BIG"})

#: Words that can appear where a column name could, and never are one.
_SQL_WORDS = frozenset(
    {
        "ALL",
        "AND",
        "AS",
        "ASC",
        "BETWEEN",
        "BY",
        "CASE",
        "CAST",
        "CHAR",
        "CURRENT",
        "DATE",
        "DAY",
        "DAYS",
        "DEC",
        "DECIMAL",
        "DESC",
        "DISTINCT",
        "ELSE",
        "END",
        "ESCAPE",
        "EXISTS",
        "FALSE",
        "FETCH",
        "FIRST",
        "FOR",
        "FROM",
        "HOUR",
        "HOURS",
        "IN",
        "INTEGER",
        "IS",
        "LIKE",
        "MICROSECOND",
        "MINUTE",
        "MINUTES",
        "MONTH",
        "MONTHS",
        "NOT",
        "NULL",
        "ONLY",
        "OR",
        "ROW",
        "ROWS",
        "SECOND",
        "SECONDS",
        "SELECT",
        "SOME",
        "ANY",
        "THEN",
        "TIME",
        "TIMESTAMP",
        "TRUE",
        "USER",
        "VARCHAR",
        "WHEN",
        "WHERE",
        "WITH",
        "YEAR",
        "YEARS",
        "SMALLINT",
        "BIGINT",
        "UR",
        "CS",
        "RS",
        "RR",
    }
)

_CLAUSE_WORDS = (
    "INTO",
    "FROM",
    "WHERE",
    "GROUP BY",
    "HAVING",
    "ORDER BY",
    "FETCH FIRST",
    "FOR UPDATE",
    "FOR READ ONLY",
    "FOR FETCH ONLY",
    "OPTIMIZE FOR",
    "WITH UR",
    "WITH CS",
    "WITH RS",
    "WITH RR",
    "WITH HOLD",
    "UNION",
    "EXCEPT",
    "INTERSECT",
    "VALUES",
    "SET",
)

_HOST_VAR_RE = re.compile(
    r":\s*([A-Z0-9][A-Z0-9\-_]*(?:\.[A-Z0-9][A-Z0-9\-_]*)*)"
    r"(?:\s*(?:INDICATOR\s*)?:\s*[A-Z0-9][A-Z0-9\-_]*)?"
)
_IDENT_RE = re.compile(
    r"(?<![:\w#@$-])([A-Z#@$][A-Z0-9_#@$]*)(?:\s*\.\s*([A-Z#@$][A-Z0-9_#@$]*))?"
    r"(?![\w#@$-])"
)
_STRING_RE = re.compile(r"'(?:[^']|'')*'")
_COMPARE_RE = re.compile(r"(=|<>|\^=|!=|>=|<=|>|<|\bLIKE\b)")


@dataclass(frozen=True)
class SqlColumnFlow:
    """One host variable <-> one column.

    ``direction`` is ``"out"`` when the host variable is written into the
    column (INSERT/UPDATE) and ``"in"`` when the column is read into the
    host variable (SELECT/FETCH INTO). ``kind`` is ``"sql"`` for a bare
    column or host variable, ``"aggregate"`` when the value passes through
    SUM/COUNT/..., and ``"sql-expr"`` for any other expression.
    ``exact`` is False when the column's table could not be pinned down to
    one (an unqualified column in a multi-table query).
    """

    host_var: str
    table: str
    column: str
    direction: str
    kind: str
    exact: bool = True


@dataclass(frozen=True)
class SqlKeyUse:
    """A host variable that selects rows by a column (``WHERE col = :hv``)."""

    host_var: str
    table: str
    column: str
    exact: bool = True


@dataclass
class SqlFlowResult:
    flows: list[SqlColumnFlow] = field(default_factory=list)
    keys: list[SqlKeyUse] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    #: ``DECLARE name CURSOR FOR <select>``: (name, select text).
    declared_cursor: tuple[str, str] | None = None


def host_var_name(raw: str) -> str:
    """``:A.B`` names B OF A, the COBOL qualification of a host variable."""
    parts = [p.strip() for p in raw.upper().lstrip(":").split(".") if p.strip()]
    return " OF ".join(reversed(parts))


def _normalize(sql: str) -> str:
    text = _STRING_RE.sub("''", sql.upper())
    return " ".join(text.split())


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _top_level_positions(text: str) -> list[int]:
    """Indexes of characters that sit outside every parenthesis."""
    positions: list[int] = []
    depth = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            positions.append(i)
    return positions


def _find_clause(text: str, word: str, start: int = 0) -> int:
    """First top-level occurrence of clause keyword *word* at or after
    *start*, or -1."""
    top = set(_top_level_positions(text))
    pattern = re.compile(r"\b" + word.replace(" ", r"\s+") + r"\b")
    for match in pattern.finditer(text, start):
        if match.start() in top:
            return match.start()
    return -1


def _clause_body(text: str, word: str) -> str | None:
    """The text after top-level clause *word* up to the next clause."""
    at = _find_clause(text, word)
    if at < 0:
        return None
    begin = at + len(word)
    end = len(text)
    for other in _CLAUSE_WORDS:
        if other == word:
            continue
        nxt = _find_clause(text, other, begin)
        if 0 <= nxt < end:
            end = nxt
    return text[begin:end].strip()


def _balanced(text: str, open_at: int) -> tuple[str, int]:
    """The text inside the parenthesis opening at *open_at*, and the index
    just past its closing parenthesis."""
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[open_at + 1 : i], i + 1
    return text[open_at + 1 :], len(text)


def _host_vars(expr: str) -> list[str]:
    return [host_var_name(m.group(1)) for m in _HOST_VAR_RE.finditer(expr)]


def _strip_host_vars(expr: str) -> str:
    return _HOST_VAR_RE.sub(" ", expr)


def _expr_kind(expr: str) -> str:
    stripped = expr.strip()
    for name in _AGGREGATES:
        if re.search(r"\b" + name + r"\s*\(", stripped):
            return "aggregate"
    if re.fullmatch(r"(?:[A-Z#@$][\w#@$]*\s*\.\s*)?[A-Z#@$][\w#@$]*", stripped):
        return "sql"
    if re.fullmatch(r":\s*[A-Z0-9][\w\-.]*", stripped):
        return "sql"
    return "sql-expr"


def _columns_in(expr: str) -> list[tuple[str | None, str]]:
    """(qualifier, column) pairs an expression reads, function names and
    SQL keywords excluded."""
    text = _strip_host_vars(expr)
    # A CASE arm's WHEN condition picks which value flows; it is not a value
    # itself (``CASE WHEN T.TRAN_TYPE = 'CR' THEN T.AMOUNT END`` reads only
    # AMOUNT into the result).
    text = re.sub(r"\bWHEN\b.*?\bTHEN\b", " ", text)
    out: list[tuple[str | None, str]] = []
    for match in _IDENT_RE.finditer(text):
        first, second = match.group(1), match.group(2)
        rest = text[match.end() :].lstrip()
        if rest.startswith("("):
            continue  # a function call
        if second is None:
            if first in _SQL_WORDS or first in _AGGREGATES:
                continue
            pair: tuple[str | None, str] = (None, first)
        else:
            pair = (first, second)
        if pair not in out:
            out.append(pair)
    return out


def _skipped_correlation(piece: str) -> str | None:
    """The correlation name after a parenthesised FROM item (a sub-select,
    ``TABLE(...)`` or ``FINAL TABLE (...)``): ``(...) AS X`` -> ``X``."""
    _inner, after = _balanced(piece, piece.index("("))
    words = piece[after:].split()
    if words and words[0] == "AS":
        words = words[1:]
    if (
        words
        and words[0] not in _SQL_WORDS
        and re.fullmatch(r"[A-Z0-9_#@$-]+", words[0])
    ):
        return words[0]
    return None


def _from_tables(from_body: str) -> tuple[dict[str, str], list[str], list[str]]:
    """alias -> table, the table list in order, and caveats.

    A FROM item that is not traced (a sub-select, a table function, a
    data-change reference) maps its correlation name to ``""``, so a column
    qualified by it is not mistaken for a column of a table of that name.
    """
    caveats: list[str] = []
    aliases: dict[str, str] = {}
    tables: list[str] = []
    body = re.sub(
        r"\b(?:INNER|LEFT|RIGHT|FULL|CROSS)?\s*(?:OUTER\s+)?JOIN\b", ",", from_body
    )
    for piece in _split_top_level(body):
        piece = re.split(r"\bON\b", piece, maxsplit=1)[0].strip()
        if not piece:
            continue
        skipped = None
        if piece.startswith("("):
            skipped = "a sub-select in FROM is not traced"
        elif re.match(r"(?:FINAL|NEW|OLD)\s+TABLE\s*\(", piece):
            # SELECT ... FROM FINAL TABLE (INSERT ...): the rows come from
            # the data-change statement inside, not from a table named FINAL.
            skipped = "a data-change table reference in FROM is not traced"
        elif re.match(r"TABLE\s*\(", piece):
            skipped = "a table function in FROM is not traced"
        if skipped is not None:
            caveats.append(skipped)
            name = _skipped_correlation(piece)
            # Even with no correlation name the item's columns are in scope,
            # so an unqualified column may come from it: "" marks that.
            aliases[name or ""] = ""
            continue
        # ``BANK . ACCOUNT`` is one qualified name: join it before splitting
        # the piece into table and correlation name.
        words = re.sub(r"\s*\.\s*", ".", piece).replace(" AS ", " ").split()
        table = words[0]
        tables.append(table)
        aliases[table] = table
        aliases[table.split(".")[-1]] = table
        if len(words) > 1 and words[1] not in _SQL_WORDS:
            aliases[words[1]] = table
    return aliases, tables, caveats


def _resolve_column(
    qualifier: str | None,
    column: str,
    aliases: dict[str, str],
    tables: list[str],
) -> list[tuple[str, str, bool]]:
    if qualifier is not None:
        table = aliases.get(qualifier)
        if table:
            return [(table, column, True)]
        # An untraced FROM item's correlation name (""), or a qualifier that
        # names no FROM item: no table of that name is invented.
        return []
    untraced = "" in aliases.values()
    if len(tables) == 1:
        return [(tables[0], column, not untraced)]
    return [(table, column, False) for table in tables]


def _where_keys(
    where: str, aliases: dict[str, str], tables: list[str]
) -> list[SqlKeyUse]:
    keys: list[SqlKeyUse] = []
    for conjunct in re.split(r"\bAND\b|\bOR\b", where):
        parts = _COMPARE_RE.split(conjunct, maxsplit=1)
        if len(parts) != 3:
            continue
        left, _op, right = parts
        for col_side, hv_side in ((left, right), (right, left)):
            hvs = _host_vars(hv_side)
            cols = _columns_in(col_side)
            if len(hvs) != 1 or len(cols) != 1 or _host_vars(col_side):
                continue
            qualifier, column = cols[0]
            for table, col, exact in _resolve_column(
                qualifier, column, aliases, tables
            ):
                keys.append(SqlKeyUse(hvs[0], table, col, exact))
    return keys


def _select_flows(
    select_body: str,
    into: list[str],
    from_body: str | None,
    where: str | None,
    result: SqlFlowResult,
) -> None:
    aliases: dict[str, str] = {}
    tables: list[str] = []
    if from_body is not None:
        aliases, tables, caveats = _from_tables(from_body)
        result.caveats.extend(caveats)
    items = _split_top_level(re.sub(r"^\s*DISTINCT\b", "", select_body))
    if len(items) != len(into):
        result.caveats.append(
            f"SELECT list has {len(items)} item(s) but INTO names {len(into)} "
            "host variable(s); the pairing is not traced"
        )
        return
    for item, host_var in zip(items, into, strict=True):
        expr = re.split(r"\s+AS\s+", item)[0]
        kind = _expr_kind(expr)
        if expr.strip() == "*":
            result.caveats.append("SELECT * INTO is not traced column by column")
            continue
        for qualifier, column in _columns_in(expr):
            if qualifier is not None and qualifier not in aliases:
                result.caveats.append(
                    f"{qualifier}.{column} names no table or correlation name "
                    "in FROM; not traced"
                )
            for table, col, exact in _resolve_column(
                qualifier, column, aliases, tables
            ):
                result.flows.append(
                    SqlColumnFlow(host_var, table, col, "in", kind, exact)
                )
    if where:
        result.keys.extend(_where_keys(where, aliases, tables))


def analyze_sql(sql_text: str, cursors: dict[str, str] | None = None) -> SqlFlowResult:
    """Map host variables to columns for one EXEC SQL statement.

    Args:
        sql_text: The statement text between ``EXEC SQL`` and ``END-EXEC``.
        cursors: cursor name -> its ``SELECT`` text, from the
            ``DECLARE CURSOR`` statements already seen; needed for ``FETCH``.
    """
    result = SqlFlowResult()
    text = _normalize(sql_text)
    if not text:
        return result
    verb = text.split()[0]
    cursors = cursors or {}

    if verb == "DECLARE":
        match = re.match(
            r"DECLARE\s+([A-Z0-9_#@$-]+)\s+.*?\bCURSOR\b.*?\bFOR\b\s+(.*)$", text
        )
        if match:
            name, select = match.group(1), match.group(2)
            result.declared_cursor = (name, select)
            where = _clause_body(select, "WHERE")
            if where:
                from_body = _clause_body(select, "FROM") or ""
                aliases, tables, _ = _from_tables(from_body)
                result.keys.extend(_where_keys(where, aliases, tables))
        return result

    if verb == "INSERT":
        match = re.match(
            r"INSERT\s+INTO\s+([A-Z0-9_#@$.]+(?:\s*\.\s*[A-Z0-9_#@$]+)?)\s*", text
        )
        if not match:
            result.caveats.append("INSERT target not recognised; not traced")
            return result
        table = re.sub(r"\s*\.\s*", ".", match.group(1))
        rest = text[match.end() :]
        columns: list[str] | None = None
        if rest.startswith("("):
            inner, after = _balanced(rest, 0)
            columns = [c.strip() for c in _split_top_level(inner)]
            rest = rest[after:].strip()
        if not rest.startswith("VALUES"):
            result.caveats.append(
                f"INSERT INTO {table} from a sub-select is not traced"
            )
            return result
        open_at = rest.find("(")
        if open_at < 0:
            return result
        values_inner, _ = _balanced(rest, open_at)
        values = _split_top_level(values_inner)
        if columns is None:
            result.caveats.append(
                f"INSERT INTO {table} has no column list; host variables are "
                "mapped to column positions (#1, #2, ...)"
            )
            columns = [f"#{i}" for i in range(1, len(values) + 1)]
        if len(columns) != len(values):
            result.caveats.append(
                f"INSERT INTO {table}: {len(columns)} column(s) for "
                f"{len(values)} value(s); not traced"
            )
            return result
        for column, value in zip(columns, values, strict=True):
            kind = _expr_kind(value)
            for host_var in _host_vars(value):
                result.flows.append(SqlColumnFlow(host_var, table, column, "out", kind))
        return result

    if verb == "UPDATE":
        match = re.match(
            r"UPDATE\s+([A-Z0-9_#@$]+(?:\s*\.\s*[A-Z0-9_#@$]+)?)(?:\s+(?:AS\s+)?([A-Z0-9_#@$]+))?\s+SET\b",
            text,
        )
        if not match:
            result.caveats.append("UPDATE target not recognised; not traced")
            return result
        table = re.sub(r"\s*\.\s*", ".", match.group(1))
        aliases = {table: table, table.split(".")[-1]: table}
        if match.group(2):
            aliases[match.group(2)] = table
        set_body = _clause_body(text, "SET") or ""
        for assignment in _split_top_level(set_body):
            if "=" not in assignment:
                continue
            left, right = assignment.split("=", 1)
            left = left.strip()
            if left.startswith("("):
                result.caveats.append("a row-value SET (a, b) = (...) is not traced")
                continue
            column = left.split(".")[-1].strip()
            kind = _expr_kind(right)
            for host_var in _host_vars(right):
                result.flows.append(SqlColumnFlow(host_var, table, column, "out", kind))
        where = _clause_body(text, "WHERE")
        if where:
            result.keys.extend(_where_keys(where, aliases, [table]))
        return result

    if verb == "DELETE":
        match = re.match(
            r"DELETE\s+FROM\s+([A-Z0-9_#@$]+(?:\s*\.\s*[A-Z0-9_#@$]+)?)", text
        )
        where = _clause_body(text, "WHERE")
        if match and where:
            table = re.sub(r"\s*\.\s*", ".", match.group(1))
            aliases = {table: table, table.split(".")[-1]: table}
            result.keys.extend(_where_keys(where, aliases, [table]))
        return result

    if verb in ("SELECT", "WITH") and _find_clause(text, "INTO") >= 0:
        if verb == "WITH":
            result.caveats.append("a common table expression is not traced")
            return result
        into_body = _clause_body(text, "INTO") or ""
        into = _host_vars(into_body)
        select_body = text[len("SELECT") : _find_clause(text, "INTO")]
        _select_flows(
            select_body,
            into,
            _clause_body(text, "FROM"),
            _clause_body(text, "WHERE"),
            result,
        )
        return result

    if verb == "FETCH":
        head = text.split(" INTO ", 1)[0]
        match = re.search(r"\bFROM\s+([A-Z0-9_#@$-]+)", head) or re.search(
            r"FETCH\s+(?:NEXT\s+|PRIOR\s+|FIRST\s+|LAST\s+)?([A-Z0-9_#@$-]+)", head
        )
        fetch_into = _clause_body(text, "INTO")
        if not match or fetch_into is None:
            return result
        cursor = match.group(1)
        select = cursors.get(cursor)
        if select is None:
            result.caveats.append(
                f"FETCH {cursor}: no DECLARE CURSOR seen; INTO host variables "
                "are not traced to columns"
            )
            return result
        into = _host_vars(fetch_into)
        select_body = select[len("SELECT") :]
        cut = _find_clause(select_body, "FROM")
        if cut >= 0:
            select_body = select_body[:cut]
        # The cursor's WHERE keys were reported at its DECLARE.
        _select_flows(select_body, into, _clause_body(select, "FROM"), None, result)
        return result

    if verb == "MERGE":
        result.caveats.append("MERGE is not traced")
    return result
