"""Simple statement parsers for CONTINUE, EJECT, EXIT, GOBACK, CANCEL, ALTER,
GENERATE, RELEASE, RETURN, USE, COMMIT, and ROLLBACK.

Each parser implements IStatementParser for registry-based dispatch.
"""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import (
    AlterStatement,
    CancelStatement,
    CommitStatement,
    ContinueStatement,
    EjectStatement,
    ExitStatement,
    GenerateStatement,
    GobackStatement,
    NextSentenceStatement,
    ReleaseStatement,
    ReturnStatement,
    RollbackStatement,
    SkipStatement,
    UseStatement,
)
from ._utils import (
    CONTROL_FLOW_BOUNDARIES,
    LITERAL_TOKEN_TYPES,
    SEPARATOR_TOKEN_TYPES,
    STATEMENT_KEYWORDS,
    bare_end_starts_at_end_clause,
    collect_clause_stmts,
    consume_period,
    consume_procedure_qualifier,
    is_procedure_name_token,
    is_statement_boundary,
    looks_dedented_relative_to,
    looks_like_paragraph_boundary,
    matches_keyword,
    peek_past_noise,
    previous_meaningful_token,
    skip_whitespace,
    token_column,
    token_location,
    warn_paragraph_boundary_swallowed,
)
from ._utils import (
    token_value_upper as _token_value_upper,
)


class ContinueStatementParser(IStatementParser):
    """Parser for CONTINUE statements (no-op)."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.CONTINUE, "CONTINUE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ContinueStatement:
        start = token_stream.consume()
        stmt = ContinueStatement(token_location(start))
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class NextSentenceStatementParser(IStatementParser):
    """Parser for NEXT SENTENCE statements.

    Only matches when NEXT is actually followed by SENTENCE -- TokenType.NEXT
    is reserved for this phrase at statement-start position (READ's ``NEXT
    RECORD`` form is consumed internally by the READ parser, never reaching
    the top-level statement registry), but the explicit lookahead keeps this
    parser from ever mis-firing on a malformed program.
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        if not matches_keyword(token_stream, TokenType.NEXT, "NEXT"):
            return False
        lookahead, _ = peek_past_noise(token_stream, 1)
        return bool(
            lookahead and lookahead.value and lookahead.value.upper() == "SENTENCE"
        )

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> NextSentenceStatement:
        start = token_stream.consume()  # NEXT
        stmt = NextSentenceStatement(token_location(start))
        skip_whitespace(token_stream)
        token_stream.consume()  # SENTENCE
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class EjectStatementParser(IStatementParser):
    """Parser for EJECT statements (compiler-directing listing no-op).

    Syntax: EJECT
    A page-eject directive for the compiler's source listing -- no runtime
    effect. Registering a dedicated parser (rather than leaving EJECT as an
    unrecognized bare word) keeps ``EJECT.`` from being misread as a new
    paragraph name by the PROCEDURE DIVISION boundary scanner.
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.EJECT, "EJECT")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> EjectStatement:
        start = token_stream.consume()
        stmt = EjectStatement(token_location(start))
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


#: The one home for which token types are SKIP statements AND how many
#: lines each skips -- matches() tests membership here, so a SKIP variant
#: cannot be dispatchable without a line count (or vice versa).
_SKIP_LINE_COUNTS: dict[Any, int] = {
    TokenType.SKIP1: 1,
    TokenType.SKIP2: 2,
    TokenType.SKIP3: 3,
}


class SkipStatementParser(IStatementParser):
    """Parser for SKIP1/SKIP2/SKIP3 statements (compiler-directing listing
    no-ops, the same class as EJECT).

    Syntax: SKIP1 | SKIP2 | SKIP3
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        token = token_stream.peek(0)
        return token is not None and token.type in _SKIP_LINE_COUNTS

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> SkipStatement:
        start = token_stream.consume()
        stmt = SkipStatement(token_location(start), _SKIP_LINE_COUNTS[start.type])
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class ExitStatementParser(IStatementParser):
    """Parser for EXIT statements.

    Syntax: EXIT [PROGRAM | SECTION | PARAGRAPH | PERFORM [CYCLE]]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.EXIT, "EXIT")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ExitStatement:
        start = token_stream.consume()
        stmt = ExitStatement(token_location(start))
        skip_whitespace(token_stream)

        if not token_stream.is_empty():
            token = token_stream.peek()
            val = _token_value_upper(token)
            if val in ("PROGRAM", "SECTION", "PARAGRAPH", "PERFORM"):
                token_stream.consume()
                exit_type = val
                if val == "PERFORM":
                    skip_whitespace(token_stream)
                    nxt = token_stream.peek()
                    if nxt and _token_value_upper(nxt) == "CYCLE":
                        token_stream.consume()
                        exit_type = "PERFORM CYCLE"
                stmt.set_exit_type(exit_type)

        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class GobackStatementParser(IStatementParser):
    """Parser for GOBACK statements.

    Syntax: GOBACK [RETURNING identifier]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.GOBACK, "GOBACK")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> GobackStatement:
        start = token_stream.consume()
        stmt = GobackStatement(token_location(start))
        skip_whitespace(token_stream)

        if not token_stream.is_empty():
            token = token_stream.peek()
            if _token_value_upper(token) == "RETURNING":
                token_stream.consume()
                skip_whitespace(token_stream)
                val_token = token_stream.peek()
                if val_token and val_token.type != TokenType.PERIOD:
                    token_stream.consume()
                    stmt.set_returning_value(val_token.value or "")

        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class CancelStatementParser(IStatementParser):
    """Parser for CANCEL statements.

    Syntax: CANCEL program-name-1 [program-name-2 ...]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.CANCEL, "CANCEL")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> CancelStatement:
        start = token_stream.consume()
        stmt = CancelStatement(token_location(start))
        start_column = token_column(start)
        skip_whitespace(token_stream)

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            # A following statement's verb that lexes as a plain IDENTIFIER
            # (e.g. PURGE/RAISE/RESUME have no dedicated TokenType) must not
            # be folded into the program-name list when CANCEL has no
            # trailing period.
            if token.type == TokenType.IDENTIFIER and is_statement_boundary(token):
                break
            # A missing period on this CANCEL followed by what looks like
            # the next paragraph/section header (H9): stop instead of
            # folding it into the program-name list. Disambiguated by
            # indentation (Area A vs Area B) so a program name that merely
            # wraps onto its own continuation line -- legitimate for any
            # name in the list, not just the first -- isn't misread as a
            # boundary and dropped.
            if (
                token.type == TokenType.IDENTIFIER
                and looks_like_paragraph_boundary(token_stream)
                and looks_dedented_relative_to(token_stream, start_column)
            ):
                warn_paragraph_boundary_swallowed(token_stream)
                break
            if token.type == TokenType.COMMA:
                # A comma between program names (`CANCEL WS-A, WS-B.`) is a
                # separator, not a terminator -- skip it and keep collecting,
                # mirroring the MOVE/SET parsers' target-list handling.
                token_stream.consume()
                skip_whitespace(token_stream)
                continue
            if token.type in (TokenType.IDENTIFIER, TokenType.STRING_LITERAL):
                token_stream.consume()
                stmt.add_program_name(token.value or "")
            else:
                break
            skip_whitespace(token_stream)

        return stmt


class AlterStatementParser(IStatementParser):
    """Parser for ALTER statements (obsolete).

    Syntax: ALTER paragraph-1 TO [PROCEED TO] paragraph-2
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.ALTER, "ALTER")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> AlterStatement:
        start = token_stream.consume()
        stmt = AlterStatement(token_location(start))
        skip_whitespace(token_stream)

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or token.type == TokenType.PERIOD:
                consume_period(token_stream)
                break
            if token.type in SEPARATOR_TOKEN_TYPES:
                # ``ALTER A TO PROCEED TO B, C TO PROCEED TO D`` (NC303M)
                token_stream.consume()
                skip_whitespace(token_stream)
                continue

            # Read from-paragraph (an identifier, or an all-digit numeric
            # paragraph name -- idiomatic THRU-style numbering).
            if not is_procedure_name_token(token):
                break
            from_para = token.value or ""
            token_stream.consume()
            skip_whitespace(token_stream)
            # ``ALTER PARA-5A IN QUAL-SECTION-1 TO ...`` (NIST OBNC2M):
            # a section-qualified paragraph name -- consume the qualifier.
            consume_procedure_qualifier(token_stream)

            # Expect TO
            nxt = token_stream.peek()
            if not nxt or _token_value_upper(nxt) != "TO":
                break
            token_stream.consume()
            skip_whitespace(token_stream)

            # Optional PROCEED TO
            nxt = token_stream.peek()
            if nxt and _token_value_upper(nxt) == "PROCEED":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _token_value_upper(nxt) == "TO":
                    token_stream.consume()
                    skip_whitespace(token_stream)

            # Read to-paragraph
            nxt = token_stream.peek()
            if not nxt or nxt.type == TokenType.PERIOD:
                break
            to_para = nxt.value or ""
            token_stream.consume()
            stmt.add_alteration(from_para, to_para)
            skip_whitespace(token_stream)
            consume_procedure_qualifier(token_stream)

        return stmt


class GenerateStatementParser(IStatementParser):
    """Parser for GENERATE statements (Report Writer).

    Syntax: GENERATE report-name
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.GENERATE, "GENERATE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> GenerateStatement:
        start = token_stream.consume()
        stmt = GenerateStatement(token_location(start))
        skip_whitespace(token_stream)

        token = token_stream.peek()
        if token and token.type != TokenType.PERIOD:
            token_stream.consume()
            stmt.set_report_name(token.value or "")

        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class ReleaseStatementParser(IStatementParser):
    """Parser for RELEASE statements (sort input).

    Syntax: RELEASE record-name [FROM identifier]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.RELEASE, "RELEASE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ReleaseStatement:
        start = token_stream.consume()
        stmt = ReleaseStatement(token_location(start))
        skip_whitespace(token_stream)

        # Record name
        token = token_stream.peek()
        if token and token.type != TokenType.PERIOD:
            token_stream.consume()
            stmt.set_record_name(token.value or "")

        skip_whitespace(token_stream)

        # Optional FROM
        token = token_stream.peek()
        if token and _token_value_upper(token) == "FROM":
            token_stream.consume()
            skip_whitespace(token_stream)
            src = token_stream.peek()
            if src and src.type != TokenType.PERIOD:
                token_stream.consume()
                stmt.set_from_source(src.value or "")

        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class ReturnStatementParser(IStatementParser):
    """Parser for RETURN statements (sort output).

    Syntax: RETURN file-name [RECORD] [INTO identifier] AT END statements
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.RETURN, "RETURN")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ReturnStatement:
        start = token_stream.consume()
        stmt = ReturnStatement(token_location(start))
        skip_whitespace(token_stream)

        # File name
        token = token_stream.peek()
        if token and token.type not in (TokenType.PERIOD, None):
            token_stream.consume()
            stmt.set_file_name(token.value or "")

        skip_whitespace(token_stream)

        # Optional RECORD
        token = token_stream.peek()
        if token and _token_value_upper(token) == "RECORD":
            token_stream.consume()
            skip_whitespace(token_stream)

        # Optional INTO
        token = token_stream.peek()
        if token and _token_value_upper(token) == "INTO":
            token_stream.consume()
            skip_whitespace(token_stream)
            tgt = token_stream.peek()
            if tgt and tgt.type != TokenType.PERIOD:
                token_stream.consume()
                stmt.set_into_target(tgt.value or "")

        skip_whitespace(token_stream)

        # Parse AT END / NOT AT END clauses
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            val = _token_value_upper(token)
            if val in CONTROL_FLOW_BOUNDARIES:
                break
            if val == "AT":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _token_value_upper(nxt) == "END":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    at_end_stmts = self._parse_clause_stmts(token_stream)
                    if at_end_stmts:
                        stmt.set_at_end_clause(at_end_stmts)
                    if self._sentence_period_consumed(token_stream):
                        break
            elif val == "NOT":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _token_value_upper(nxt) == "AT":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _token_value_upper(nxt) == "END":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    not_at_end_stmts = self._parse_clause_stmts(token_stream)
                    if not_at_end_stmts:
                        stmt.set_not_at_end_clause(not_at_end_stmts)
                    if self._sentence_period_consumed(token_stream):
                        break
            elif bare_end_starts_at_end_clause(token_stream):
                # ``RETURN F END stmts`` -- AT is optional.
                token_stream.consume()  # END
                skip_whitespace(token_stream)
                at_end_stmts = self._parse_clause_stmts(token_stream)
                if at_end_stmts:
                    stmt.set_at_end_clause(at_end_stmts)
                if self._sentence_period_consumed(token_stream):
                    break
            elif token.type not in LITERAL_TOKEN_TYPES and val in STATEMENT_KEYWORDS:
                break
            else:
                token_stream.consume()
            skip_whitespace(token_stream)

        return stmt

    @staticmethod
    def _parse_clause_stmts(token_stream: ITokenStream) -> list:
        """Parse imperative statements in an AT END / NOT AT END clause.

        Delegates to the shared ``collect_clause_stmts`` (the same helper
        READ/WRITE use) so a nested statement that consumed the sentence
        period ends the clause. The previous private loop did not notice
        the consumed period, so ``RETURN SF AT END MOVE 'Y' TO A.`` swallowed
        every following statement of the paragraph into ``at_end_clause``.
        """
        return collect_clause_stmts(token_stream, {"END-RETURN", "END_RETURN"})

    @staticmethod
    def _sentence_period_consumed(token_stream: ITokenStream) -> bool:
        """True when the clause body just parsed ended on the sentence period."""
        prev = previous_meaningful_token(token_stream)
        return prev is not None and prev.type == TokenType.PERIOD


class UseStatementParser(IStatementParser):
    """Parser for USE statements (declaratives).

    Syntax: USE [GLOBAL] AFTER [STANDARD] {EXCEPTION|ERROR} PROCEDURE
            ON {file-name|INPUT|OUTPUT|I-O|EXTEND}
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.USE, "USE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> UseStatement:
        start = token_stream.consume()
        stmt = UseStatement(token_location(start))
        skip_whitespace(token_stream)

        # Optional GLOBAL
        token = token_stream.peek()
        if token and _token_value_upper(token) == "GLOBAL":
            token_stream.consume()
            stmt.set_global(True)
            skip_whitespace(token_stream)

        # Consume remaining tokens until period, extracting key info
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            val = _token_value_upper(token)
            if token.type not in LITERAL_TOKEN_TYPES and (
                val in CONTROL_FLOW_BOUNDARIES or val in STATEMENT_KEYWORDS
            ):
                break
            if val in ("EXCEPTION", "ERROR"):
                stmt.set_use_type(val)
            elif val == "DEBUGGING":
                stmt.set_use_type("DEBUGGING")
            elif val in ("INPUT", "OUTPUT", "I-O", "EXTEND"):
                stmt.add_file_name(val)
            elif val not in ("AFTER", "BEFORE", "STANDARD", "PROCEDURE", "ON"):
                if token.type == TokenType.IDENTIFIER:
                    stmt.add_file_name(token.value or "")
            token_stream.consume()
            skip_whitespace(token_stream)

        return stmt


class CommitStatementParser(IStatementParser):
    """Parser for COMMIT statements (transaction control).

    Syntax: COMMIT
    Commonly used in DB2/CICS COBOL programs to commit the current
    unit of work. EXEC SQL COMMIT is handled by ExecSqlStatementParser;
    this parser handles the native COBOL COMMIT verb.
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.COMMIT, "COMMIT")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> CommitStatement:
        start = token_stream.consume()
        stmt = CommitStatement(token_location(start))
        skip_whitespace(token_stream)
        # Optionally consume WORK keyword
        token = token_stream.peek()
        if token and _token_value_upper(token) == "WORK":
            token_stream.consume()
            skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class RollbackStatementParser(IStatementParser):
    """Parser for ROLLBACK statements (transaction control).

    Syntax: ROLLBACK [WORK]
    Rolls back the current unit of work. EXEC SQL ROLLBACK is handled
    by ExecSqlStatementParser; this handles the native COBOL ROLLBACK verb.
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.ROLLBACK, "ROLLBACK")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> RollbackStatement:
        start = token_stream.consume()
        stmt = RollbackStatement(token_location(start))
        skip_whitespace(token_stream)
        # Optional WORK keyword
        token = token_stream.peek()
        if token and _token_value_upper(token) == "WORK":
            token_stream.consume()
            stmt.set_rollback_work(True)
            skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt
