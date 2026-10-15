"""SORT and MERGE statement parsers implementing IStatementParser."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import MergeStatement, SortStatement
from ._utils import (
    consume_optional_qualifiers,
    get_parse_context,
    is_statement_boundary,
    looks_dedented_relative_to,
    looks_like_paragraph_boundary,
    matches_keyword,
    skip_whitespace,
    starts_negative_handler_phrase,
    token_column,
    token_location,
    warn_paragraph_boundary_swallowed,
)
from ._utils import token_value_upper as _val


def _parse_keys(
    ts: ITokenStream, reference_column: int | None = None
) -> list[dict[str, str]]:
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
            _skip_word(ts, "IS")
            continue

        if val in ("ASCENDING", "DESCENDING"):
            order = val
            ts.consume()
            skip_whitespace(ts)

            # Optional KEY keyword, and the ``KEY IS`` spelling GnuCOBOL
            # accepts: before 2026-10-14 the IS ended the key list and every
            # key was dropped without a diagnostic.
            if _skip_word(ts, "KEY"):
                _skip_word(ts, "IS")

            # Collect field names
            while not ts.is_empty():
                f = ts.peek()
                if not f:
                    break
                if f.type == TokenType.COMMA:
                    # A comma between key fields (`KEY a, b`) is a
                    # separator, not a terminator -- skip it and keep
                    # collecting fields.
                    ts.consume()
                    skip_whitespace(ts)
                    continue
                fv = _val(f)
                if f.type == TokenType.PERIOD or fv in (
                    "ASCENDING",
                    "DESCENDING",
                    "ON",
                    "WITH",
                    "COLLATING",
                    "SEQUENCE",
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
                    # A missing period followed by what looks like the next
                    # paragraph/section header (H9): stop instead of folding
                    # it into the KEY field list. Disambiguated by
                    # indentation (Area A vs Area B) so a key field that
                    # merely wraps onto its own continuation line --
                    # legitimate for any field in the list, not just the
                    # first -- isn't misread as a boundary and dropped.
                    if looks_like_paragraph_boundary(ts) and looks_dedented_relative_to(
                        ts, reference_column
                    ):
                        warn_paragraph_boundary_swallowed(ts)
                        break
                    ts.consume()
                    # ``KEY K OF SR``: keep the qualifier (it was dropped,
                    # and ended the KEY list, losing every later key).
                    field = consume_optional_qualifiers(ts, f.value or "")
                    keys.append({"field": field, "order": order})
                else:
                    break
                skip_whitespace(ts)
        else:
            break

    return keys


def _skip_word(ts: ITokenStream, word: str) -> bool:
    """Consume *word* (and trailing layout) when it is next; True if it was."""
    token = ts.peek()
    if token is None or _val(token) != word:
        return False
    ts.consume()
    skip_whitespace(ts)
    return True


def _parse_collating_sequence(ts: ITokenStream) -> str | None:
    """Parse ``[COLLATING] SEQUENCE [IS] alphabet-name`` from either of its
    first two words. COLLATING is optional in IBM Enterprise COBOL; before
    2026-10-14 a bare ``SEQUENCE NATIVE`` was folded into the key list."""
    _skip_word(ts, "COLLATING")
    _skip_word(ts, "SEQUENCE")
    _skip_word(ts, "IS")
    n = ts.peek()
    if n and n.type != TokenType.PERIOD:
        ts.consume()
        skip_whitespace(ts)
        return n.value
    return None


def _warn_no_keys(ts: ITokenStream, verb: str, location: Any) -> None:
    """Warn that a file SORT/MERGE collected no keys: a key list the parser
    could not read is otherwise indistinguishable from an empty one."""
    line = getattr(location, "line", None)
    where = f" at line {line}" if line else ""
    context = get_parse_context(ts)
    host = getattr(context, "host", None) if context else None
    add_warning = getattr(host, "add_warning", None)
    if callable(add_warning):
        add_warning(
            f"{verb} statement{where} has no ON ASCENDING/DESCENDING KEY "
            "phrase that could be read: no sort keys were recorded"
        )


def _parse_file_list(
    ts: ITokenStream, reference_column: int | None = None
) -> list[str]:
    """Parse a list of file names."""
    files: list[str] = []
    while not ts.is_empty():
        token = ts.peek()
        if not token:
            break
        if token.type == TokenType.COMMA:
            # A comma between file names (`USING a, b`) is a separator, not
            # a terminator -- skip it and keep collecting files.
            ts.consume()
            skip_whitespace(ts)
            continue
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
        # A missing period followed by what looks like the next
        # paragraph/section header (H9): stop instead of folding it into
        # the file-name list. Disambiguated by indentation (Area A vs
        # Area B) so a file name that merely wraps onto its own
        # continuation line -- legitimate for any file in the list, not
        # just the first -- isn't misread as a boundary and dropped.
        if (
            token.type == TokenType.IDENTIFIER
            and looks_like_paragraph_boundary(ts)
            and looks_dedented_relative_to(ts, reference_column)
        ):
            warn_paragraph_boundary_swallowed(ts)
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
        start_column = token_column(start)
        skip_whitespace(token_stream)

        # File name
        token = token_stream.peek()
        if token and token.type not in (TokenType.PERIOD, None):
            token_stream.consume()
            stmt.set_file_name(token.value or "")
        skip_whitespace(token_stream)

        # Parse keys
        keys = _parse_keys(token_stream, start_column)
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
            if starts_negative_handler_phrase(token_stream):
                # An enclosing handler's ``NOT AT END`` / ``NOT INVALID
                # KEY`` / ``NOT ON EXCEPTION``: not a clause of this verb.
                break
            if (
                token.type == TokenType.IDENTIFIER
                and looks_like_paragraph_boundary(token_stream)
                and looks_dedented_relative_to(token_stream, start_column)
            ):
                # A missing period on this SORT followed by what looks like
                # the next paragraph/section header (H9): stop instead of
                # falling through to the generic-clause-token consume below.
                warn_paragraph_boundary_swallowed(token_stream)
                break
            elif val in ("WITH", "DUPLICATES"):
                # [WITH] DUPLICATES [IN ORDER]: WITH is optional.
                _skip_word(token_stream, "WITH")
                if _skip_word(token_stream, "DUPLICATES"):
                    stmt.duplicates_in_order = True
                    _skip_word(token_stream, "IN")
                    _skip_word(token_stream, "ORDER")
            elif val in ("COLLATING", "SEQUENCE"):
                stmt.collating_sequence = _parse_collating_sequence(token_stream)
            elif val == "USING":
                token_stream.consume()
                skip_whitespace(token_stream)
                for f in _parse_file_list(token_stream, start_column):
                    stmt.add_using_file(f)
            elif val == "GIVING":
                token_stream.consume()
                skip_whitespace(token_stream)
                for f in _parse_file_list(token_stream, start_column):
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

        if not stmt.keys and (
            stmt.using_files
            or stmt.giving_files
            or stmt.input_procedure
            or stmt.output_procedure
        ):
            # A file SORT always has a key; a table SORT may omit it.
            _warn_no_keys(token_stream, "SORT", stmt.location)

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
        start_column = token_column(start)
        skip_whitespace(token_stream)

        # File name
        token = token_stream.peek()
        if token and token.type not in (TokenType.PERIOD, None):
            token_stream.consume()
            stmt.set_file_name(token.value or "")
        skip_whitespace(token_stream)

        # Parse keys
        keys = _parse_keys(token_stream, start_column)
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
            if starts_negative_handler_phrase(token_stream):
                # An enclosing handler's ``NOT AT END`` / ``NOT INVALID
                # KEY`` / ``NOT ON EXCEPTION``: not a clause of this verb.
                break
            if (
                token.type == TokenType.IDENTIFIER
                and looks_like_paragraph_boundary(token_stream)
                and looks_dedented_relative_to(token_stream, start_column)
            ):
                # A missing period on this MERGE followed by what looks like
                # the next paragraph/section header (H9): stop instead of
                # falling through to the generic-clause-token consume below.
                warn_paragraph_boundary_swallowed(token_stream)
                break
            elif val in ("COLLATING", "SEQUENCE"):
                stmt.collating_sequence = _parse_collating_sequence(token_stream)
            elif val == "USING":
                token_stream.consume()
                skip_whitespace(token_stream)
                for f in _parse_file_list(token_stream, start_column):
                    stmt.add_using_file(f)
            elif val == "GIVING":
                token_stream.consume()
                skip_whitespace(token_stream)
                for f in _parse_file_list(token_stream, start_column):
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

        if not stmt.keys:
            _warn_no_keys(token_stream, "MERGE", stmt.location)
        return stmt
