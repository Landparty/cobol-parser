"""SORT and MERGE statement parsers implementing IStatementParser."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import MergeStatement, SortStatement
from ._utils import (
    is_statement_boundary,
    matches_keyword,
    skip_whitespace,
    token_location,
)
from ._utils import token_value_upper as _val


def _parse_keys(ts: ITokenStream) -> list[dict[str, str]]:
    """Parse ON ASCENDING/DESCENDING KEY field-1 [field-2 ...] clauses."""
    keys: list[dict[str, str]] = []
    while not ts.is_empty():
        token = ts.peek()
        if not token:
            break
        val = _val(token)

        if val == "ON":
            ts.consume()
            skip_whitespace(ts)
            continue

        if val == "KEY":
            ts.consume()
            skip_whitespace(ts)
            continue

        if val in ("ASCENDING", "DESCENDING"):
            order = val
            ts.consume()
            skip_whitespace(ts)

            # Optional KEY keyword
            nxt = ts.peek()
            if nxt and _val(nxt) == "KEY":
                ts.consume()
                skip_whitespace(ts)

            # Collect field names
            while not ts.is_empty():
                f = ts.peek()
                if not f:
                    break
                fv = _val(f)
                if f.type == TokenType.PERIOD or fv in (
                    "ASCENDING",
                    "DESCENDING",
                    "ON",
                    "WITH",
                    "COLLATING",
                    "INPUT",
                    "OUTPUT",
                    "USING",
                    "GIVING",
                    "DUPLICATES",
                ):
                    break
                if f.type == TokenType.IDENTIFIER:
                    # A following statement's verb that lexes as a plain
                    # IDENTIFIER (e.g. PURGE/RAISE/RESUME have no dedicated
                    # TokenType) must not be folded into the KEY field list.
                    if is_statement_boundary(f):
                        break
                    ts.consume()
                    keys.append({"field": f.value or "", "order": order})
                else:
                    break
                skip_whitespace(ts)
        else:
            break

    return keys


def _parse_file_list(ts: ITokenStream) -> list[str]:
    """Parse a list of file names."""
    files: list[str] = []
    while not ts.is_empty():
        token = ts.peek()
        if not token:
            break
        val = _val(token)
        if token.type == TokenType.PERIOD or val in (
            "GIVING",
            "OUTPUT",
            "INPUT",
            "WITH",
            "COLLATING",
        ):
            break
        if token.type == TokenType.IDENTIFIER and is_statement_boundary(token):
            # A following statement's verb that lexes as a plain IDENTIFIER
            # (e.g. PURGE/RAISE/RESUME have no dedicated TokenType) must not
            # be folded into the file-name list.
            break
        if token.type in (TokenType.IDENTIFIER, TokenType.STRING_LITERAL):
            ts.consume()
            files.append(token.value or "")
        else:
            break
        skip_whitespace(ts)
    return files


class SortStatementParser(IStatementParser):
    """Parser for SORT statements.

    Syntax:
        SORT file-name
            ON {ASCENDING|DESCENDING} [KEY] field-1 [field-2] ...
            [WITH DUPLICATES IN ORDER]
            [COLLATING SEQUENCE IS alphabet-name]
            {USING file-1 [file-2] | INPUT PROCEDURE IS para-1 [THRU para-2]}
            {GIVING file-1 [file-2] | OUTPUT PROCEDURE IS para-1 [THRU para-2]}
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.SORT, "SORT")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> SortStatement:
        start = token_stream.consume()
        stmt = SortStatement(token_location(start))
        skip_whitespace(token_stream)

        # File name
        token = token_stream.peek()
        if token and token.type not in (TokenType.PERIOD, None):
            token_stream.consume()
            stmt.set_file_name(token.value or "")
        skip_whitespace(token_stream)

        # Parse keys
        keys = _parse_keys(token_stream)
        for k in keys:
            stmt.add_key(k["field"], k["order"])

        # Parse remaining clauses
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            val = _val(token)

            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            if is_statement_boundary(token):
                # No period before the next statement: stop rather than
                # swallow it as a bogus SORT clause token.
                break
            elif val == "WITH":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "DUPLICATES":
                    token_stream.consume()
                    stmt.duplicates_in_order = True
                    skip_whitespace(token_stream)
                    # Skip "IN ORDER"
                    for kw in ("IN", "ORDER"):
                        n = token_stream.peek()
                        if n and _val(n) == kw:
                            token_stream.consume()
                            skip_whitespace(token_stream)
            elif val == "COLLATING":
                token_stream.consume()
                skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and _val(n) == "SEQUENCE":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and _val(n) == "IS":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and n.type != TokenType.PERIOD:
                    token_stream.consume()
                    stmt.collating_sequence = n.value
            elif val == "USING":
                token_stream.consume()
                skip_whitespace(token_stream)
                for f in _parse_file_list(token_stream):
                    stmt.add_using_file(f)
            elif val == "GIVING":
                token_stream.consume()
                skip_whitespace(token_stream)
                for f in _parse_file_list(token_stream):
                    stmt.add_giving_file(f)
            elif val == "INPUT":
                token_stream.consume()
                skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and _val(n) == "PROCEDURE":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and _val(n) == "IS":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                n = token_stream.peek()
                thru = None
                if n and n.type == TokenType.IDENTIFIER:
                    proc_name = n.value or ""
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    n = token_stream.peek()
                    if n and _val(n) in ("THRU", "THROUGH"):
                        token_stream.consume()
                        skip_whitespace(token_stream)
                        n = token_stream.peek()
                        if n and n.type == TokenType.IDENTIFIER:
                            thru = n.value
                            token_stream.consume()
                            skip_whitespace(token_stream)
                    stmt.set_input_procedure(proc_name, thru)
            elif val == "OUTPUT":
                token_stream.consume()
                skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and _val(n) == "PROCEDURE":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and _val(n) == "IS":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                n = token_stream.peek()
                thru = None
                if n and n.type == TokenType.IDENTIFIER:
                    proc_name = n.value or ""
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    n = token_stream.peek()
                    if n and _val(n) in ("THRU", "THROUGH"):
                        token_stream.consume()
                        skip_whitespace(token_stream)
                        n = token_stream.peek()
                        if n and n.type == TokenType.IDENTIFIER:
                            thru = n.value
                            token_stream.consume()
                            skip_whitespace(token_stream)
                    stmt.set_output_procedure(proc_name, thru)
            else:
                token_stream.consume()
                skip_whitespace(token_stream)

        return stmt


class MergeStatementParser(IStatementParser):
    """Parser for MERGE statements.

    Syntax:
        MERGE file-name
            ON {ASCENDING|DESCENDING} [KEY] field-1 [field-2] ...
            [COLLATING SEQUENCE IS alphabet-name]
            USING file-1 file-2 [file-3 ...]
            {GIVING file-1 | OUTPUT PROCEDURE IS para-1 [THRU para-2]}
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.MERGE, "MERGE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> MergeStatement:
        start = token_stream.consume()
        stmt = MergeStatement(token_location(start))
        skip_whitespace(token_stream)

        # File name
        token = token_stream.peek()
        if token and token.type not in (TokenType.PERIOD, None):
            token_stream.consume()
            stmt.set_file_name(token.value or "")
        skip_whitespace(token_stream)

        # Parse keys
        keys = _parse_keys(token_stream)
        for k in keys:
            stmt.add_key(k["field"], k["order"])

        # Parse remaining clauses
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            val = _val(token)

            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            if is_statement_boundary(token):
                # No period before the next statement: stop rather than
                # swallow it as a bogus MERGE clause token.
                break
            elif val == "COLLATING":
                token_stream.consume()
                skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and _val(n) == "SEQUENCE":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and _val(n) == "IS":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and n.type != TokenType.PERIOD:
                    token_stream.consume()
                    stmt.collating_sequence = n.value
            elif val == "USING":
                token_stream.consume()
                skip_whitespace(token_stream)
                for f in _parse_file_list(token_stream):
                    stmt.add_using_file(f)
            elif val == "GIVING":
                token_stream.consume()
                skip_whitespace(token_stream)
                for f in _parse_file_list(token_stream):
                    stmt.add_giving_file(f)
            elif val == "OUTPUT":
                token_stream.consume()
                skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and _val(n) == "PROCEDURE":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and _val(n) == "IS":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                n = token_stream.peek()
                thru = None
                if n and n.type == TokenType.IDENTIFIER:
                    proc_name = n.value or ""
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    n = token_stream.peek()
                    if n and _val(n) in ("THRU", "THROUGH"):
                        token_stream.consume()
                        skip_whitespace(token_stream)
                        n = token_stream.peek()
                        if n and n.type == TokenType.IDENTIFIER:
                            thru = n.value
                            token_stream.consume()
                            skip_whitespace(token_stream)
                    stmt.set_output_procedure(proc_name, thru)
            else:
                token_stream.consume()
                skip_whitespace(token_stream)

        return stmt
