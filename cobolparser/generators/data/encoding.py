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
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from enum import StrEnum

from .editing import edit_numeric
from .errors import CopybookLayoutError
from .layout import (
    FieldCategory,
    FieldSpec,
    VaryingLength,
    present_indexes,
    unresolved_odo_counters,
)
from .storage import (
    BINARY_NATIVE_USAGES,
    BINARY_USAGES,
    FLOAT_USAGES,
    PACKED_USAGES,
    POINTER_USAGES,
    SINGLE_FLOAT_USAGES,
    binary_byte_length,
)


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


def _encode_text(text: str, size: int, opts: EncodingOptions) -> bytes:
    """Left-justified, space-padded, truncated to *size* -- COBOL's own
    alphanumeric MOVE semantics, applied at the byte level."""
    codec = EBCDIC_CODEC if opts.charset is Charset.EBCDIC else "ascii"
    raw = text.encode(codec, errors="replace")
    if len(raw) >= size:
        return raw[:size]
    return raw + bytes([opts.space]) * (size - len(raw))


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
    units = value.scaleb(spec.decimal_digits)
    scaling = spec.scaling_positions
    if scaling > 0:
        # Trailing P: the low `scaling` digits are implied zeros that no
        # byte holds -- ``123000`` in ``9(3)PPP`` is stored as ``123``.
        # Truncation, not rounding, is what the compiler does with a value
        # that is not a whole multiple (``123456`` -> ``123``).
        return int(units.scaleb(-scaling).to_integral_value(rounding=ROUND_DOWN))
    return int(units.to_integral_value())


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
        return _encode_text(text, width, opts)
    # DISPLAY from here down.  An unedited numeric picture is zoned decimal.
    # A numeric-edited one holds what a MOVE into it would leave: the CSV
    # cell is the logical value (`1234.56`), the bytes are the edited form
    # (`$1,234.56`).  A picture `edit_numeric` does not model keeps the
    # cell's text as is.
    if (
        spec.blank_when_zero
        and spec.category in (FieldCategory.NUMERIC, FieldCategory.NUMERIC_EDITED)
        and _scaled_integer(text, spec) == 0
    ):
        # BLANK WHEN ZERO: a zero value is stored as spaces, not digits.
        return bytes([opts.space]) * width
    if spec.category is FieldCategory.NUMERIC:
        return _encode_zoned(text, spec, opts)
    if spec.category is FieldCategory.NUMERIC_EDITED:
        edited = edit_numeric(spec.picture, text)
        if edited is not None and len(edited) == width:
            return _encode_text(edited, width, opts)
    return _encode_text(text, width, opts)


def encode_record(
    specs: list[FieldSpec],
    row: list[str],
    opts: EncodingOptions,
    *,
    data_length: int | None = None,
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
) -> int:
    """Byte length one generated *row* occupies, RDW included when framed.

    Cheaper than measuring ``len(encode_record(...))`` -- it sums the widths
    the layout already knows rather than building the bytes -- and used
    wherever a length is wanted for reporting rather than for writing.
    *data_length* means the same thing it does on :func:`encode_record`.
    """
    options = opts or EncodingOptions()
    fmt = options.resolved_format(specs, varying=data_length is not None)
    if fmt is RecordFormat.FIXED:
        return record_length(specs)
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
    national = sorted(
        {
            spec.qualified_name
            for spec in specs
            if spec.category is FieldCategory.NATIONAL
            or _normalized_usage(spec) == "NATIONAL"
        }
    )
    if national:
        caveats.append(
            "national data (PIC N / USAGE NATIONAL) is written as single-byte "
            "text in the record's charset, space-padded to the field's width, "
            "not as the UTF-16 a real compiler stores (and a real file's "
            "national bytes do not decode back as the same text): "
            f"{', '.join(national)}"
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
    value = cell if not (spec.is_filler and not spec.value_clause) else ""
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
) -> str:
    """Render *rows* as an annotated, field-by-field hex dump.

    The one record-image format that survives being opened in a text editor,
    which is exactly where a copybook is being looked at when someone asks
    what its ``COMP-3`` field really contains.  Every line ties an offset and
    a length to the field that owns those bytes, so a layout mistake shows up
    as a shifted offset rather than as unexplained garbage further down.

    Any :func:`encoding_caveats` are printed in the header rather than
    swallowed: a dump that silently ignored ``SYNCHRONIZED`` would be
    confidently wrong about every offset after the aligned item.
    """
    fmt = opts.resolved_format(specs, varying=varying is not None)
    length = record_length(specs)
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
    fd_decides = varying is not None and not any(spec.odo_controls for spec in specs)
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
        out.append(f"* record length: {length} bytes")
    if varying is not None:
        depending = (
            f" DEPENDING ON {varying.depending_on}" if varying.depending_on else ""
        )
        out.append(
            f"* FD RECORD VARYING FROM {varying.minimum} TO "
            f"{varying.maximum}{depending}"
        )
    out.append(
        f"* charset: {opts.charset.value}   "
        f"comp-5/float byte order: {opts.resolved_endian.value}"
    )
    for caveat in encoding_caveats(specs, opts, varying=varying):
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
        out.append(f"\n* --- record {index} of {len(rows)}: {body + framing} bytes ---")
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
                raw = raw[: declared - written]
            written += len(raw)
            out.extend(_dump_field_lines(spec, cell, offset, raw, opts))
            offset += len(raw)
    return "\n".join(out) + "\n"
