"""
COBOL data item AST nodes with PICTURE clauses and usage information.

This module implements AST nodes for COBOL data definitions including
data items, PICTURE clauses, OCCURS clauses, and IBM-specific data types.
"""

import re
from typing import Any

from .._storage import PICTURELESS_USAGES, storage_size
from .ast_base import ASTNode, SourceLocation

# Pre-compiled regex patterns for PictureClause parsing (avoids re-compilation per instance)
_PIC_P_FACTOR_RE = re.compile(r"P(\((\d+)\))?")
_PIC_ALPHA_RE = re.compile(r"([XA])(\((\d+)\))?$")
_PIC_NATIONAL_RE = re.compile(r"N(\((\d+)\))?$")
# UTF-8 (``PIC U`` / ``PIC U(n)``, Enterprise COBOL 6.3): fixed
# character-length -- n UTF-8 characters, for which the compiler reserves
# 4 x n bytes (the widest n characters can be).  ``PIC U BYTE-LENGTH n`` is
# the fixed byte-length form and reserves n bytes.
_PIC_UTF8_RE = re.compile(r"^U(?:\((\d+)\))?$")
_PIC_DBCS_RE = re.compile(r"G(\((\d+)\))?$")
_PIC_BASIC_NUMERIC_RE = re.compile(r"S?9(\((\d+)\))?$")
_PIC_SIGNED_RE = re.compile(r"S(9+|\((\d+)\)|9\((\d+)\))$")
_PIC_LEFT_V_RE = re.compile(r"S?(9+|9\((\d+)\))$")
_PIC_RIGHT_V_RE = re.compile(r"(9+|9\((\d+)\))$")
_PIC_COMPLEX_RE = re.compile(r"S?(9+)V(9+)$")
_PIC_DIGIT_X_RE = re.compile(r"[9XN]")
_PIC_NINE_RE = re.compile(r"9")
# Strips ``(n)`` repeat counts so editing-symbol detection isn't fooled by the
# digits inside a repeat factor (e.g. the ``0`` in ``9(10)``).
_PIC_PAREN_COUNT_RE = re.compile(r"\(\d+\)")

# Editing/insertion symbols that only ever appear in *edited* picture clauses.
# Plain data-description symbols (9 X A S V P) are deliberately excluded. The
# simple insertions B and 0 are kept apart: in a well-formed PICTURE they can
# only be insertion characters, so ``999B99`` / ``0009`` / ``XXBXX`` are edited
# items whose size counts them (reading them as anything else sized ``999B99``
# at five bytes instead of six and shifted every later record offset). In a
# pattern that also holds characters no PICTURE may contain they are just
# more junk, and the pattern keeps the lenient fallback.
_PIC_EDIT_SYMBOLS: frozenset[str] = frozenset("Z*+-,./$")
_PIC_SIMPLE_INSERTION_SYMBOLS: frozenset[str] = frozenset("B0")
# Symbols that always occupy a digit position in a numeric-edited item.
_PIC_EDIT_DIGIT_SYMBOLS: frozenset[str] = frozenset("9Z*")
# Symbols that occupy a digit position only as part of a *floating* insertion
# string (two or more of the same symbol): the leftmost one is the currency
# sign / operational sign itself, every further one stands for a digit.  A
# single ``$``/``+``/``-`` is a fixed insertion character and no digit at all.
_PIC_FLOATING_SYMBOLS: frozenset[str] = frozenset("$+-")

# Characters that may legally appear in a PICTURE pattern (case-insensitive),
# once repeat factors ``(n)`` and the two-letter ``CR``/``DB`` symbols have been
# removed. ``G``/``N`` cover DBCS/national items and ``E`` the (rare) external
# floating-point form; including them keeps validation from flagging valid
# vendor pictures. ``(`` and ``)`` are validated separately.
_PIC_VALID_SYMBOLS: frozenset[str] = frozenset("ABXSVPZ90/,.+-*$GNEU")
# Matches a single (possibly empty / non-numeric) repeat factor with no nesting.
_PIC_REPEAT_RE = re.compile(r"\(([^()]*)\)")


class PictureClause(ASTNode):
    """AST node for COBOL PICTURE clauses."""

    def __init__(
        self,
        pattern: str,
        location: SourceLocation,
        currency_symbols: frozenset[str] | set[str] | None = None,
        decimal_point_is_comma: bool = False,
        currency_signs: dict[str, str] | None = None,
    ):
        """*currency_symbols* are the PICTURE currency symbols the program
        declares through ``SPECIAL-NAMES. CURRENCY SIGN IS ...`` (other than
        the default ``$``) that occur in *pattern*. Each is edited exactly
        like ``$`` -- a fixed or floating currency insertion character -- so
        the pattern is sized and validated as if it were written with
        ``$``, while :attr:`pattern` keeps the characters as written.

        *decimal_point_is_comma* (``SPECIAL-NAMES. DECIMAL-POINT IS COMMA``)
        exchanges the roles of ``,`` and ``.``: ``,`` is the editing decimal
        point and ``.`` a simple insertion character. The pattern is sized
        and validated through the default spelling (``9(3),99`` as
        ``9(3).99``) and, like the currency symbols, kept as written.

        *currency_signs* maps each of those symbols to the currency string
        its ``CURRENCY SIGN`` clause declares (``{"#": "EUR"}``): what an
        edited record shows in the symbol's position. A string of n
        characters makes the item n - 1 bytes wider than its pattern."""
        super().__init__("PictureClause", location)
        self.currency_symbols: frozenset[str] = frozenset(currency_symbols or ())
        self.currency_signs: dict[str, str] = {
            symbol: sign
            for symbol, sign in (currency_signs or {}).items()
            if symbol in self.currency_symbols
        }
        self.decimal_point_is_comma: bool = bool(decimal_point_is_comma)
        # Sized and validated through the ``$`` / default-decimal-point
        # spelling (see above); the verbatim pattern is restored once both
        # passes have run.
        translation: dict[int, str] = {ord(sym): "$" for sym in self.currency_symbols}
        if self.decimal_point_is_comma:
            translation[ord(",")] = "."
            translation[ord(".")] = ","
        self.pattern = pattern.translate(translation) if translation else pattern
        self.size: int | None = None
        self.integer_digits: int | None = None
        self.decimal_digits: int | None = None
        self.total_digits: int | None = None
        self.is_signed: bool = False
        self.has_scaling_factor: bool = False
        self.scaling_factor: int = 0
        # Direction of the P run for a scaled picture (see
        # `_parse_scaled_pattern`): True for a leading run (`PPP9(3)`, a
        # fraction), False for a trailing one (`9(3)PPP`, a large integer),
        # None when the picture is not P-scaled at all. The one place this
        # is decided -- every other consumer that cares about direction
        # (`generators/data/layout.py`'s `FieldSpec.scaling_positions`)
        # reads it from here instead of re-deriving it from the raw pattern.
        self.scaling_leading: bool | None = None
        self.is_edited: bool = False
        self.is_numeric_edited: bool = False
        self.is_alphanumeric_edited: bool = False
        #: National (``N``) or national-edited (``N`` with ``B``/``0``/``/``)
        #: picture: every character position is a two-byte UTF-16 unit, and
        #: ``size`` already counts the bytes.
        self.is_national: bool = False
        #: National-edited: ``N`` with ``B``/``0``/``/`` insertion characters.
        self.is_national_edited: bool = False
        #: Fixed character-length UTF-8 (``PIC U(n)``): the n characters the
        #: item holds; ``size`` is the 4 x n bytes reserved for them.
        #: ``None`` for any other picture, and for ``PIC U BYTE-LENGTH n``.
        self.utf8_characters: int | None = None
        # Populated by ``_validate_pattern``: ``is_valid`` is False when the
        # pattern violates a PICTURE syntax rule, with human-readable reasons
        # in ``validation_errors``. Parsing stays lenient regardless so a bad
        # picture never aborts the surrounding parse.
        self.is_valid: bool = True
        self.validation_errors: list[str] = []
        self._parse_pattern()
        self._validate_pattern()
        if translation:
            self.pattern = pattern
        self._widen_for_currency_string()
        if self.currency_symbols:
            self._metadata["currency_symbols"] = sorted(self.currency_symbols)
        if self.currency_signs:
            self._metadata["currency_signs"] = dict(sorted(self.currency_signs.items()))
        if self.decimal_point_is_comma:
            self._metadata["decimal_point_is_comma"] = True

    def _widen_for_currency_string(self) -> None:
        """A currency string longer than one character (``CURRENCY SIGN IS
        'CHF ' WITH PICTURE SYMBOL 'F'``) occupies its full length in the
        one position that shows it, fixed or floating; every other
        occurrence of the symbol is one position (#491, #311)."""
        widest = max(
            (len(sign) for sign in self.currency_signs.values() if sign),
            default=1,
        )
        if widest > 1 and self.size is not None:
            self.size += widest - 1

    def _parse_pattern(self) -> None:
        """Parse the PICTURE pattern to extract size and digit information."""
        # PICTURE symbols are case-insensitive (``pic s9(5)v99`` is
        # ``PIC S9(5)V99``). The checks below test for ``S`` and ``P`` and
        # match regexes spelled in upper case, so a lower-case picture was
        # read as unsigned (``SIGN SEPARATE`` then lost its byte) and a
        # lower-case ``p`` scaled picture fell to the digit-counting
        # fallback (``9(3)ppp`` sized as one digit). Declared currency
        # symbols were already translated to ``$`` above, so upper-casing
        # cannot change what they mean.
        pattern = self.pattern.upper()

        # Cheap membership tests before regex work -- the regexes below
        # were being invoked even when they could not possibly match.
        if "S" in pattern:
            self.is_signed = True

        if "P" in pattern:
            p_matches = _PIC_P_FACTOR_RE.findall(pattern)
            if p_matches:
                self.has_scaling_factor = True
                # Every P position counts: ``PPP`` and ``P(3)`` both scale by
                # three, so the factor is the sum over the whole run rather
                # than the first match's own repeat count.
                self.scaling_factor = sum(
                    int(count) if count else 1 for _, count in p_matches
                )
            if self._parse_scaled_pattern(pattern):
                return

        # 0. Unedited pictures that split one symbol's run across several
        # repeat factors, or mix a factor with repeated letters: ``X(2)X(3)``,
        # ``AAX(2)``, ``9(2)9(3)``, ``S9(3)99``, ``NN``.  The regexes below
        # each match a single ``C(n)`` or a bare run of one letter, so these
        # fell through to the digit-counting fallback, which ignores repeat
        # factors and national doubling -- ``X(2)X(3)`` was sized at two bytes
        # instead of five, shifting every later offset in the record.
        if self._parse_plain_pattern(pattern):
            return

        # 0b. National-edited pictures (``N(2)BN``, ``NN/NN``): N with the
        # simple insertion characters B, 0 and /.  Each position -- insertion
        # characters included -- is a two-byte national character.  These
        # used to fall into the numeric-edited path, which sized
        # ``N(2)BN`` at four bytes (not eight) and called it numeric.
        if self._parse_national_edited_pattern(pattern):
            return

        # Use the first character as a cheap guard for the simple
        # alphanumeric/national branches below, so we avoid those regexes
        # when the pattern cannot be X/A/N-based.
        first = pattern[0] if pattern else ""

        # 1. Basic alphanumeric patterns: X, X(n), A, A(n)
        if first == "X" or first == "A":
            alpha_match = _PIC_ALPHA_RE.match(pattern)
            if alpha_match:
                count_str = alpha_match.group(3)
                self.size = int(count_str) if count_str else 1
                return

        # 1b. National (PIC N) and DBCS (PIC G) patterns: N, N(n), G, G(n).
        # Each N/G names one *double-byte* character position, so the item
        # occupies twice as many bytes as it has symbols -- ``PIC N(10)`` is
        # 20 bytes on IBM Enterprise COBOL, and so is ``PIC G(10)`` (which
        # always pairs with USAGE DISPLAY-1). ``size`` is what every layout
        # surface (record offsets, encoder, decoder) reads as the item's
        # byte width, so it carries the doubled count; nothing else in this
        # codebase models UTF-16/DBCS content, and a 20-byte slot is what a
        # record image and a ``data-items`` offset both need to agree on.
        if first in ("N", "G"):
            wide_match = (_PIC_NATIONAL_RE if first == "N" else _PIC_DBCS_RE).match(
                pattern
            )
            if wide_match:
                count_str = wide_match.group(2)
                self.size = 2 * (int(count_str) if count_str else 1)
                self.is_national = first == "N"
                return

        # 1c. UTF-8 (PIC U) patterns: U, U(n). ``PIC U(n)`` is fixed
        # character-length: n characters in 4 x n reserved bytes (IBM
        # Enterprise COBOL 6.3+, "UTF-8 data items"), so ``size`` -- the
        # byte width every layout surface reads -- is 4n, and
        # ``utf8_characters`` keeps n.  Sizing it n bytes put every later
        # offset 3n bytes short.  ``PIC U BYTE-LENGTH n`` is the fixed
        # byte-length form; ``CobolDataItem.set_byte_length`` sizes it n.
        if first == "U":
            utf8_match = _PIC_UTF8_RE.match(pattern)
            if utf8_match:
                count_str = utf8_match.group(1)
                characters = int(count_str) if count_str else 1
                self.utf8_characters = characters
                self.size = 4 * characters
                return

        # 2. Basic numeric patterns: 9, 9(n)
        basic_numeric = _PIC_BASIC_NUMERIC_RE.match(pattern)
        if basic_numeric:
            count_str = basic_numeric.group(2)
            digit_count = int(count_str) if count_str else 1
            self.integer_digits = digit_count
            self.decimal_digits = 0
            self.total_digits = digit_count
            self.size = digit_count
            return

        # 3. Signed patterns: S9(n), S999, etc.
        signed_match = _PIC_SIGNED_RE.match(pattern)
        if signed_match:
            if signed_match.group(2):  # S(n) format
                digit_count = int(signed_match.group(2))
            elif signed_match.group(3):  # S9(n) format
                digit_count = int(signed_match.group(3))
            else:  # S999... format
                digit_count = len(signed_match.group(1))

            self.integer_digits = digit_count
            self.decimal_digits = 0
            self.total_digits = digit_count
            self.size = digit_count
            return

        # 4. Decimal patterns: split at V and parse each side. An edited
        # picture with a V (``Z(3)V99``) is left to step 7, which counts its
        # Z/*/insertion positions; the split here only understands 9s and
        # would size ``Z(3)V99`` as two bytes.
        if "V" in pattern and not self._is_edited_pattern(pattern):
            parts = pattern.split("V")
            if len(parts) == 2:
                left_part = parts[0]
                right_part = parts[1]

                # Parse integer part (before V)
                left_match = _PIC_LEFT_V_RE.match(left_part)
                if left_match:
                    if left_match.group(2):  # 9(n) format
                        integer_part = int(left_match.group(2))
                    else:  # 9999... format
                        integer_part = len(_PIC_NINE_RE.findall(left_part))
                else:
                    integer_part = 0  # SV format

                # Parse decimal part (after V)
                right_match = _PIC_RIGHT_V_RE.match(right_part)
                if right_match:
                    if right_match.group(2):  # 9(n) format
                        decimal_part = int(right_match.group(2))
                    else:  # 9999... format
                        decimal_part = len(_PIC_NINE_RE.findall(right_part))
                else:
                    decimal_part = 0

                self.integer_digits = integer_part
                self.decimal_digits = decimal_part
                self.total_digits = integer_part + decimal_part
                self.size = self.total_digits
                return

        # 5. Leading decimal patterns: SV9(n), V9(n) - already handled above in V parsing
        # This is redundant now since we handle V patterns above

        # 6. Scaling factor patterns (SP(n)9, S9P(n), SVPP9(3), 9(3)PPP) are
        # handled by _parse_scaled_pattern before the V split above, since a
        # V next to the P run would otherwise be read as an ordinary decimal
        # point with nothing parseable on either side.

        # 7. Edited pictures (numeric-edited and alphanumeric-edited).
        # Covers zero-suppression (Z, *), floating/fixed insertion ($, +, -),
        # simple insertion (B, 0, /, comma), the actual decimal point (.), and
        # the credit/debit symbols (CR, DB). The displayed size counts every
        # character position the picture occupies after expanding (n) repeats.
        if self._is_edited_pattern(pattern):
            self._parse_edited_pattern(pattern)
            return

        # 8. Complex patterns with repetition: S999V999, etc.
        complex_match = _PIC_COMPLEX_RE.match(pattern)
        if complex_match:
            integer_part = len(complex_match.group(1))
            decimal_part = len(complex_match.group(2))

            self.integer_digits = integer_part
            self.decimal_digits = decimal_part
            self.total_digits = integer_part + decimal_part
            self.size = self.total_digits
            return

        # 8. Fallback for unrecognized patterns
        # Count all 9s and Xs to estimate size
        digit_count = len(_PIC_DIGIT_X_RE.findall(pattern))
        if digit_count > 0:
            self.size = digit_count
            if "9" in pattern:
                self.total_digits = digit_count
                # Estimate integer vs decimal based on V
                if "V" in pattern:
                    v_pos = pattern.find("V")
                    integer_nines = len(_PIC_NINE_RE.findall(pattern[:v_pos]))
                    decimal_nines = len(_PIC_NINE_RE.findall(pattern[v_pos:]))
                    self.integer_digits = integer_nines
                    self.decimal_digits = decimal_nines
                else:
                    self.integer_digits = digit_count
                    self.decimal_digits = 0
        else:
            # Default size if nothing else matches
            self.size = 1

    def _validate_pattern(self) -> None:
        """Validate the PICTURE pattern, recording any rule violations.

        The checks are intentionally conservative -- they only flag patterns
        that are unambiguously illegal in standard/IBM COBOL, so valid (and
        even unusual but legal) pictures are never rejected:

        * empty pattern
        * characters outside the legal PICTURE symbol set
        * malformed repeat factors: unbalanced/nested ``()``, empty ``()``,
          a non-numeric or zero count, or a ``(n)`` not following a symbol
        * more than one ``V`` (assumed decimal point)
        * both ``V`` and an actual decimal point ``.``
        * more than one actual decimal point ``.``
        * more than one ``S``, or an ``S`` that is not the leftmost symbol
        """
        errors: list[str] = []
        pattern = self.pattern

        if not pattern or not pattern.strip():
            self.validation_errors = ["PICTURE clause is empty"]
            self.is_valid = False
            return

        up = pattern.upper()

        # --- repeat factors: balance, content, and placement ---------------
        if up.count("(") != up.count(")"):
            errors.append(f"unbalanced parentheses in PICTURE '{pattern}'")
        for match in _PIC_REPEAT_RE.finditer(up):
            inner = match.group(1)
            if not inner.isdigit() or int(inner) == 0:
                errors.append(
                    f"invalid repeat count '({inner})' in PICTURE '{pattern}'"
                )
            start = match.start()
            if start == 0 or up[start - 1] in "(),.":
                errors.append(
                    f"repeat count '({inner})' must follow a picture symbol "
                    f"in PICTURE '{pattern}'"
                )

        # Skeleton with repeat factors removed, then the two-letter CR/DB
        # symbols stripped, leaving only single-character picture symbols.
        skeleton = _PIC_REPEAT_RE.sub("", up)
        core = skeleton.replace("CR", "").replace("DB", "")

        # --- illegal characters --------------------------------------------
        bad = sorted({ch for ch in core if ch not in _PIC_VALID_SYMBOLS})
        for ch in bad:
            errors.append(f"invalid character '{ch}' in PICTURE '{pattern}'")

        # --- decimal-point / sign rules ------------------------------------
        if skeleton.count("V") > 1:
            errors.append(f"PICTURE '{pattern}' has more than one 'V'")
        if "V" in skeleton and "." in skeleton:
            errors.append(
                f"PICTURE '{pattern}' cannot contain both 'V' and a decimal point"
            )
        if skeleton.count(".") > 1:
            errors.append(f"PICTURE '{pattern}' has more than one decimal point")

        s_count = skeleton.count("S")
        if s_count > 1:
            errors.append(f"PICTURE '{pattern}' has more than one 'S'")
        elif s_count == 1 and skeleton[0] != "S":
            errors.append(f"'S' must be the leftmost symbol in PICTURE '{pattern}'")

        if errors:
            self.validation_errors = errors
            self.is_valid = False

    @staticmethod
    def _is_edited_pattern(pattern: str) -> bool:
        """Return True when the pattern contains editing/insertion symbols.

        Repeat factors (``(n)``) are stripped first so the digits inside them
        (e.g. the ``0`` in ``9(10)``) are not mistaken for insertion symbols.
        """
        skeleton = _PIC_PAREN_COUNT_RE.sub("", pattern).upper()
        if any(ch in _PIC_EDIT_SYMBOLS for ch in skeleton):
            return True
        if "CR" in skeleton or "DB" in skeleton:
            return True
        return any(ch in _PIC_SIMPLE_INSERTION_SYMBOLS for ch in skeleton) and all(
            ch in _PIC_VALID_SYMBOLS for ch in skeleton
        )

    @staticmethod
    def _expand_symbols(pattern: str) -> list[str]:
        """Expand a picture string into one entry per character position.

        ``9(3)`` -> ``['9', '9', '9']`` and ``$(4)`` -> ``['$', ...]``. The
        two-character ``CR``/``DB`` credit-debit symbols are kept as single
        entries so the caller can score them as two positions.
        """
        symbols: list[str] = []
        i = 0
        n = len(pattern)
        while i < n:
            ch = pattern[i]
            upper = ch.upper()
            # CR / DB credit-debit symbols occupy two positions but parse as one
            if upper == "C" and i + 1 < n and pattern[i + 1].upper() == "R":
                symbols.append("CR")
                i += 2
                continue
            if upper == "D" and i + 1 < n and pattern[i + 1].upper() == "B":
                symbols.append("DB")
                i += 2
                continue
            # Expand a trailing (n) repeat factor against the preceding symbol
            if i + 1 < n and pattern[i + 1] == "(":
                close = pattern.find(")", i + 2)
                if close != -1:
                    try:
                        count = int(pattern[i + 2 : close])
                    except ValueError:
                        count = 1
                    symbols.extend([ch] * count)
                    i = close + 1
                    continue
            symbols.append(ch)
            i += 1
        return symbols

    def _parse_plain_pattern(self, pattern: str) -> bool:
        """Populate the fields for an unedited, unscaled picture of any shape.

        Handles numeric (``S``/``V``/``9``), alphanumeric (``X``/``A``/``9``)
        and national/DBCS (``N``/``G``) pictures after expanding every repeat
        factor, so the size counts each character position however the
        picture spells it.  Returns False for anything else -- edited, ``P``
        scaled, malformed -- leaving the general parse to deal with it.
        """
        if "(" in pattern and not all(
            inner.isdigit() and int(inner) > 0
            for inner in _PIC_REPEAT_RE.findall(pattern)
        ):
            return False
        symbols = [s.upper() for s in self._expand_symbols(pattern)]
        kinds = set(symbols)
        if not symbols:
            return False
        if kinds <= {"S", "V", "9"}:
            if "9" not in kinds or symbols.count("V") > 1 or symbols.count("S") > 1:
                return False
            if "S" in kinds and symbols[0] != "S":
                return False
            split = symbols.index("V") if "V" in kinds else len(symbols)
            self.integer_digits = symbols[:split].count("9")
            self.decimal_digits = symbols[split:].count("9")
            self.total_digits = self.integer_digits + self.decimal_digits
            self.size = self.total_digits
            return True
        if kinds <= {"X", "A", "9"}:
            self.size = len(symbols)
            return True
        if kinds in ({"N"}, {"G"}):
            self.size = 2 * len(symbols)
            self.is_national = kinds == {"N"}
            return True
        return False

    def _parse_national_edited_pattern(self, pattern: str) -> bool:
        """Populate the fields for a national-edited picture (``N(2)BN``),
        or a DBCS picture with ``B`` insertion (``GGBGG``).

        Returns False unless *pattern* is made of ``N`` and at least one of
        the national insertion characters ``B``/``0``/``/``, or of ``G`` and
        ``B``.
        """
        if "(" in pattern and not all(
            inner.isdigit() and int(inner) > 0
            for inner in _PIC_REPEAT_RE.findall(pattern)
        ):
            return False
        symbols = [s.upper() for s in self._expand_symbols(pattern)]
        kinds = set(symbols)
        if kinds == {"G", "B"}:
            # DBCS (``USAGE DISPLAY-1``) with ``B`` insertion: ``GGBGG``.
            # A DBCS ``B`` is a double-byte space, so every position is two
            # bytes. These fell into the numeric-edited path, which sized
            # ``GGBGG`` at five bytes (not ten) and called it numeric.
            self.is_edited = True
            self.size = 2 * len(symbols)
            return True
        if "N" not in kinds or not kinds <= {"N", "B", "0", "/"} or kinds == {"N"}:
            return False
        self.is_edited = True
        self.is_national = True
        self.is_national_edited = True
        self.size = 2 * len(symbols)
        return True

    def _parse_scaled_pattern(self, pattern: str) -> bool:
        """Populate the fields for a ``P``-scaled numeric picture.

        ``P`` is a decimal scaling position: it holds no byte, but it shifts
        the assumed decimal point one place further away from the digits.
        ``9(3)PPP`` therefore describes an integer of six digits whose low
        three are always zero (``123000``), stored in three bytes;
        ``SVPP9(3)`` describes a five-place fraction whose first two places
        are always zero (``0.00123``), also stored in three bytes.  The
        ``integer_digits``/``decimal_digits`` counts include the P positions
        (they describe the *value*), while ``size`` and ``total_digits``
        count only the ``9``s (they describe the *storage*) -- which is what
        keeps a ``PIC 9(3)PPP COMP-3`` item at two bytes, not four.

        Returns False when *pattern* is not a plain ``S``/``V``/``P``/``9``
        picture with one contiguous run of ``P`` at exactly one end, leaving
        the general parse to deal with it.
        """
        symbols = [s.upper() for s in self._expand_symbols(pattern)]
        core = [s for s in symbols if s not in ("S", "V")]
        if not core or any(s not in ("9", "P") for s in core):
            return False
        nines = core.count("9")
        ps = core.count("P")
        if nines == 0 or ps == 0:
            return False
        leading = core[0] == "P"
        trailing = core[-1] == "P"
        if leading == trailing:
            return False  # P on both ends, or P in the middle: not a scaled picture
        run = core[:ps] if leading else core[-ps:]
        if any(s != "P" for s in run):
            return False

        self.scaling_leading = leading
        if leading:
            self.integer_digits = 0
            self.decimal_digits = ps + nines
        else:
            self.integer_digits = nines + ps
            self.decimal_digits = 0
        self.total_digits = nines
        self.size = nines
        return True

    def _parse_edited_pattern(self, pattern: str) -> None:
        """Populate size/digit fields for an edited picture clause."""
        self.is_edited = True
        symbols = self._expand_symbols(pattern)

        size = 0
        integer_digits = 0
        decimal_digits = 0
        seen_decimal = False
        has_alpha = False

        # A floating insertion string (``$$$,$$9``, ``++++9``, ``--,--9``)
        # is two or more of the same symbol: its leftmost occurrence is the
        # sign or currency character and holds no digit; each further one
        # stands for a digit position. A lone ``$``/``+``/``-`` is a fixed
        # insertion character and holds no digit either. Counting every
        # such symbol as a digit -- the previous rule for ``$`` -- made
        # ``$$$,$$9`` a six-digit field, and the value generator then
        # produced numbers the edited picture cannot display.
        #
        # An external floating-point picture (``-9.9(5)E-99``) describes its
        # value with the mantissa only: the ``E``, the exponent's sign and
        # its two digits are display positions, not digits of the value.
        # Counting them made ``-9.9(5)E-99`` an eight-place fraction (the
        # exponent sign read as a second floating ``-``), and generated
        # values no longer fitted the picture.
        upper_symbols = [s.upper() for s in symbols]
        mantissa_end = (
            upper_symbols.index("E")
            if "E" in upper_symbols and not {"X", "A"} & set(upper_symbols)
            else len(symbols)
        )
        floating_counts = {
            sym: sum(1 for s in upper_symbols[:mantissa_end] if s == sym)
            for sym in _PIC_FLOATING_SYMBOLS
        }
        floating_seen: set[str] = set()
        # ``P`` scaling positions in an edited picture (``ZZPPP``) hold no
        # character but are digits of the *value*, exactly as in an
        # unedited scaled picture (see ``_parse_scaled_pattern``).
        scaling_count = 0
        scaling_leading = False

        for index, sym in enumerate(symbols):
            upper = sym.upper()
            if index >= mantissa_end:
                size += 1
                continue
            if upper in ("S", "V", "P"):
                # Non-printing description symbols; V marks the decimal split.
                if upper == "V":
                    seen_decimal = True
                elif upper == "P":
                    if scaling_count == 0:
                        scaling_leading = integer_digits + decimal_digits == 0
                    scaling_count += 1
                continue
            if upper in ("CR", "DB"):
                size += 2
                continue
            size += 1
            is_digit = upper in _PIC_EDIT_DIGIT_SYMBOLS
            if upper in _PIC_FLOATING_SYMBOLS:
                # Only the second and later symbols of a floating string
                # are digit positions.
                is_digit = floating_counts[upper] >= 2 and upper in floating_seen
                floating_seen.add(upper)
            if upper in ("X", "A"):
                has_alpha = True
            elif upper == ".":
                seen_decimal = True
            elif is_digit:
                if seen_decimal:
                    decimal_digits += 1
                else:
                    integer_digits += 1

        self.size = size
        if has_alpha:
            self.is_alphanumeric_edited = True
        else:
            self.is_numeric_edited = True
            self.total_digits = integer_digits + decimal_digits
            if scaling_count and self.total_digits:
                self.scaling_leading = scaling_leading
                if scaling_leading:
                    decimal_digits += integer_digits + scaling_count
                    integer_digits = 0
                else:
                    integer_digits += scaling_count
            self.integer_digits = integer_digits
            self.decimal_digits = decimal_digits

    def to_dict(self) -> dict[str, Any]:
        """Convert PICTURE clause to dictionary representation."""
        return {
            "node_type": self.node_type,
            "pattern": self.pattern,
            "size": self.size,
            "integer_digits": self.integer_digits,
            "decimal_digits": self.decimal_digits,
            "total_digits": self.total_digits,
            "is_signed": self.is_signed,
            "has_scaling_factor": self.has_scaling_factor,
            "scaling_factor": self.scaling_factor,
            "is_edited": self.is_edited,
            "is_numeric_edited": self.is_numeric_edited,
            "is_alphanumeric_edited": self.is_alphanumeric_edited,
            "is_national": self.is_national,
            "is_national_edited": self.is_national_edited,
            "is_valid": self.is_valid,
            "validation_errors": self.validation_errors,
            "location": self.location.to_dict(),
            "metadata": self._metadata or {},
        }


class OccursClause(ASTNode):
    """AST node for COBOL OCCURS clauses (arrays/tables)."""

    def __init__(self, location: SourceLocation):
        super().__init__("OccursClause", location)
        self.min_times: int | None = None
        self.max_times: int | None = None
        self.depending_on: str | None = None
        #: ``DEPENDING ON CNT OF CTL [IN ...]``: the qualifiers that locate a
        #: counter whose name is not unique, innermost first.
        #: ``depending_on`` stays the bare data-name every consumer matches.
        self.depending_on_qualifiers: list[str] = []
        #: ``OCCURS UNBOUNDED DEPENDING ON`` (Enterprise COBOL 5+): the table
        #: has no declared maximum, so ``max_times`` stays None. Only legal
        #: in the LINKAGE SECTION, where the caller supplies the storage.
        self.is_unbounded: bool = False
        self.indexed_by: str | None = None
        # INDEXED BY may name several indexes; ``indexed_by`` keeps the first
        # for backward compatibility, ``index_names`` keeps them all.
        self.index_names: list[str] = []
        # ASCENDING/DESCENDING KEY IS ... — required for SEARCH ALL (binary
        # search). Each entry: {"direction": "ASCENDING"|"DESCENDING",
        # "keys": [data-name, ...]}.
        self.key_clauses: list[dict[str, Any]] = []

    @property
    def times(self) -> int | None:
        """Get the OCCURS times (for fixed OCCURS)."""
        if self.min_times == self.max_times:
            return self.min_times
        return self.max_times  # Fallback to max_times

    def set_fixed_occurs(self, times: int) -> None:
        """Set fixed OCCURS count (e.g., OCCURS 10 TIMES)."""
        self.min_times = times
        self.max_times = times

    def set_variable_occurs(
        self, min_times: int, max_times: int | None, depending_on: str | None
    ) -> None:
        """Set variable OCCURS (e.g., OCCURS 1 TO 100 TIMES DEPENDING ON)."""
        self.min_times = min_times
        self.max_times = max_times
        self.depending_on = depending_on

    def set_indexed_by(self, index_name: str) -> None:
        """Set INDEXED BY clause (records the first index name)."""
        self.indexed_by = index_name

    def add_index_name(self, index_name: str) -> None:
        """Append an INDEXED BY index name (supports multiple indexes)."""
        self.index_names.append(index_name)
        if self.indexed_by is None:
            self.indexed_by = index_name

    def add_key_clause(self, direction: str, keys: list[str]) -> None:
        """Record an ASCENDING/DESCENDING KEY clause for the table."""
        self.key_clauses.append({"direction": direction.upper(), "keys": list(keys)})

    def to_dict(self) -> dict[str, Any]:
        """Convert OCCURS clause to dictionary representation."""
        result: dict[str, Any] = {
            "node_type": self.node_type,
            "min_times": self.min_times,
            "max_times": self.max_times,
            "depending_on": self.depending_on,
            "indexed_by": self.indexed_by,
            "location": self.location.to_dict(),
            "metadata": self._metadata or {},
        }
        if self.index_names:
            result["index_names"] = list(self.index_names)
        if self.key_clauses:
            result["key_clauses"] = [dict(kc) for kc in self.key_clauses]
        if self.is_unbounded:
            result["is_unbounded"] = True
        if self.depending_on_qualifiers:
            result["depending_on_qualifiers"] = list(self.depending_on_qualifiers)
        return result


def _implied_picture_usage(picture: PictureClause) -> str | None:
    """The USAGE a PICTURE implies on its own: ``NATIONAL`` for ``N``
    pictures, ``DISPLAY-1`` for ``G`` (DBCS) ones, else None."""
    if picture.is_national:
        return "NATIONAL"
    body = _PIC_PAREN_COUNT_RE.sub("", picture.pattern.upper())
    if body and set(body) <= {"G", "B"} and "G" in body:
        return "DISPLAY-1"
    return None


class CobolDataItem(ASTNode):
    """AST node for COBOL data item definitions."""

    def __init__(self, name: str, level: int, location: SourceLocation):
        super().__init__("DataItem", location)
        self.name = name
        self.level = level
        self.picture_clause: PictureClause | None = None
        self.usage: str = "DISPLAY"  # Default usage
        #: True when this entry itself carries a USAGE clause (``set_usage`` /
        #: ``set_object_reference``); False when ``usage`` is the DISPLAY
        #: default or was inherited from an enclosing group's USAGE.
        self.usage_explicit: bool = False
        self.value_clause: str | None = None
        self.occurs_clause: OccursClause | None = None
        self.redefines: str | None = None
        self.is_filler: bool = name.upper() == "FILLER"
        self.sign_clause: str | None = None
        self.synchronized: bool = False
        self.justified: bool = False
        self.blank_when_zero: bool = False
        self.is_external: bool = False
        self.is_global: bool = False
        #: ``VOLATILE`` (Enterprise COBOL 6.2): the item may be changed by
        #: something the compiler cannot see, so it is never optimized away.
        self.is_volatile: bool = False
        #: ``PIC U BYTE-LENGTH n`` (UTF-8, 6.3): the declared byte width,
        #: which also becomes the PICTURE's ``size``.
        self.byte_length: int | None = None
        #: ``DYNAMIC LENGTH [LIMIT n]`` (6.3): a dynamic-length elementary
        #: item; ``dynamic_length_limit`` is the LIMIT, None when unstated.
        self.is_dynamic_length: bool = False
        self.dynamic_length_limit: int | None = None
        #: ``USAGE OBJECT REFERENCE [class-name]`` (OO COBOL): the class the
        #: reference is typed with, or None for a universal reference.
        self.object_class: str | None = None
        #: ``GROUP-USAGE [IS] NATIONAL|UTF-8`` on a group: every subordinate
        #: elementary item is implicitly of that usage.
        self.group_usage: str | None = None

    @property
    def initial_value(self) -> str | None:
        """Get the initial value (VALUE clause)."""
        return self.value_clause

    @initial_value.setter
    def initial_value(self, value: str) -> None:
        """Set the initial value (VALUE clause)."""
        self.value_clause = value

    def set_picture_clause(self, picture: PictureClause) -> None:
        """Set the PICTURE clause for this data item.

        A picture of ``N`` symbols implies ``USAGE NATIONAL`` and one of
        ``G`` symbols ``USAGE DISPLAY-1`` (IBM Enterprise COBOL, default
        ``NSYMBOL(NATIONAL)``); ``usage`` says so unless the entry states a
        USAGE of its own, which a later ``set_usage`` still overrides.
        """
        self.picture_clause = picture
        self.add_child(picture)
        if not self.usage_explicit:
            implied = _implied_picture_usage(picture)
            if implied is not None:
                self.usage = implied

    def set_byte_length(self, byte_length: int) -> None:
        """Record ``BYTE-LENGTH n`` and size the PICTURE accordingly."""
        self.byte_length = byte_length
        if self.picture_clause is not None:
            self.picture_clause.size = byte_length
            self.picture_clause.utf8_characters = None

    def set_dynamic_length(self, limit: int | None = None) -> None:
        """Record ``DYNAMIC LENGTH [LIMIT n]``."""
        self.is_dynamic_length = True
        self.dynamic_length_limit = limit

    def set_object_reference(self, class_name: str | None = None) -> None:
        """Record ``[USAGE] OBJECT REFERENCE [class-name]``."""
        self.usage = "OBJECT REFERENCE"
        self.usage_explicit = True
        self.object_class = class_name

    def set_usage(self, usage: str) -> None:
        """Set the USAGE clause for this data item."""
        self.usage = usage
        self.usage_explicit = True

    def set_value_clause(self, value: str) -> None:
        """Set the VALUE clause for this data item."""
        self.value_clause = value

    def set_occurs_clause(self, occurs: OccursClause) -> None:
        """Set the OCCURS clause for this data item."""
        self.occurs_clause = occurs
        self.add_child(occurs)

    def set_redefines(self, redefines_item: str) -> None:
        """Set the REDEFINES clause for this data item."""
        self.redefines = redefines_item

    def is_group_item(self) -> bool:
        """Check if this is a group item (has CobolDataItem children, no PICTURE)."""
        cobol_data_children = [
            child for child in self.children if isinstance(child, CobolDataItem)
        ]
        return len(cobol_data_children) > 0 and self.picture_clause is None

    def is_elementary_item(self) -> bool:
        """Check if this is an elementary item: no CobolDataItem children, and
        either a PICTURE or a USAGE that never takes one (``COMP-1`` /
        ``COMP-2``, ``INDEX``, the ``POINTER`` family, ``OBJECT REFERENCE``).

        A childless item with neither stays unclassified -- e.g. a group
        whose subordinate entries are missing -- rather than being guessed
        elementary."""
        cobol_data_children = [
            child for child in self.children if isinstance(child, CobolDataItem)
        ]
        if cobol_data_children:
            return False
        if self.picture_clause is not None:
            return True
        return (self.usage or "").upper() in PICTURELESS_USAGES

    def get_elementary_items(self) -> list["CobolDataItem"]:
        """Get all elementary items under this data item."""
        elementary_items = []

        if self.is_elementary_item():
            elementary_items.append(self)
        else:
            for child in self.children:
                if isinstance(child, CobolDataItem):
                    elementary_items.extend(child.get_elementary_items())

        return elementary_items

    def get_all_children(self) -> list["CobolDataItem"]:
        """Get all child data items recursively."""
        all_children = []

        for child in self.children:
            if isinstance(child, CobolDataItem):
                all_children.append(child)
                all_children.extend(child.get_all_children())

        return all_children

    def calculate_size(self) -> int:
        """Bytes this item occupies, every OCCURS occurrence included.

        Defers to :func:`cobolparser._storage.storage_size` -- the one
        authority on how many bytes a data item takes, shared with the
        record-image encoder and with ``layout_offsets`` (which backs the
        ``data-items`` subcommand), so no elementary item's width can drift
        between them.  This method used to carry its own copy of that
        arithmetic and had drifted in six ways: it knew
        ``COMP``/``COMP-4``/``COMP-3`` but not the
        ``BINARY``/``COMPUTATIONAL``/``COMPUTATIONAL-3`` spellings of the
        same usages (so ``PIC S9(9) BINARY`` reported 9 bytes, not 4); it
        reached its ``COMP-1``/``COMP-2`` branch only for an item that had a
        PICTURE, which those usages never do (so both reported 0, as did
        ``USAGE INDEX``); it never spent the extra byte a DISPLAY item with
        ``SIGN IS SEPARATE`` needs, which the PICTURE's character count does
        not include; it summed a group's REDEFINES children on top of what
        they redefine instead of sharing one slot; and it applied an OCCURS
        multiplier to elementary items only, never to a group.

        One divergence from ``layout_offsets`` is deliberate rather than
        drift, and shared widths do not remove it: under
        ``OCCURS ... DEPENDING ON`` this reserves the table's **maximum**
        (matching ``generators.data.layout``/``encoding``, and so the record
        images ``gen-data`` writes), while ``layout_offsets`` reserves a
        single occurrence because the real multiplier is not known until
        run time.  Across the sample and NIST corpora that is the only thing
        the two disagree about: 18,121 records, 14 differences, every one an
        ODO table.
        """
        return self._occurrence_size() * self._occurs_multiplier()

    def _occurs_multiplier(self) -> int:
        """How many occurrences this item's OCCURS clause reserves.

        ``OCCURS ... DEPENDING ON`` is counted at its maximum, matching how
        every other layout surface in the package flattens a variable table.
        """
        occurs = self.occurs_clause
        if occurs is None:
            return 1
        return occurs.max_times or occurs.min_times or 1

    def _occurrence_size(self) -> int:
        """Bytes *one* occurrence of this item occupies."""
        children = self._direct_data_children()
        if not children:
            picture = self.picture_clause
            return storage_size(
                self.usage,
                picture_size=picture.size if picture else None,
                total_digits=picture.total_digits if picture else None,
                sign_clause=self.sign_clause,
                is_signed=bool(picture and picture.is_signed),
                national_picture=bool(picture and picture.is_national),
            )

        # A group is the sum of its REDEFINES *slots*, not of its children.
        # COBOL requires a REDEFINES entry to immediately follow the item it
        # redefines, so a slot is a contiguous run of ``[base, redefiner,
        # ...]`` sharing one piece of storage; the slot costs the largest
        # member, and only closing it advances the running total.  Same rule
        # as ``layout_offsets._layout_siblings``.
        total = 0
        slot = 0
        for child in children:
            if not child.redefines:
                total += slot
                slot = 0
            slot = max(slot, child.calculate_size())
        return total + slot

    def _direct_data_children(self) -> list["CobolDataItem"]:
        """Direct children that are real subordinate storage.

        Level-88 condition names are :class:`ConditionNameItem` and never
        appear here.  A level-66 RENAMES entry re-groups storage that is
        already counted, and a level-77 is by definition a standalone record
        that the parser's level-number nesting can misfile under a preceding
        group -- counting either would double-count bytes (and, for the 77,
        would misclassify its parent as a group and discard the parent's own
        PICTURE).  Matches ``layout_offsets._direct_data_children``.
        """
        return [
            child
            for child in self.children
            if isinstance(child, CobolDataItem) and child.level not in (66, 77)
        ]

    @property
    def layout_name(self) -> str:
        """The name this entry is laid out under: FILLER for any FILLER item.

        An entry written without a data-name (``05 PIC X(3).``) keeps the
        parser's synthetic ``ANONYMOUS-<level>-<line>`` as its ``name``, but
        it is FILLER with the word omitted, so record layouts, paths and
        columns name it exactly as they name ``05 FILLER PIC X(3).``.
        """
        return "FILLER" if self.is_filler else self.name

    def to_dict(self) -> dict[str, Any]:
        """Convert data item to dictionary representation."""
        result = {
            "node_type": self.node_type,
            "name": self.name,
            "level": self.level,
            "usage": self.usage,
            "is_filler": self.is_filler,
            "is_group_item": self.is_group_item(),
            "is_elementary_item": self.is_elementary_item(),
            "calculated_size": self.calculate_size(),
            "location": self.location.to_dict(),
            "metadata": self._metadata or {},
        }

        if self.picture_clause:
            result["picture_clause"] = self.picture_clause.to_dict()

        if self.value_clause:
            result["value_clause"] = self.value_clause

        if self.occurs_clause:
            result["occurs_clause"] = self.occurs_clause.to_dict()

        if self.sign_clause:
            result["sign_clause"] = self.sign_clause
        if self.synchronized:
            result["synchronized"] = True
        if self.justified:
            result["justified"] = True
        if self.blank_when_zero:
            result["blank_when_zero"] = True
        if self.is_external:
            result["is_external"] = True
        if self.is_global:
            result["is_global"] = True
        if self.is_volatile:
            result["is_volatile"] = True
        if self.byte_length is not None:
            result["byte_length"] = self.byte_length
        if self.is_dynamic_length:
            result["is_dynamic_length"] = True
            result["dynamic_length_limit"] = self.dynamic_length_limit
        if self.object_class is not None:
            result["object_class"] = self.object_class
        if self.group_usage is not None:
            result["group_usage"] = self.group_usage

        if self.redefines:
            result["redefines"] = self.redefines

        # Include child data items
        child_data_items = [
            child.to_dict()
            for child in self.children
            if isinstance(child, CobolDataItem)
        ]
        if child_data_items:
            result["children"] = child_data_items

        # Include level-88 condition names. These are parsed into
        # ConditionNameItem children but were historically dropped at the
        # JSON boundary.
        condition_names = [
            child.to_dict()
            for child in self.children
            if isinstance(child, ConditionNameItem)
        ]
        if condition_names:
            result["condition_names"] = condition_names

        return result


class ConditionNameItem(ASTNode):
    """AST node for COBOL level-88 condition name items.

    A condition name binds one or more VALUES to a boolean condition that
    can be tested in the Procedure Division (e.g. ``IF STATUS-OPEN PERFORM ...``).
    It is always stored as a child of the immediately preceding elementary data item.
    """

    def __init__(self, name: str, location: SourceLocation):
        super().__init__("ConditionNameItem", location)
        self.name = name
        self.values: list[str] = []
        #: ``VALUE ... WHEN SET TO FALSE [IS] literal`` (IBM): the value
        #: ``SET condition-name TO FALSE`` moves into the conditional
        #: variable; ``None`` when the entry has no such phrase.
        self.false_value: str | None = None
        #: The kind of literal each entry of ``values`` was written as --
        #: ``"string"``, ``"numeric"``, ``"figurative"`` or ``"all"`` -- in
        #: the same order (``values`` keeps a quoted literal's content only,
        #: so ``'7'`` and ``7`` both read ``7``). ``None`` where the parser
        #: did not record it. Not serialized; lint's ``value-clause`` rule
        #: reads it.
        self.value_kinds: list[str | None] = []

    def add_value(self, value: str, kind: str | None = None) -> None:
        """Add a VALUE entry for this condition name."""
        self.values.append(value)
        self.value_kinds.append(kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type,
            "name": self.name,
            "values": self.values,
            "false_value": self.false_value,
            "location": self.location.to_dict(),
            "metadata": self._metadata or {},
        }


class RenamesItem(ASTNode):
    """AST node for COBOL level-66 RENAMES items.

    Declares a contiguous alias view over one or more existing data items.
    Always appears at the top level of a section (not nested under any 01-item).
    """

    def __init__(
        self,
        name: str,
        renames_from: str,
        location: SourceLocation,
        renames_through: str | None = None,
    ):
        super().__init__("RenamesItem", location)
        self.name = name
        self.renames_from = renames_from
        self.renames_through = renames_through
        #: ``RENAMES A OF REC THRU C OF REC``: the qualifiers that locate
        #: each operand, innermost first. ``renames_from`` /
        #: ``renames_through`` stay the bare data-names.
        self.renames_from_qualifiers: list[str] = []
        self.renames_through_qualifiers: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "node_type": self.node_type,
            "name": self.name,
            "renames_from": self.renames_from,
            "renames_through": self.renames_through,
            "location": self.location.to_dict(),
            "metadata": self._metadata or {},
        }
        if self.renames_from_qualifiers:
            result["renames_from_qualifiers"] = list(self.renames_from_qualifiers)
        if self.renames_through_qualifiers:
            result["renames_through_qualifiers"] = list(self.renames_through_qualifiers)
        return result


# Module exports
__all__ = [
    "PictureClause",
    "OccursClause",
    "CobolDataItem",
    "ConditionNameItem",
    "RenamesItem",
]
