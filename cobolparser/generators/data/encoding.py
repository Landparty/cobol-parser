"""Byte-level record encoding: generated values -> real COBOL storage bytes.

Everything else in this package works in *display* form -- a CSV cell holds
``72436.21`` whether the field behind it is ``PIC 9(7)V99`` or
``PIC S9(7)V99 COMP-3``.  That is the right currency for a CSV, and for
mockymock (which splices ``MOVE <literal> TO <field>`` and lets the compiler
do the packing).  It is the wrong currency the moment someone wants the
*record image*: the actual bytes a program would ``READ``, or a dataset
uploaded to z/OS.  A ``COMP-3`` amount is five bytes of packed nibbles, not
nine characters of text, and no amount of CSV gets you there.

This module is that missing half.  It owns two things:

* :func:`encode_field` / :func:`encode_record` -- the display value from
  :mod:`.values` rendered into the bytes its field occupies.
* :func:`encoding_caveats` -- every reason the resulting image may not match
  what a real compiler lays out, so a caller can say so rather than hand
  over a plausible-looking lie.

The widths those encoders fill come from :mod:`.storage`, which is the one
authority on the question for the whole package (``layout_offsets`` defers
to it too, so ``data-items`` offsets and record images cannot disagree).

Deliberate limits, all of them loud rather than silent (see
:class:`RecordEncodingError` and :func:`encoding_caveats`):

* **SYNCHRONIZED is not modelled.**  Slack bytes before an aligned ``COMP``
  item would shift every following offset, and this package's offset model
  (``layout_offsets.compute_record_layout``, which backs ``data-items``) is
  unaligned throughout.  Guessing here would put two contradictory offset
  models in one repo, so a ``SYNCHRONIZED`` item is reported as a caveat
  instead.
* **COMP-1/COMP-2 are IEEE 754**, not z/OS hexadecimal floating point.
  That matches GnuCOBOL and Enterprise COBOL under ``FLOAT(IEEE)``; an HFP
  dataset needs a conversion this module does not do.
* **OCCURS DEPENDING ON** reserves its maximum under
  :attr:`RecordFormat.FIXED`, matching how the layout is flattened
  everywhere else in this package.  Under the variable-length formats the
  occurrences past the counter's own value are dropped instead, which is
  the whole difference between a RECFM=F and a RECFM=V image of the same
  copybook -- see :class:`RecordFormat`.
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from decimal import ROUND_DOWN, Context, Decimal, InvalidOperation
from enum import StrEnum

from ..._storage import (
    BINARY_NATIVE_USAGES,
    BINARY_USAGES,
    FIXED_SIZE_USAGES,
    FLOAT_USAGES,
    PACKED_USAGES,
    POINTER_USAGES,
    SINGLE_FLOAT_USAGES,
    binary_byte_length,
    is_known_usage,
)
from ..._vocabulary import FIGURATIVE_CONSTANTS
from ...layout.errors import CopybookLayoutError
from ...layout.fields import (
    FieldCategory,
    FieldSpec,
    LiteralCell,
    VaryingLength,
    _strip_literal_quotes,
    is_initial_value,
    present_indexes,
    unresolved_odo_counters,
    value_clause_hex_bytes,
)
from .editing import edit_numeric, is_float_picture


class RecordEncodingError(CopybookLayoutError):
    """Raised when a value cannot be rendered into its field's storage.

    A subclass of :class:`~.errors.CopybookLayoutError` so a caller that
    already handles "this copybook cannot be turned into records" keeps
    working, but distinguishable for callers that want to report the
    offending field.
    """


class Charset(StrEnum):
    """Character encoding for the DISPLAY-encoded bytes of a record."""

    ASCII = "ascii"
    EBCDIC = "ebcdic"


class Endian(StrEnum):
    """Byte order for the storage classes whose order is not fixed.

    Applies to ``COMP-5`` and to ``COMP-1``/``COMP-2``.  ``COMP``/``COMP-4``
    are *not* affected: they are always big-endian, which is both what IBM
    Enterprise COBOL defines and -- verified by compiling a probe program --
    what GnuCOBOL writes on a little-endian host, since its
    ``binary-byteorder`` default is big-endian.

    ``COMP-5`` is the opposite case, and the reason this enum exists: its
    whole point is *native* binary, so the same program produces big-endian
    bytes on z/OS and little-endian bytes on x86.  The same probe confirmed
    GnuCOBOL writes ``COMP-5`` and both float usages in host order.

    ``AUTO`` picks from the charset, which is the closest thing to a
    statement of intent available: an EBCDIC record is bound for z/OS and
    gets big-endian; an ASCII one is bound for the local runtime and gets
    host order.
    """

    AUTO = "auto"
    BIG = "big"
    LITTLE = "little"
    NATIVE = "native"


#: z/OS's traditional EBCDIC code page.  Chosen over the other cpXXX
#: variants because it is the one IBM Enterprise COBOL documentation and
#: every mainframe file-transfer default assume.
EBCDIC_CODEC = "cp037"

_EBCDIC_SPACE = 0x40
_ASCII_SPACE = 0x20

#: Zone nibbles of a signed EBCDIC zoned-decimal field's sign digit.
_EBCDIC_ZONE_UNSIGNED = 0xF0
_EBCDIC_ZONE_POSITIVE = 0xC0
_EBCDIC_ZONE_NEGATIVE = 0xD0

#: ASCII zoned decimal as GnuCOBOL writes it (``sign: ascii``): a positive
#: digit stays ``'0'``-``'9'``, a negative digit sets 0x40 in the zone, so
#: ``-1`` ends in ``'q'``.  Verified against GnuCOBOL's default config.
_ASCII_ZONE_UNSIGNED = 0x30
_ASCII_ZONE_POSITIVE = 0x30
_ASCII_ZONE_NEGATIVE = 0x70

#: Sign nibbles of a packed-decimal (COMP-3) field's low-order half-byte.
_PACKED_POSITIVE = "C"
_PACKED_NEGATIVE = "D"
_PACKED_UNSIGNED = "F"


class RecordFormat(StrEnum):
    """How the records of a generated file are sized and framed.

    COBOL files come in two shapes, and a copybook alone does not say which
    one a program expects:

    ``FIXED``
        RECFM=F/FB.  Every record is the same length -- the layout's full
        length -- and an ``OCCURS ... DEPENDING ON`` table reserves all of
        its occurrences whether or not the counter says they are used.  The
        default, and the only shape this package emitted before variable
        records existed.
    ``VARIABLE``
        RECFM=V/VB.  Each record holds only the occurrences its own counter
        names, and carries a 4-byte **RDW** (record descriptor word) saying
        how long it is: a big-endian 16-bit total length *including the RDW
        itself*, then two reserved zero bytes.  Without that prefix a reader
        handed a stream of differently-sized records has no way to find the
        next one, which is why the RDW is part of the format rather than a
        separate switch.
    ``VARIABLE_BARE``
        The same trimmed records with no RDW, for a consumer that already
        knows where each record ends -- typically because
        :attr:`EncodingOptions.record_separator` delimits them, or because
        the records are being read one at a time rather than from a stream.
    ``AUTO``
        ``VARIABLE`` when the layout contains an ``OCCURS ... DEPENDING ON``
        table, ``FIXED`` otherwise.  A copybook whose length genuinely varies
        is the one case where the fixed image is a guess, so this picks the
        shape the layout itself implies.  Resolved by
        :meth:`EncodingOptions.resolved_format`.
    """

    AUTO = "auto"
    FIXED = "fixed"
    VARIABLE = "variable"
    VARIABLE_BARE = "variable-bare"

    @property
    def is_variable(self) -> bool:
        """True for the two trimmed formats.  ``AUTO`` is False -- resolve it
        against a layout first."""
        return self in (RecordFormat.VARIABLE, RecordFormat.VARIABLE_BARE)


#: Bytes an RDW occupies in front of a RECFM=V record.
RDW_SIZE = 4
#: Largest value the RDW's 16-bit length field can express, and therefore the
#: longest record (RDW included) a RECFM=V dataset can hold.
MAX_VARIABLE_RECORD = 0xFFFF


def encode_rdw(body_length: int) -> bytes:
    """The record descriptor word for a record of *body_length* data bytes.

    ``LL LL 00 00``: the total length *including* these four bytes, as a
    big-endian halfword, then two reserved bytes that z/OS requires to be
    zero on a non-spanned record.  Big-endian regardless of
    :attr:`EncodingOptions.endian` and of the charset -- the RDW is physical
    file structure written by the access method, not data written by the
    program, so it does not follow the record's own conventions.
    """
    total = body_length + RDW_SIZE
    if total > MAX_VARIABLE_RECORD:
        raise RecordEncodingError(
            f"record of {body_length} bytes exceeds the {MAX_VARIABLE_RECORD}-byte "
            "limit an RDW can describe; a record this long needs RECFM=VS "
            "(spanned), which is not generated"
        )
    return total.to_bytes(2, "big") + b"\x00\x00"


@dataclass(frozen=True)
class EncodingOptions:
    """How to render a record's bytes.

    Attributes:
        charset: Encoding of every DISPLAY-encoded byte -- alphanumeric
            text, zoned decimal digits, edited pictures, and fill.
        endian: Byte order for ``COMP-5`` and the floating-point usages.
            ``COMP``/``COMP-4`` are always big-endian regardless.  Defaults
            to ``AUTO`` -- see :class:`Endian` and
            :attr:`resolved_endian`.
        record_separator: Bytes appended after every record.  Empty (the
            default) is a true fixed-length record file, as RECFM=F expects;
            ``b"\\n"`` makes a DISPLAY-only record image readable in a text
            editor, at the cost of no longer being a faithful RECFM=F image.
        record_format: Fixed- or variable-length records; see
            :class:`RecordFormat`.  Defaults to ``FIXED``, so a copybook with
            no ``OCCURS ... DEPENDING ON`` table -- which is every copybook
            whose length cannot vary -- encodes to exactly the bytes it
            always did.
    """

    charset: Charset = Charset.ASCII
    endian: Endian = Endian.AUTO
    record_separator: bytes = b""
    record_format: RecordFormat = RecordFormat.FIXED

    @property
    def space(self) -> int:
        """The charset's space byte, used for alphanumeric fill."""
        return _EBCDIC_SPACE if self.charset is Charset.EBCDIC else _ASCII_SPACE

    @property
    def resolved_endian(self) -> Endian:
        """:attr:`endian` with ``AUTO``/``NATIVE`` resolved to a real order.

        Always one of ``BIG``/``LITTLE``, so callers never have to think
        about the host, and every output path can report which one was used
        rather than leaving the reader to infer it.
        """
        host = Endian.BIG if sys.byteorder == "big" else Endian.LITTLE
        if self.endian is Endian.NATIVE:
            return host
        if self.endian is Endian.AUTO:
            return Endian.BIG if self.charset is Charset.EBCDIC else host
        return self.endian

    def resolved_format(
        self, specs: list[FieldSpec], *, varying: bool = False
    ) -> RecordFormat:
        """:attr:`record_format` with ``AUTO`` decided against *specs*.

        Always one of the three concrete formats, so every encoding path can
        branch on the answer without re-deriving it -- the same contract
        :attr:`resolved_endian` provides for byte order.

        *varying* reports the other reason a record's length is not fixed:
        an FD ``RECORD VARYING`` range, which lives outside the layout and
        so cannot be seen in *specs*.  Callers holding a
        :class:`~.layout.VaryingLength` pass ``True``.
        """
        if self.record_format is not RecordFormat.AUTO:
            return self.record_format
        if varying or any(spec.odo_controls for spec in specs):
            return RecordFormat.VARIABLE
        return RecordFormat.FIXED


def _normalized_usage(spec: FieldSpec) -> str:
    return (spec.usage or "DISPLAY").upper()


#: Figurative constants that fill a FILLER's every byte with one fixed byte.
_FILLER_FILL_BYTES: dict[str, int | None] = {
    "SPACE": None,  # the charset's own space byte
    "SPACES": None,
    "LOW-VALUE": 0x00,
    "LOW-VALUES": 0x00,
    "NULL": 0x00,
    "NULLS": 0x00,
    "HIGH-VALUE": 0xFF,
    "HIGH-VALUES": 0xFF,
}


def _filler_fill(spec: FieldSpec, opts: EncodingOptions) -> bytes | None:
    """The bytes a ``FILLER ... VALUE SPACES`` (or ``LOW-``/``HIGH-VALUES``,
    ``NULL``, optionally after ``ALL``) leaves in the record, else ``None``.

    The value generator reads those figuratives as "no meaningful content"
    and draws random text for the cell, which is right for a named field a
    program fills in -- and wrong for a FILLER, whose declared bytes are all
    it ever holds (the report-line gap between two columns).  ``None`` means
    the FILLER's cell is to be encoded as usual.
    """
    if not spec.is_filler or not spec.value_clause:
        return None
    word = spec.value_clause.strip().upper()
    if word.startswith("ALL "):
        word = word[4:].strip()
    if word not in _FILLER_FILL_BYTES:
        return None
    fill = _FILLER_FILL_BYTES[word]
    return bytes([opts.space if fill is None else fill]) * field_storage_size(spec)


def _total_digits(spec: FieldSpec) -> int:
    """Digit positions the field holds, floored at 1.

    A PICTURE-less numeric item (``INDEX``, ``POINTER``) never reaches the
    numeric encoders, so the floor only guards a malformed picture whose
    digit counts both came back zero.  ``P`` scaling positions are not
    stored (:attr:`FieldSpec.stored_digits`), so ``9(3)PPP`` is three.
    """
    return max(1, spec.stored_digits)


def _is_sign_separate(spec: FieldSpec) -> bool:
    return "SEPARATE" in (spec.sign_clause or "").upper()


def _is_sign_leading(spec: FieldSpec) -> bool:
    return "LEADING" in (spec.sign_clause or "").upper()


def _effective_data_length(
    specs: list[FieldSpec], data_length: int | None
) -> int | None:
    """*data_length*, unless an ``OCCURS DEPENDING ON`` table already decides.

    The two ways a record's length varies can both be declared at once, and
    then only one of them can win: the table does, because its count is real
    data that says how many occurrences this record holds, while an FD range
    only bounds the length. Cutting the table-trimmed body to an FD-drawn
    length on top would slice a table mid-occurrence at an unrelated offset.

    :meth:`~.copybook.CopybookDataGenerator.generate_from_record` already
    declines to draw a length for such a record, so nothing in this package
    passes both; this enforces it for a direct caller too, which is what
    keeps :func:`encoding_caveats`' promise ("the table decides") true
    everywhere rather than only on the generated path.
    """
    if data_length is None or any(spec.odo_controls for spec in specs):
        return None
    return data_length


def field_storage_size(spec: FieldSpec) -> int:
    """:attr:`FieldSpec.storage_size`, as a function for symmetry with the
    other module-level helpers here."""
    return spec.storage_size


def _encode_text(
    text: str, size: int, opts: EncodingOptions, *, justified: bool = False
) -> bytes:
    """Left-justified, space-padded, truncated to *size* -- COBOL's own
    alphanumeric MOVE semantics, applied at the byte level.

    *justified* (``JUSTIFIED RIGHT``) mirrors it: the value is right-aligned
    behind leading spaces, and an oversized one loses its leftmost
    characters rather than its rightmost.
    """
    codec = EBCDIC_CODEC if opts.charset is Charset.EBCDIC else "ascii"
    return _place_bytes(
        text.encode(codec, errors="replace"), size, opts, justified=justified
    )


def _place_bytes(
    raw: bytes, size: int, opts: EncodingOptions, *, justified: bool = False
) -> bytes:
    """*raw* in a *size*-byte alphanumeric field: padded with the charset's
    space or truncated, left-aligned unless *justified* (see
    :func:`_encode_text`)."""
    if len(raw) >= size:
        return raw[len(raw) - size :] if justified else raw[:size]
    pad = bytes([opts.space]) * (size - len(raw))
    return pad + raw if justified else raw + pad


#: Exact decimal arithmetic for :func:`_scaled_integer`.  The default context
#: holds 28 significant digits, and ``scaleb`` rounds to it: a 31-digit
#: ``ARITH(EXTEND)`` value lost its low-order digits before it was packed.
_EXACT = Context(prec=1000)


def _scaled_integer(text: str, spec: FieldSpec) -> int:
    """The field's value as an integer of its own digit positions.

    ``72436.21`` in a ``V99`` field is the integer ``7243621``: COBOL stores
    no decimal point, only an implied scale.  A blank cell (``blank_rate``)
    and a non-numeric cell both encode as zero rather than failing -- a
    generated record must always be writable.
    """
    stripped = (text or "").strip()
    if not stripped:
        return 0
    try:
        value = Decimal(stripped)
    except (InvalidOperation, ValueError):
        return 0
    if not value.is_finite():
        return 0
    # Quantize by shifting the exponent rather than multiplying: exact for
    # every value _format_number can have produced, including PIC 9(18).
    units = value.scaleb(spec.decimal_digits, context=_EXACT)
    scaling = spec.scaling_positions
    if scaling > 0:
        # Trailing P: the low `scaling` digits are implied zeros that no
        # byte holds -- ``123000`` in ``9(3)PPP`` is stored as ``123``.
        # Truncation, not rounding, is what the compiler does with a value
        # that is not a whole multiple (``123456`` -> ``123``).
        return int(
            units.scaleb(-scaling, context=_EXACT).to_integral_value(
                rounding=ROUND_DOWN, context=_EXACT
            )
        )
    # Decimal places beyond the PICTURE's are truncated, not rounded, as a
    # COBOL numeric MOVE does: ``9.999`` into ``9V99`` stores ``999``.
    # Rounding (half-even) stored ``1000``, which the high-order truncation
    # in `_digits_string` then turned into ``000`` -- a zero.
    return int(units.to_integral_value(rounding=ROUND_DOWN, context=_EXACT))


def _digits_string(magnitude: int, digits: int) -> str:
    """*magnitude* as exactly *digits* characters, high-order truncated.

    Truncation matches COBOL's own numeric MOVE (an oversized value loses
    its high-order digits, it does not raise), and cannot happen for a value
    that :mod:`.values` generated for this field in the first place.
    """
    return str(magnitude).rjust(digits, "0")[-digits:]


def _encode_zoned(text: str, spec: FieldSpec, opts: EncodingOptions) -> bytes:
    """Numeric DISPLAY: one byte per digit, sign as an overpunch or a
    SIGN IS SEPARATE byte of its own."""
    digits = _total_digits(spec)
    scaled = _scaled_integer(text, spec)
    negative = scaled < 0 and spec.is_signed
    body = _digits_string(abs(scaled), digits)

    # The overpunch convention is a property of the charset, not a separate
    # choice: EBCDIC zones the sign into the C/D nibbles, ASCII (as GnuCOBOL
    # writes and reads it) sets 0x40 in the zone of the signed digit.  The
    # third convention in the wild -- EBCDIC signs transcoded into ASCII as
    # `{ABC`/`}JKL` -- is deliberately not offered: it belongs to files
    # already converted off a mainframe, and there is no compiler here to
    # verify an implementation of it against.
    if opts.charset is Charset.EBCDIC:
        unsigned_zone = _EBCDIC_ZONE_UNSIGNED
        signed_zone = _EBCDIC_ZONE_NEGATIVE if negative else _EBCDIC_ZONE_POSITIVE
    else:
        unsigned_zone = _ASCII_ZONE_UNSIGNED
        signed_zone = _ASCII_ZONE_NEGATIVE if negative else _ASCII_ZONE_POSITIVE

    raw = bytearray(unsigned_zone | int(d) for d in body)

    if not spec.is_signed:
        return bytes(raw)
    if _is_sign_separate(spec):
        sign_byte = _encode_text("-" if negative else "+", 1, opts)
        return (
            bytes(sign_byte + raw) if _is_sign_leading(spec) else bytes(raw + sign_byte)
        )
    index = 0 if _is_sign_leading(spec) else len(raw) - 1
    raw[index] = signed_zone | (raw[index] & 0x0F)
    return bytes(raw)


def _encode_packed(text: str, spec: FieldSpec) -> bytes:
    """COMP-3: two BCD digit nibbles per byte, sign in the low nibble."""
    digits = _total_digits(spec)
    scaled = _scaled_integer(text, spec)
    negative = scaled < 0 and spec.is_signed
    body = _digits_string(abs(scaled), digits)
    if not spec.is_signed:
        sign = _PACKED_UNSIGNED
    else:
        sign = _PACKED_NEGATIVE if negative else _PACKED_POSITIVE
    nibbles = body + sign
    if len(nibbles) % 2:
        nibbles = "0" + nibbles
    return bytes.fromhex(nibbles)


def _encode_binary(text: str, spec: FieldSpec, opts: EncodingOptions) -> bytes:
    """COMP/COMP-4/COMP-5: two's-complement integer of the field's width."""
    usage = _normalized_usage(spec)
    digits = _total_digits(spec)
    width = binary_byte_length(digits)
    order: str = (
        opts.resolved_endian.value
        if usage in BINARY_NATIVE_USAGES
        else Endian.BIG.value
    )
    scaled = _scaled_integer(text, spec)
    if not spec.is_signed and scaled < 0:
        scaled = -scaled
    try:
        return scaled.to_bytes(width, order, signed=spec.is_signed)  # type: ignore[arg-type]
    except OverflowError as exc:
        # Reachable, unlike the zoned and packed encoders: those run their
        # magnitude through `_digits_string`, which truncates to the
        # PICTURE's digit count the way a COBOL numeric MOVE does, so they
        # cannot overflow. Binary has no such step -- a value that does not
        # fit the field's *byte width* has no representation at all here, so
        # it is refused rather than silently reshaped. Nothing this package
        # generates can reach it (`ValueFactory` respects the PICTURE, and a
        # VALUE clause is clamped to it); a caller handing `encode_record` a
        # row of its own can.
        raise RecordEncodingError(
            f"{spec.qualified_name}: value {scaled} does not fit "
            f"{width} bytes of {usage}"
        ) from exc


def _encode_float(text: str, spec: FieldSpec, opts: EncodingOptions) -> bytes:
    """COMP-1/COMP-2 as IEEE 754 binary32/binary64.  See the module
    docstring on why this is not z/OS hexadecimal floating point."""
    stripped = (text or "").strip()
    try:
        value = float(stripped) if stripped else 0.0
    except ValueError:
        value = 0.0
    single = _normalized_usage(spec) in SINGLE_FLOAT_USAGES
    prefix = "<" if opts.resolved_endian is Endian.LITTLE else ">"
    try:
        return struct.pack(f"{prefix}{'f' if single else 'd'}", value)
    except OverflowError as exc:
        raise RecordEncodingError(
            f"{spec.qualified_name}: {value} is out of range for "
            f"{_normalized_usage(spec)}"
        ) from exc


def encode_field(spec: FieldSpec, text: str, opts: EncodingOptions) -> bytes:
    """Render one generated cell into the bytes its field occupies.

    The result is always exactly :func:`field_storage_size` bytes long --
    that invariant is what lets :func:`encode_record` concatenate blindly
    and still land on the record length the layout predicted.
    """
    usage = _normalized_usage(spec)
    width = field_storage_size(spec)
    if width == 0:
        return b""

    if spec.is_filler and not spec.value_clause:
        # FILLER names no field a program reads, so whatever the value
        # generator put in its CSV cell is noise in a record image.  An empty
        # cell falls through every encoder below as spaces (text) or zeros
        # (numeric) -- COBOL's own convention for uninitialized filler --
        # without any of them needing to know about FILLER.
        text = ""
    filled = _filler_fill(spec, opts)
    if filled is not None:
        return filled
    # A VALUE-clause initial value is stored as declared: initialisation is
    # not affected by JUSTIFIED or BLANK WHEN ZERO (#558).  Both still apply
    # to every other cell, which stands for a MOVE result.
    justified = spec.justified and not is_initial_value(text)

    if usage in FIXED_SIZE_USAGES or not is_known_usage(usage):
        # COBOL 2002 FLOAT-EXTENDED / BINARY-CHAR..DOUBLE (sized exactly,
        # bytes not modelled) or a USAGE word nothing here knows: zeros of
        # the field's width, named in ``encoding_caveats`` (#524).
        return bytes(width)
    if usage == "INDEX" or usage in POINTER_USAGES:
        # Neither is file data: an index is a compiler-managed occurrence
        # number and a pointer is an address, both meaningless in a record
        # written by anything other than the running program.  Binary zeros
        # are the only honest content.
        return bytes(width)
    if usage in FLOAT_USAGES:
        return _encode_float(text, spec, opts)
    if usage in PACKED_USAGES:
        return _encode_packed(text, spec)
    if usage in BINARY_USAGES:
        return _encode_binary(text, spec, opts)
    if usage == "NATIONAL":
        # Numeric / numeric-edited national (``PIC 9(5) USAGE NATIONAL``):
        # two bytes per position.  National data is not modelled as UTF-16
        # (see ``encoding_caveats``), so -- like a ``PIC N`` field -- the
        # value is written as text padded to the field's full width rather
        # than as five zoned bytes in a ten-byte slot.
        return _encode_text(text, width, opts, justified=justified)
    # DISPLAY from here down.  An unedited numeric picture is zoned decimal.
    # A numeric-edited one holds what a MOVE into it would leave: the CSV
    # cell is the logical value (`1234.56`), the bytes are the edited form
    # (`$1,234.56`).  A picture `edit_numeric` does not model keeps the
    # cell's text as is.
    if (
        spec.blank_when_zero
        and not is_initial_value(text)
        and spec.category in (FieldCategory.NUMERIC, FieldCategory.NUMERIC_EDITED)
        and _scaled_integer(text, spec) == 0
    ):
        # BLANK WHEN ZERO: a zero value is stored as spaces, not digits.
        return bytes([opts.space]) * width
    if spec.category is FieldCategory.NUMERIC:
        return _encode_zoned(text, spec, opts)
    if spec.category is FieldCategory.NUMERIC_EDITED:
        edited = edit_numeric(
            spec.picture,
            text,
            decimal_point_is_comma=spec.decimal_point_is_comma,
            currency_signs=spec.currency_signs,
        )
        if edited is not None and len(edited) == width:
            return _encode_text(edited, width, opts)
    if isinstance(text, LiteralCell):
        # A hex literal (``VALUE X'C1C2'``) names bytes, not characters: the
        # cell is only their Latin-1 stand-in, and re-encoding it in the
        # record charset wrote C1 C2 as ``?``s (ASCII) or 65 62 (EBCDIC).
        # The bytes come with the cell, not from a lookup by its text: an
        # ordinary ``'AB'`` or ``VALUE SPACE`` with the same text as a hex
        # literal's stand-in is still charset-encoded.
        return _place_bytes(
            literal_cell_bytes(text, opts), width, opts, justified=justified
        )
    return _encode_text(text, width, opts, justified=justified)


def literal_cell_bytes(cell: LiteralCell, opts: EncodingOptions) -> bytes:
    """The bytes *cell* is written as: its own :attr:`~LiteralCell.data`,
    with any :attr:`~LiteralCell.text_runs` (the basic parts of ``'AB' &
    X'0102'``) in the record charset (#479)."""
    if not cell.text_runs:
        return cell.data
    out = bytearray(cell.data)
    for start, end in cell.text_runs:
        out[start:end] = _encode_text(
            cell.data[start:end].decode("latin-1"), end - start, opts
        )
    return bytes(out)


#: Figurative constants as the cell :class:`~.values.ValueFactory` writes for
#: a level-88 (or ``ZERO``/``QUOTE`` VALUE clause) naming them: every
#: position filled with the character, ``SPACE`` as the empty cell.
_FIGURATIVE_FILL: dict[str, str] = {
    "SPACE": "",
    "SPACES": "",
    "ZERO": "0",
    "ZEROS": "0",
    "ZEROES": "0",
    "QUOTE": '"',
    "QUOTES": '"',
}

#: Every figurative word, writable or not.
_ALL_FIGURATIVES = FIGURATIVE_CONSTANTS


def _ordinary_literal_cells(spec: FieldSpec) -> list[str]:
    """The cells *spec*'s own non-hex declared values are generated as: its
    level-88 literals and figuratives, and a quoted or ``ZERO``/``QUOTE``
    VALUE clause.  ``VALUE SPACES``/``LOW-VALUES`` are left out because the
    generator replaces them with a random value."""
    raws = [v for v in spec.condition_values if not isinstance(v, LiteralCell)]
    if (
        spec.value_clause
        and value_clause_hex_bytes(spec.value_clause, spec.character_positions) is None
    ):
        clause = spec.value_clause.strip()
        if clause.upper() in ("ZERO", "ZEROS", "ZEROES", "QUOTE", "QUOTES"):
            raws.append(clause)
        elif clause.upper() not in _ALL_FIGURATIVES:
            raws.append(_strip_literal_quotes(clause))
    width = max(1, spec.character_positions)
    cells: list[str] = []
    for raw in raws:
        fill = _FIGURATIVE_FILL.get(raw.upper())
        if fill is not None:
            cells.append(fill * width)
        elif raw.upper() not in _ALL_FIGURATIVES:
            cells.append(raw)
    return cells


def hex_literal_cell_for(
    spec: FieldSpec, raw: bytes, opts: EncodingOptions
) -> str | None:
    """The hex literal cell *raw* was written from, for the decoder.

    :func:`encode_field` writes a :class:`LiteralCell` as its own bytes, so
    reading them back in the record charset gives other text (``X'FF'`` is
    ``\x9f`` in EBCDIC, ``X'C1C2'`` is ``AB``) and ``decode(encode(row))``
    would not be *row*.  When *raw* is exactly one of the field's hex
    literals, padded the way the encoder pads it, this returns that
    literal's cell.  ``None`` when it is not, or when one of the field's
    ordinary declared values encodes to the same bytes (``'AB'`` next to
    ``X'C1C2'`` under EBCDIC): the bytes cannot say which was meant, and the
    charset reading is the honest one.
    """
    if not spec.literal_bytes:
        return None
    width = spec.storage_size
    if len(raw) != width:
        return None
    # A VALUE-clause cell is placed left-aligned even under JUSTIFIED RIGHT
    # (#558), a level-88 one right-aligned: either placement is the literal.
    alignments = {spec.justified, False}
    for cell, data in spec.literal_bytes.items():
        if isinstance(cell, LiteralCell):
            data = literal_cell_bytes(cell, opts)
        if all(_place_bytes(data, width, opts, justified=j) != raw for j in alignments):
            continue
        for ordinary in _ordinary_literal_cells(spec):
            if any(
                _encode_text(ordinary, width, opts, justified=j) == raw
                for j in alignments
            ):
                return None
        return cell
    return None


def encode_record(
    specs: list[FieldSpec],
    row: list[str],
    opts: EncodingOptions,
    *,
    data_length: int | None = None,
    pad_to: int | None = None,
) -> bytes:
    """Concatenate one generated row into its record image.

    *specs* must be the byte-complete layout -- FILLER included, REDEFINES
    excluded, every OCCURS occurrence expanded -- which is what
    :meth:`~.copybook.CopybookDataGenerator` builds when asked for record
    output.  A layout missing FILLER would silently produce short records.

    Under :attr:`RecordFormat.FIXED` every field in *specs* contributes its
    bytes, so the result is the same length for every row.  Under either
    variable format only the occurrences this row's ``OCCURS ... DEPENDING
    ON`` counters actually name are written (see
    :func:`~.layout.present_indexes`), and ``VARIABLE`` prefixes the RDW that
    tells a reader where the record ends.

    *data_length* is the other source of a short record: an FD
    ``RECORD VARYING FROM min TO max`` range, under which the layout is an
    ordinary fixed one and each record simply carries fewer of its bytes.
    The body is cut to that many bytes -- mid-field if that is where the
    length falls, which is exactly what a program reading
    ``REC(1:LEN)`` sees.  Passing it also settles
    :attr:`RecordFormat.AUTO`, since a declared length is by definition a
    record that varies.  The length is drawn per row at *generation* time
    (:meth:`~.copybook.CopybookDataGenerator.generate_from_record`) rather
    than here, so this function stays deterministic and RNG-free.

    *pad_to* is the file's ``LRECL`` under :attr:`RecordFormat.FIXED` when
    it is longer than this layout -- a shorter 01 under an FD that also
    declares a longer one.  The record is filled out to it with the
    charset's space, because RECFM=F means every record is that long.
    """
    if len(specs) != len(row):
        raise RecordEncodingError(
            f"row has {len(row)} cells but the layout has {len(specs)} fields"
        )
    fmt = opts.resolved_format(specs, varying=data_length is not None)
    declared = _effective_data_length(specs, data_length)
    if fmt is RecordFormat.FIXED:
        body = b"".join(
            encode_field(spec, cell, opts)
            for spec, cell in zip(specs, row, strict=True)
        )
        if pad_to is not None and pad_to > len(body):
            body += bytes([opts.space]) * (pad_to - len(body))
    else:
        body = b"".join(
            encode_field(specs[index], row[index], opts)
            for index in present_indexes(specs, row)
        )
        if declared is not None:
            body = body[:declared]
    return encode_rdw(len(body)) + body if fmt is RecordFormat.VARIABLE else body


def record_length(specs: list[FieldSpec]) -> int:
    """Byte length of the record *specs* describes, every occurrence present.

    The fixed-length answer, and the *maximum* for a variable-length file --
    which is the number RECFM=V's ``LRECL`` is set from, so it stays the
    headline length either way.  For what one particular row occupies, see
    :func:`row_record_length`.
    """
    return sum(field_storage_size(spec) for spec in specs)


def minimum_record_length(specs: list[FieldSpec]) -> int:
    """Byte length of the shortest record *specs* can produce.

    Every ``OCCURS ... DEPENDING ON`` table at its declared minimum; equal to
    :func:`record_length` for a layout without one.  Together the two bound
    the ``LRECL`` range a variable-length dataset needs.
    """
    kept = 0
    for spec in specs:
        if any(
            spec.subscripts[control.subscript_index] > control.min_times
            for control in spec.odo_controls
            if control.subscript_index < len(spec.subscripts)
        ):
            continue
        kept += field_storage_size(spec)
    return kept


def row_record_length(
    specs: list[FieldSpec],
    row: list[str],
    opts: EncodingOptions | None = None,
    *,
    data_length: int | None = None,
    pad_to: int | None = None,
) -> int:
    """Byte length one generated *row* occupies, RDW included when framed.

    Cheaper than measuring ``len(encode_record(...))`` -- it sums the widths
    the layout already knows rather than building the bytes -- and used
    wherever a length is wanted for reporting rather than for writing.
    *data_length* and *pad_to* mean the same things they do on
    :func:`encode_record`.
    """
    options = opts or EncodingOptions()
    fmt = options.resolved_format(specs, varying=data_length is not None)
    if fmt is RecordFormat.FIXED:
        return max(record_length(specs), pad_to or 0)
    body = sum(
        field_storage_size(specs[index]) for index in present_indexes(specs, row)
    )
    declared = _effective_data_length(specs, data_length)
    if declared is not None:
        body = min(body, declared)
    return body + RDW_SIZE if fmt is RecordFormat.VARIABLE else body


def encoding_caveats(
    specs: list[FieldSpec],
    opts: EncodingOptions | None = None,
    *,
    varying: VaryingLength | None = None,
) -> list[str]:
    """Every reason a record image built from *specs* may not match what a
    real compiler lays out.

    Returned rather than raised: the image is still the best available
    answer, and a caller that surfaces these (the CLI prints them to stderr,
    the hex dump inlines them) leaves the user better off than one that
    refuses.  Empty means the layout is fully modelled.

    *opts* decides which ``OCCURS DEPENDING ON`` caveat applies -- reserving
    the maximum is a limitation of a fixed-length image but the definition of
    a variable-length one -- and defaults to the fixed-length reading, so a
    caller that does not care about record format keeps the answer it always
    got.
    """
    caveats: list[str] = []
    synchronized = sorted({spec.qualified_name for spec in specs if spec.synchronized})
    if synchronized:
        caveats.append(
            "SYNCHRONIZED alignment is not modelled -- these items may sit at "
            "a higher offset under a real compiler, shifting everything after "
            f"them: {', '.join(synchronized)}"
        )
    unmodelled = sorted(
        {
            f"{spec.qualified_name} ({_normalized_usage(spec)})"
            for spec in specs
            if _normalized_usage(spec) in FIXED_SIZE_USAGES
        }
    )
    if unmodelled:
        caveats.append(
            "these USAGEs are sized but their bytes are not modelled; written "
            f"as binary zeros: {', '.join(unmodelled)}"
        )
    unknown = sorted(
        {
            f"{spec.qualified_name} ({_normalized_usage(spec)})"
            for spec in specs
            if not is_known_usage(spec.usage)
        }
    )
    if unknown:
        caveats.append(
            "unsupported USAGE: the field's byte length is unknown, so it and "
            "every later offset in the record may be wrong (written as binary "
            f"zeros): {', '.join(unknown)}"
        )
    floats = sorted(
        {
            spec.qualified_name
            for spec in specs
            if _normalized_usage(spec) in FLOAT_USAGES
        }
    )
    if floats:
        caveats.append(
            "COMP-1/COMP-2 are encoded as IEEE 754, not z/OS hexadecimal "
            f"floating point: {', '.join(floats)}"
        )
    # DBCS (PIC G, or PIC N with USAGE DISPLAY-1) is its own caveat, not
    # the national one: what a real compiler stores there is double-byte
    # EBCDIC (e.g. X'42C1' for a DBCS "A"), not UTF-16.
    dbcs = sorted(
        {
            spec.qualified_name
            for spec in specs
            if _normalized_usage(spec) == "DISPLAY-1"
            and spec.category
            not in (
                FieldCategory.NUMERIC,
                FieldCategory.NUMERIC_EDITED,
                FieldCategory.FLOAT,
            )
        }
    )
    national = sorted(
        {
            spec.qualified_name
            for spec in specs
            if spec.category is FieldCategory.NATIONAL
            or _normalized_usage(spec) == "NATIONAL"
        }
        - set(dbcs)
    )
    if national:
        caveats.append(
            "national data (PIC N / USAGE NATIONAL) is written as single-byte "
            "text in the record's charset, space-padded to the field's width, "
            "not as the UTF-16 a real compiler stores (and a real file's "
            "national bytes do not decode back as the same text): "
            f"{', '.join(national)}"
        )
    utf8 = sorted(
        {spec.qualified_name for spec in specs if spec.utf8_characters is not None}
    )
    if utf8:
        caveats.append(
            "UTF-8 data (PIC U(n)) is written as single-byte text in the "
            "record's charset, space-padded to the 4 x n bytes the field "
            "reserves, not as the UTF-8 a real compiler stores: "
            f"{', '.join(utf8)}"
        )
    unedited = sorted(
        {
            spec.qualified_name
            for spec in specs
            if spec.category is FieldCategory.NUMERIC_EDITED
            and _normalized_usage(spec) == "DISPLAY"
            and not is_float_picture(
                spec.picture, decimal_point_is_comma=spec.decimal_point_is_comma
            )
            and edit_numeric(
                spec.picture,
                "0",
                decimal_point_is_comma=spec.decimal_point_is_comma,
                currency_signs=spec.currency_signs,
            )
            is None
        }
    )
    if unedited:
        caveats.append(
            "numeric-edited picture not modelled (e.g. two CURRENCY SIGN "
            "symbols in one picture): the field is written as its logical value, "
            "unedited, not as the edited form a MOVE leaves: "
            f"{', '.join(unedited)}"
        )
    if dbcs:
        caveats.append(
            "DBCS data (PIC G / USAGE DISPLAY-1) is written as single-byte "
            "text in the record's charset, space-padded to the field's width, "
            "not as the double-byte characters a real compiler stores (and a "
            "real file's DBCS bytes do not decode back as the same text): "
            f"{', '.join(dbcs)}"
        )
    fmt = (opts or EncodingOptions()).resolved_format(
        specs, varying=varying is not None
    )
    if varying is not None and any(spec.odo_controls for spec in specs):
        caveats.append(
            "this record has both an OCCURS DEPENDING ON table and an FD "
            "RECORD VARYING range; the table decides each record's length, "
            "and the FD range is not applied on top of it"
        )
    if varying is not None and not fmt.is_variable:
        caveats.append(
            f"a record-length range of {varying.minimum} to {varying.maximum} "
            "is declared, but fixed-length output was asked for, so every "
            "record is written at full length"
        )
    depending = sorted(
        {spec.qualified_name for spec in specs if spec.occurs_depending_on is not None}
    )
    if depending and not fmt.is_variable:
        caveats.append(
            "OCCURS DEPENDING ON tables are written at their maximum length, "
            "as RECFM=F requires; a real variable-length record would be "
            "shorter when the depending-on item is less than that maximum -- "
            "RecordFormat.VARIABLE (--record-format variable) writes that "
            f"instead: {', '.join(depending)}"
        )
    if fmt.is_variable:
        orphans = unresolved_odo_counters(specs)
        if orphans:
            caveats.append(
                "these OCCURS DEPENDING ON counters are not part of the record, "
                "so nothing generated can set them and their tables are written "
                f"at full length: {', '.join(orphans)}"
            )
    return caveats


#: Hex bytes shown on one dump line before wrapping onto a continuation.
_DUMP_BYTES_PER_LINE = 8


def _printable(raw: bytes, opts: EncodingOptions) -> str:
    """*raw* as text, with every non-printable byte shown as ``.``.

    Decoded through the record's own charset, so an EBCDIC dump reads as the
    characters a mainframe would see rather than as mojibake.
    """
    codec = EBCDIC_CODEC if opts.charset is Charset.EBCDIC else "latin-1"
    text = raw.decode(codec, errors="replace")
    return "".join(ch if ch.isprintable() else "." for ch in text)


def _dump_field_lines(
    spec: FieldSpec,
    cell: str,
    offset: int,
    raw: bytes,
    opts: EncodingOptions,
) -> list[str]:
    """One field's rows in the hex dump: what it is, then its bytes."""
    picture = spec.picture or ""
    usage = _normalized_usage(spec)
    blank = spec.is_filler and (
        not spec.value_clause or _filler_fill(spec, opts) is not None
    )
    value = "" if blank else cell
    head = (
        f"{offset:06X}  {len(raw):>4}  {spec.column[:24]:<24} "
        f"{picture[:14]:<14} {usage:<9} {value[:18]:<18} "
    )
    indent = " " * len(head)
    lines: list[str] = []
    for start in range(0, max(len(raw), 1), _DUMP_BYTES_PER_LINE):
        chunk = raw[start : start + _DUMP_BYTES_PER_LINE]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        prefix = head if start == 0 else indent
        lines.append(
            f"{prefix}{hex_part:<{_DUMP_BYTES_PER_LINE * 3}} |{_printable(chunk, opts)}|"
        )
    return lines


def _dump_absent_lines(spec: FieldSpec, offset: int) -> list[str]:
    """A field the record's declared length stops short of."""
    return [
        f"{offset:06X}     0  {spec.column[:24]:<24} "
        f"{(spec.picture or '')[:14]:<14} {_normalized_usage(spec):<9} "
        f"{'(past record length)':<18} "
    ]


def _dump_slack_lines(offset: int, size: int, opts: EncodingOptions) -> list[str]:
    """The space fill out to the FD's LRECL, shaped like a FILLER's rows."""
    raw = bytes([opts.space]) * size
    head = (
        f"{offset:06X}  {size:>4}  {'(FD LRECL slack)':<24} {'':<14} {'':<9} {'':<18} "
    )
    indent = " " * len(head)
    return [
        f"{head if start == 0 else indent}"
        f"{' '.join(f'{b:02X}' for b in chunk):<{_DUMP_BYTES_PER_LINE * 3}} "
        f"|{_printable(chunk, opts)}|"
        for start in range(0, size, _DUMP_BYTES_PER_LINE)
        for chunk in [raw[start : start + _DUMP_BYTES_PER_LINE]]
    ]


def _dump_rdw_lines(rdw: bytes, opts: EncodingOptions) -> list[str]:
    """The RDW's own row in the hex dump, shaped like a field's."""
    head = (
        f"{0:06X}  {len(rdw):>4}  {'(RDW)':<24} "
        f"{'':<14} {'':<9} {int.from_bytes(rdw[:2], 'big'):<18} "
    )
    hex_part = " ".join(f"{b:02X}" for b in rdw)
    return [f"{head}{hex_part:<{_DUMP_BYTES_PER_LINE * 3}} |{_printable(rdw, opts)}|"]


def hex_dump(
    specs: list[FieldSpec],
    rows: list[list[str]],
    opts: EncodingOptions,
    *,
    record_name: str = "",
    data_lengths: list[int] | None = None,
    varying: VaryingLength | None = None,
    extra_caveats: list[str] | None = None,
    pad_to: int | None = None,
) -> str:
    """Render *rows* as an annotated, field-by-field hex dump.

    The one record-image format that survives being opened in a text editor,
    which is exactly where a copybook is being looked at when someone asks
    what its ``COMP-3`` field really contains.  Every line ties an offset and
    a length to the field that owns those bytes, so a layout mistake shows up
    as a shifted offset rather than as unexplained garbage further down.

    Any :func:`encoding_caveats` are printed in the header rather than
    swallowed: a dump that silently ignored ``SYNCHRONIZED`` would be
    confidently wrong about every offset after the aligned item.  So are
    *extra_caveats* (the dataset's own, e.g. a clamped ``RECORD VARYING``).
    *pad_to* is :func:`encode_record`'s, and its slack is shown as its own
    row so the record's length adds up.
    """
    fmt = opts.resolved_format(specs, varying=varying is not None)
    length = record_length(specs)
    slack = max(0, (pad_to or 0) - length) if fmt is RecordFormat.FIXED else 0
    framing = RDW_SIZE if fmt is RecordFormat.VARIABLE else 0
    out: list[str] = [
        f"* record layout: {record_name or '(unnamed)'}",
        f"* record format: {fmt.value}"
        + (" (RECFM=F/FB)" if fmt is RecordFormat.FIXED else " (RECFM=V/VB)")
        + ("" if fmt is not RecordFormat.VARIABLE_BARE else ", no RDW"),
    ]
    # The FD range describes this record's length only while it is the thing
    # deciding it. When a table decides, the layout's own bounds are the
    # honest span; the FD clause is still printed below, as metadata.
    fd_decides = (
        varying is not None
        and varying.per_record
        and not any(spec.odo_controls for spec in specs)
    )
    if fmt.is_variable:
        low = (
            varying.minimum if fd_decides and varying else minimum_record_length(specs)
        )
        high = varying.maximum if fd_decides and varying else length
        out.append(
            f"* record length: {low + framing} to {high + framing} bytes"
            + (" (RDW included)" if framing else "")
        )
    else:
        out.append(
            f"* record length: {length + slack} bytes"
            + (f" (FD LRECL; the layout is {length})" if slack else "")
        )
    if varying is not None:
        depending = (
            f" DEPENDING ON {varying.depending_on}" if varying.depending_on else ""
        )
        out.append(
            f"* FD RECORD VARYING FROM {varying.minimum} TO "
            f"{varying.maximum}{depending}"
            + (
                ""
                if varying.per_record
                else " (no DEPENDING ON: each record is its 01's full length)"
            )
        )
    out.append(
        f"* charset: {opts.charset.value}   "
        f"comp-5/float byte order: {opts.resolved_endian.value}"
    )
    for caveat in [
        *(extra_caveats or []),
        *encoding_caveats(specs, opts, varying=varying),
    ]:
        out.append(f"* caveat: {caveat}")
    out.append(
        "*"
        f"\n{'OFFSET':<6}  {'LEN':>4}  {'FIELD':<24} "
        f"{'PICTURE':<14} {'USAGE':<9} {'VALUE':<18} BYTES"
    )

    for index, row in enumerate(rows, start=1):
        positions = (
            list(range(len(specs)))
            if fmt is RecordFormat.FIXED
            else present_indexes(specs, row)
        )
        body = sum(field_storage_size(specs[i]) for i in positions)
        declared = _effective_data_length(
            specs, data_lengths[index - 1] if data_lengths else None
        )
        if declared is not None and fmt.is_variable:
            body = min(body, declared)
        out.append(
            f"\n* --- record {index} of {len(rows)}: "
            f"{body + framing + slack} bytes ---"
        )
        offset = 0
        if framing:
            # The RDW is not a field, but it is bytes in the file, and a dump
            # that started at offset 0 with the first field would put every
            # subsequent offset four bytes below where it really sits.
            rdw = encode_rdw(body)
            out.extend(_dump_rdw_lines(rdw, opts))
            offset = len(rdw)
        written = 0
        for position in positions:
            spec = specs[position]
            cell = row[position]
            raw = encode_field(spec, cell, opts)
            if declared is not None and fmt.is_variable:
                if written >= declared:
                    # Past the record's declared length: these fields are
                    # simply not in the file.  Shown as absent rather than
                    # omitted, so a reader can see where the cut fell.
                    out.extend(_dump_absent_lines(spec, offset))
                    continue
                full = len(raw)
                raw = raw[: declared - written]
                if len(raw) < full:
                    # The cell is the whole value; the file holds only the
                    # bytes before the cut, so showing the cell would claim
                    # bytes that were never written.
                    cell = f"(cut {len(raw)}/{full} bytes)"
            written += len(raw)
            out.extend(_dump_field_lines(spec, cell, offset, raw, opts))
            offset += len(raw)
        if slack:
            out.extend(_dump_slack_lines(offset, slack, opts))
    return "\n".join(out) + "\n"
