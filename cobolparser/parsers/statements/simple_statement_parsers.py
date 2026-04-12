"""Simple statement parsers for CONTINUE, EXIT, GOBACK, CANCEL, ALTER,
GENERATE, RELEASE, RETURN, USE, COMMIT, and ROLLBACK.

Each parser implements IStatementParser for registry-based dispatch.
"""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import (
    AlterStatement,
    CancelStatement,
    CommitStatement,
    ContinueStatement,
    ExitStatement,
    GenerateStatement,
    GobackStatement,
    ReleaseStatement,
    ReturnStatement,
    RollbackStatement,
    UseStatement,
)
from ._utils import (
    CONTROL_FLOW_BOUNDARIES,
    STATEMENT_KEYWORDS,
    consume_period,
    skip_whitespace,
    try_parse_nested_statement,
)
from ._utils import (
    token_value_upper as _token_value_upper,
)


class ContinueStatementParser(IStatementParser):
    """Parser for CONTINUE statements (no-op)."""

    def matches(self, token_stream: ITokenStream) -> bool:
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.CONTINUE:
            return True
        return (
            token.type == TokenType.IDENTIFIER
            and _token_value_upper(token) == "CONTINUE"
        )

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ContinueStatement:
        start = token_stream.consume()
        stmt = ContinueStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class ExitStatementParser(IStatementParser):
    """Parser for EXIT statements.

    Syntax: EXIT [PROGRAM | SECTION | PARAGRAPH | PERFORM [CYCLE]]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.EXIT:
            return True
        return (
            token.type == TokenType.IDENTIFIER and _token_value_upper(token) == "EXIT"
        )

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ExitStatement:
        start = token_stream.consume()
        stmt = ExitStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
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
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.GOBACK:
            return True
        return (
            token.type == TokenType.IDENTIFIER and _token_value_upper(token) == "GOBACK"
        )

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> GobackStatement:
        start = token_stream.consume()
        stmt = GobackStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
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
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.CANCEL:
            return True
        return (
            token.type == TokenType.IDENTIFIER and _token_value_upper(token) == "CANCEL"
        )

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> CancelStatement:
        start = token_stream.consume()
        stmt = CancelStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
        skip_whitespace(token_stream)

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
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
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.ALTER:
            return True
        return (
            token.type == TokenType.IDENTIFIER and _token_value_upper(token) == "ALTER"
        )

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> AlterStatement:
        start = token_stream.consume()
        stmt = AlterStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
        skip_whitespace(token_stream)

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or token.type == TokenType.PERIOD:
                consume_period(token_stream)
                break

            # Read from-paragraph
            if token.type != TokenType.IDENTIFIER:
                break
            from_para = token.value or ""
            token_stream.consume()
            skip_whitespace(token_stream)

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

        return stmt


class GenerateStatementParser(IStatementParser):
    """Parser for GENERATE statements (Report Writer).

    Syntax: GENERATE report-name
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.GENERATE:
            return True
        return (
            token.type == TokenType.IDENTIFIER
            and _token_value_upper(token) == "GENERATE"
        )

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> GenerateStatement:
        start = token_stream.consume()
        stmt = GenerateStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
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
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.RELEASE:
            return True
        return (
            token.type == TokenType.IDENTIFIER
            and _token_value_upper(token) == "RELEASE"
        )

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ReleaseStatement:
        start = token_stream.consume()
        stmt = ReleaseStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
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
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.RETURN:
            return True
        return (
            token.type == TokenType.IDENTIFIER and _token_value_upper(token) == "RETURN"
        )

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ReturnStatement:
        start = token_stream.consume()
        stmt = ReturnStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
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
            elif val in STATEMENT_KEYWORDS:
                break
            else:
                token_stream.consume()
            skip_whitespace(token_stream)

        return stmt

    @staticmethod
    def _parse_clause_stmts(token_stream: ITokenStream) -> list:
        """Parse imperative statements in an AT END / NOT AT END clause."""
        stmts: list = []
        while not token_stream.is_empty():
            skip_whitespace(token_stream)
            token = token_stream.peek()
            if not token:
                break
            val = _token_value_upper(token)
            if (
                token.type == TokenType.PERIOD
                or val
                in (
                    "NOT",
                    "END-RETURN",
                )
                or val in CONTROL_FLOW_BOUNDARIES
            ):
                break
            nested = try_parse_nested_statement(token_stream)
            if nested:
                stmts.append(nested)
            else:
                break
        return stmts


class UseStatementParser(IStatementParser):
    """Parser for USE statements (declaratives).

    Syntax: USE [GLOBAL] AFTER [STANDARD] {EXCEPTION|ERROR} PROCEDURE
            ON {file-name|INPUT|OUTPUT|I-O|EXTEND}
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.USE:
            return True
        return token.type == TokenType.IDENTIFIER and _token_value_upper(token) == "USE"

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> UseStatement:
        start = token_stream.consume()
        stmt = UseStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
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
            if val in CONTROL_FLOW_BOUNDARIES or val in STATEMENT_KEYWORDS:
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
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.COMMIT:
            return True
        return (
            token.type == TokenType.IDENTIFIER and _token_value_upper(token) == "COMMIT"
        )

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> CommitStatement:
        start = token_stream.consume()
        stmt = CommitStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
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
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.ROLLBACK:
            return True
        return (
            token.type == TokenType.IDENTIFIER
            and _token_value_upper(token) == "ROLLBACK"
        )

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> RollbackStatement:
        start = token_stream.consume()
        stmt = RollbackStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
        skip_whitespace(token_stream)
        # Optional WORK keyword
        token = token_stream.peek()
        if token and _token_value_upper(token) == "WORK":
            token_stream.consume()
            stmt.set_rollback_work(True)
            skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt
