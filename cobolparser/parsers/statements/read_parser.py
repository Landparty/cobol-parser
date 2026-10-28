"""Read statement parser implementing IStatementParser interface."""

from typing import Any

from cobolparser.parsers.statements._utils import (
    bare_end_starts_at_end_clause,
    collect_clause_stmts,
    consume_end_keyword_and_period,
    consume_key_is,
    consume_optional_qualifiers,
    create_statement,
    is_statement_boundary,
    matches_keyword,
    parse_invalid_key_clauses,
    peek_past_noise,
    skip_statement_separators,
    skip_whitespace,
    token_value_upper,
    try_consume_keyword,
)

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import IOReadStatement  # noqa: F401 used via factory


class ReadStatementParser(IStatementParser):
    """Parser for READ statements.

    Supports:
    - READ file-name [NEXT|FIRST|LAST|PREVIOUS|CURRENT]
    - READ file-name [INTO target]
    - READ file-name [KEY IS key-name]
    - READ file-name [WITH [NO] LOCK]
    - READ file-name [AT END stmts] [NOT AT END stmts] [END-READ]
    - READ file-name [INVALID KEY stmts] [NOT INVALID KEY stmts] [END-READ]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.READ, "READ")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> IOReadStatement:
        """Parse a READ statement."""
        stmt, _ = create_statement(token_stream, IOReadStatement)

        skip_whitespace(token_stream)

        # Parse file name (required)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER:
            stmt.set_file_name(token.value)
            token_stream.consume()
        else:
            return stmt

        skip_whitespace(token_stream)

        # Optional access mode: NEXT, FIRST, LAST, PREVIOUS, CURRENT
        token = token_stream.peek()
        if token and token.type == TokenType.NEXT:
            stmt.set_access_mode("NEXT")
            token_stream.consume()
            skip_whitespace(token_stream)
        elif token and token.type == TokenType.IDENTIFIER and token.value:
            val = token.value.upper()
            if val in ("FIRST", "LAST", "PREVIOUS", "CURRENT"):
                stmt.set_access_mode(val)
                token_stream.consume()
                skip_whitespace(token_stream)

        # Optional RECORD keyword (consumed, ignored)
        token = token_stream.peek()
        if token and token.type == TokenType.RECORD:
            token_stream.consume()
            skip_whitespace(token_stream)

        # Optional INTO clause
        token = token_stream.peek()
        if token and token.type == TokenType.INTO:
            token_stream.consume()
            skip_whitespace(token_stream)
            token = token_stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                into_target = token.value or ""
                token_stream.consume()
                into_target = consume_optional_qualifiers(token_stream, into_target)
                stmt.set_into(into_target)
                skip_whitespace(token_stream)

        # Optional KEY IS clause (may be tokenized as KEY_IS or KEY + IS)
        if consume_key_is(token_stream):
            token = token_stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                key_name = token.value or ""
                token_stream.consume()
                key_name = consume_optional_qualifiers(token_stream, key_name)
                stmt.set_key(key_name)
                skip_whitespace(token_stream)

        # Optional WITH [NO] LOCK
        # Lexer emits TokenType.WITH for "WITH" (not IDENTIFIER).
        if try_consume_keyword(token_stream, TokenType.WITH, "WITH"):
            token = token_stream.peek()
            if token and (
                token.type == TokenType.NO
                or (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "NO"
                )
            ):
                token_stream.consume()
                skip_whitespace(token_stream)
                # Consume LOCK
                token = token_stream.peek()
                if token and token.type == TokenType.LOCK:
                    token_stream.consume()
                    skip_whitespace(token_stream)
                stmt.set_lock_mode(with_lock=False, with_nowait=True)
            elif token and token.type == TokenType.LOCK:
                token_stream.consume()
                skip_whitespace(token_stream)
                stmt.set_lock_mode(with_lock=True)
            elif token and token.type == TokenType.WITH_LOCK:
                token_stream.consume()
                skip_whitespace(token_stream)
                stmt.set_lock_mode(with_lock=True)

        # KEY IS may also follow the lock phrase (``READ F WITH LOCK KEY IS
        # K``); the earlier KEY IS check only covers the form before it.
        skip_whitespace(token_stream)
        if consume_key_is(token_stream):
            key_tok = token_stream.peek()
            if (
                key_tok
                and key_tok.type == TokenType.IDENTIFIER
                and not is_statement_boundary(key_tok)
            ):
                token_stream.consume()
                stmt.set_key(
                    consume_optional_qualifiers(token_stream, key_tok.value or "")
                )
                skip_whitespace(token_stream)

        # Optional [AT] END clause -- AT is optional in standard COBOL, and
        # NIST RL110A actually writes ``READ F END GO TO ...``; a separator
        # before the clause (``READ F ; AT END``, SQ203A) is punctuation.
        skip_statement_separators(token_stream)
        token = token_stream.peek()
        if (token and token.type == TokenType.AT) or bare_end_starts_at_end_clause(
            token_stream
        ):
            if token and token.type == TokenType.AT:
                token_stream.consume()
                skip_whitespace(token_stream)
            # Consume END keyword
            token = token_stream.peek()
            if (
                token
                and token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() == "END"
            ):
                token_stream.consume()
                skip_whitespace(token_stream)
            clause_stmts = collect_clause_stmts(
                token_stream, {"END-READ", "NOT", "END_READ"}
            )
            stmt.set_at_end_clause(clause_stmts)

        # Optional NOT AT END clause. The NOT is consumed only when READ's
        # own phrase follows it (``NOT [AT] END`` / ``NOT INVALID KEY``): a
        # READ nested in a CALL's ``ON EXCEPTION`` is followed by the CALL's
        # ``NOT ON EXCEPTION``, and swallowing its NOT lost that handler and
        # the READ itself (the CALL re-read ``ON EXCEPTION`` over it).
        token = token_stream.peek()
        following, following_at = peek_past_noise(token_stream, 1)
        following_val = token_value_upper(following)
        if following_val == "END":
            after_end, _ = peek_past_noise(token_stream, following_at + 1)
            owns_not = token_value_upper(after_end) not in (
                "PROGRAM",
                "FUNCTION",
                "DIVISION",
            )
        else:
            owns_not = following is not None and following.type in (
                TokenType.AT,
                TokenType.INVALID,
            )
        if token and token.type == TokenType.NOT and owns_not:
            token_stream.consume()
            skip_whitespace(token_stream)
            next_tok = token_stream.peek()
            if (next_tok and next_tok.type == TokenType.AT) or (
                bare_end_starts_at_end_clause(token_stream)
            ):
                # NOT [AT] END -- AT optional here as well
                if next_tok and next_tok.type == TokenType.AT:
                    token_stream.consume()
                    skip_whitespace(token_stream)
                # Consume END
                token = token_stream.peek()
                if (
                    token
                    and token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "END"
                ):
                    token_stream.consume()
                    skip_whitespace(token_stream)
                clause_stmts = collect_clause_stmts(
                    token_stream, {"END-READ", "INVALID", "NOT"}
                )
                stmt.set_not_at_end_clause(clause_stmts)
            elif next_tok and next_tok.type == TokenType.INVALID:
                # NOT INVALID KEY — fall through handled below after re-peeking
                # We already consumed NOT, so handle INVALID KEY now
                token_stream.consume()  # INVALID
                skip_whitespace(token_stream)
                token = token_stream.peek()
                if token and token.type == TokenType.KEY:
                    token_stream.consume()
                    skip_whitespace(token_stream)
                clause_stmts = collect_clause_stmts(token_stream, {"END-READ", "NOT"})
                stmt.set_not_invalid_key_clause(clause_stmts)
            # else: consumed NOT unexpectedly, continue

        # Optional INVALID KEY / NOT INVALID KEY clauses (NOT INVALID KEY may
        # already have been parsed above when it followed an AT END clause).
        parse_invalid_key_clauses(token_stream, stmt, "END-READ")

        consume_end_keyword_and_period(token_stream, "END-READ")

        return stmt
