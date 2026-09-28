"""Call statement parser implementing IStatementParser interface."""

from typing import Any, cast

from cobolparser.parsers.statements._utils import (
    CONTROL_FLOW_BOUNDARIES,
    SCOPE_TERMINATORS,
    STATEMENT_KEYWORDS,
    STATEMENT_TOKEN_TYPES,
    consume_optional_qualifiers,
    get_parse_context,
    is_statement_boundary,
    matches_keyword,
    peek_past_noise,
    previous_meaningful_token,
    skip_statement_separators,
    skip_whitespace,
    token_value_upper,
)

from ...core.ast_factory import get_factory
from ...core.exceptions import ParseError
from ...core.interfaces import IStatementParser, ITokenStream, ParseContext
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import CallStatement


class CallStatementParser(IStatementParser):
    """Parser for CALL statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.CALL, "CALL")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> CallStatement:
        """Parse a CALL statement.

        Supports:
        - CALL "program-name"  (static)
        - CALL variable-name   (dynamic)
        - CALL ... USING [BY REFERENCE|CONTENT|VALUE] parameters
        - CALL ... RETURNING variable
        - CALL ... GIVING variable
        """
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = cast(
            CallStatement,
            factory.create(
                CallStatement,
                start_token.location if start_token else SourceLocation(0, 0),
            ),
        )

        # Get context for error reporting if available
        parse_ctx: ParseContext | None = token_stream.context
        if parse_ctx is None:
            parse_ctx = getattr(token_stream, "_context", None)
        if parse_ctx is None and hasattr(token_stream, "context"):
            parse_ctx = token_stream.context

        try:
            skip_whitespace(token_stream)
            token = token_stream.peek()

            if not token:
                # Missing program name
                if parse_ctx:
                    parse_ctx.error(
                        "CALL statement requires a program name (literal or variable)",
                        start_token.location if start_token else SourceLocation(0, 0),
                    )
                return stmt

            # Parse the program name (can be literal or identifier)
            if token.type == TokenType.STRING_LITERAL:
                # Static CALL with literal program name
                program_name = token.value
                stmt.set_called_program(program_name, is_dynamic=False)
                token_stream.consume()
            elif token.type == TokenType.IDENTIFIER:
                # Dynamic CALL with variable program name
                program_name = token.value
                stmt.set_called_program(program_name, is_dynamic=True)
                token_stream.consume()
                # ``CALL WS-SERVICE-PGM (WS-IDX) USING ...`` -- a table-driven
                # dispatch. The bare name stays ``called_program`` (what
                # DynamicCallAnalyzer resolves); the full subscripted /
                # qualified reference is kept in metadata rather than being
                # stranded as unparsed tokens.
                full_reference = consume_optional_qualifiers(
                    token_stream, program_name or ""
                )
                if full_reference != (program_name or ""):
                    stmt.set_metadata("called_program_reference", full_reference)
            else:
                # Unknown token type, report error
                if parse_ctx:
                    parse_ctx.error(
                        f"Expected program name (literal or identifier), found {token.type.name if hasattr(token.type, 'name') else str(token.type)}",
                        (
                            token.location
                            if hasattr(token, "location")
                            else SourceLocation(0, 0)
                        ),
                    )
                token_stream.consume()
                return stmt

            # Parse optional USING and RETURNING clauses

            while not token_stream.is_empty():
                # ``USING A, B; ON OVERFLOW ...`` -- a separator before a
                # handler clause is plain COBOL punctuation.
                skip_statement_separators(token_stream)
                token = token_stream.peek()

                if not token:
                    break

                if token.type == TokenType.PERIOD:
                    token_stream.consume()
                    break

                # Check for statement keywords that end the CALL statement
                if token.type in STATEMENT_TOKEN_TYPES:
                    # This is a new statement, not part of CALL
                    break

                if token.type == TokenType.IDENTIFIER and token.value:
                    if (
                        token.value.upper() in STATEMENT_KEYWORDS
                        and token.value.upper() not in ("RETURNING", "GIVING")
                    ):
                        # This is a new statement, not part of CALL
                        break

                # Parse USING clause
                if token.type == TokenType.USING or (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "USING"
                ):
                    token_stream.consume()
                    # Parse parameter list until RETURNING or GIVING or PERIOD
                    self._parse_using_clause(token_stream, stmt)
                    continue
                elif (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "RETURNING"
                ):
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    token = token_stream.peek()
                    if token and token.type == TokenType.IDENTIFIER:
                        stmt.set_returning_parameter(token.value)
                        token_stream.consume()
                elif (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "GIVING"
                ):
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    token = token_stream.peek()
                    if token and token.type == TokenType.IDENTIFIER:
                        stmt.set_giving_parameter(token.value)
                        token_stream.consume()
                elif token_value_upper(token) in ("EXCEPTION", "OVERFLOW"):
                    # ``ON`` is optional: ``CALL ... EXCEPTION stmts`` and
                    # ``CALL ... OVERFLOW stmts`` are standard COBOL. Without
                    # this branch the word was swallowed as a bogus USING
                    # parameter and the handler body escaped to the enclosing
                    # paragraph as free-standing statements -- silently.
                    kind = token_value_upper(token)
                    token_stream.consume()
                    if kind == "EXCEPTION":
                        nested = self._parse_nested_stmts(
                            token_stream, stop_at={"ON", "NOT", "END-CALL"}
                        )
                        stmt.on_exception = nested if nested else None
                    else:
                        nested = self._parse_nested_stmts(
                            token_stream, stop_at={"ON", "NOT", "END-CALL"}
                        )
                        stmt.on_overflow = nested if nested else []
                    for _nested_stmt in nested or []:
                        stmt.add_child(_nested_stmt)
                elif token.type == TokenType.ON or (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "ON"
                ):
                    next_tok = token_stream.peek(1)
                    next_val = (
                        next_tok.value.upper() if next_tok and next_tok.value else ""
                    )
                    if next_val == "EXCEPTION":
                        token_stream.consume()  # ON
                        token_stream.consume()  # EXCEPTION
                        nested = self._parse_nested_stmts(
                            token_stream, stop_at={"ON", "NOT", "END-CALL"}
                        )
                        stmt.on_exception = nested if nested else None
                        for _nested_stmt in nested or []:
                            stmt.add_child(_nested_stmt)
                    elif next_val == "OVERFLOW":
                        token_stream.consume()  # ON
                        token_stream.consume()  # OVERFLOW
                        nested = self._parse_nested_stmts(
                            token_stream, stop_at={"ON", "NOT", "END-CALL"}
                        )
                        stmt.on_overflow = nested if nested else []
                        for _nested_stmt in nested or []:
                            stmt.add_child(_nested_stmt)
                    else:
                        break
                elif token.type == TokenType.NOT or (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "NOT"
                ):
                    # NOT [ON] EXCEPTION clause (ON is optional here too)
                    t1, i1 = peek_past_noise(token_stream, 1)
                    if t1 and token_value_upper(t1) == "ON":
                        t2, _ = peek_past_noise(token_stream, i1 + 1)
                    else:
                        t2 = t1
                    if t2 and token_value_upper(t2) == "EXCEPTION":
                        token_stream.consume()  # NOT
                        skip_whitespace(token_stream)
                        if token_value_upper(token_stream.peek()) == "ON":
                            token_stream.consume()  # ON
                            skip_whitespace(token_stream)
                        token_stream.consume()  # EXCEPTION
                        nested = self._parse_nested_stmts(
                            token_stream, stop_at={"ON", "NOT", "END-CALL"}
                        )
                        stmt.not_on_exception = nested if nested else None
                        for _nested_stmt in nested or []:
                            stmt.add_child(_nested_stmt)
                    else:
                        break
                elif (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "END-CALL"
                ):
                    token_stream.consume()  # consume END-CALL
                    break
                else:
                    # Skip unknown tokens or end of CALL statement
                    break
        except ParseError:
            pass

        return stmt

    def _parse_nested_stmts(self, token_stream: ITokenStream, stop_at: set) -> list:
        """Parse statements until a stop keyword is found.

        Used for ON EXCEPTION / NOT ON EXCEPTION clause bodies.
        Returns list of CobolStatement objects.
        """
        stmts = []
        registry = getattr(token_stream, "_registry", None)
        while not token_stream.is_empty():
            skip_statement_separators(token_stream)
            token = token_stream.peek()
            if not token:
                break
            val = token.value.upper() if token.value else ""
            # A handler body also ends at the enclosing statement's own
            # boundary: ``IF c CALL ... NOT ON EXCEPTION MOVE ... ELSE ...``
            # / ``PERFORM ... CALL ... ON EXCEPTION ... END-PERFORM``.
            # Previously ELSE/END-IF/END-PERFORM were "unsupported
            # statements" here and the enclosing IF/PERFORM lost its
            # structure (the ELSE branch was folded into the handler).
            if (
                val in stop_at
                or val == "."
                or val in CONTROL_FLOW_BOUNDARIES
                or val in SCOPE_TERMINATORS
            ):
                break
            if registry:
                parser = registry.find_parser(token_stream)
                if parser:
                    try:
                        nested_stmt = parser.parse(token_stream)
                        stmts.append(nested_stmt)
                        # A nested statement that consumed the sentence-
                        # terminating period ends the handler body.
                        prev = previous_meaningful_token(token_stream)
                        if prev is not None and prev.type == TokenType.PERIOD:
                            break
                    except ParseError:
                        token_stream.consume()
                else:
                    self._warn_and_skip_handler_statement(token_stream, token, stop_at)
            else:
                self._warn_and_skip_handler_statement(token_stream, token, stop_at)
        return stmts

    def _warn_and_skip_handler_statement(
        self, token_stream: ITokenStream, token: Any, stop_at: set
    ) -> None:
        """Surface one warning per dropped statement, then skip its tokens.

        Mirrors ``ProcedureDivisionParser._warn_unsupported_statement`` /
        ``_skip_to_next_statement`` (audit C2): without this, an unknown verb
        inside ON EXCEPTION / NOT ON EXCEPTION / ON OVERFLOW was silently
        dropped one token at a time with ``errors=0, warnings=0``, unlike the
        identical verb at top level.
        """
        value = (token.value or "").upper() if token is not None else ""
        line = getattr(getattr(token, "location", None), "line", None)
        where = f" at line {line}" if line else ""
        context = get_parse_context(token_stream)
        host = getattr(context, "host", None) if context is not None else None
        add_warning = getattr(host, "add_warning", None)
        if value and callable(add_warning):
            add_warning(
                f"Unsupported statement '{value}'{where} skipped inside a CALL "
                "exception/overflow handler: no parser is registered for this "
                "verb; its tokens were discarded up to the next statement "
                "boundary"
            )
        token_stream.consume()
        while not token_stream.is_empty():
            nxt = token_stream.peek()
            if not nxt:
                break
            nxt_val = nxt.value.upper() if nxt.value else ""
            if (
                nxt_val in stop_at
                or nxt_val == "."
                or nxt_val in CONTROL_FLOW_BOUNDARIES
                or is_statement_boundary(nxt)
            ):
                break
            token_stream.consume()

    def _parse_using_clause(
        self, token_stream: ITokenStream, stmt: CallStatement
    ) -> None:
        """Parse USING clause with optional BY REFERENCE|CONTENT|VALUE modifiers."""

        # A BY REFERENCE|CONTENT|VALUE phrase governs every parameter that
        # follows it until the next BY phrase (``BY CONTENT a, b`` passes
        # BOTH a and b by content) -- so this must persist across loop
        # iterations, not reset per parameter. Only re-initialized here,
        # once, before the first parameter; the loop body below only
        # overwrites it when an actual BY keyword is seen.
        passing_mode = (
            "REFERENCE"  # Default when no BY phrase precedes the first parameter
        )
        while not token_stream.is_empty():
            skip_whitespace(token_stream)
            token = token_stream.peek()

            if not token or token.type == TokenType.PERIOD:
                break

            # Commas are pure separators between USING parameters (and
            # between BY-phrase groups); skip them and continue to the next
            # parameter instead of treating them as the end of the clause.
            if token.type == TokenType.COMMA:
                token_stream.consume()
                continue

            # Check for end of USING clause
            if token.type == TokenType.IDENTIFIER and token.value:
                val_upper = token.value.upper()
                if val_upper in ("RETURNING", "GIVING", "ON", "EXCEPTION", "OVERFLOW"):
                    break
                # Check for statement keywords
                if val_upper in STATEMENT_KEYWORDS:
                    break
                # Scope terminators of an enclosing statement (e.g. END-READ
                # when this CALL is an AT END clause body) end the parameters.
                if val_upper in SCOPE_TERMINATORS:
                    break
            # Check for statement token types
            elif token.type in STATEMENT_TOKEN_TYPES:
                break
            # Check for non-parameter tokens (like NUMERIC_LITERAL), end of USING clause
            elif token.type not in (
                TokenType.BY,
                TokenType.USING,
            ) and token.type not in (
                TokenType.IDENTIFIER,
                TokenType.STRING_LITERAL,
                TokenType.NUMERIC_LITERAL,
                TokenType.LEVEL_NUMBER,
                TokenType.VALUE,
                TokenType.OMITTED,
                TokenType.FIGURATIVE_CONSTANT,
                TokenType.MINUS,
                TokenType.PLUS,
            ):
                break

            # Check for BY [REFERENCE|CONTENT|VALUE] -- only overwrites the
            # mode established above/by a prior iteration when a BY keyword
            # is actually present; otherwise passing_mode carries over
            # unchanged (see the persistence note above the loop).
            if token.type == TokenType.BY or (
                token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() == "BY"
            ):
                token_stream.consume()
                skip_whitespace(token_stream)
                token = token_stream.peek()
                if token and (
                    token.type == TokenType.IDENTIFIER or token.type == TokenType.VALUE
                ):
                    mode_val = token.value.upper() if token.value else ""
                    if mode_val in ("REFERENCE", "CONTENT", "VALUE"):
                        passing_mode = mode_val
                        token_stream.consume()
                        skip_whitespace(token_stream)
                        token = token_stream.peek()

            # ``BY CONTENT ZERO`` / ``BY VALUE -7`` -- a figurative constant
            # or a signed numeric literal is one argument; stopping here
            # dropped it and every argument after it.
            if token and token.type == TokenType.FIGURATIVE_CONSTANT:
                token_stream.consume()
                stmt.add_using_parameter(token.value.upper(), passing_mode)
                continue
            if token and token.type in (TokenType.MINUS, TokenType.PLUS):
                number = token_stream.peek(1)
                if number is None or number.type not in (
                    TokenType.NUMERIC_LITERAL,
                    TokenType.LEVEL_NUMBER,
                ):
                    break
                token_stream.consume()
                token_stream.consume()
                stmt.add_using_parameter(token.value + number.value, passing_mode)
                continue

            # Parse parameter name (OMITTED is a valid USING parameter
            # placeholder per the COBOL grammar, not just a mode modifier).
            if token and token.type in (
                TokenType.IDENTIFIER,
                TokenType.STRING_LITERAL,
                # ``BY VALUE 100`` / ``USING 100.00`` -- a numeric literal is
                # a legal argument (the lexer classes 1-2 digit integers as
                # LEVEL_NUMBER regardless of context).
                TokenType.NUMERIC_LITERAL,
                TokenType.LEVEL_NUMBER,
                TokenType.OMITTED,
            ):
                param_name = token.value if token.value else "OMITTED"
                token_stream.consume()
                if token.type == TokenType.IDENTIFIER:
                    # ``ADDRESS OF x`` / ``LENGTH OF x`` argument forms, then
                    # a trailing subscript / OF-IN qualifier chain
                    # (``USING SUBSCRIPTED-DATA (4)``) -- fold them into the
                    # parameter rather than stranding them as unparsed tokens.
                    if param_name.upper() in ("ADDRESS", "LENGTH"):
                        of_tok, of_idx = peek_past_noise(token_stream, 0)
                        if of_tok and token_value_upper(of_tok) == "OF":
                            name_tok, _ = peek_past_noise(token_stream, of_idx + 1)
                            if name_tok and name_tok.type == TokenType.IDENTIFIER:
                                skip_whitespace(token_stream)
                                token_stream.consume()  # OF
                                skip_whitespace(token_stream)
                                token_stream.consume()  # identifier
                                param_name = f"{param_name.upper()} OF {name_tok.value}"
                    param_name = consume_optional_qualifiers(token_stream, param_name)
                stmt.add_using_parameter(param_name, passing_mode)
            else:
                # No parameter found, end of USING clause
                break
