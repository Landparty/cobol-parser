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
picture and in the edited text alike (``Z.ZZ9,99`` shows ``1.234,56``).  A ``SPECIAL-NAMES. CURRENCY SIGN``
symbol (``currency_signs={"#": "#"}``, ``{"F": "CHF "}``) is edited
exactly like ``$`` and shows its currency string in the one position the
``$`` would hold; a string of n characters makes the edited text n - 1
characters wider, the width :class:`~...models.data_items.PictureClause`
sizes the item at.  A picture using anything else (a currency symbol whose
declaration is unknown, two currency symbols) returns ``None`` and the
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

from collections.abc import Mapping
from decimal import ROUND_DOWN, Context, Decimal, InvalidOperation

from ...models.data_items import PictureClause

__all__ = ["deedit_float", "deedit_numeric", "edit_numeric", "is_float_picture"]

_SUPPORTED = frozenset({"9", "Z", "*", "0", "B", "/", ",", ".", "V", "+", "-"})
_SUPPORTED |= {"CR", "DB", "$"}
_FLOATING = ("$", "+", "-")
_SIMPLE_INSERTION = frozenset({"0", "B", "/", ","})
#: Symbols that can stand for a digit position (a floating string's too).
_DIGIT_SYMBOLS = frozenset({"9", "Z", "*", "$", "+", "-"})
#: ``DECIMAL-POINT IS COMMA`` exchanges ``,`` and ``.``; an involution, so the
#: same table maps a picture to the default spelling and edited text back.
_SWAP_DECIMAL = str.maketrans({",": ".", ".": ","})
#: Decimal arithmetic here must be exact: the default context's 28 digits
#: silently rounded a 31-digit value (``ARITH(EXTEND)``) before it was edited.
_EXACT = Context(prec=1000)


class _Layout:
    """One picture's symbols, with each one's role decided once.

    *scaling* is the number of ``P`` scaling positions the picture had
    (already removed from *symbols*: a ``P`` holds no character), and
    *scaling_leading* whether they sat left of every digit (``PPZZ``, a
    fraction) rather than right of them (``ZZPPP``, a multiple of 1000).
    """

    def __init__(
        self,
        symbols: list[str],
        floating: str | None,
        *,
        scaling: int = 0,
        scaling_leading: bool = False,
    ) -> None:
        self.symbols = symbols
        self.scaling = scaling
        self.scaling_leading = scaling_leading
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
    scaling = symbols.count("P")
    scaling_leading = False
    if scaling:
        # One contiguous run of P at one end of the digit positions: left of
        # every digit (a fraction) or right of every one (a large integer).
        # A P anywhere else is not a picture this module can edit.
        first = symbols.index("P")
        if symbols[first : first + scaling] != ["P"] * scaling:
            return None
        digits_before = any(s in _DIGIT_SYMBOLS for s in symbols[:first])
        digits_after = any(s in _DIGIT_SYMBOLS for s in symbols[first + scaling :])
        if digits_before == digits_after:
            return None
        scaling_leading = digits_after
        symbols = [s for s in symbols if s != "P"]
    if not symbols or any(s not in _SUPPORTED for s in symbols):
        return None
    floating = [f for f in _FLOATING if symbols.count(f) >= 2]
    if len(floating) > 1:
        return None
    return _Layout(
        symbols,
        floating[0] if floating else None,
        scaling=scaling,
        scaling_leading=scaling_leading,
    )


def _float_layout(picture: str | None) -> tuple[str, int, int, bool, str] | None:
    """An external floating-point picture (``-9.9(5)E-99``), or ``None``.

    Returns ``(mantissa_sign, integer_positions, fraction_positions,
    has_point, exponent_sign)``.  The shape IBM defines: a ``+`` or ``-``,
    a mantissa of ``9``s with exactly one ``.`` or ``V``, ``E``, a ``+`` or
    ``-``, and exactly two exponent ``9``s.
    """
    if not picture:
        return None
    symbols = [s.upper() for s in PictureClause._expand_symbols(picture)]
    if "E" not in symbols:
        return None
    at = symbols.index("E")
    mantissa, exponent = symbols[:at], symbols[at + 1 :]
    if len(mantissa) < 2 or mantissa[0] not in ("+", "-"):
        return None
    if exponent not in (["+", "9", "9"], ["-", "9", "9"]):
        return None
    body = mantissa[1:]
    points = [i for i, s in enumerate(body) if s in (".", "V")]
    if len(points) != 1 or any(s not in ("9", ".", "V") for s in body):
        return None
    split = points[0]
    integer_positions, fraction_positions = split, len(body) - split - 1
    if integer_positions + fraction_positions == 0:
        return None
    return (
        mantissa[0],
        integer_positions,
        fraction_positions,
        body[split] == ".",
        exponent[0],
    )


def _sign_char(symbol: str, negative: bool) -> str:
    """A fixed ``+`` shows ``+``/``-``; a fixed ``-`` shows a space/``-``."""
    if negative:
        return "-"
    return "+" if symbol == "+" else " "


def _edit_float(layout: tuple[str, int, int, bool, str], number: Decimal) -> str | None:
    """*number* in an external floating-point picture, normalized so the
    mantissa's leading digit is significant (``+1.23450E+02``)."""
    mantissa_sign, integer_positions, fraction_positions, has_point, exp_sign = layout
    width = integer_positions + fraction_positions
    magnitude = number.copy_abs()
    exponent = 0
    if magnitude:
        exponent = magnitude.adjusted() - (integer_positions - 1)
    scaled = int(
        magnitude.scaleb(
            fraction_positions - exponent, context=_EXACT
        ).to_integral_value(rounding=ROUND_DOWN, context=_EXACT)
    )
    if scaled == 0:
        exponent = 0
    if abs(exponent) > 99:
        return None
    digits = str(scaled).rjust(width, "0")
    point = "." if has_point else ""
    return (
        _sign_char(mantissa_sign, number < 0 and scaled != 0)
        + digits[:integer_positions]
        + point
        + digits[integer_positions:]
        + "E"
        + _sign_char(exp_sign, exponent < 0)
        + f"{abs(exponent):02d}"
    )


def is_float_picture(
    picture: str | None, *, decimal_point_is_comma: bool = False
) -> bool:
    """Whether *picture* is an external floating-point picture."""
    if decimal_point_is_comma and picture is not None:
        picture = picture.translate(_SWAP_DECIMAL)
    return _float_layout(picture) is not None


def deedit_float(
    picture: str | None, text: str, *, decimal_point_is_comma: bool = False
) -> Decimal | None:
    """The value *text* holds under an external floating-point *picture*.

    ``None`` when *picture* is not external floating-point, or *text* is not
    a value it can display.  *decimal_point_is_comma* as for
    :func:`edit_numeric`.
    """
    if decimal_point_is_comma:
        if picture is None:
            return None
        return deedit_float(
            picture.translate(_SWAP_DECIMAL), text.translate(_SWAP_DECIMAL)
        )
    layout = _float_layout(picture)
    if layout is None:
        return None
    mantissa_sign, integer_positions, fraction_positions, has_point, exp_sign = layout
    width = 1 + integer_positions + int(has_point) + fraction_positions + 4
    if len(text) != width:
        return None
    signs = ("+", "-") if mantissa_sign == "+" else (" ", "-")
    exp_signs = ("+", "-") if exp_sign == "+" else (" ", "-")
    body = text[1 : 1 + integer_positions + int(has_point) + fraction_positions]
    tail = text[len(text) - 4 :]
    digits = (
        body[:integer_positions] + body[integer_positions + 1 :] if has_point else body
    )
    if (
        text[0] not in signs
        or (has_point and body[integer_positions] != ".")
        or not digits.isdigit()
        or tail[0] != "E"
        or tail[1] not in exp_signs
        or not tail[2:].isdigit()
    ):
        return None
    exponent = int(tail[2:]) * (-1 if tail[1] == "-" else 1)
    value = Decimal(int(digits)).scaleb(exponent - fraction_positions, context=_EXACT)
    return -value if text[0] == "-" and value else value


def _currency_spelling(
    picture: str | None, currency_signs: Mapping[str, str | None]
) -> tuple[str | None, str | None] | None:
    """*picture* with its declared currency symbol spelled ``$``, and the
    currency string the edited text shows there instead (``None``: the
    picture uses no declared symbol).  ``None`` when the symbol's currency
    string is unknown, or the picture mixes it with ``$`` or another
    declared symbol -- forms this module does not model."""
    if picture is None:
        return None
    used = [symbol for symbol in currency_signs if symbol in picture]
    if not used:
        return picture, None
    if len(used) > 1 or "$" in picture:
        return None
    sign = currency_signs[used[0]]
    if not sign:
        return None
    return picture.replace(used[0], "$"), sign


def edit_numeric(
    picture: str | None,
    value: str,
    *,
    decimal_point_is_comma: bool = False,
    currency_signs: Mapping[str, str | None] | None = None,
) -> str | None:
    """*value* (a logical number, ``-1234.56``) as *picture* displays it.

    Returns ``None`` when the picture uses a symbol this module does not
    model.  A blank or non-numeric *value* edits as zero, the same way the
    other encoders treat it: a generated record must always be writable.
    *decimal_point_is_comma* reads *picture* under ``DECIMAL-POINT IS
    COMMA`` and writes the edited text the same way; *value* is always a
    logical number with a ``.`` decimal point.  *currency_signs* maps each
    ``CURRENCY SIGN`` symbol the picture may use to its currency string (see
    the module docstring).
    """
    if currency_signs:
        spelled = _currency_spelling(picture, currency_signs)
        if spelled is None:
            return None
        picture, sign = spelled
        edited = edit_numeric(
            picture, value, decimal_point_is_comma=decimal_point_is_comma
        )
        if edited is None or sign is None:
            return edited
        if "$" in edited:
            # One position shows the whole string; the item is that much
            # wider than its pattern (``PictureClause`` sizes it so, #491).
            return edited.replace("$", sign, 1)
        # Suppressed to spaces, currency position included: the extra
        # positions are spaces too.
        return " " * (len(sign) - 1) + edited
    if decimal_point_is_comma:
        if picture is None:
            return None
        edited = edit_numeric(picture.translate(_SWAP_DECIMAL), value)
        return None if edited is None else edited.translate(_SWAP_DECIMAL)
    float_layout = _float_layout(picture)
    layout = _layout(picture) if float_layout is None else None
    if layout is None and float_layout is None:
        return None
    try:
        number = Decimal((value or "").strip() or "0")
    except InvalidOperation:
        number = Decimal(0)
    if not number.is_finite():
        number = Decimal(0)
    if float_layout is not None:
        return _edit_float(float_layout, number)
    assert layout is not None
    if layout.scaling:
        # A P position holds no character: ``57000`` in ``ZZPPP`` shows
        # ``57``, and ``0.0012`` in ``PPZZ`` shows ``12``.
        number = number.scaleb(
            (
                (layout.scaling + layout.integer_positions)
                if layout.scaling_leading
                else -layout.scaling
            ),
            context=_EXACT,
        )
    negative = bool(number < 0)
    width = layout.integer_positions + layout.fraction_positions
    # Truncated, not rounded: a MOVE drops the places the picture has no
    # room for (``9.999`` into ``ZZ9.99`` edits as ``  9.99``).
    scaled = int(
        number.copy_abs()
        .scaleb(layout.fraction_positions, context=_EXACT)
        .to_integral_value(rounding=ROUND_DOWN, context=_EXACT)
    )
    return _edit_digits(layout, scaled % 10**width if width else 0, negative)


def _edit_digits(layout: _Layout, scaled: int, negative: bool) -> str:
    """*scaled* (the value as an integer of the picture's digit positions,
    already within its width) and its sign, as *layout* displays them."""
    width = layout.integer_positions + layout.fraction_positions
    digits = str(scaled).rjust(width, "0") if width else ""
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
    (keeping the decimal point) when ``*`` is the suppression symbol.

    "All" is every character position, a fixed sign or ``CR``/``DB`` among
    them: ``***.**CR`` edits zero as ``***.****``, just as ``***.**-`` edits
    it as ``***.***`` (IBM LRM, zero suppression and replacement editing;
    GnuCOBOL's move.c pads every non-decimal-point byte the same way)."""
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
            out.extend("**")
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
    picture: str | None,
    text: str,
    *,
    decimal_point_is_comma: bool = False,
    currency_signs: Mapping[str, str | None] | None = None,
) -> tuple[int, bool] | None:
    """The digits and sign *text* holds under *picture*.

    Returns ``(magnitude, negative)`` -- the value as an integer of the
    picture's digit positions, the scale implied by its fraction positions --
    or ``None`` when the picture is not one :func:`edit_numeric` models,
    *text* is not the picture's width, or *text* is not exactly what
    :func:`edit_numeric` writes for the value it holds -- a byte in an
    insertion, sign, ``CR``/``DB`` or currency position that no edit puts
    there, or a space in a ``9`` position, is rejected rather than read past.
    A suppressed digit position (a space, ``*``, the floating symbol) reads
    as zero, which is exactly what the edit put there.  *decimal_point_is_comma* as for
    :func:`edit_numeric`, and so is *currency_signs*.
    """
    if currency_signs:
        spelled = _currency_spelling(picture, currency_signs)
        if spelled is None:
            return None
        picture, sign = spelled
        if sign is not None:
            if "$" in text:
                # The declared sign replaces ``$``; a ``$`` is no edit's.
                return None
            if sign in text:
                text = text.replace(sign, "$", 1)
            elif not text[: len(sign) - 1].strip():
                # No currency shown (a value suppressed to spaces): the
                # string's extra positions are leading spaces.
                text = text[len(sign) - 1 :]
            else:
                return None
        return deedit_numeric(
            picture, text, decimal_point_is_comma=decimal_point_is_comma
        )
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
        elif (
            sym in _SIMPLE_INSERTION
            and layout.float_first < i < layout.float_last
            and layout.floating in ("+", "-")
        ):
            # A floating sign lands immediately left of the first digit
            # kept, which may be an insertion position inside the floating
            # string: ``PIC +++,+++`` edits -514 as ``   -514``, the ``-``
            # sitting where the comma would be.
            negative = negative or chunk == "-"
    magnitude = int("".join(digits)) if digits else 0
    negative = negative and magnitude != 0
    # The loop above reads digits and sign; it does not check the positions
    # that hold neither (an insertion ``.``/``,``/``B``/``/``, a fixed sign,
    # ``CR``/``DB``, ``$``) nor a space in a ``9`` position.  Editing the
    # value back and comparing does, exactly: ``'9999999'`` in ``ZZ9.99-``
    # is no value's edited form, so ``deedit(edit(v)) == v`` holds in both
    # directions rather than only one.
    if _edit_digits(layout, magnitude, negative) != text:
        return None
    return magnitude, negative
