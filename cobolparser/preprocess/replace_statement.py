"""COBOL source-text manipulation: the ``REPLACE`` compiler-directing statement
and stripping of un-expanded ``COPY`` statements.

Both are *text-manipulation* operations a real COBOL compiler applies to the
program's source text **before** the syntax analyser runs — analogous to the
COPY/REPLACE "text manipulation" phase in the standard. This module implements
the pieces the standalone (non-copybook-expanding) parse pipeline needs:

* :func:`apply_replace_statements` — applies ``REPLACE ==pseudo-text-1== BY
  ==pseudo-text-2==.`` (one or more operand pairs) and cancels them at
  ``REPLACE OFF.``. Matching is on the COBOL *text-word* stream: it is
  whitespace-, comma-, and semicolon-insensitive between words, so a
  multi-word / multi-line pseudo-text matches the source regardless of layout.
* :func:`strip_unexpanded_copy_statements` — blanks ``COPY`` statements the
  parser is **not** going to expand (``parse_cobol`` does not resolve
  copybooks) so their body — in particular a ``REPLACING ==pseudo-text==``
  operand that legally contains statement keywords and periods — never leaks
  into the token stream as a malformed statement. Reuses the same
  pseudo-text-aware :class:`CopyStatementLexer` the expansion path uses, so
  there is a single COPY parser rather than a divergent second one.

Both passes preserve the physical line count of their input (every newline in a
removed/replaced span is re-emitted) so downstream error line numbers stay
aligned with the normalized source.
"""

from .copy_statement_parser import CopyStatementLexer

# COBOL separators that are equivalent to a space when matching text words: the
# space, comma, and semicolon separators (plus the layout characters produced
# by ``normalize_fixed_format``). A separator period is handled specially — it
# is itself a text word — so it is deliberately absent here.
_WORD_SEPARATORS = frozenset(" \t\r\n,;")
_QUOTES = ("'", '"')
# A parenthesis is a separator AND a text word of its own (IBM "text words"),
# so ``WS-A(1)`` is the words ``WS-A`` ``(`` ``1`` ``)`` and ``==WS-A==``
# finds the subscripted reference too.
_PARENS = ("(", ")")


def _tokenize_text_words(text: str) -> list[tuple[str, int, int]]:
    """Split *text* into COBOL *text words* with their character offsets.

    A text word is one of:

    * a literal (``"..."`` / ``'...'``, doubled quotes kept intact) — one word;
    * a *separator period* (a ``.`` that is not a decimal point) — one word;
    * a parenthesis — one word;
    * otherwise a maximal run of non-separator characters.

    Space, comma, and semicolon separators are treated as equivalent to a
    single space and are not emitted, matching COBOL's rule that these
    separators are interchangeable for pseudo-text comparison.

    Returns a list of ``(word_text, start_index, end_index)`` tuples.
    """
    words: list[tuple[str, int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in _WORD_SEPARATORS:
            i += 1
            continue
        if c in _QUOTES:
            quote = c
            j = i + 1
            while j < n:
                if text[j] == quote:
                    if j + 1 < n and text[j + 1] == quote:
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            words.append((text[i:j], i, j))
            i = j
            continue
        if c == ".":
            # A bare period is a separator period (its own text word).
            words.append((".", i, i + 1))
            i += 1
            continue
        if c in _PARENS:
            words.append((c, i, i + 1))
            i += 1
            continue
        # Ordinary word: run until a separator, quote, parenthesis, or
        # separator period.
        j = i
        while j < n:
            cj = text[j]
            if cj in _WORD_SEPARATORS or cj in _QUOTES or cj in _PARENS:
                break
            if cj == ".":
                nxt = text[j + 1] if j + 1 < n else ""
                # Separator period (followed by whitespace / separator / end /
                # another period) ends the word; a decimal point mid-token
                # (``3.14``) stays part of the word.
                if nxt == "" or nxt in _WORD_SEPARATORS or nxt == ".":
                    break
            j += 1
        words.append((text[i:j], i, j))
        i = j
    return words


def _word_eq(source_word: str, find_word: str) -> bool:
    """Compare a source text word with a pattern text word.

    Non-literal COBOL words compare case-insensitively; literals compare
    exactly (COBOL alphanumeric literals are case-sensitive).
    """
    if source_word[:1] in _QUOTES or find_word[:1] in _QUOTES:
        return source_word == find_word
    return source_word.upper() == find_word.upper()


class _ReplacePair:
    """A single ``==find== BY ==replace==`` operand pair, pre-tokenized.

    ``partial_word`` is set for the IBM *partial-word* form ``==:TAG:==``:
    a pseudo-text that is a single word delimited by colons matches that
    text *inside* a source word (``:TAG:-ROWS`` -> ``WS-ROWS``), the way
    ``COPY ... REPLACING ==:TAG:==`` does. ``find_tokens`` is then empty.
    """

    __slots__ = ("find_tokens", "partial_word", "replace_text", "mode")

    def __init__(self, find_text: str, replace_text: str, mode: str = "ALL") -> None:
        self.find_tokens: list[str] = [w[0] for w in _tokenize_text_words(find_text)]
        self.partial_word: str | None = None
        # ``ALL`` (whole text words), ``LEADING`` or ``TRAILING``. For the
        # latter two ``partial_word`` holds the (upper-cased) single text word
        # compared against the leftmost / rightmost characters of each
        # non-literal source word.
        self.mode = mode
        if mode in ("LEADING", "TRAILING"):
            self.partial_word = self.find_tokens[0].upper()
            self.find_tokens = []
        elif (
            len(self.find_tokens) == 1
            and len(self.find_tokens[0]) > 2
            and self.find_tokens[0][0] == ":"
            and self.find_tokens[0][-1] == ":"
        ):
            self.partial_word = self.find_tokens[0].upper()
            self.find_tokens = []
        # Replacement is emitted verbatim as text words joined by single
        # spaces; a period token is joined without a leading space so a
        # sentence terminator stays attached, and so are parentheses on
        # both sides (``WS-B(2)`` stays ``WS-B(2)``).
        replace_tokens = [w[0] for w in _tokenize_text_words(replace_text)]
        parts: list[str] = []
        attach_next = False
        for tok in replace_tokens:
            if parts and (attach_next or tok in (".", "(", ")")):
                parts[-1] = parts[-1] + tok
            else:
                parts.append(tok)
            attach_next = tok == "("
        self.replace_text = " ".join(parts)


class _ReplaceStatement:
    """A parsed ``REPLACE`` compiler-directing statement occupying
    ``source[start:end]``. ``pairs`` is empty for ``REPLACE OFF.``."""

    __slots__ = ("start", "end", "pairs", "is_off")

    def __init__(
        self, start: int, end: int, pairs: list[_ReplacePair], is_off: bool
    ) -> None:
        self.start = start
        self.end = end
        self.pairs = pairs
        self.is_off = is_off


class _ReplaceScanner:
    """Locates ``REPLACE`` statements in a source string, skipping literals."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.pos = 0
        self.length = len(source)

    def _peek(self, offset: int = 0) -> str:
        idx = self.pos + offset
        return self.source[idx] if idx < self.length else ""

    def _skip_separators(self) -> None:
        while self.pos < self.length and self.source[self.pos] in " \t\r\n,;":
            self.pos += 1

    def _match_word(self, word: str) -> bool:
        """Match *word* (case-insensitive) at the current position with a word
        boundary, consuming it (and leading separators) on success."""
        start = self.pos
        self._skip_separators()
        end = self.pos + len(word)
        if self.source[self.pos : end].upper() == word.upper():
            nxt = self.source[end] if end < self.length else ""
            if not (nxt.isalnum() or nxt in ("-", "_")):
                self.pos = end
                return True
        self.pos = start
        return False

    def _read_pseudo_text(self) -> str | None:
        """At a ``==`` delimiter, read pseudo-text and return its content
        (without delimiters). Returns ``None`` if not positioned on ``==`` or
        the closing ``==`` is missing."""
        self._skip_separators()
        if self._peek() != "=" or self._peek(1) != "=":
            return None
        i = self.pos + 2
        content_start = i
        in_literal = ""
        while i < self.length:
            ch = self.source[i]
            if in_literal:
                if ch == in_literal:
                    if i + 1 < self.length and self.source[i + 1] == in_literal:
                        i += 2
                        continue
                    in_literal = ""
                i += 1
                continue
            if ch in _QUOTES:
                in_literal = ch
                i += 1
                continue
            if ch == "=" and i + 1 < self.length and self.source[i + 1] == "=":
                content = self.source[content_start:i]
                self.pos = i + 2
                return content
            i += 1
        return None

    def _parse_replace_at(self, start: int) -> _ReplaceStatement | None:
        """Try to parse a REPLACE statement whose ``REPLACE`` keyword has just
        been consumed (``self.pos`` points just past it). ``start`` is the index
        of the ``R`` in ``REPLACE``. Returns the statement or ``None`` when the
        text is not a well-formed REPLACE (leaving ``self.pos`` unchanged is the
        caller's responsibility)."""
        if self._match_word("OFF"):
            self._skip_separators()
            if self._peek() == ".":
                self.pos += 1
                return _ReplaceStatement(start, self.pos, [], is_off=True)
            return None

        pairs: list[_ReplacePair] = []
        while True:
            # ``LEADING`` / ``TRAILING`` (IBM, COBOL 2002) qualify one pair:
            # its pseudo-text-1 is then a single text word matched against
            # the start / end of each source word.
            mode = "ALL"
            if self._match_word("LEADING"):
                mode = "LEADING"
            elif self._match_word("TRAILING"):
                mode = "TRAILING"
            find_text = self._read_pseudo_text()
            if find_text is None:
                return None
            if not self._match_word("BY"):
                return None
            replace_text = self._read_pseudo_text()
            if replace_text is None:
                return None
            if mode != "ALL" and not _is_partial_operand(find_text, replace_text):
                return None
            pairs.append(_ReplacePair(find_text, replace_text, mode))

            self._skip_separators()
            if self._peek() == ".":
                self.pos += 1
                return _ReplaceStatement(start, self.pos, pairs, is_off=False)
            # Otherwise another operand pair must follow (its opening ``==``,
            # possibly qualified by LEADING / TRAILING).
            if not (self._peek() == "=" and self._peek(1) == "="):
                save = self.pos
                qualified = self._match_word("LEADING") or self._match_word("TRAILING")
                self.pos = save
                if not qualified:
                    return None

    def scan(self, warnings: list[str] | None = None) -> list[_ReplaceStatement]:
        """Return every well-formed REPLACE statement in the source. A
        ``REPLACE`` keyword that does not start a well-formed statement is
        reported on *warnings* (its substitutions would otherwise silently
        never happen) and otherwise left in place."""
        statements: list[_ReplaceStatement] = []
        while self.pos < self.length:
            ch = self.source[self.pos]
            # Skip over literals so a REPLACE inside a string is not matched.
            if ch in _QUOTES:
                quote = ch
                self.pos += 1
                while self.pos < self.length:
                    if self.source[self.pos] == quote:
                        if (
                            self.pos + 1 < self.length
                            and self.source[self.pos + 1] == quote
                        ):
                            self.pos += 2
                            continue
                        self.pos += 1
                        break
                    self.pos += 1
                continue
            # A `*>` inline comment (outside a literal) runs to end of line:
            # a REPLACE mentioned there is prose, not a statement.
            if ch == "*" and self._peek(1) == ">":
                newline = self.source.find("\n", self.pos)
                self.pos = self.length if newline == -1 else newline
                continue
            keyword_start = self.pos
            # Left word-boundary check so ``NOREPLACE`` is not matched.
            prev = self.source[keyword_start - 1] if keyword_start > 0 else ""
            if (not (prev.isalnum() or prev in ("-", "_"))) and self._match_word(
                "REPLACE"
            ):
                # Captured immediately after the keyword match so a rewind
                # can't land mid-word when separators preceded the keyword
                # (keyword_start may point at those separators).
                after_keyword = self.pos
                stmt = self._parse_replace_at(keyword_start)
                if stmt is not None:
                    statements.append(stmt)
                    continue
                # Not a well-formed REPLACE — rewind past the keyword only,
                # so the text _parse_replace_at consumed is re-scanned.
                if warnings is not None:
                    line = self.source.count("\n", 0, after_keyword) + 1
                    snippet = " ".join(
                        self.source[after_keyword - 7 : after_keyword + 50].split()
                    )
                    warnings.append(
                        f"Line {line}: REPLACE statement could not be parsed and "
                        f"was ignored -- its substitutions are NOT applied: "
                        f"{snippet!r}"
                    )
                self.pos = after_keyword
                continue
            self.pos += 1
        return statements


def _is_partial_operand(find_text: str, replace_text: str) -> bool:
    """A LEADING / TRAILING pair needs pseudo-text-1 to be exactly one
    non-literal text word, and pseudo-text-2 to be at most one."""
    find_words = [w[0] for w in _tokenize_text_words(find_text)]
    replace_words = [w[0] for w in _tokenize_text_words(replace_text)]
    return (
        len(find_words) == 1
        and find_words[0][:1] not in _QUOTES
        and len(replace_words) <= 1
    )


def _partial_replace(word: str, pair: _ReplacePair) -> str | None:
    """Return *word* rewritten by the partial-word *pair*, or ``None`` when the
    pair does not apply to it. A literal is never partially replaced."""
    pattern = pair.partial_word
    if pattern is None or word[:1] in _QUOTES:
        return None
    upper = word.upper()
    if pair.mode == "LEADING":
        if not upper.startswith(pattern):
            return None
        return pair.replace_text + word[len(pattern) :]
    if pair.mode == "TRAILING":
        if not upper.endswith(pattern):
            return None
        return word[: len(word) - len(pattern)] + pair.replace_text
    # ``==:TAG:==``: every occurrence inside the word (``:P:-A-:P:``).
    hit = upper.find(pattern)
    if hit < 0:
        return None
    pieces: list[str] = []
    pos = 0
    while hit >= 0:
        pieces.append(word[pos:hit])
        pieces.append(pair.replace_text)
        pos = hit + len(pattern)
        hit = upper.find(pattern, pos)
    pieces.append(word[pos:])
    return "".join(pieces)


def _blank_span(text: str) -> str:
    """Return *text* with every non-newline character replaced by a space, so a
    removed span keeps its exact line (and column) footprint."""
    return "".join(c if c in "\r\n" else " " for c in text)


def _apply_pairs_to_segment(segment: str, pairs: list[_ReplacePair]) -> str:
    """Apply the active REPLACE *pairs* to *segment* via a single left-to-right
    text-word scan (first matching pair wins at each position). Non-matched text
    — including all whitespace and newlines — is preserved verbatim; a replaced
    span re-emits its newline count so the line total is unchanged."""
    active = [p for p in pairs if p.find_tokens or p.partial_word]
    if not active:
        return segment
    words = _tokenize_text_words(segment)
    out: list[str] = []
    pos = 0
    wi = 0
    n_words = len(words)
    while wi < n_words:
        matched: _ReplacePair | None = None
        partial_text: str | None = None
        for pair in active:
            if pair.partial_word is not None:
                partial_text = _partial_replace(words[wi][0], pair)
                if partial_text is None:
                    continue
                matched = pair
                break
            flen = len(pair.find_tokens)
            if wi + flen > n_words:
                continue
            if all(
                _word_eq(words[wi + k][0], pair.find_tokens[k]) for k in range(flen)
            ):
                matched = pair
                break
        if matched is None:
            wi += 1
            continue
        if partial_text is not None:
            start_char, end_char = words[wi][1], words[wi][2]
            out.append(segment[pos:start_char])
            out.append(partial_text)
            pos = end_char
            wi += 1
            continue
        flen = len(matched.find_tokens)
        start_char = words[wi][1]
        end_char = words[wi + flen - 1][2]
        out.append(segment[pos:start_char])
        span = segment[start_char:end_char]
        out.append(matched.replace_text + "\n" * span.count("\n"))
        pos = end_char
        wi += flen
    out.append(segment[pos:])
    return "".join(out)


def apply_replace_statements(source: str, warnings: list[str] | None = None) -> str:
    """Apply COBOL ``REPLACE`` compiler-directing statements to *source*.

    ``REPLACE ==a== BY ==b== [==c== BY ==d== ...] .`` establishes a set of
    pseudo-text substitutions applied to all following source text until the
    next ``REPLACE`` statement or ``REPLACE OFF.``. Matching is on the text-word
    stream (whitespace / comma / semicolon insensitive). The ``REPLACE``
    statements themselves are removed. Line count is preserved.

    Args:
        source: Free-form COBOL source (post ``normalize_fixed_format``).
        warnings: Optional list; receives a diagnostic if a ``REPLACE`` set is
            still active at end of input (no closing ``REPLACE OFF.``), and
            one per ``REPLACE`` keyword that is not a well-formed statement.

    Returns:
        Source with all REPLACE substitutions applied and the statements removed.
    """
    if "REPLACE" not in source.upper():
        return source

    statements = _ReplaceScanner(source).scan(warnings)
    if not statements:
        return source

    out: list[str] = []
    cursor = 0
    active: list[_ReplacePair] = []
    for stmt in statements:
        # Emit the segment before this REPLACE statement with the currently
        # active substitutions applied.
        segment = source[cursor : stmt.start]
        out.append(_apply_pairs_to_segment(segment, active))
        # Remove the REPLACE statement itself (preserving its newlines).
        out.append(_blank_span(source[stmt.start : stmt.end]))
        active = [] if stmt.is_off else list(stmt.pairs)
        cursor = stmt.end

    out.append(_apply_pairs_to_segment(source[cursor:], active))
    if active and warnings is not None:
        warnings.append(
            "REPLACE statement set was still active at end of source "
            "(no closing 'REPLACE OFF.'); substitutions applied through EOF"
        )
    return "".join(out)


def strip_unexpanded_copy_statements(
    source: str, warnings: list[str] | None = None
) -> str:
    """Blank ``COPY`` statements that will not be expanded, preserving lines.

    In the standalone parse pipeline (``parse_cobol`` does not resolve
    copybooks) a ``COPY`` statement's text is not code the parser can use; worse,
    a ``COPY ... REPLACING ==pseudo-text==`` operand legally contains COBOL
    statement keywords and periods, which — left in the stream — are misparsed
    as malformed statements (e.g. ``BY MOVE`` leaking as a ``MOVE`` with no
    ``TO``). Removing the whole statement here mirrors what a compiler does when
    the copybook is unavailable: the text simply is not present.

    Reuses :class:`CopyStatementLexer` (the same pseudo-text-aware scanner the
    expansion path uses) so the statement span — including a REPLACING clause
    whose pseudo-text spans lines — is identified consistently.

    Args:
        source: Free-form COBOL source (post ``normalize_fixed_format``).
        warnings: Optional list; receives one diagnostic per removed COPY plus
            any diagnostics the lexer recorded for COPY statements it could not
            fully tokenize.

    Returns:
        Source with recognized COPY statements blanked. When no COPY statements
        are present the input string is returned unchanged.
    """
    if "COPY" not in source.upper():
        return source

    lexer = CopyStatementLexer(source, "<main>")
    statements = lexer.tokenize_copy_statements()
    if not statements:
        if warnings is not None and lexer.warnings:
            warnings.extend(lexer.warnings)
        return source

    # Blank each statement span in place; iterate so we can splice by index.
    pieces: list[str] = []
    cursor = 0
    for stmt in sorted(statements, key=lambda s: s.start_index):
        start, end = stmt.start_index, stmt.end_index
        if start < cursor:
            continue
        pieces.append(source[cursor:start])
        pieces.append(_blank_span(source[start:end]))
        cursor = end
        if warnings is not None:
            member = (stmt.member_name or "").strip()
            # Wording is path-neutral: this pass runs both when no copybook
            # path was configured AND when expansion ran but could not
            # resolve this member (missing file) — the caller can't tell
            # which from here.
            warnings.append(
                f"COPY {member} was not expanded; "
                "its content is omitted from the parsed program"
            )
    pieces.append(source[cursor:])
    if warnings is not None and lexer.warnings:
        warnings.extend(lexer.warnings)
    return "".join(pieces)


__all__ = [
    "apply_replace_statements",
    "strip_unexpanded_copy_statements",
]
