"""INITIALIZE and INSPECT statement parsers implementing IStatementParser."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import InitializeStatement, InspectStatement
from ._utils import (
    consume_optional_qualifiers,
    consume_period,
    is_statement_boundary,
    looks_dedented_relative_to,
    looks_like_paragraph_boundary,
    matches_keyword,
    peek_past_noise,
    skip_whitespace,
    starts_negative_handler_phrase,
    token_column,
    token_location,
    warn_paragraph_boundary_swallowed,
)
from ._utils import token_value_upper as _val

_REPLACING_CATEGORIES = frozenset(
    {
        "ALPHABETIC",
        "ALPHANUMERIC",
        "ALPHANUMERIC-EDITED",
        "NATIONAL",
        "NATIONAL-EDITED",
        "NUMERIC",
        "NUMERIC-EDITED",
        "DBCS",
        "EGCS",
    }
)
#: Words that end INITIALIZE's target list and start one of its phrases.
_INITIALIZE_PHRASE_STARTS = _REPLACING_CATEGORIES | {
    "REPLACING",
    "WITH",
    "ALL",
    "THEN",
    "TO",
}


class InitializeStatementParser(IStatementParser):
    """Parser for INITIALIZE statements.

    Syntax (IBM Enterprise COBOL 6)::

        INITIALIZE identifier-1 [identifier-2 ...]
            [WITH FILLER]
            [{ALL | category} TO VALUE]
            [THEN REPLACING {category [DATA] BY {value}} ...]
            [THEN TO DEFAULT]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.INITIALIZE, "INITIALIZE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> InitializeStatement:
        start = token_stream.consume()
        stmt = InitializeStatement(token_location(start))
        skip_whitespace(token_stream)

        # Collect target identifiers
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            val = _val(token)
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                return stmt
            if val in _INITIALIZE_PHRASE_STARTS:
                break
            # A following statement's verb that lexes as a plain IDENTIFIER
            # (e.g. PURGE/RAISE/RESUME have no dedicated TokenType) must not
            # be folded into the target list when INITIALIZE has no trailing
            # period.
            if token.type == TokenType.IDENTIFIER and is_statement_boundary(token):
                break
            if token.type == TokenType.COMMA:
                # A comma between targets (`INITIALIZE a, b, c`) is a
                # separator, not a terminator -- skip it and keep collecting
                # targets, mirroring the MOVE/SET parsers' target-list
                # handling.
                token_stream.consume()
                skip_whitespace(token_stream)
                continue
            if token.type == TokenType.IDENTIFIER:
                token_stream.consume()
                # Fold a subscript / OF-IN qualifier chain into the target
                # (`INITIALIZE TBL (I) B OF C`) instead of stranding it as
                # unparsed trailing tokens.
                stmt.add_target(
                    consume_optional_qualifiers(token_stream, token.value or "")
                )
            elif token.type == TokenType.STRING_LITERAL:
                token_stream.consume()
                stmt.add_target(token.value or "")
            else:
                break
            skip_whitespace(token_stream)

        # Optional WITH FILLER clause
        token = token_stream.peek()
        if token and _val(token) == "WITH":
            token_stream.consume()
            skip_whitespace(token_stream)
            nxt = token_stream.peek()
            if nxt and _val(nxt) == "FILLER":
                token_stream.consume()
                stmt.with_filler = True
                skip_whitespace(token_stream)

        # Optional ``{ALL | category} TO VALUE`` phrase
        token = token_stream.peek()
        if token and _val(token) in _REPLACING_CATEGORIES | {"ALL"}:
            nxt = token_stream.peek(1)
            after = token_stream.peek(2)
            if nxt and _val(nxt) == "TO" and after and _val(after) == "VALUE":
                stmt.to_value_category = _val(token)
                for _ in range(3):
                    token_stream.consume()
                skip_whitespace(token_stream)

        # Optional [THEN] REPLACING clauses
        if self._match_then(token_stream, "REPLACING"):
            token_stream.consume()
            skip_whitespace(token_stream)
            self._parse_replacing(token_stream, stmt)

        # Optional [THEN] TO DEFAULT
        if self._match_then(token_stream, "TO"):
            nxt = token_stream.peek(1)
            if nxt and _val(nxt) == "DEFAULT":
                token_stream.consume()
                token_stream.consume()
                stmt.to_default = True
                skip_whitespace(token_stream)

        consume_period(token_stream)
        return stmt

    @staticmethod
    def _match_then(ts: ITokenStream, keyword: str) -> bool:
        """Consume an optional ``THEN`` when *keyword* follows it; report
        whether *keyword* is now the next token (left unconsumed)."""
        token = ts.peek()
        if token and _val(token) == "THEN":
            nxt = ts.peek(1)
            if not nxt or _val(nxt) != keyword:
                return False
            ts.consume()
            skip_whitespace(ts)
            token = ts.peek()
        return bool(token and _val(token) == keyword)

    def _parse_replacing(self, ts: ITokenStream, stmt: InitializeStatement) -> None:
        while not ts.is_empty():
            token = ts.peek()
            if not token:
                break
            val = _val(token)
            if token.type == TokenType.PERIOD:
                break
            if val in _REPLACING_CATEGORIES:
                category = val
                ts.consume()
                skip_whitespace(ts)
                # Optional DATA keyword
                nxt = ts.peek()
                if nxt and _val(nxt) == "DATA":
                    ts.consume()
                    skip_whitespace(ts)
                # Expect BY
                nxt = ts.peek()
                if nxt and _val(nxt) == "BY":
                    ts.consume()
                    skip_whitespace(ts)
                # Value
                nxt = ts.peek()
                if nxt and nxt.type != TokenType.PERIOD:
                    ts.consume()
                    by_value = nxt.value or ""
                    if nxt.type == TokenType.IDENTIFIER:
                        # `BY WS-X OF GRP` / `BY TBL (I)`: a qualified or
                        # subscripted sending item is one value.
                        by_value = consume_optional_qualifiers(ts, by_value)
                    stmt.add_replacing_clause(category, by_value)
                skip_whitespace(ts)
            else:
                break


#: Token types an INSPECT operand (the thing tallied / replaced / the
#: replacement) may take.
_INSPECT_LITERAL_TOKEN_TYPES = frozenset(
    {
        TokenType.STRING_LITERAL,
        TokenType.NUMERIC_LITERAL,
        TokenType.FIGURATIVE_CONSTANT,
    }
)
_INSPECT_VALUE_TOKEN_TYPES = _INSPECT_LITERAL_TOKEN_TYPES | {TokenType.IDENTIFIER}
#: Words that start the next REPLACING/TALLYING phrase -- never an operand.
_INSPECT_KEYWORDS = frozenset(
    {
        "ALL",
        "LEADING",
        "FIRST",
        "CHARACTERS",
        "BEFORE",
        "AFTER",
        "REPLACING",
        "TALLYING",
        "CONVERTING",
        "BY",
        "TO",
    }
)


class InspectStatementParser(IStatementParser):
    """Parser for INSPECT statements.

    Syntax:
        INSPECT identifier TALLYING ...
        INSPECT identifier REPLACING ...
        INSPECT identifier CONVERTING from TO to
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.INSPECT, "INSPECT")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> InspectStatement:
        start = token_stream.consume()
        stmt = InspectStatement(token_location(start))
        start_column = token_column(start)
        skip_whitespace(token_stream)

        # Target identifier -- with its subscript / reference modification /
        # OF-IN qualifier chain folded in, the way MOVE/READ/WRITE read
        # theirs. Reading it as one token left ``(1:5)`` in the stream, and
        # the TALLYING/REPLACING dispatch below (which expects a keyword
        # next) then silently dropped the whole clause.
        token = token_stream.peek()
        if token and token.type not in (TokenType.PERIOD, None):
            token_stream.consume()
            target = token.value or ""
            if token.type == TokenType.IDENTIFIER:
                target = consume_optional_qualifiers(token_stream, target)
            stmt.set_target(target)
        skip_whitespace(token_stream)

        # Determine type
        token = token_stream.peek()
        if not token:
            return stmt

        val = _val(token)
        if val == "TALLYING":
            stmt.set_inspect_type("TALLYING")
            token_stream.consume()
            skip_whitespace(token_stream)
            self._parse_tallying(token_stream, stmt, start_column)
        elif val == "REPLACING":
            stmt.set_inspect_type("REPLACING")
            token_stream.consume()
            skip_whitespace(token_stream)
            self._parse_replacing(token_stream, stmt)
        elif val == "CONVERTING":
            stmt.set_inspect_type("CONVERTING")
            token_stream.consume()
            skip_whitespace(token_stream)
            self._parse_converting(token_stream, stmt)

        # Consume to period
        while not token_stream.is_empty():
            t = token_stream.peek()
            if not t:
                break
            if t.type == TokenType.PERIOD:
                token_stream.consume()
                break
            # Check for REPLACING after TALLYING
            if _val(t) == "REPLACING" and stmt.inspect_type == "TALLYING":
                stmt.set_inspect_type("TALLYING_REPLACING")
                token_stream.consume()
                skip_whitespace(token_stream)
                self._parse_replacing(token_stream, stmt)
                continue
            # No trailing period before the next statement: stop rather than
            # swallow it (audit 2026-07-06 H2). Without this, the loop ran to
            # the next period and ate every intervening statement.
            if is_statement_boundary(t):
                break
            # An enclosing statement's ``NOT AT END`` / ``NOT INVALID KEY``
            # / ``NOT ON EXCEPTION``: INSPECT has no such phrase, and eating
            # it here lost the enclosing handler.
            if starts_negative_handler_phrase(token_stream):
                break
            # A missing period on this INSPECT followed by what looks like
            # the next paragraph/section header (H9): stop instead of
            # silently discarding it in this "consume to period" trailer.
            if (
                t.type == TokenType.IDENTIFIER
                and looks_like_paragraph_boundary(token_stream)
                and looks_dedented_relative_to(token_stream, start_column)
            ):
                warn_paragraph_boundary_swallowed(token_stream)
                break
            token_stream.consume()
            skip_whitespace(token_stream)

        return stmt

    def _parse_tallying(
        self,
        ts: ITokenStream,
        stmt: InspectStatement,
        reference_column: int | None = None,
    ) -> None:
        """Parse TALLYING clauses: counter FOR {CHARACTERS|ALL|LEADING} [value] ..."""
        while not ts.is_empty():
            token = ts.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                break
            val = _val(token)
            if val == "REPLACING":
                break

            if token.type != TokenType.IDENTIFIER:
                break
            # A following statement's verb that lexes as a plain IDENTIFIER
            # (e.g. PURGE/RAISE/RESUME have no dedicated TokenType) must not
            # be mistaken for the next TALLYING counter name.
            if is_statement_boundary(token):
                break
            # A missing period on this INSPECT followed by what looks like
            # the next paragraph/section header (H9): stop instead of
            # mistaking it for a TALLYING counter name -- for any counter in
            # the clause, not just the first, so a counter name that merely
            # wraps onto its own continuation line isn't dropped. The
            # "consume to period" trailer in parse() re-checks this same
            # token and owns the warning, so this just needs to break, not
            # warn.
            if looks_like_paragraph_boundary(ts) and looks_dedented_relative_to(
                ts, reference_column
            ):
                break

            # Counter name (a subscripted / qualified counter folded in, or
            # its ``(1)`` would stand where FOR is expected)
            ts.consume()
            counter = consume_optional_qualifiers(ts, token.value or "")
            skip_whitespace(ts)

            # Expect FOR
            nxt = ts.peek()
            if not nxt or _val(nxt) != "FOR":
                # Put counter in as a basic clause
                stmt.add_tallying_clause(counter, "CHARACTERS")
                break
            ts.consume()
            skip_whitespace(ts)

            # Parse FOR type
            nxt = ts.peek()
            if not nxt:
                break
            for_type = _val(nxt)
            if for_type in ("CHARACTERS", "ALL", "LEADING"):
                ts.consume()
                skip_whitespace(ts)

                value = None
                if for_type != "CHARACTERS":
                    value = self._consume_inspect_value(ts)

                # Optional BEFORE [INITIAL] ... AFTER [INITIAL] ... -- a single
                # FOR-phrase may carry both qualifiers simultaneously.
                before, after = self._parse_before_after(ts)

                stmt.add_tallying_clause(counter, for_type, value, before, after)

                # ``FOR ALL 'X' 'Y'``: further *literal* values under the same
                # ALL/LEADING each get their own clause. Only literals are
                # taken -- an IDENTIFIER here is the next counter name.
                while for_type != "CHARACTERS":
                    extra = ts.peek()
                    if not (extra and extra.type in _INSPECT_LITERAL_TOKEN_TYPES):
                        break
                    ts.consume()
                    skip_whitespace(ts)
                    before, after = self._parse_before_after(ts)
                    stmt.add_tallying_clause(
                        counter, for_type, extra.value, before, after
                    )
            else:
                break

    def _parse_replacing(self, ts: ITokenStream, stmt: InspectStatement) -> None:
        """Parse REPLACING clauses."""
        while not ts.is_empty():
            token = ts.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                break
            val = _val(token)
            if val in ("CHARACTERS", "ALL", "LEADING", "FIRST"):
                replace_type = val
                ts.consume()
                skip_whitespace(ts)

                # ``CHARACTERS BY x`` has no search operand; recording the
                # keyword as one read it as a (nonexistent) data item. None,
                # like TALLYING ``FOR CHARACTERS``'s ``value``.
                from_value: str | None = None
                if replace_type != "CHARACTERS":
                    from_value = self._consume_inspect_value(ts) or ""

                # Expect BY
                to_value = self._consume_by_value(ts)

                # Optional BEFORE [INITIAL] ... AFTER [INITIAL] ... -- a single
                # REPLACING phrase may carry both qualifiers simultaneously.
                before, after = self._parse_before_after(ts)

                stmt.add_replacing_clause(
                    replace_type, from_value, to_value, before, after
                )

                # ``ALL 'A' BY 'B' 'C' BY 'D'``: further ``from BY to`` pairs
                # under the same ALL/LEADING/FIRST. A pair is only taken when
                # a BY actually follows the candidate value, so the next
                # keyword (or a stray token) is left for the loop head.
                while replace_type != "CHARACTERS":
                    nxt = ts.peek()
                    if not (nxt and nxt.type in _INSPECT_VALUE_TOKEN_TYPES):
                        break
                    if _val(nxt) in _INSPECT_KEYWORDS:
                        break
                    if not self._by_follows_value(ts):
                        break
                    from_value = self._consume_inspect_value(ts) or ""
                    to_value = self._consume_by_value(ts)
                    before, after = self._parse_before_after(ts)
                    stmt.add_replacing_clause(
                        replace_type, from_value, to_value, before, after
                    )
            else:
                break

    @staticmethod
    def _consume_inspect_value(ts: ITokenStream) -> str | None:
        """One TALLYING/REPLACING operand: a literal, a figurative constant
        (``SPACES``/``ZEROS``/... lex as FIGURATIVE_CONSTANT and were
        previously rejected, leaving ``LEADING SPACES BY ZEROS`` with empty
        from/to values), or an identifier with its subscript / qualifier
        chain folded in. Returns None (consuming nothing) otherwise."""
        v = ts.peek()
        if not (v and v.type in _INSPECT_VALUE_TOKEN_TYPES):
            return None
        ts.consume()
        value = v.value or ""
        if v.type == TokenType.IDENTIFIER:
            value = consume_optional_qualifiers(ts, value)
        skip_whitespace(ts)
        return value

    def _consume_by_value(self, ts: ITokenStream) -> str:
        """``BY <value>`` -- the replacement operand; "" when BY is absent."""
        nxt = ts.peek()
        if not (nxt and _val(nxt) == "BY"):
            return ""
        ts.consume()
        skip_whitespace(ts)
        return self._consume_inspect_value(ts) or ""

    @staticmethod
    def _by_follows_value(ts: ITokenStream) -> bool:
        """True when the value at the current position (possibly subscripted
        or qualified) is followed by ``BY`` -- i.e. it starts another
        ``from BY to`` pair rather than something else."""
        i = 1
        depth = 0
        while True:
            tok, i = peek_past_noise(ts, i)
            if tok is None:
                return False
            if tok.type == TokenType.LEFT_PAREN:
                depth += 1
            elif tok.type == TokenType.RIGHT_PAREN:
                depth -= 1
            elif depth == 0:
                if _val(tok) in ("OF", "IN"):
                    i += 1
                    tok, i = peek_past_noise(ts, i)
                    if tok is None:
                        return False
                else:
                    return _val(tok) == "BY"
            elif depth < 0:
                return False
            i += 1

    def _parse_before_after(self, ts: ITokenStream) -> tuple[str | None, str | None]:
        """Parse an optional ``BEFORE [INITIAL] ... AFTER [INITIAL] ...`` suffix.

        The COBOL standard allows a single TALLYING/REPLACING phrase to carry
        BOTH a BEFORE and an AFTER qualifier at once, and IBM Enterprise
        COBOL permits them in either order -- so this loops until neither
        qualifier matches (each captured at most once) instead of checking a
        fixed BEFORE-then-AFTER sequence.
        """
        before: str | None = None
        after: str | None = None
        while True:
            p = ts.peek()
            qualifier = _val(p) if p else ""
            if not (
                (qualifier == "BEFORE" and before is None)
                or (qualifier == "AFTER" and after is None)
            ):
                break
            ts.consume()
            skip_whitespace(ts)
            p = ts.peek()
            if p and _val(p) == "INITIAL":
                ts.consume()
                skip_whitespace(ts)
            # The delimiter may be a figurative constant (``BEFORE INITIAL
            # SPACE``) or a subscripted/qualified identifier; accepting only
            # a bare identifier/literal left SPACE (or ``(2)``) in the stream,
            # and the TALLYING loop then silently dropped every later
            # counter clause.
            value = self._consume_inspect_value(ts)
            if value is not None:
                if qualifier == "BEFORE":
                    before = value
                else:
                    after = value
            else:
                # Qualifier with no value (malformed) -- stop rather than
                # loop forever on the same unconsumable token.
                break
        return before, after

    def _parse_converting(self, ts: ITokenStream, stmt: InspectStatement) -> None:
        """Parse CONVERTING from TO to [BEFORE|AFTER [INITIAL] delimiter]...

        Operands go through the same reader TALLYING/REPLACING use, so a
        subscripted / qualified identifier or a figurative constant is taken
        whole rather than dropping the clause, and the BEFORE/AFTER phrase
        is kept instead of being skipped by the trailer in ``parse()``."""
        from_val = self._consume_inspect_value(ts)
        if from_val is None:
            return
        nxt = ts.peek()
        if not (nxt and _val(nxt) == "TO"):
            return
        ts.consume()
        skip_whitespace(ts)
        to_val = self._consume_inspect_value(ts)
        if to_val is None:
            return
        stmt.set_converting(from_val, to_val)
        before, after = self._parse_before_after(ts)
        stmt.converting_before = before
        stmt.converting_after = after
