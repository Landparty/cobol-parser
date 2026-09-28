"""Numeric-edited pictures: the display form a COBOL MOVE produces, and back.

A generated CSV carries a numeric-edited field's *logical* value (``1234.56``
for ``PIC $$,$$9.99``) -- the edit mask is presentation, and tooling reading
the CSV wants the number.  A record image is different: it holds the bytes a
program's ``MOVE`` into the field would have left there, which is the edited
form ``$1,234.56``.  :func:`edit_numeric` produces that form and
:func:`deedit_numeric` reads it back, so ``deedit(edit(v)) == v`` keeps
``decode(encode(row)) == row`` true for edited fields as it is for every
other storage class.

Supported symbols are the ones IBM Enterprise COBOL defines for a
numeric-edited item under the default ``CURRENCY SIGN``:
``9 Z * 0 B / , . V + - CR DB $``.  Under ``DECIMAL-POINT IS COMMA``
(``decimal_point_is_comma=True``) ``,`` and ``.`` exchange roles, in the
picture and in the edited text alike (``Z.ZZ9,99`` shows ``1.234,56``).  A picture using anything else (a ``P``
scaling position, a non-default currency symbol) returns ``None`` and the
caller keeps its previous behaviour rather than writing a guessed form.

Editing rules implemented (IBM Enterprise COBOL Language Reference,
"PICTURE clause editing"):

* ``Z`` and ``*`` suppress leading zeros, replacing them (and any simple
  insertion character among them) with a space or an asterisk respectively,
  until the first non-zero digit, a ``9``, or the decimal point.
* A floating insertion string -- two or more ``$``, ``+`` or ``-`` -- does the
  same, and then places its symbol immediately left of the first digit
  kept.  The leftmost symbol of the string holds no digit.
* A single ``$`` / ``+`` / ``-`` and ``CR`` / ``DB`` are fixed insertion
  characters: ``+`` shows ``+`` or ``-``, ``-`` shows a space or ``-``,
  ``CR`` / ``DB`` show themselves on a negative value and two spaces
  otherwise.
* A zero value in a picture whose every digit position is ``Z`` (or a
  floating symbol) edits to all spaces; with ``*`` it edits to all asterisks
  except the decimal point.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from ...models.data_items import PictureClause

__all__ = ["deedit_numeric", "edit_numeric"]

_SUPPORTED = frozenset({"9", "Z", "*", "0", "B", "/", ",", ".", "V", "+", "-"})
_SUPPORTED |= {"CR", "DB", "$"}
_FLOATING = ("$", "+", "-")
_SIMPLE_INSERTION = frozenset({"0", "B", "/", ","})
#: ``DECIMAL-POINT IS COMMA`` exchanges ``,`` and ``.``; an involution, so the
#: same table maps a picture to the default spelling and edited text back.
_SWAP_DECIMAL = str.maketrans({",": ".", ".": ","})


class _Layout:
    """One picture's symbols, with each one's role decided once."""

    def __init__(self, symbols: list[str], floating: str | None) -> None:
        self.symbols = symbols
        self.floating = floating
        first = last = -1
        if floating is not None:
            positions = [i for i, s in enumerate(symbols) if s == floating]
            first, last = positions[0], positions[-1]
        self.float_first = first
        self.float_last = last
        # Which symbols stand for a digit.
        self.is_digit = [
            s in ("9", "Z", "*") or (s == floating and first < i <= last)
            for i, s in enumerate(symbols)
        ]
        point = next(
            (i for i, s in enumerate(symbols) if s in (".", "V")), len(symbols)
        )
        self.integer_positions = sum(self.is_digit[:point])
        self.fraction_positions = sum(self.is_digit[point:])
        self.suppress_only = "9" not in symbols


def _layout(picture: str | None) -> _Layout | None:
    if not picture:
        return None
    symbols = [s.upper() for s in PictureClause._expand_symbols(picture)]
    if not symbols or any(s not in _SUPPORTED for s in symbols):
        return None
    floating = [f for f in _FLOATING if symbols.count(f) >= 2]
    if len(floating) > 1:
        return None
    return _Layout(symbols, floating[0] if floating else None)


def edit_numeric(
    picture: str | None, value: str, *, decimal_point_is_comma: bool = False
) -> str | None:
    """*value* (a logical number, ``-1234.56``) as *picture* displays it.

    Returns ``None`` when the picture uses a symbol this module does not
    model.  A blank or non-numeric *value* edits as zero, the same way the
    other encoders treat it: a generated record must always be writable.
    *decimal_point_is_comma* reads *picture* under ``DECIMAL-POINT IS
    COMMA`` and writes the edited text the same way; *value* is always a
    logical number with a ``.`` decimal point.
    """
    if decimal_point_is_comma:
        if picture is None:
            return None
        edited = edit_numeric(picture.translate(_SWAP_DECIMAL), value)
        return None if edited is None else edited.translate(_SWAP_DECIMAL)
    layout = _layout(picture)
    if layout is None:
        return None
    try:
        number = Decimal((value or "").strip() or "0")
    except InvalidOperation:
        number = Decimal(0)
    if not number.is_finite():
        number = Decimal(0)
    negative = number < 0
    width = layout.integer_positions + layout.fraction_positions
    scaled = int(abs(number).scaleb(layout.fraction_positions).to_integral_value())
    digits = str(scaled % 10**width).rjust(width, "0") if width else ""
    if scaled == 0:
        negative = False

    if scaled == 0 and layout.suppress_only:
        return _edit_zero(layout)

    out: list[str] = []
    fill = " "
    significant = False
    in_suppression = False
    significance_at = -1
    digit_index = 0
    for i, sym in enumerate(layout.symbols):
        if layout.is_digit[i]:
            digit = digits[digit_index]
            digit_index += 1
            if sym == "9" or significant or digit != "0":
                if not significant:
                    significant = True
                    significance_at = len(out)
                out.append(digit)
            else:
                in_suppression = True
                fill = "*" if sym == "*" else " "
                out.append(fill)
        elif i == layout.float_first:
            # The floating string's leftmost symbol: never a digit, and
            # rewritten below once significance says where the symbol lands.
            in_suppression = True
            fill = " "
            out.append(" ")
        elif sym in (".", "V"):
            if not significant:
                significant = True
                significance_at = len(out)
            if sym == ".":
                out.append(".")
        elif sym in _SIMPLE_INSERTION:
            if in_suppression and not significant:
                out.append(fill)
            else:
                out.append(" " if sym == "B" else sym)
        elif sym == "+":
            out.append("-" if negative else "+")
        elif sym == "-":
            out.append("-" if negative else " ")
        elif sym in ("CR", "DB"):
            out.extend(sym if negative else "  ")
        elif sym == "$":
            out.append("$")

    if layout.floating is not None:
        # The symbol sits immediately left of the first digit kept, but
        # never left of where the floating string itself starts.
        start = _output_index(layout, layout.float_first)
        at = max(start, (significance_at if significance_at >= 0 else len(out)) - 1)
        out[at] = _floating_char(layout.floating, negative)
    return "".join(out)


def _edit_zero(layout: _Layout) -> str:
    """A zero value in a picture with no ``9``: all spaces, or all ``*``
    (keeping the decimal point) when ``*`` is the suppression symbol."""
    width = sum(
        2 if s in ("CR", "DB") else 0 if s == "V" else 1 for s in layout.symbols
    )
    if "*" not in layout.symbols:
        return " " * width
    out: list[str] = []
    for sym in layout.symbols:
        if sym == "V":
            continue
        if sym in ("CR", "DB"):
            out.extend("  ")
        else:
            out.append("." if sym == "." else "*")
    return "".join(out)


def _output_index(layout: _Layout, symbol_index: int) -> int:
    """The character offset *symbol_index* starts at in the edited text."""
    return sum(
        2 if s in ("CR", "DB") else 0 if s == "V" else 1
        for s in layout.symbols[:symbol_index]
    )


def _floating_char(symbol: str, negative: bool) -> str:
    if symbol == "$":
        return "$"
    if symbol == "+":
        return "-" if negative else "+"
    return "-" if negative else " "


def deedit_numeric(
    picture: str | None, text: str, *, decimal_point_is_comma: bool = False
) -> tuple[int, bool] | None:
    """The digits and sign *text* holds under *picture*.

    Returns ``(magnitude, negative)`` -- the value as an integer of the
    picture's digit positions, the scale implied by its fraction positions --
    or ``None`` when the picture is not one :func:`edit_numeric` models,
    *text* is not the picture's width, or a digit position holds a character
    no edit could have put there.  A digit position holding anything
    but a digit (a space, ``*``, the floating symbol) reads as zero, which is
    exactly what the edit put there.  *decimal_point_is_comma* as for
    :func:`edit_numeric`.
    """
    if decimal_point_is_comma:
        if picture is None:
            return None
        return deedit_numeric(
            picture.translate(_SWAP_DECIMAL), text.translate(_SWAP_DECIMAL)
        )
    layout = _layout(picture)
    if layout is None:
        return None
    width = _output_index(layout, len(layout.symbols))
    if len(text) != width:
        return None
    digits: list[str] = []
    negative = False
    at = 0
    for i, sym in enumerate(layout.symbols):
        size = 2 if sym in ("CR", "DB") else 0 if sym == "V" else 1
        chunk = text[at : at + size]
        at += size
        if layout.is_digit[i]:
            if chunk.isdigit():
                digits.append(chunk)
                continue
            if chunk not in (" ", "*") and chunk != layout.floating:
                if not (layout.floating in ("+", "-") and chunk in ("+", "-")):
                    return None
            digits.append("0")
            negative = negative or chunk == "-"
        elif sym in ("+", "-") or i == layout.float_first:
            negative = negative or chunk == "-"
        elif sym in ("CR", "DB"):
            negative = negative or chunk.upper() == sym
    magnitude = int("".join(digits)) if digits else 0
    return magnitude, negative and magnitude != 0
