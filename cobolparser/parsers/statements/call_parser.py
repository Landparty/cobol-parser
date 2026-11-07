"""Call statement parser implementing IStatementParser interface."""

from collections.abc import Callable
from typing import Any, ClassVar, cast

from cobolparser.parsers.statements._utils import (
    CONTROL_FLOW_BOUNDARIES,
    SCOPE_TERMINATORS,
    STATEMENT_KEYWORDS,
    STATEMENT_TOKEN_TYPES,
    _looks_like_statement_boundary,
    consume_optional_qualifiers,
    get_parse_context,
    is_statement_boundary,
    join_source_parts,
    literal_operand_text,
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
from ...lexer import Token, TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import CallStatement


def _call_parse_context(token_stream: ITokenStream) -> ParseContext | None:
    """The stream's parse context, for error reporting, if it has one."""
    parse_ctx: ParseContext | None = token_stream.context
    if parse_ctx is None:
        parse_ctx = getattr(token_stream, "_context", None)
    if parse_ctx is None and hasattr(token_stream, "context"):
        parse_ctx = token_stream.context
    return parse_ctx


def _starts_next_statement(token: Token) -> bool:
    """True when *token* is a statement verb that ends the CALL (RETURNING
    and GIVING are statement keywords too, but CALL phrases here)."""
    if token.type in STATEMENT_TOKEN_TYPES:
        return True
    if token.type != TokenType.IDENTIFIER or not token.value:
        return False
    upper = token.value.upper()
    return upper in STATEMENT_KEYWORDS and upper not in ("RETURNING", "GIVING")


def _phrase_word(token: Token) -> str:
    """The CALL phrase word *token* spells, for ``_PHRASE_HANDLERS``: the
    USING / ON / NOT token types, any IDENTIFIER's upper-cased value, and
    EXCEPTION / OVERFLOW whatever they lexed as; ``""`` otherwise."""
    if token.type == TokenType.USING:
        return "USING"
    if token.type == TokenType.IDENTIFIER:
        return token.value.upper() if token.value else ""
    upper = token_value_upper(token)
    if upper in ("EXCEPTION", "OVERFLOW"):
        return upper
    if token.type == TokenType.ON:
        return "ON"
    if token.type == TokenType.NOT:
        return "NOT"
    return ""


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
        parse_ctx = _call_parse_context(token_stream)

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

            if not self._parse_program_name(token_stream, stmt, token, parse_ctx):
                return stmt

            # Parse optional USING and RETURNING clauses
            self._parse_call_phrases(token_stream, stmt)
        except ParseError:
            pass

        return stmt

    def _parse_program_name(
        self,
        token_stream: ITokenStream,
        stmt: CallStatement,
        token: Token,
        parse_ctx: ParseContext | None,
    ) -> bool:
        """Consume the program name (literal or identifier) at *token*.
        False -- after reporting and consuming the token -- when it is
        neither, which ends the CALL."""
        if token.type == TokenType.STRING_LITERAL:
            # Static CALL with literal program name
            stmt.set_called_program(token.value, is_dynamic=False)
            token_stream.consume()
            return True
        if token.type == TokenType.IDENTIFIER:
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
            return True
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
        return False

    def _parse_call_phrases(
        self, token_stream: ITokenStream, stmt: CallStatement
    ) -> None:
        """Parse the phrases after the program name (USING, RETURNING,
        GIVING, the exception/overflow handlers, END-CALL) through
        ``_PHRASE_HANDLERS`` until the CALL ends."""
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
            if _starts_next_statement(token):
                # This is a new statement, not part of CALL
                break

            handler = self._PHRASE_HANDLERS.get(_phrase_word(token))
            # Anything else: unknown token or end of CALL statement
            if handler is None or not handler(self, token_stream, stmt):
                break

    # ------------------------------------------------------------------
    # Phrase handlers: called with the phrase word peeked, not consumed.
    # True to keep reading phrases, False to end the CALL.
    # ------------------------------------------------------------------

    def _phrase_using(self, token_stream: ITokenStream, stmt: CallStatement) -> bool:
        token_stream.consume()
        # Parse parameter list until RETURNING or GIVING or PERIOD
        self._parse_using_clause(token_stream, stmt)
        return True

    def _phrase_returning(
        self, token_stream: ITokenStream, stmt: CallStatement
    ) -> bool:
        token_stream.consume()
        skip_whitespace(token_stream)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER:
            token_stream.consume()
            # ``RETURNING WS-RC OF WS-CTL`` / ``RETURNING T (I)``:
            # the item is the whole data reference (the
            # qualifier was dropped as unparsed tokens).
            stmt.set_returning_parameter(
                consume_optional_qualifiers(token_stream, token.value)
            )
        return True

    def _phrase_giving(self, token_stream: ITokenStream, stmt: CallStatement) -> bool:
        token_stream.consume()
        skip_whitespace(token_stream)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER:
            token_stream.consume()
            stmt.set_giving_parameter(
                consume_optional_qualifiers(token_stream, token.value)
            )
        return True

    def _phrase_bare_handler(
        self, token_stream: ITokenStream, stmt: CallStatement
    ) -> bool:
        # ``ON`` is optional: ``CALL ... EXCEPTION stmts`` and
        # ``CALL ... OVERFLOW stmts`` are standard COBOL. Without
        # this handler the word was swallowed as a bogus USING
        # parameter and the handler body escaped to the enclosing
        # paragraph as free-standing statements -- silently.
        kind = token_value_upper(token_stream.peek())
        token_stream.consume()
        attr = "on_exception" if kind == "EXCEPTION" else "on_overflow"
        self._parse_handler_body(token_stream, stmt, attr)
        return True

    def _phrase_on(self, token_stream: ITokenStream, stmt: CallStatement) -> bool:
        # ``ON <newline> EXCEPTION``: look past the line break,
        # or the handler was dropped and its body escaped.
        next_tok, _ = peek_past_noise(token_stream, 1)
        next_val = next_tok.value.upper() if next_tok and next_tok.value else ""
        if next_val not in ("EXCEPTION", "OVERFLOW"):
            return False
        token_stream.consume()  # ON
        skip_whitespace(token_stream)
        token_stream.consume()  # EXCEPTION / OVERFLOW
        attr = "on_exception" if next_val == "EXCEPTION" else "on_overflow"
        self._parse_handler_body(token_stream, stmt, attr)
        return True

    def _phrase_not(self, token_stream: ITokenStream, stmt: CallStatement) -> bool:
        # NOT [ON] EXCEPTION clause (ON is optional here too)
        t1, i1 = peek_past_noise(token_stream, 1)
        if t1 and token_value_upper(t1) == "ON":
            t2, _ = peek_past_noise(token_stream, i1 + 1)
        else:
            t2 = t1
        if not (t2 and token_value_upper(t2) == "EXCEPTION"):
            return False
        token_stream.consume()  # NOT
        skip_whitespace(token_stream)
        if token_value_upper(token_stream.peek()) == "ON":
            token_stream.consume()  # ON
            skip_whitespace(token_stream)
        token_stream.consume()  # EXCEPTION
        self._parse_handler_body(token_stream, stmt, "not_on_exception")
        return True

    def _phrase_end_call(self, token_stream: ITokenStream, stmt: CallStatement) -> bool:
        token_stream.consume()  # consume END-CALL
        return False

    _PHRASE_HANDLERS: ClassVar[
        dict[str, Callable[["CallStatementParser", ITokenStream, CallStatement], bool]]
    ] = {
        "USING": _phrase_using,
        "RETURNING": _phrase_returning,
        "GIVING": _phrase_giving,
        "EXCEPTION": _phrase_bare_handler,
        "OVERFLOW": _phrase_bare_handler,
        "ON": _phrase_on,
        "NOT": _phrase_not,
        "END-CALL": _phrase_end_call,
    }

    def _parse_handler_body(
        self, token_stream: ITokenStream, stmt: CallStatement, attr: str
    ) -> None:
        """Parse an exception/overflow handler body into *attr* and attach
        its statements as children of *stmt*."""
        nested = self._parse_nested_stmts(
            token_stream, stop_at={"ON", "NOT", "END-CALL"}
        )
        self._set_handler(token_stream, stmt, attr, nested)
        for _nested_stmt in nested or []:
            stmt.add_child(_nested_stmt)

    _HANDLER_PHRASES = {
        "on_exception": "ON EXCEPTION",
        "on_overflow": "ON OVERFLOW",
        "not_on_exception": "NOT ON EXCEPTION",
    }

    def _set_handler(
        self, token_stream: ITokenStream, stmt: Any, attr: str, nested: list
    ) -> None:
        """Store a handler body on *stmt*; a repeated phrase is merged.

        ``CALL ... ON EXCEPTION A ON EXCEPTION B`` repeats a phrase (invalid
        COBOL); the second body used to overwrite the first silently. Both
        bodies are kept, in order, and the repeat is reported.
        """
        existing = getattr(stmt, attr)
        if existing is None:
            if attr == "on_overflow":
                setattr(stmt, attr, nested if nested else [])
            else:
                setattr(stmt, attr, nested if nested else None)
            return
        existing.extend(nested or [])
        context = get_parse_context(token_stream)
        host = getattr(context, "host", None) if context is not None else None
        add_warning = getattr(host, "add_warning", None)
        if callable(add_warning):
            line = getattr(stmt.location, "line", None)
            where = f" (CALL at line {line})" if line else ""
            add_warning(
                f"Duplicate {self._HANDLER_PHRASES[attr]} phrase{where}: its "
                "statements were appended to the first handler"
            )

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

            # Check for [BY] REFERENCE|CONTENT|VALUE -- only overwrites the
            # mode established above/by a prior iteration when a mode word
            # is actually present; otherwise passing_mode carries over
            # unchanged (see the persistence note above the loop). BY is
            # optional in IBM's CALL syntax (``USING CONTENT X REFERENCE Y``),
            # as it is in the PROCEDURE DIVISION header, so a bare mode word
            # switches the mode too rather than being taken as an argument.
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
                # ``FUNCTION name(args)`` is one argument (#579): left to the
                # identifier path, FUNCTION became an argument of its own and
                # every later one moved a position right.
                function_arg = _consume_function_argument(token_stream)
                if function_arg is not None:
                    stmt.add_using_parameter(function_arg, passing_mode)
                    continue
                # A literal argument keeps its quotes (``BY CONTENT 'A'``
                # is not the data item A; ``X'00'`` is not ``00``).
                param_name = literal_operand_text(token) or "OMITTED"
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


def _consume_function_argument(token_stream: ITokenStream) -> str | None:
    """Consume ``FUNCTION name [(args)] [(refmod)]`` as one CALL argument.

    Returns the argument text in MOVE's source spelling
    (``FUNCTION UPPER-CASE(WS-NAME)``, ``FUNCTION CURRENT-DATE(1:8)``), or
    ``None`` -- consuming nothing -- when the next token is not ``FUNCTION``
    followed by a function name. Every directly following parenthesised
    group is folded in: an argument list and a reference modifier both
    belong to the function, and no next argument can start with ``(``.
    A literal inside the parentheses keeps its quotes. An unclosed ``(``
    stops at the first token that could never sit inside one rather than
    running on through later statements.
    """
    token = token_stream.peek()
    if token is None or token_value_upper(token) != "FUNCTION":
        return None
    name_tok, name_idx = peek_past_noise(token_stream, 1)
    if name_tok is None or name_tok.type != TokenType.IDENTIFIER:
        return None
    token_stream.consume()  # FUNCTION
    skip_whitespace(token_stream)
    token_stream.consume()  # the function name
    parts = ["FUNCTION", name_tok.value]
    depth = 0
    while not token_stream.is_empty():
        if depth > 0:
            skip_whitespace(token_stream)
        t = token_stream.peek()
        if t is None:
            break
        if depth == 0 and t.type != TokenType.LEFT_PAREN:
            break
        if depth > 0 and _looks_like_statement_boundary(t):
            break
        if t.type == TokenType.LEFT_PAREN:
            depth += 1
        elif t.type == TokenType.RIGHT_PAREN:
            depth -= 1
        parts.append(literal_operand_text(t))
        token_stream.consume()
    return join_source_parts(parts)
