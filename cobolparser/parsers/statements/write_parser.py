"""Write statement parser implementing IStatementParser interface."""

from typing import Any

from cobolparser.parsers.statements._utils import (
    collect_clause_stmts,
    consume_end_keyword_and_period,
    create_statement,
    matches_keyword,
    parse_invalid_key_clauses,
    skip_whitespace,
    try_consume_keyword,
)

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import IOWriteStatement


class WriteStatementParser(IStatementParser):
    """Parser for WRITE statements using IStatementParser interface.

    Supports:
    - WRITE record-name
    - WRITE record-name FROM source-data
    - WRITE record-name [FROM source] [BEFORE/AFTER [ADVANCING] [n] [LINES|LINE|PAGE]]
    - WRITE record-name [FROM source] [BEFORE/AFTER [ADVANCING] identifier [LINES|LINE]]
    - WRITE record-name [FROM source] [BEFORE/AFTER [ADVANCING] mnemonic-name]
      (a SPECIAL-NAMES mnemonic-name, e.g. `AFTER ADVANCING TOP-OF-PAGE`)
    - WRITE record-name [AT END-OF-PAGE stmts] [NOT AT END-OF-PAGE stmts] [END-WRITE]
      (sequential/line-sequential files; format 1)
    - WRITE record-name [INVALID KEY stmts] [NOT INVALID KEY stmts] [END-WRITE]
      (indexed/relative files; format 2 -- mutually exclusive with END-OF-PAGE
      per the standard grammar, but both branches are attempted here since
      nothing upstream tells the parser which file organization is in play)
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.WRITE, "WRITE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> IOWriteStatement:
        """Parse a WRITE statement."""
        stmt, _ = create_statement(token_stream, IOWriteStatement)

        # Skip whitespace
        skip_whitespace(token_stream)

        # Parse record name (required)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER:
            record_name = token.value
            stmt.set_record_name(record_name)
            token_stream.consume()
        else:
            # Missing record name - just return what we have
            return stmt

        skip_whitespace(token_stream)

        # Check for FROM clause: lexer emits TokenType.FROM for "FROM"
        if try_consume_keyword(token_stream, TokenType.FROM, "FROM"):
            # Parse FROM source: an identifier (the common case) or a
            # literal -- `WRITE rec FROM 'some text'` is a real IBM/
            # GnuCOBOL extension seen in production batch programs (e.g.
            # writing a fixed exception-message record).
            token = token_stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                source = token.value
                stmt.set_from(source)
                token_stream.consume()
            elif token and token.type == TokenType.STRING_LITERAL:
                stmt.set_from(f'"{token.value or ""}"')
                token_stream.consume()

            skip_whitespace(token_stream)

        # Check for ADVANCING clause: BEFORE/AFTER ADVANCING [n] [LINES|LINE|PAGE]
        # Lexer emits TokenType.BEFORE / TokenType.AFTER for these keywords.
        token = token_stream.peek()
        is_before_after = token and (
            token.type in (TokenType.BEFORE, TokenType.AFTER)
            or (
                token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() in ("BEFORE", "AFTER")
            )
        )
        if is_before_after and token is not None:
            advancing_mode = (token.value or "").upper()
            token_stream.consume()
            skip_whitespace(token_stream)

            # ADVANCING itself is optional in the standard grammar:
            # `WRITE rec AFTER 1`, `AFTER 1 LINE`, and `AFTER PAGE` are all
            # legal without it, so its absence must not drop the clause.
            try_consume_keyword(token_stream, TokenType.ADVANCING, "ADVANCING")
            stmt.advancing_mode = advancing_mode

            # Optional count (numeric literal or level number). Store it —
            # it was historically consumed and dropped, so `WRITE ... AFTER
            # ADVANCING 2 LINES` lost the "2 LINES".
            advancing_count: int | None = None
            advancing_identifier: str | None = None
            advancing_mnemonic: str | None = None
            token = token_stream.peek()
            if token and token.type in (
                TokenType.LEVEL_NUMBER,
                TokenType.NUMERIC_LITERAL,
            ):
                try:
                    advancing_count = int(token.value) if token.value else None
                except ValueError:
                    advancing_count = None
                token_stream.consume()
                skip_whitespace(token_stream)
            elif (
                token
                and token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() != "PAGE"
            ):
                # `{identifier-1 | mnemonic-name-1}` per the standard
                # grammar: a data-name holding a line count (followed by
                # LINE/LINES, e.g. `ADVANCING WS-LINE-COUNT LINES`) or a
                # SPECIAL-NAMES mnemonic-name for a printer channel, which
                # takes no LINE/LINES suffix (e.g. `ADVANCING TOP-OF-PAGE`,
                # a mnemonic defined via `SPECIAL-NAMES. C01 IS TOP-OF-PAGE`).
                name = token.value
                token_stream.consume()
                skip_whitespace(token_stream)
                next_token = token_stream.peek()
                if next_token and next_token.type in (
                    TokenType.LINES,
                    TokenType.LINE,
                ):
                    advancing_identifier = name
                else:
                    advancing_mnemonic = name

            # Optional LINES / LINE / PAGE
            # Lexer emits TokenType.LINES for "LINES" and TokenType.LINE for "LINE";
            # PAGE has no dedicated token type so it arrives as IDENTIFIER.
            advancing_page = False
            token = token_stream.peek()
            if token and (
                token.type in (TokenType.LINES, TokenType.LINE)
                or (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "PAGE"
                )
            ):
                advancing_page = bool(token.value) and token.value.upper() == "PAGE"
                token_stream.consume()
                skip_whitespace(token_stream)

            stmt.set_advancing(
                advancing_mode,
                lines=advancing_count,
                page=advancing_page,
                identifier=advancing_identifier,
                mnemonic=advancing_mnemonic,
            )

        # Optional AT END-OF-PAGE clause (sequential/line-sequential files;
        # format 1). Mirrors READ's AT END / NOT AT END pattern above, but
        # matches TokenType.END_OF_PAGE directly since the lexer gives
        # "END-OF-PAGE"/"EOP" a dedicated token type rather than lexing them
        # as a plain "END" IDENTIFIER the way READ's "AT END" does.
        skip_whitespace(token_stream)
        token = token_stream.peek()
        if token and token.type == TokenType.AT:
            token_stream.consume()
            skip_whitespace(token_stream)
            token = token_stream.peek()
            if token and token.type == TokenType.END_OF_PAGE:
                token_stream.consume()
                skip_whitespace(token_stream)
            clause_stmts = collect_clause_stmts(
                token_stream, {"END-WRITE", "NOT", "END_WRITE"}
            )
            stmt.set_at_eop_clause(clause_stmts)

        # Optional NOT AT END-OF-PAGE clause
        token = token_stream.peek()
        if token and token.type == TokenType.NOT:
            token_stream.consume()
            skip_whitespace(token_stream)
            next_tok = token_stream.peek()
            if next_tok and next_tok.type == TokenType.AT:
                token_stream.consume()
                skip_whitespace(token_stream)
                token = token_stream.peek()
                if token and token.type == TokenType.END_OF_PAGE:
                    token_stream.consume()
                    skip_whitespace(token_stream)
                clause_stmts = collect_clause_stmts(
                    token_stream, {"END-WRITE", "INVALID", "NOT"}
                )
                stmt.set_not_at_eop_clause(clause_stmts)
            elif next_tok and next_tok.type == TokenType.INVALID:
                # NOT INVALID KEY (format 2) -- we already consumed NOT, so
                # handle INVALID KEY now rather than leaving it for
                # parse_invalid_key_clauses below (which expects NOT still
                # unconsumed).
                token_stream.consume()  # INVALID
                skip_whitespace(token_stream)
                token = token_stream.peek()
                if token and token.type == TokenType.KEY:
                    token_stream.consume()
                    skip_whitespace(token_stream)
                clause_stmts = collect_clause_stmts(token_stream, {"END-WRITE", "NOT"})
                stmt.set_not_invalid_key_clause(clause_stmts)
            # else: consumed NOT unexpectedly, continue

        # Optional INVALID KEY / NOT INVALID KEY clauses (indexed/relative
        # files; format 2). NOT INVALID KEY may already have been parsed
        # above when it followed an AT END-OF-PAGE-shaped NOT.
        skip_whitespace(token_stream)
        parse_invalid_key_clauses(token_stream, stmt, "END-WRITE")

        consume_end_keyword_and_period(token_stream, "END-WRITE")

        return stmt
