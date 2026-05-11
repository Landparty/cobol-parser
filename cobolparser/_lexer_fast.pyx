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
    # tokenize_program_text
    # ------------------------------------------------------------------
    def tokenize_program_text(self, str text, int line_num, int start_col):
        """Tokenize one logical COBOL line; C-typed loop counters."""
        cdef int pos          = 0
        cdef int length       = len(text)
        cdef int lookahead_pos
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
                is_line_start_quote = pos == 0 or text[:pos].strip() == ""

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

                # Pattern "42-DATANAMES" - identifier, not numeric literal
                if (
                    lookahead_pos < length
                    and text[lookahead_pos] == "-"
                    and lookahead_pos + 1 < length
                    and text[lookahead_pos + 1].isalpha()
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

            # ---- alpha identifiers / keywords ----------------------
            if char.isalpha() or char == "_":
                token, new_pos = self.read_word_from_text(
                    text, pos, line_num, start_col
                )
                tokens.append(token)
                pos = new_pos
                continue

            # ---- single-character tokens ---------------------------
            if char in self.SINGLE_CHAR_TOKENS:
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
