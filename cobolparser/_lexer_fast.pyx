# cython: language_level=3
"""Cython-accelerated hot-path methods for the COBOL lexer.

Subclasses the pure-Python CobolLexer and overrides the three innermost
hot-path methods with Cython-typed implementations:

  - check_division_header   guarded by first-char pre-check (~95% skip rate)
  - read_word_from_text     list+join instead of O(n^2) += concatenation
  - tokenize_program_text   C-typed loop counters, digit lookahead fixed

Imported transparently by lexer.py; pure-Python fallback used when not compiled.
"""

cimport cython

import sys

from cobolparser.lexer import (
    _CobolLexerPure as _CobolLexerBase,
    Token,
    TokenType,
    LexerError,
    _LEVEL_NUM_RE,
    _LEVEL_NUMBER_1_2DIGIT_RE,
    _FF_INDICATOR,
    _DIVISION_FIRST,
)
from cobolparser.models.ast_base import SourceLocation


# Pre-computed lengths of division keyword prefixes
_DIV_IDENTIFICATION_LEN = len("IDENTIFICATION")
_DIV_ID_LEN             = len("ID")
_DIV_ENVIRONMENT_LEN    = len("ENVIRONMENT")
_DIV_DATA_LEN           = len("DATA")
_DIV_PROCEDURE_LEN      = len("PROCEDURE")


class CobolLexer(_CobolLexerBase):
    """Cython-accelerated COBOL lexer; drop-in replacement for the pure-Python version."""

    # ------------------------------------------------------------------
    # check_division_header
    # ------------------------------------------------------------------
    def check_division_header(self, str text, int start_pos):
        """Return (token_type, end_pos) if text[start_pos:] starts a division header."""
        cdef int length = len(text)

        if start_pos >= length:
            return None, start_pos

        # Fast first-char guard: ~95% of words are not division headers.
        if text[start_pos] not in _DIVISION_FIRST:
            return None, start_pos

        remaining = text[start_pos:start_pos + 24].upper()

        if remaining.startswith("IDENTIFICATION DIVISION"):
            return TokenType.IDENTIFICATION_DIVISION, start_pos + _DIV_IDENTIFICATION_LEN
        if remaining.startswith("ID DIVISION"):
            return TokenType.IDENTIFICATION_DIVISION, start_pos + _DIV_ID_LEN
        if remaining.startswith("ENVIRONMENT DIVISION"):
            return TokenType.ENVIRONMENT_DIVISION, start_pos + _DIV_ENVIRONMENT_LEN
        if remaining.startswith("DATA DIVISION"):
            return TokenType.DATA_DIVISION, start_pos + _DIV_DATA_LEN
        if remaining.startswith("PROCEDURE DIVISION"):
            return TokenType.PROCEDURE_DIVISION, start_pos + _DIV_PROCEDURE_LEN

        return None, start_pos

    # ------------------------------------------------------------------
    # read_word_from_text
    # ------------------------------------------------------------------
    def read_word_from_text(self, str text, int start_pos, int line_num, int start_col):
        """Read one identifier or keyword token; O(n) via list+join."""
        cdef int pos    = start_pos
        cdef int length = len(text)
        cdef str char
        cdef list parts

        location = SourceLocation(line_num + 1, start_col + start_pos, 1)

        # Division-header check only when first char could be a division name
        if pos < length and text[pos] in _DIVISION_FIRST:
            division_type, division_end = self.check_division_header(text, start_pos)
            if division_type is not None:
                division_word = text[start_pos:division_end].strip().split()[0]
                return Token(division_type, division_word, location), division_end

        # Accumulate chars into a list; join once at the end (avoids O(n^2))
        parts = []
        while pos < length:
            char = text[pos]
            if char.isalnum() or char == "-" or char == "_":
                parts.append(char)
                pos += 1
            else:
                break

        value       = "".join(parts)
        upper_value = sys.intern(value.upper())

        if upper_value in self.KEYWORDS:
            token_type = self.KEYWORDS[upper_value]
        elif upper_value in self.FIGURATIVE_CONSTANTS:
            token_type = TokenType.FIGURATIVE_CONSTANT
        elif _LEVEL_NUM_RE.match(value):
            token_type = TokenType.LEVEL_NUMBER
        else:
            token_type = TokenType.IDENTIFIER

        return Token(token_type, value, location), pos

    # ------------------------------------------------------------------
    # tokenize  (outer per-line loop)
    # ------------------------------------------------------------------
    def tokenize(self):
        """Tokenize the entire COBOL source code.

        Mirrors the pure-Python implementation but with C-typed loop
        counters and direct list operations to remove the per-line Python
        overhead that dominates the profile once the inner tokenization
        methods are Cythonized.
        """
        cdef int line_num
        cdef int n_lines
        cdef bint free_form = self.free_form
        cdef list lines = self.lines
        cdef list tokens
        cdef list out_tokens = []
        cdef str line
        cdef str program_text

        self.tokens = out_tokens
        self.errors = []
        # Mirror the pure-Python lexer: warnings must also reset per
        # tokenize() call, or repeated calls on one lexer duplicate them.
        self.warnings = []

        n_lines = len(lines)
        for line_num in range(n_lines):
            line = lines[line_num]
            if free_form:
                if line.endswith("\n"):
                    program_text = line[:-1]
                else:
                    program_text = line
                tokens = self.tokenize_program_text(program_text, line_num, 1)
                if tokens:
                    out_tokens.extend(tokens)
                    out_tokens.append(
                        Token(
                            TokenType.NEWLINE,
                            "\n",
                            SourceLocation(line_num + 1, len(line) + 1, 1),
                        )
                    )
            else:
                tokens = self.handle_cobol_line_format(line, line_num)
                if tokens:
                    out_tokens.extend(tokens)
                    if tokens[0].type is not TokenType.COMMENT:
                        out_tokens.append(
                            Token(
                                TokenType.NEWLINE,
                                "\n",
                                SourceLocation(line_num + 1, len(line) + 1, 1),
                            )
                        )

        out_tokens.append(
            Token(TokenType.EOF, "", SourceLocation(n_lines + 1, 1, 1))
        )
        return out_tokens

    # ------------------------------------------------------------------
    # _try_single_line_string
    # ------------------------------------------------------------------
    def _try_single_line_string(self, str text, int start_pos, int line_num, int start_col):
        """Read a single-line string literal; returns ``(token | None, new_pos, unterminated)``.

        C-typed loop; matches the pure-Python implementation including the
        doubled-quote escape ``''`` -> ``'``.
        """
        cdef str quote = text[start_pos]
        cdef int pos = start_pos + 1
        cdef int length = len(text)
        cdef str ch
        cdef list chars = []

        location = SourceLocation(line_num + 1, start_col + start_pos, 1)

        while pos < length:
            ch = text[pos]
            if ch == quote:
                if pos + 1 < length and text[pos + 1] == quote:
                    # doubled quote escape (e.g. '' inside '...')
                    chars.append(quote)
                    pos += 2
                    continue
                pos += 1
                return (
                    Token(TokenType.STRING_LITERAL, "".join(chars), location),
                    pos,
                    False,
                )
            chars.append(ch)
            pos += 1

        # Not closed on this line
        return None, pos, True

    # ------------------------------------------------------------------
    # read_number_from_text
    # ------------------------------------------------------------------
    def read_number_from_text(self, str text, int start_pos, int line_num, int start_col):
        """Read a numeric literal (or level number) starting at *start_pos*.

        C-typed scan loop -- avoids the per-char Python attribute lookups in
        the pure-Python fallback. Behaviour matches the base implementation.
        """
        cdef int pos          = start_pos
        cdef int length       = len(text)
        cdef bint has_decimal = False
        cdef bint has_exponent = False
        cdef str char

        location = SourceLocation(line_num + 1, start_col + start_pos, 1)

        while pos < length:
            char = text[pos]
            if char.isdigit():
                pos += 1
            elif (
                char == "."
                and not has_decimal
                and not has_exponent
                and pos + 1 < length
                and text[pos + 1].isdigit()
            ):
                # A period is only a decimal point when followed by a digit:
                # a COBOL numeric literal cannot end with a decimal point, so
                # "16." at end of sentence is the literal 16 followed by the
                # sentence-terminating period separator.
                has_decimal = True
                pos += 1
            elif (char == "E" or char == "e") and pos > start_pos and not has_exponent:
                has_exponent = True
                pos += 1
                if pos < length and (text[pos] == "+" or text[pos] == "-"):
                    pos += 1
            else:
                break

        value = text[start_pos:pos]

        # Level number 01-99 detection mirrors the pure-Python path
        if (
            not has_decimal
            and not has_exponent
            and _LEVEL_NUMBER_1_2DIGIT_RE.match(value)
            and 1 <= int(value) <= 99
        ):
            return Token(TokenType.LEVEL_NUMBER, value, location), pos

        return Token(TokenType.NUMERIC_LITERAL, value, location), pos

    # ------------------------------------------------------------------
    # tokenize_program_text
    # ------------------------------------------------------------------
    def tokenize_program_text(self, str text, int line_num, int start_col):
        """Tokenize one logical COBOL line; C-typed loop counters."""
        cdef int pos          = 0
        cdef int length       = len(text)
        cdef int lookahead_pos
        cdef int exponent_end
        cdef int probe
        cdef int digits_start
        cdef int scan_pos
        cdef bint has_alpha
        cdef str char

        tokens = []

        while pos < length:
            char = text[pos]

            # ---- whitespace ----------------------------------------
            if char == " " or char == "\t":
                pos += 1
                continue

            location = SourceLocation(line_num + 1, start_col + pos, 1)

            # ---- string literals -----------------------------------
            if char == '"' or char == "'":
                # Must match the pure-Python " \t"-only whitespace definition
                # exactly (not str.strip(), which is broader — e.g. "\v"/"\f"
                # /NBSP — and would let the compiled build classify a
                # continuation candidate differently from the fallback path
                # for the same input).
                if pos == 0:
                    is_line_start_quote = True
                else:
                    is_line_start_quote = True
                    for _ws_i in range(pos):
                        if text[_ws_i] != " " and text[_ws_i] != "\t":
                            is_line_start_quote = False
                            break

                token, new_pos, unterminated = self._try_single_line_string(
                    text, pos, line_num, start_col
                )
                if unterminated:
                    next_line_index   = line_num + 1
                    current_line      = (
                        self.lines[line_num] if line_num < len(self.lines) else ""
                    )
                    start_continuation = False

                    if not self.free_form:
                        if next_line_index < len(self.lines):
                            next_line = self.lines[next_line_index]
                            if (
                                len(next_line) > _FF_INDICATOR
                                and next_line[_FF_INDICATOR] == "-"
                            ):
                                start_continuation = True

                        if (
                            is_line_start_quote
                            and len(current_line) > 6
                            and current_line[_FF_INDICATOR] == "-"
                        ):
                            start_continuation = True

                        current_line_upper = current_line.upper()
                        if (
                            "VALUE" in current_line_upper
                            and next_line_index < len(self.lines)
                            and len(self.lines[next_line_index]) > _FF_INDICATOR
                            and self.lines[next_line_index][_FF_INDICATOR] == "-"
                        ):
                            start_continuation = True

                    if start_continuation:
                        self._open_string_quote    = char
                        self._open_string_location = SourceLocation(
                            line_num + 1, start_col + pos, 1
                        )
                        if new_pos > pos + 1:
                            self._open_string_value.append(text[pos + 1 : new_pos])
                        return tokens
                    else:
                        partial_value = (
                            text[pos + 1 : new_pos] if new_pos > pos + 1 else ""
                        )
                        err_location = SourceLocation(line_num + 1, start_col + pos, 1)
                        if not self.free_form:
                            self.errors.append(
                                LexerError(
                                    "Unterminated string literal",
                                    err_location,
                                    char + partial_value,
                                )
                            )
                        else:
                            # Mirrors lexer.py's H7 fix: not promoted to a
                            # hard error (a lone quote can legitimately
                            # appear in a free-form comment), but no longer
                            # fully silent either.
                            self.warnings.append(
                                f"Unterminated string literal at line "
                                f"{line_num + 1}, column {start_col + pos}: "
                                "closed at end of line instead of a matching "
                                "quote"
                            )
                        tokens.append(
                            Token(TokenType.STRING_LITERAL, partial_value, err_location)
                        )
                        pos = new_pos
                        continue
                else:
                    if token is not None:
                        tokens.append(token)
                    pos = new_pos
                    continue

            # ---- digit-initial tokens ------------------------------
            if char.isdigit():
                # Advance past all leading digits (string result unused)
                lookahead_pos = pos
                while lookahead_pos < length and text[lookahead_pos].isdigit():
                    lookahead_pos += 1

                # If a scientific-notation-shaped exponent (E/e, optional
                # sign, digits) follows immediately, skip past it too before
                # deciding identifier vs number -- a bare `43E00` is a
                # number, but `43E00-PROD` is a single hyphenated
                # paragraph/data name whose first segment merely happens to
                # look like an exponent. Checking only the character right
                # after the leading digit run (as below) misread every such
                # name as a numeric literal followed by a stray MINUS and
                # identifier.
                exponent_end = lookahead_pos
                if exponent_end < length and text[exponent_end].upper() == "E":
                    probe = exponent_end + 1
                    if probe < length and text[probe] in ("+", "-"):
                        probe += 1
                    digits_start = probe
                    while probe < length and text[probe].isdigit():
                        probe += 1
                    if probe > digits_start:
                        exponent_end = probe

                # Walk any further hyphen-joined segments (each a digit run
                # or a letter run) looking for a letter anywhere in the rest
                # of the word -- a single one-hop lookahead misses names
                # like `22310-01-TRAITE`, where the first letter only
                # appears two hyphens in.
                has_alpha = False
                scan_pos = exponent_end
                while (
                    scan_pos < length
                    and text[scan_pos] == "-"
                    and scan_pos + 1 < length
                    and text[scan_pos + 1].isalnum()
                ):
                    scan_pos += 1
                    if text[scan_pos].isalpha():
                        has_alpha = True
                    while scan_pos < length and text[scan_pos].isalnum():
                        if text[scan_pos].isalpha():
                            has_alpha = True
                        scan_pos += 1

                # Patterns "42-DATANAMES" and "25COUNT" / "45A" — identifier.
                # Scientific notation (3E2, 1E+5) is excluded: E/e followed by
                # a digit or sign+digit stays on the read_number_from_text path.
                if has_alpha or (
                    lookahead_pos < length
                    and (
                        (
                            text[lookahead_pos] == "-"
                            and lookahead_pos + 1 < length
                            and text[lookahead_pos + 1].isalpha()
                        )
                        or (
                            text[lookahead_pos].isalpha()
                            and not (
                                text[lookahead_pos].upper() == "E"
                                and (
                                    (
                                        lookahead_pos + 1 < length
                                        and text[lookahead_pos + 1].isdigit()
                                    )
                                    or (
                                        lookahead_pos + 2 < length
                                        and text[lookahead_pos + 1] in ("+", "-")
                                        and text[lookahead_pos + 2].isdigit()
                                    )
                                )
                            )
                        )
                    )
                ):
                    token, new_pos = self.read_word_from_text(
                        text, pos, line_num, start_col
                    )
                else:
                    token, new_pos = self.read_number_from_text(
                        text, pos, line_num, start_col
                    )
                tokens.append(token)
                pos = new_pos
                continue

            # ---- typed literals (X".." N".." NX".." etc.) ----------
            # Must precede the identifier path so the prefix letter is not
            # consumed as a separate identifier.
            if char.upper() in self.LITERAL_PREFIXES:
                prefixed = self.read_prefixed_literal_from_text(
                    text, pos, line_num, start_col
                )
                if prefixed is not None:
                    token, new_pos = prefixed
                    tokens.append(token)
                    pos = new_pos
                    continue

            # ---- alpha identifiers / keywords ----------------------
            if char.isalpha() or char == "_":
                token, new_pos = self.read_word_from_text(
                    text, pos, line_num, start_col
                )
                tokens.append(token)
                pos = new_pos
                continue

            # ---- free-form inline comment (`*> ... EOL`) ------------
            # Mirrors lexer.py: must run before the single-character
            # dispatch below, else `*` is read as MULTIPLY_OP.
            if char == "*" and pos + 1 < length and text[pos + 1] == ">":
                tokens.append(Token(TokenType.COMMENT, text[pos:], location))
                pos = length
                continue

            # ---- single-character tokens ---------------------------
            if char in self.SINGLE_CHAR_TOKENS:
                # Leading-decimal numeric literals: .7  .25  .003 — valid COBOL.
                if char == "." and pos + 1 < length and text[pos + 1].isdigit():
                    token, new_pos = self.read_number_from_text(text, pos, line_num, start_col)
                    tokens.append(token)
                    pos = new_pos
                else:
                    tokens.append(Token(self.SINGLE_CHAR_TOKENS[char], char, location))
                    pos += 1
                continue

            # ---- ampersand: benign separator -----------------------
            if char == "&":
                pos += 1
                continue

            # ---- unknown character ---------------------------------
            self.errors.append(LexerError(f"Invalid character: {char}", location, char))
            pos += 1

        return tokens
