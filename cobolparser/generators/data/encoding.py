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
* **OCCURS DEPENDING ON** reserves its maximum, matching how the layout is
  flattened everywhere else in this package.
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from .errors import CopybookLayoutError
from .layout import FieldCategory, FieldSpec
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
    """

    charset: Charset = Charset.ASCII
    endian: Endian = Endian.AUTO
    record_separator: bytes = b""

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


def _normalized_usage(spec: FieldSpec) -> str:
    return (spec.usage or "DISPLAY").upper()


def _total_digits(spec: FieldSpec) -> int:
    """Digit positions the field holds, floored at 1.

    A PICTURE-less numeric item (``INDEX``, ``POINTER``) never reaches the
    numeric encoders, so the floor only guards a malformed picture whose
    digit counts both came back zero.
    """
    return max(1, spec.integer_digits + spec.decimal_digits)


def _is_sign_separate(spec: FieldSpec) -> bool:
    return "SEPARATE" in (spec.sign_clause or "").upper()


def _is_sign_leading(spec: FieldSpec) -> bool:
    return "LEADING" in (spec.sign_clause or "").upper()


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
    return int(value.scaleb(spec.decimal_digits).to_integral_value())


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
    except OverflowError as exc:  # pragma: no cover - guarded by _digits_string
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
    # DISPLAY from here down.  An edited picture's generated text is already
    # the edited form and already the picture's own width, so it encodes as
    # text; only an unedited numeric picture is zoned decimal.
    if spec.category is FieldCategory.NUMERIC:
        return _encode_zoned(text, spec, opts)
    return _encode_text(text, width, opts)


def encode_record(
    specs: list[FieldSpec],
    row: list[str],
    opts: EncodingOptions,
) -> bytes:
    """Concatenate one generated row into its record image.

    *specs* must be the byte-complete layout -- FILLER included, REDEFINES
    excluded, every OCCURS occurrence expanded -- which is what
    :meth:`~.copybook.CopybookDataGenerator` builds when asked for record
    output.  A layout missing FILLER would silently produce short records.
    """
    if len(specs) != len(row):
        raise RecordEncodingError(
            f"row has {len(row)} cells but the layout has {len(specs)} fields"
        )
    return b"".join(
        encode_field(spec, cell, opts) for spec, cell in zip(specs, row, strict=True)
    )


def record_length(specs: list[FieldSpec]) -> int:
    """Byte length of the record *specs* describes."""
    return sum(field_storage_size(spec) for spec in specs)


def encoding_caveats(specs: list[FieldSpec]) -> list[str]:
    """Every reason a record image built from *specs* may not match what a
    real compiler lays out.

    Returned rather than raised: the image is still the best available
    answer, and a caller that surfaces these (the CLI prints them to stderr,
    the hex dump inlines them) leaves the user better off than one that
    refuses.  Empty means the layout is fully modelled.
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
    depending = sorted(
        {spec.qualified_name for spec in specs if spec.occurs_depending_on is not None}
    )
    if depending:
        caveats.append(
            "OCCURS DEPENDING ON tables are written at their maximum length; "
            "a real record would be shorter when the depending-on item is "
            f"less than that maximum: {', '.join(depending)}"
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


def hex_dump(
    specs: list[FieldSpec],
    rows: list[list[str]],
    opts: EncodingOptions,
    *,
    record_name: str = "",
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
    length = record_length(specs)
    out: list[str] = [
        f"* record layout: {record_name or '(unnamed)'}",
        f"* record length: {length} bytes",
        f"* charset: {opts.charset.value}   "
        f"comp-5/float byte order: {opts.resolved_endian.value}",
    ]
    for caveat in encoding_caveats(specs):
        out.append(f"* caveat: {caveat}")
    out.append(
        "*"
        f"\n{'OFFSET':<6}  {'LEN':>4}  {'FIELD':<24} "
        f"{'PICTURE':<14} {'USAGE':<9} {'VALUE':<18} BYTES"
    )

    for index, row in enumerate(rows, start=1):
        out.append(f"\n* --- record {index} of {len(rows)} ---")
        offset = 0
        for spec, cell in zip(specs, row, strict=True):
            raw = encode_field(spec, cell, opts)
            out.extend(_dump_field_lines(spec, cell, offset, raw, opts))
            offset += len(raw)
    return "\n".join(out) + "\n"
