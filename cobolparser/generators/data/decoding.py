"""Record decoding: real COBOL storage bytes -> the values behind them.

:mod:`.encoding` turns generated values into the bytes a program would
``READ``.  This module is the other direction, and the one people actually
have a file for: a VSAM extract, an EBCDIC flat file, a tape image someone
FTP'd off z/OS -- bytes with no self-description whatsoever, whose only key
is the copybook that was compiled against them.  Point the two at each other
and you get a table.

The inverse is exact where the forward direction is:

* ``COMP-3`` packed nibbles, ``COMP``/``COMP-4`` big-endian binary,
  ``COMP-5`` and the floats in the configured order, zoned DISPLAY with the
  sign overpunched or ``SIGN IS SEPARATE`` -- each read back through the same
  width :mod:`.storage` gave the encoder.
* Numbers are rendered exactly as :class:`~.values.ValueFactory` renders
  them (no leading zeros, the field's own ``decimal_digits`` places, a
  leading ``-``), so ``decode(encode(row)) == row`` holds cell for cell.
  Two columns are exempt by construction rather than by accident: a float
  comes back in shortest form (``2675.6950`` reads as ``2675.695`` -- the
  same number, without a trailing zero the bytes never held), and ``FILLER``
  comes back empty because :func:`.encoding.encode_field` deliberately
  writes spaces there rather than the generated cell.

Where it cannot be exact, it says so rather than guessing:

* **The sign conventions are read more widely than they are written.**  The
  encoder writes one convention per charset; real files carry several, so a
  zoned field accepts every EBCDIC sign nibble (``A``/``C``/``E``/``F``
  positive, ``B``/``D`` negative), GnuCOBOL's ASCII zone, *and* the
  ``{ABC…``/``}JKL…`` overpunches an EBCDIC file picks up when it is
  transcoded to ASCII by a file transfer.  That last one is deliberately
  not *written* by :mod:`.encoding` -- there is no compiler here to verify
  an implementation against -- but a decoder that choked on it would be
  useless on half the files in the wild.
* **Bytes that are not what the PICTURE says** are reported, not silently
  zeroed: :attr:`DecodedField.error` names the problem, the value is
  best-effort, and :attr:`DecodedRecord.errors` collects them per record.
  A copybook applied to the wrong file shows up as a wall of these, which
  is the single most useful thing this module can tell you.
* **``USAGE INDEX``/``POINTER``** decode to hex.  They hold a compiler-managed
  occurrence number and an address; neither means anything in a file written
  by another run of the program, and rendering one as a number would imply
  it does.
* **``COMP-1``** is float32: its value cannot be recovered to more than about
  seven significant digits, so it is rendered to seven and the number itself
  is approximate.  ``COMP-2`` recovers the value exactly (to fifteen
  digits), even though its rendering drops trailing zeros.

Which *layout* a record is read through is :mod:`.views`' problem, not this
module's -- ``REDEFINES`` means one run of bytes has several meanings and
only the program knows which applies.  :class:`RecordDecoder` takes the
whole :class:`~.views.RecordViews` and decodes through one of them at a
time, so switching overlay is a re-read of the same bytes rather than a
re-parse of the copybook.
"""

from __future__ import annotations

import csv
import io
import os
import struct
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ...models.data_items import CobolDataItem
from .encoding import (
    EBCDIC_CODEC,
    RDW_SIZE,
    Charset,
    EncodingOptions,
    Endian,
    RecordFormat,
)
from .errors import CopybookLayoutError
from .layout import FieldCategory, FieldSpec
from .options import DataGeneratorOptions
from .storage import (
    BINARY_NATIVE_USAGES,
    BINARY_USAGES,
    FLOAT_USAGES,
    PACKED_USAGES,
    POINTER_USAGES,
    SINGLE_FLOAT_USAGES,
    binary_byte_length,
)
from .views import PlacedField, RecordView, RecordViews, build_record_views


class RecordDecodingError(CopybookLayoutError):
    """Raised when a *file* cannot be framed into records at all.

    Reserved for the structural failures that make every following record
    meaningless -- an RDW claiming more bytes than the file holds, a
    fixed-length format with no length to cut at.  A field whose *bytes* are
    wrong is never an exception: it is reported on the field, because the
    rest of the record is still worth reading.
    """


#: Sign nibbles of a packed-decimal field, and of a zoned field's EBCDIC
#: sign byte.  ``C``/``F`` and ``D`` are what a compiler writes (and what
#: :mod:`.encoding` writes); ``A``/``E`` and ``B`` are the alternates the
#: architecture also accepts, and they do turn up in files written by
#: assembler and by older compilers.
_NEGATIVE_NIBBLES = frozenset({0xB, 0xD})
_SIGN_NIBBLES = frozenset({0xA, 0xB, 0xC, 0xD, 0xE, 0xF})

#: ASCII overpunch characters an EBCDIC zoned field turns into when a file
#: transfer transcodes it byte-for-byte through cp037.  ``{`` is +0 and
#: ``}`` is -0; the letters carry digits 1-9.
_ASCII_OVERPUNCH_POSITIVE = "{ABCDEFGHI"
_ASCII_OVERPUNCH_NEGATIVE = "}JKLMNOPQR"

#: Significant digits each float usage can actually carry.  Rendering more
#: would dress up float32's noise as precision the file never held.
_FLOAT_DIGITS = 7
_DOUBLE_DIGITS = 15


@dataclass(frozen=True)
class DecodedField:
    """One field of one record, as read out of its bytes.

    Attributes:
        name: The field's column name -- unique within the view, subscript
            suffix included for a table occurrence.
        qualified_name: Dotted path from the record root.
        offset: Byte offset this occurrence was actually read from, within
            the record.  For a fixed-length record this equals the view's
            static offset; under ``OCCURS ... DEPENDING ON`` it is where the
            field really landed once absent occurrences were skipped.
        length: Bytes consumed.  Shorter than the field's storage width only
            when the record ended mid-field.
        picture: PICTURE string, or ``None`` for a pictureless item.
        usage: USAGE clause, ``DISPLAY`` when the item declares none.
        category: The data category the value was decoded as.
        value: The decoded value, rendered the way
            :class:`~.values.ValueFactory` renders a generated one.
        raw: The bytes themselves, for a hex pane to show alongside.
        present: False when the record does not contain this field at all --
            an ``OCCURS ... DEPENDING ON`` occurrence its counter excludes,
            or a field past a short record's end.  :attr:`value` is empty and
            :attr:`length` is 0.
        truncated: True when the record ended part-way through this field.
            The value is decoded from the bytes that were there.
        error: What is wrong with these bytes, or ``None``.  A field with an
            error still carries a best-effort :attr:`value`.
    """

    name: str
    qualified_name: str
    offset: int
    length: int
    picture: str | None
    usage: str
    category: str
    value: str
    raw: bytes
    present: bool = True
    truncated: bool = False
    error: str | None = None

    @property
    def hex(self) -> str:
        """The field's bytes as spaced hex pairs (``C1 C2 F3``)."""
        return " ".join(f"{byte:02X}" for byte in self.raw)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the decoded field, bytes rendered as hex."""
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "offset": self.offset,
            "length": self.length,
            "picture": self.picture,
            "usage": self.usage,
            "category": self.category,
            "value": self.value,
            "hex": self.hex,
            "present": self.present,
            "truncated": self.truncated,
            "error": self.error,
        }


@dataclass(frozen=True)
class DecodedRecord:
    """One record, decoded through one view.

    Attributes:
        index: 0-based position of this record in the file.
        file_offset: Byte offset the record (its RDW included) starts at.
        length: Bytes the record occupies in the file, RDW included.
        view: Name of the view it was decoded through.
        fields: Every field of the view, in byte order -- absent ones
            included, flagged rather than dropped, so a caller rendering a
            table always gets the same columns for every row.
        raw: The record's data bytes, RDW excluded.
        rdw: The 4-byte record descriptor word, or ``None`` under a format
            that has none.
    """

    index: int
    file_offset: int
    length: int
    view: str
    fields: list[DecodedField]
    raw: bytes
    rdw: bytes | None = None

    @property
    def errors(self) -> list[str]:
        """``field: problem`` for every field whose bytes were not readable."""
        return [f"{item.name}: {item.error}" for item in self.fields if item.error]

    @property
    def truncated(self) -> bool:
        """True when the record was shorter than the view needs."""
        return any(item.truncated or not item.present for item in self.fields)

    def values(self) -> dict[str, str]:
        """The record as a column-name-keyed dict, in field order."""
        return {item.name: item.value for item in self.fields}

    def value(self, name: str) -> str | None:
        """One field's value by column or qualified name, or ``None``."""
        wanted = name.upper()
        for item in self.fields:
            if wanted in (item.name.upper(), item.qualified_name.upper()):
                return item.value
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialise the record and every field in it."""
        return {
            "index": self.index,
            "file_offset": self.file_offset,
            "length": self.length,
            "view": self.view,
            "truncated": self.truncated,
            "errors": self.errors,
            "fields": [item.to_dict() for item in self.fields],
        }


@dataclass
class DecodeResult:
    """Every record a decode run read, plus what it could not account for.

    Attributes:
        record_name: The copybook record the layout came from.
        view: Name of the view the records were decoded through.
        views: Every view name available, so a caller can offer the switch
            without rebuilding the layout.
        header: Column names for tabular output -- the view's own fields, so
            an empty file still reports the shape it was read through.
        records: The decoded records, in file order.
        bytes_read: Bytes consumed by the records in :attr:`records`.
        trailing: Bytes left over after the last whole record -- a file whose
            length is not a multiple of its record length, which usually
            means the record length is wrong.  Reported, never dropped
            silently.
        caveats: Reasons the decode may not match what the program sees,
            from :func:`~.encoding.encoding_caveats` and
            :attr:`~.views.RecordViews.caveats` alike.
    """

    record_name: str
    view: str
    views: list[str]
    header: list[str] = field(default_factory=list)
    records: list[DecodedRecord] = field(default_factory=list)
    bytes_read: int = 0
    trailing: bytes = b""
    caveats: list[str] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        """How many fields across every record failed to decode cleanly."""
        return sum(len(record.errors) for record in self.records)

    def to_csv(self, *, line_terminator: str = "\n") -> str:
        """Render the decoded records as CSV, header row first.

        The exact inverse of :meth:`~.dataset.GeneratedDataset.to_csv`: the
        same column names, the same value rendering, the same ``"\\n"``
        terminator -- so a generated CSV, written as records and read back,
        is byte-identical to the original.
        """
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator=line_terminator)
        writer.writerow(self.header)
        for record in self.records:
            writer.writerow([item.value for item in record.fields])
        return buffer.getvalue()

    def to_dicts(self) -> list[dict[str, str]]:
        """The decoded records as column-name-keyed dicts."""
        return [record.values() for record in self.records]

    def to_dict(self) -> dict[str, Any]:
        """Serialise the whole run, field by field."""
        return {
            "record_name": self.record_name,
            "view": self.view,
            "views": list(self.views),
            "record_count": len(self.records),
            "bytes_read": self.bytes_read,
            "trailing_bytes": len(self.trailing),
            "error_count": self.error_count,
            "caveats": list(self.caveats),
            "records": [record.to_dict() for record in self.records],
        }


# ---------------------------------------------------------------------------
# Field decoding: one storage class at a time
# ---------------------------------------------------------------------------


def _normalized_usage(spec: FieldSpec) -> str:
    return (spec.usage or "DISPLAY").upper()


def _total_digits(spec: FieldSpec) -> int:
    return max(1, spec.integer_digits + spec.decimal_digits)


def _is_sign_separate(spec: FieldSpec) -> bool:
    return "SEPARATE" in (spec.sign_clause or "").upper()


def _is_sign_leading(spec: FieldSpec) -> bool:
    return "LEADING" in (spec.sign_clause or "").upper()


def _render_number(magnitude: int, negative: bool, decimals: int) -> str:
    """A decoded integer of *decimals* implied places, as display text.

    Deliberately identical to :meth:`~.values.ValueFactory._format_number`'s
    output shape -- no leading zeros, exactly ``decimals`` places when the
    field is scaled, a leading ``-`` only on a non-zero negative -- because
    that equality is what makes ``decode(encode(row)) == row`` a property
    that can be tested rather than a hope.
    """
    if decimals:
        text = f"{Decimal(magnitude).scaleb(-decimals):.{decimals}f}"
    else:
        text = str(magnitude)
    return f"-{text}" if negative and magnitude != 0 else text


def _decode_text(raw: bytes, opts: EncodingOptions) -> str:
    """DISPLAY text: the charset's characters, trailing pad stripped.

    ASCII is read as latin-1 rather than strict ASCII: a byte the encoder
    could not have written is still a byte in the file, and showing it beats
    raising on it.  Trailing spaces and NULs go because they are how COBOL
    pads a short value into a fixed field; leading ones stay, because they
    may be the value.
    """
    codec = EBCDIC_CODEC if opts.charset is Charset.EBCDIC else "latin-1"
    return raw.decode(codec, errors="replace").rstrip(" \x00")


def _decode_zoned(
    raw: bytes, spec: FieldSpec, opts: EncodingOptions
) -> tuple[str, str | None]:
    """Numeric DISPLAY: one digit per byte, sign overpunched or separate."""
    decimals = spec.decimal_digits
    body = raw
    negative = False
    error: str | None = None

    if spec.is_signed and _is_sign_separate(spec):
        if not body:
            return _render_number(0, False, decimals), "empty field"
        sign_byte, body = (
            (body[:1], body[1:]) if _is_sign_leading(spec) else (body[-1:], body[:-1])
        )
        sign_char = _decode_text(sign_byte, opts).strip()
        negative = sign_char == "-"
        if sign_char not in ("+", "-", ""):
            error = f"sign byte {sign_byte.hex().upper()} is neither '+' nor '-'"

    # Where the sign lives when it is overpunched onto a digit rather than
    # given a byte of its own: the first digit under SIGN IS LEADING, the
    # last otherwise -- the same two positions :func:`.encoding._encode_zoned`
    # writes it to.
    sign_index = (
        0
        if (spec.is_signed and not _is_sign_separate(spec) and _is_sign_leading(spec))
        else len(body) - 1
    )
    magnitude = 0
    for index, byte in enumerate(body):
        digit, byte_negative, byte_error = _zoned_digit(
            byte, opts, signed_position=spec.is_signed and index == sign_index
        )
        magnitude = magnitude * 10 + digit
        negative = negative or byte_negative
        if byte_error and error is None:
            error = f"byte {index} ({byte:02X}) {byte_error}"
    return _render_number(magnitude, negative, decimals), error


def _zoned_digit(
    byte: int, opts: EncodingOptions, *, signed_position: bool
) -> tuple[int, bool, str | None]:
    """One zoned byte as ``(digit, negative, error)``.

    Every sign convention this module accepts converges here; see the module
    docstring for why it reads more of them than :mod:`.encoding` writes.  A
    sign is only ever honoured in the position the encoder would have put one
    -- a ``D`` zone in the middle of a field is a corrupt digit, not a
    negative number, and calling it a sign would flip a value that is merely
    unreadable.
    """
    low = byte & 0x0F
    zone = byte & 0xF0

    if opts.charset is Charset.EBCDIC:
        if low > 9:
            return 0, False, "is not a digit"
        if zone == 0xF0:
            return low, False, None
        if zone in (0xA0, 0xB0, 0xC0, 0xD0, 0xE0):
            if not signed_position:
                return low, False, "carries a sign zone outside the sign position"
            return low, (zone >> 4) in _NEGATIVE_NIBBLES, None
        if byte == 0x40:  # a space, which is how an unset numeric field reads
            return 0, False, "is a space, not a digit"
        return low, False, "has an unrecognised zone"

    char = chr(byte)
    if "0" <= char <= "9":
        return int(char), False, None
    if signed_position:
        # An EBCDIC zoned field transcoded to ASCII byte-for-byte: the sign
        # digit becomes one of `{ABC...` / `}JKL...`. GnuCOBOL's own ASCII
        # convention -- zone 0x70 on the signed digit -- is the other one.
        index = _ASCII_OVERPUNCH_POSITIVE.find(char)
        if index >= 0:
            return index, False, None
        index = _ASCII_OVERPUNCH_NEGATIVE.find(char)
        if index >= 0:
            return index, True, None
        if zone == 0x70 and low <= 9:
            return low, True, None
    return (low if low <= 9 else 0), False, "is not a digit"


def _decode_packed(raw: bytes, spec: FieldSpec) -> tuple[str, str | None]:
    """COMP-3: two BCD digits per byte, sign in the final low nibble."""
    if not raw:
        return _render_number(0, False, spec.decimal_digits), "empty field"
    nibbles = raw.hex().upper()
    sign_nibble = int(nibbles[-1], 16)
    error: str | None = None
    if sign_nibble not in _SIGN_NIBBLES:
        error = f"sign nibble {nibbles[-1]} is not a valid packed sign"
    magnitude = 0
    for position, char in enumerate(nibbles[:-1]):
        digit = int(char, 16)
        if digit > 9:
            if error is None:
                error = f"nibble {position} ({char}) is not a digit"
            digit = 0
        magnitude = magnitude * 10 + digit
    negative = sign_nibble in _NEGATIVE_NIBBLES
    return _render_number(magnitude, negative, spec.decimal_digits), error


def _decode_binary(
    raw: bytes, spec: FieldSpec, opts: EncodingOptions
) -> tuple[str, str | None]:
    """COMP/COMP-4/COMP-5: a two's-complement integer of the field's width."""
    usage = _normalized_usage(spec)
    order: str = (
        opts.resolved_endian.value
        if usage in BINARY_NATIVE_USAGES
        else Endian.BIG.value
    )
    value = int.from_bytes(raw, order, signed=spec.is_signed)  # type: ignore[arg-type]
    error = None
    expected = binary_byte_length(_total_digits(spec))
    if len(raw) != expected:
        error = f"{len(raw)} bytes where {usage} needs {expected}"
    return _render_number(abs(value), value < 0, spec.decimal_digits), error


def _decode_float(
    raw: bytes, spec: FieldSpec, opts: EncodingOptions
) -> tuple[str, str | None]:
    """COMP-1/COMP-2 as IEEE 754.  See :mod:`.encoding` on z/OS HFP."""
    single = _normalized_usage(spec) in SINGLE_FLOAT_USAGES
    width = 4 if single else 8
    if len(raw) != width:
        return "0", f"{len(raw)} bytes where the usage needs {width}"
    prefix = "<" if opts.resolved_endian is Endian.LITTLE else ">"
    value = struct.unpack(f"{prefix}{'f' if single else 'd'}", raw)[0]
    digits = _FLOAT_DIGITS if single else _DOUBLE_DIGITS
    return f"{value:.{digits}g}", None


def decode_field(
    placed: PlacedField,
    raw: bytes,
    opts: EncodingOptions,
    *,
    offset: int | None = None,
) -> DecodedField:
    """Read one field's bytes back into the value they hold.

    The inverse of :func:`.encoding.encode_field`, dispatching on the same
    ``USAGE``-then-category ladder so the two cannot disagree about which
    storage class a field is.  *raw* shorter than the field's width is not an
    error the caller has to pre-empt: the field comes back
    :attr:`~DecodedField.truncated`, decoded from what was there.

    *offset* overrides the view's static placement with where the field was
    really read from, which is not the same number once an ``OCCURS ...
    DEPENDING ON`` table ahead of it came up short.
    """
    spec = placed.spec
    usage = _normalized_usage(spec)
    width = spec.storage_size
    error: str | None = None

    if usage == "INDEX" or usage in POINTER_USAGES:
        value = "0x" + raw.hex().upper() if raw else ""
    elif usage in FLOAT_USAGES:
        value, error = _decode_float(raw, spec, opts)
    elif usage in PACKED_USAGES:
        value, error = _decode_packed(raw, spec)
    elif usage in BINARY_USAGES:
        value, error = _decode_binary(raw, spec, opts)
    elif spec.category is FieldCategory.NUMERIC:
        value, error = _decode_zoned(raw, spec, opts)
    else:
        value = _decode_text(raw, opts)

    return DecodedField(
        name=spec.column,
        qualified_name=spec.qualified_name,
        offset=placed.offset if offset is None else offset,
        length=len(raw),
        picture=spec.picture,
        usage=usage,
        category=spec.category.value,
        value=value,
        raw=raw,
        present=True,
        truncated=len(raw) < width,
        error=error,
    )


def _absent_field(placed: PlacedField, offset: int) -> DecodedField:
    """A field the record does not contain -- trimmed table, or short record."""
    spec = placed.spec
    return DecodedField(
        name=spec.column,
        qualified_name=spec.qualified_name,
        offset=offset,
        length=0,
        picture=spec.picture,
        usage=_normalized_usage(spec),
        category=spec.category.value,
        value="",
        raw=b"",
        present=False,
    )


# ---------------------------------------------------------------------------
# Record decoding: OCCURS DEPENDING ON resolved from the record's own counters
# ---------------------------------------------------------------------------


def _counter_key(spec: FieldSpec, control_index: int) -> tuple[str, tuple[int, ...]]:
    control = spec.odo_controls[control_index]
    return (control.depending_on.upper(), spec.subscripts[: control.subscript_index])


def decode_record(
    view: RecordView,
    data: bytes,
    opts: EncodingOptions,
    *,
    trim_tables: bool = True,
) -> list[DecodedField]:
    """Decode *data* through *view*, field by field, in byte order.

    ``OCCURS ... DEPENDING ON`` is resolved from the record's own counters as
    they are decoded, which is the whole reason this walks the fields rather
    than slicing at the view's static offsets: an occurrence the counter
    excludes contributes no bytes, and everything after it moves up.  A
    counter this record does not contain leaves its table at full length,
    matching :func:`.encoding.occurrence_count`'s own fallback.

    *trim_tables* is the mirror image of
    :attr:`~.encoding.RecordFormat.is_variable` on the writing side, and has
    to be: under RECFM=F the table reserves all of its occurrences whatever
    the counter says, so trimming here would skip bytes that are in the
    record and mis-align every field after the table.  The caller passes what
    the record format says; :meth:`RecordDecoder.decode_bytes` does that for
    you.

    Fields past the end of *data* come back absent rather than raising: a
    short record is a fact about the file, and the fields that *were* there
    are still worth reading.
    """
    counts: dict[tuple[str, tuple[int, ...]], int] = {}
    out: list[DecodedField] = []
    # *data* is the whole record, so an overlay starts where the item it
    # redefines does rather than at byte 0 -- switching view re-reads the
    # same record from a different offset, which is the point.
    position = view.offset

    for placed in view.fields:
        spec = placed.spec
        if trim_tables and not _present(spec, counts):
            out.append(_absent_field(placed, position))
            continue
        if position >= len(data):
            out.append(_absent_field(placed, position))
            continue
        raw = data[position : position + spec.storage_size]
        decoded = decode_field(placed, raw, opts, offset=position)
        out.append(decoded)
        position += len(raw)
        if spec.odo_counter_bounds is not None:
            counts[(spec.name.upper(), spec.subscripts)] = _counter_value(
                decoded.value, spec.odo_counter_bounds
            )
    return out


def _present(spec: FieldSpec, counts: dict[tuple[str, tuple[int, ...]], int]) -> bool:
    """Whether this occurrence is in a record whose counters read *counts*."""
    for index, control in enumerate(spec.odo_controls):
        if control.subscript_index >= len(spec.subscripts):
            continue
        key = _counter_key(spec, index)
        if key not in counts:
            # The counter is not part of this record (it may live in
            # WORKING-STORAGE, which COBOL permits) or has not been read
            # yet. Reserving the whole table is the only answer that never
            # claims bytes the record does not have.
            continue
        if spec.subscripts[control.subscript_index] > counts[key]:
            return False
    return True


def _counter_value(text: str, bounds: tuple[int, int]) -> int:
    """A decoded counter clamped into the table's own bounds."""
    try:
        count = int(Decimal(text.strip() or "0"))
    except (ArithmeticError, ValueError):
        return bounds[1]
    return max(bounds[0], min(bounds[1], count))


# ---------------------------------------------------------------------------
# File decoding: framing a stream of bytes into records
# ---------------------------------------------------------------------------


class RecordDecoder:
    """Reads a record image file back through a copybook layout.

    Built from a :class:`~.views.RecordViews` so that switching ``REDEFINES``
    overlay costs a re-read of the same bytes rather than a re-parse of the
    copybook::

        decoder = RecordDecoder.from_copybook_file("CUSTOMER.cpy")
        result = decoder.decode_file("CUSTOMER.DAT", EncodingOptions(
            charset=Charset.EBCDIC
        ))
        print(result.to_csv())
        print(decoder.decode_file("CUSTOMER.DAT", view="CUST-REC.ADDR-OVERSEAS"))
    """

    def __init__(
        self,
        views: RecordViews,
        opts: EncodingOptions | None = None,
        *,
        record_length: int | None = None,
    ) -> None:
        """
        Args:
            views: The record's base layout and its ``REDEFINES`` overlays.
            opts: Charset, byte order and record format.  Defaults to
                ASCII, host order, fixed-length -- the same defaults
                :mod:`.encoding` writes with.
            record_length: Bytes per record under a fixed-length format,
                when the file's ``LRECL`` is not the layout's own length.
                A file whose records carry trailing slack (or whose
                copybook covers only a prefix of them) needs this; without
                it the layout's length is used.
        """
        self.views = views
        self.options = opts or EncodingOptions()
        self.record_length = record_length

    # -- construction -------------------------------------------------------

    @classmethod
    def from_copybook_source(
        cls,
        source: str,
        *,
        filename: str = "<copybook>",
        record: str | None = None,
        opts: EncodingOptions | None = None,
        options: DataGeneratorOptions | None = None,
        record_length: int | None = None,
    ) -> RecordDecoder:
        """Build a decoder from copybook (or whole-program) text.

        Raises:
            CopybookLayoutError: if the source has no usable record layout,
                or the requested *record* is not in it.
        """
        from .copybook import parse_copybook_records, select_record

        records = parse_copybook_records(source, filename=filename)
        chosen = select_record(records, record, filename)
        return cls.from_record(
            chosen, opts=opts, options=options, record_length=record_length
        )

    @classmethod
    def from_copybook_file(
        cls,
        path: str | os.PathLike[str],
        *,
        record: str | None = None,
        opts: EncodingOptions | None = None,
        options: DataGeneratorOptions | None = None,
        record_length: int | None = None,
    ) -> RecordDecoder:
        """Read a copybook from *path* and build a decoder from it."""
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        return cls.from_copybook_source(
            source,
            filename=str(path),
            record=record,
            opts=opts,
            options=options,
            record_length=record_length,
        )

    @classmethod
    def from_record(
        cls,
        record: CobolDataItem,
        *,
        opts: EncodingOptions | None = None,
        options: DataGeneratorOptions | None = None,
        record_length: int | None = None,
    ) -> RecordDecoder:
        """Build a decoder from an already-parsed record item."""
        return cls(
            build_record_views(record, options),
            opts,
            record_length=record_length,
        )

    # -- decoding -----------------------------------------------------------

    def resolve_view(self, view: str | None) -> RecordView:
        """The named view, or the base one.

        Raises:
            RecordDecodingError: if no view goes by that name, listing the
                ones that do -- a mistyped overlay is the likeliest way to
                reach this, and the answer is always in that list.
        """
        found = self.views.get(view)
        if found is None:
            raise RecordDecodingError(
                f"no view named {view!r}; available: " + ", ".join(self.views.names)
            )
        return found

    def decode_bytes(
        self,
        data: bytes,
        *,
        view: str | None = None,
        opts: EncodingOptions | None = None,
        max_records: int | None = None,
        skip: int = 0,
    ) -> DecodeResult:
        """Frame *data* into records and decode each one.

        *skip* drops that many records from the front before decoding (it
        still has to frame them, since under a variable format no record's
        position is knowable without reading the one before it), and
        *max_records* stops after that many have been kept -- together, the
        paging a viewer needs to open a 2 GB extract without decoding all of
        it.
        """
        options = opts or self.options
        chosen = self.resolve_view(view)
        result = DecodeResult(
            record_name=self.views.record_name,
            view=chosen.name,
            views=self.views.names,
            header=[placed.spec.column for placed in chosen.fields],
            caveats=self._caveats(chosen, options),
        )
        # Whether a table's occurrences past its counter are in the record is
        # decided by the record format, not by the counter: RECFM=F reserves
        # them all. Resolved once, from the base view, because it is a
        # property of the file rather than of the view being read.
        trim_tables = options.resolved_format(
            [placed.spec for placed in self.views.base.fields]
        ).is_variable
        position = 0
        index = 0
        stopped_early = False
        while position < len(data):
            if max_records is not None and len(result.records) >= max_records:
                # Bytes left because the caller asked for a page, not because
                # the file has a stray tail. Reporting them as trailing would
                # make every paged read look like a broken file.
                stopped_early = True
                break
            frame = self._next_frame(data, position, options)
            if frame is None:
                break
            body, consumed, rdw = frame
            if index >= skip:
                result.records.append(
                    DecodedRecord(
                        index=index,
                        file_offset=position,
                        length=consumed,
                        view=chosen.name,
                        fields=decode_record(
                            chosen, body, options, trim_tables=trim_tables
                        ),
                        raw=body,
                        rdw=rdw,
                    )
                )
            position += consumed
            index += 1
        result.bytes_read = position
        result.trailing = b"" if stopped_early else data[position:]
        return result

    def decode_file(
        self,
        path: str | os.PathLike[str],
        *,
        view: str | None = None,
        opts: EncodingOptions | None = None,
        max_records: int | None = None,
        skip: int = 0,
    ) -> DecodeResult:
        """Read *path* in binary and decode it.

        Binary mode is not incidental: a COMP field routinely contains 0x0A
        and 0x0D, and a text-mode read would translate them.
        """
        with open(path, "rb") as handle:
            data = handle.read()
        return self.decode_bytes(
            data, view=view, opts=opts, max_records=max_records, skip=skip
        )

    # -- framing ------------------------------------------------------------

    def _next_frame(
        self,
        data: bytes,
        position: int,
        opts: EncodingOptions,
    ) -> tuple[bytes, int, bytes | None] | None:
        """One record's ``(body, bytes consumed, RDW)`` starting at *position*.

        Always framed by the **base** view, whichever view the caller is
        reading through: where a record ends is a property of the file, not
        of the overlay somebody chose to look at it with.  A 200-byte record
        read through a 20-byte redefinition is still 200 bytes long, and
        framing on the overlay would walk the file at the wrong stride.

        ``None`` means what is left is not a whole record -- reported as
        :attr:`DecodeResult.trailing` rather than decoded into a row of
        plausible-looking rubbish.
        """
        view = self.views.base
        fmt = opts.resolved_format([placed.spec for placed in view.fields])
        separator = opts.record_separator
        remaining = len(data) - position

        if fmt is RecordFormat.VARIABLE:
            if remaining < RDW_SIZE:
                return None
            rdw = data[position : position + RDW_SIZE]
            total = int.from_bytes(rdw[:2], "big")
            if total < RDW_SIZE or total > remaining:
                raise RecordDecodingError(
                    f"record {position}: RDW claims {total} bytes but only "
                    f"{remaining} remain; the file is not RECFM=V, or the "
                    "wrong --record-format was asked for"
                )
            body = data[position + RDW_SIZE : position + total]
            return (
                body,
                total + self._separator_width(data, position + total, separator),
                rdw,
            )

        if fmt is RecordFormat.FIXED:
            length = self.record_length or view.length
            if length <= 0:
                raise RecordDecodingError(
                    f"{view.name}: the layout is zero bytes long, so a "
                    "fixed-length file cannot be split into records; pass an "
                    "explicit record length"
                )
            if remaining < length:
                return None
            body = data[position : position + length]
            return (
                body,
                length + self._separator_width(data, position + length, separator),
                None,
            )

        # VARIABLE_BARE: nothing frames the records but the layout itself.
        # Decoding consumes exactly the bytes this record's own counters say
        # it holds, so the next record starts where this one stopped.
        if separator:
            end = data.find(separator, position)
            if end < 0:
                body = data[position:]
                return body, len(body), None
            return data[position:end], (end - position) + len(separator), None
        fields = decode_record(view, data[position:], opts, trim_tables=True)
        consumed = max((item.offset + item.length for item in fields), default=0)
        if consumed <= 0:
            return None
        return data[position : position + consumed], consumed, None

    @staticmethod
    def _separator_width(data: bytes, at: int, separator: bytes) -> int:
        """Bytes to skip for a record separator sitting at *at*, if it is."""
        if not separator:
            return 0
        return len(separator) if data[at : at + len(separator)] == separator else 0

    def _caveats(self, view: RecordView, opts: EncodingOptions) -> list[str]:
        """Everything that could make this decode disagree with the program."""
        from .encoding import encoding_caveats

        specs = [placed.spec for placed in view.fields]
        caveats = list(self.views.caveats)
        for caveat in encoding_caveats(specs, opts):
            if caveat not in caveats:
                caveats.append(caveat)
        if any(_normalized_usage(spec) in SINGLE_FLOAT_USAGES for spec in specs):
            caveats.append(
                "COMP-1 holds about seven significant digits, so its decoded "
                "value is shown to seven and does not round-trip exactly"
            )
        return caveats


# ---------------------------------------------------------------------------
# The hex pane
# ---------------------------------------------------------------------------

_DUMP_BYTES_PER_LINE = 8


def _printable(raw: bytes, opts: EncodingOptions) -> str:
    codec = EBCDIC_CODEC if opts.charset is Charset.EBCDIC else "latin-1"
    text = raw.decode(codec, errors="replace")
    return "".join(ch if ch.isprintable() else "." for ch in text)


def decoded_hex_dump(result: DecodeResult, opts: EncodingOptions) -> str:
    """Render a decode as a hex pane whose lines are the field boundaries.

    The same shape :func:`.encoding.hex_dump` produces for a *generated*
    record, built from bytes somebody else wrote: every line ties an offset
    and a length to the field that owns those bytes and to the value read out
    of them.  A copybook applied to the wrong file shows up here immediately
    -- the offsets drift, the text column turns to mojibake, and the error
    column fills up -- which no plain hex viewer can tell you.
    """
    out: list[str] = [
        f"* record layout: {result.record_name}",
        f"* view: {result.view}"
        + ("" if len(result.views) < 2 else f"   (of {', '.join(result.views)})"),
        f"* charset: {opts.charset.value}   "
        f"comp-5/float byte order: {opts.resolved_endian.value}",
        f"* records: {len(result.records)}   bytes read: {result.bytes_read}"
        + (f"   trailing: {len(result.trailing)}" if result.trailing else ""),
    ]
    for caveat in result.caveats:
        out.append(f"* caveat: {caveat}")
    out.append(
        "*"
        f"\n{'OFFSET':<6}  {'LEN':>4}  {'FIELD':<24} "
        f"{'PICTURE':<14} {'USAGE':<9} {'VALUE':<18} BYTES"
    )

    for record in result.records:
        out.append(
            f"\n* --- record {record.index + 1}"
            f" at file offset {record.file_offset:#08x}:"
            f" {record.length} bytes ---"
        )
        for item in record.fields:
            out.extend(_dump_field_lines(item, opts))
            if item.error:
                out.append(f"{'':<6}  {'':>4}  ! {item.name}: {item.error}")
    if result.trailing:
        out.append(
            f"\n* --- {len(result.trailing)} trailing bytes, not a whole " "record ---"
        )
    return "\n".join(out) + "\n"


def _dump_field_lines(item: DecodedField, opts: EncodingOptions) -> list[str]:
    """One decoded field's rows: what it is, then the bytes it was read from."""
    if not item.present:
        return [
            f"{item.offset:06X}     0  {item.name[:24]:<24} "
            f"{(item.picture or '')[:14]:<14} {item.usage:<9} "
            f"{'(not in record)':<18} "
        ]
    head = (
        f"{item.offset:06X}  {item.length:>4}  {item.name[:24]:<24} "
        f"{(item.picture or '')[:14]:<14} {item.usage:<9} "
        f"{item.value[:18]:<18} "
    )
    indent = " " * len(head)
    lines: list[str] = []
    for start in range(0, max(len(item.raw), 1), _DUMP_BYTES_PER_LINE):
        chunk = item.raw[start : start + _DUMP_BYTES_PER_LINE]
        hex_part = " ".join(f"{byte:02X}" for byte in chunk)
        prefix = head if start == 0 else indent
        lines.append(
            f"{prefix}{hex_part:<{_DUMP_BYTES_PER_LINE * 3}} "
            f"|{_printable(chunk, opts)}|"
        )
    return lines
