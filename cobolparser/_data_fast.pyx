# cython: language_level=3
"""Cython-accelerated parser-side hot paths for the Data Division.

Currently provides two helpers:

* :func:`parse_picture_clause_fast`, which mirrors
  :meth:`DataDivisionParser._parse_picture_clause` but operates
  directly on the underlying token list and cursor index. This
  sidesteps the Python-level overhead of repeated
  ``token_stream.peek()`` / ``.consume()`` / ``.is_empty()`` calls in
  the inner loop that walks every token of every PICTURE clause.
* :func:`parse_data_item_clauses_fast`, which accelerates the
  per-clause loop of :meth:`DataDivisionParser._parse_data_item` using
  the same token-list-and-cursor approach.

The pure-Python implementation in
``cobolparser.parsers.divisions.data`` remains the authoritative
behaviour; this module is imported transparently when compiled and
falls back to the pure-Python path otherwise.
"""

cimport cython


def parse_picture_clause_fast(
    list tokens,
    int pos,
    object pic_terminator_keywords,
    object pic_pattern_token_types,
    object comp_token_types,
    object period_type,
    object newline_type,
):
    """Parse a PICTURE pattern starting at ``tokens[pos]``.

    Returns ``(pattern_or_None, new_pos)`` where ``pattern`` is the
    concatenated PIC string (e.g. ``"X(10)"``, ``"9(7)V99"``) or
    ``None`` if no pattern tokens were collected.

    The token-type constants (``period_type``, ``newline_type`` etc.)
    are passed in rather than imported so that the build does not
    depend on importing ``cobolparser.lexer.TokenType`` at module load
    time. The caller already has them as locals.
    """
    cdef int n = len(tokens)
    cdef int paren_depth = 0
    cdef list parts = []
    cdef str token_value
    cdef object token
    cdef object tok_type
    cdef str value_upper

    while pos < n:
        token = tokens[pos]
        if token is None:
            break

        tok_type = token.type
        token_value = token.value

        # Stop at specific keywords when outside parentheses
        if paren_depth == 0:
            if tok_type is period_type:
                break
            if token_value:
                value_upper = token_value.upper()
                if value_upper in pic_terminator_keywords:
                    break
            if tok_type in comp_token_types:
                break

        # Collect picture pattern tokens
        if tok_type in pic_pattern_token_types:
            if paren_depth == 0 and token_value.endswith("."):
                parts.append(token_value[:-1])
                pos += 1
                break
            parts.append(token_value)
            pos += 1
        elif token_value == "(":
            parts.append(token_value)
            paren_depth += 1
            pos += 1
        elif token_value == ")":
            parts.append(token_value)
            paren_depth -= 1
            pos += 1
        elif token_value == ",":
            parts.append(token_value)
            pos += 1
        elif tok_type is newline_type:
            pos += 1
        else:
            break

    if parts:
        return "".join(parts), pos
    return None, pos


def parse_data_item_clauses_fast(
    list tokens,
    int pos,
    object data_item,
    object location,
    object parser_self,
    object token_stream,
    object pic_terminator_keywords,
    object pic_pattern_token_types,
    object comp_keywords,
    object comp_token_types,
    object division_token_types,
    object picture_clause_cls,
    object occurs_clause_cls,
    object period_type,
    object level_number_type,
    object identifier_type,
    object numeric_literal_type,
    object newline_type,
):
    """Drive the per-clause loop of :meth:`_parse_data_item`.

    All simple clauses (PICTURE, VALUE-keyword/COMP-keyword/REDEFINES,
    OCCURS) are handled directly against the token list. The two
    clauses that require sub-parsing -- VALUE and USAGE -- delegate
    back to ``parser_self._parse_value_clause`` /
    ``parser_self._parse_usage_clause`` after syncing the stream
    cursor, so error-reporting and clause-specific behaviour stay in
    one place.

    Returns the updated ``pos``.
    """
    cdef int n = len(tokens)
    cdef object token
    cdef object tok_type
    cdef str tok_value
    cdef str value_upper
    cdef int min_count
    cdef int max_count
    cdef object occurs
    cdef object nxt
    cdef object count_token
    cdef object max_token
    cdef object on_token
    cdef object dep_token
    cdef object by_token
    cdef object idx_token
    cdef object redef_token
    cdef str depending_var
    cdef bint has_depending

    while pos < n:
        token = tokens[pos]
        if token is None:
            break

        tok_type = token.type

        # Period ends this data item. Leave it unconsumed and hand back to
        # the pure-Python loop, which consumes the terminator itself. This
        # keeps the two loops symmetric whether the fast loop ran to the end
        # of the item or bailed early on a clause it does not handle.
        if tok_type is period_type:
            break

        # Level number starts next item
        if tok_type is level_number_type:
            break

        # Division tokens end this data item (don't consume them)
        if tok_type in division_token_types:
            break

        tok_value = token.value
        value_upper = tok_value.upper() if tok_value else ""

        # PICTURE / PIC clause -- delegate to the Python helper (the single
        # source of truth for picture extraction, including edited pictures
        # with embedded decimal points and currency/sign symbols).
        if value_upper == "PICTURE" or value_upper == "PIC":
            pos += 1  # consume PIC keyword
            token_stream._pos = pos
            pattern = parser_self._parse_picture_clause(token_stream)
            pos = token_stream._pos
            if pattern:
                data_item.set_picture_clause(picture_clause_cls(pattern, location))
            continue

        # VALUE clause -- delegate to Python helper (handles literals,
        # figurative constants, complex 88-style value lists).
        if value_upper == "VALUE":
            pos += 1  # consume VALUE keyword
            token_stream._pos = pos
            value = parser_self._parse_value_clause(token_stream)
            pos = token_stream._pos
            if value:
                data_item.set_value_clause(value)
            continue

        # USAGE clause -- same: delegate to Python helper.
        if value_upper == "USAGE":
            pos += 1  # consume USAGE keyword
            token_stream._pos = pos
            usage = parser_self._parse_usage_clause(token_stream)
            pos = token_stream._pos
            if usage:
                data_item.set_usage(usage)
            continue

        # COMP, COMP-3, etc. without USAGE keyword (str form)
        if value_upper in comp_keywords:
            data_item.set_usage(value_upper)
            pos += 1
            continue

        # COMP token types (COMP_1, COMP_2, ...)
        if tok_type in comp_token_types:
            data_item.set_usage(tok_value.upper())
            pos += 1
            continue

        # REDEFINES clause
        if value_upper == "REDEFINES":
            pos += 1  # consume REDEFINES
            if pos < n:
                redef_token = tokens[pos]
                if redef_token is not None and redef_token.type is identifier_type:
                    data_item.set_redefines(redef_token.value)
                    pos += 1
            continue

        # OCCURS clause -- walk it inline; pure token-driven, no
        # sub-parsing callbacks needed.
        if value_upper == "OCCURS":
            pos += 1  # consume OCCURS
            occurs = occurs_clause_cls(location)
            min_count = 0
            max_count = 0

            if pos < n:
                count_token = tokens[pos]
                if count_token is not None and count_token.type in (
                    numeric_literal_type,
                    level_number_type,
                ):
                    try:
                        min_count = int(count_token.value)
                        max_count = min_count
                    except (TypeError, ValueError):
                        pass
                    pos += 1

            # Variable OCCURS: OCCURS min TO max
            if pos < n:
                nxt = tokens[pos]
                if (
                    nxt is not None
                    and nxt.value
                    and nxt.value.upper() == "TO"
                ):
                    pos += 1  # consume TO
                    if pos < n:
                        max_token = tokens[pos]
                        if max_token is not None and max_token.type in (
                            numeric_literal_type,
                            level_number_type,
                        ):
                            try:
                                max_count = int(max_token.value)
                            except (TypeError, ValueError):
                                max_count = min_count
                            pos += 1

            # Skip newlines, optional TIMES keyword
            while pos < n and tokens[pos] is not None and tokens[pos].type is newline_type:
                pos += 1
            if pos < n:
                nxt = tokens[pos]
                if nxt is not None and nxt.value and nxt.value.upper() == "TIMES":
                    pos += 1

            # DEPENDING ON clause
            depending_var = ""
            has_depending = False
            while pos < n and tokens[pos] is not None and tokens[pos].type is newline_type:
                pos += 1
            if pos < n:
                nxt = tokens[pos]
                if nxt is not None and nxt.value and nxt.value.upper() == "DEPENDING":
                    pos += 1
                    if pos < n:
                        on_token = tokens[pos]
                        if on_token is not None and on_token.value and on_token.value.upper() == "ON":
                            pos += 1
                    if pos < n:
                        dep_token = tokens[pos]
                        if dep_token is not None and dep_token.type is identifier_type:
                            depending_var = dep_token.value
                            has_depending = True
                            pos += 1

            # ASCENDING / DESCENDING KEY IS key-1 [key-2 ...] clauses (may
            # repeat). These sit between DEPENDING ON and INDEXED BY and are
            # what make a table valid for SEARCH ALL; dropping them lost real
            # semantics and previously also cascaded into dropping INDEXED BY.
            while pos < n and tokens[pos] is not None and tokens[pos].type is newline_type:
                pos += 1
            while (
                pos < n
                and tokens[pos] is not None
                and tokens[pos].value
                and tokens[pos].value.upper() in ("ASCENDING", "DESCENDING")
            ):
                direction = tokens[pos].value.upper()
                pos += 1  # consume ASCENDING/DESCENDING
                while pos < n and tokens[pos] is not None and tokens[pos].type is newline_type:
                    pos += 1
                if pos < n and tokens[pos] is not None and tokens[pos].value and tokens[pos].value.upper() == "KEY":
                    pos += 1
                while pos < n and tokens[pos] is not None and tokens[pos].type is newline_type:
                    pos += 1
                if pos < n and tokens[pos] is not None and tokens[pos].value and tokens[pos].value.upper() == "IS":
                    pos += 1
                keys = []
                while True:
                    while pos < n and tokens[pos] is not None and tokens[pos].type is newline_type:
                        pos += 1
                    if (
                        pos < n
                        and tokens[pos] is not None
                        and tokens[pos].type is identifier_type
                        and tokens[pos].value
                        and tokens[pos].value.upper() not in ("ASCENDING", "DESCENDING", "INDEXED", "KEY")
                    ):
                        keys.append(tokens[pos].value)
                        pos += 1
                    else:
                        break
                if keys:
                    occurs.add_key_clause(direction, keys)
                while pos < n and tokens[pos] is not None and tokens[pos].type is newline_type:
                    pos += 1

            # INDEXED BY clause (one or more index names)
            while pos < n and tokens[pos] is not None and tokens[pos].type is newline_type:
                pos += 1
            if pos < n:
                nxt = tokens[pos]
                if nxt is not None and nxt.value and nxt.value.upper() == "INDEXED":
                    pos += 1
                    if pos < n:
                        by_token = tokens[pos]
                        if by_token is not None and by_token.value and by_token.value.upper() == "BY":
                            pos += 1
                    while True:
                        while pos < n and tokens[pos] is not None and tokens[pos].type is newline_type:
                            pos += 1
                        if pos < n and tokens[pos] is not None and tokens[pos].type is identifier_type:
                            occurs.add_index_name(tokens[pos].value)
                            pos += 1
                        else:
                            break

            if has_depending:
                occurs.set_variable_occurs(min_count, max_count, depending_var)
            else:
                occurs.set_fixed_occurs(max_count)

            if occurs.max_times is not None:
                data_item.set_occurs_clause(occurs)
            continue

        # NEWLINE is whitespace -- consume it cheaply and keep going.
        if tok_type is newline_type:
            pos += 1
            continue

        # Any other token is a clause this fast loop does not handle
        # (SIGN, SYNCHRONIZED, JUSTIFIED, BLANK, bare POINTER, EXTERNAL,
        # GLOBAL, ...). Stop here without consuming it and hand control
        # back to the pure-Python loop in ``_parse_data_item``, which is
        # the single source of truth for those clauses. This avoids
        # duplicating (and re-drifting) the clause logic across the two
        # implementations.
        break

    return pos
