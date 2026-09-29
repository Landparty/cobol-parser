"""How many bytes a COBOL data item actually occupies.

Split out from both :mod:`cobolparser.generators.data.layout` (which knows a
field's PICTURE and category) and :mod:`cobolparser.generators.data.encoding`
(which turns a value into those bytes) so the two cannot drift: a record image
whose field widths disagreed with the offsets ``data-items`` reports would be
wrong in a way neither module could detect on its own.
:mod:`cobolparser.generators.data.layout_offsets` defers here too, as does
:meth:`cobolparser.models.data_items.CobolDataItem.calculate_size`, so every
surface answers this question the same way.

Lives at the package root, beside :mod:`cobolparser._errors`, and for the same
reason: ``cobolparser.generators.data.__init__`` eagerly imports
``program_layout``, which imports ``cobolparser.models``, so a model importing
this from under ``generators.data`` would close an import cycle.
``cobolparser.generators.data.storage`` re-exports everything here, so the
importers that predate the move are unaffected.

Zero dependencies beyond the standard library, deliberately -- it is imported
by modules on both sides of the layout/encoding split, and by the models.
"""

from __future__ import annotations

#: ``USAGE INDEX`` occupies a fullword.  It carries no PICTURE, so nothing
#: in the layout can derive this -- before this constant existed an INDEX
#: item was sized from its (absent) picture and came out as zero bytes,
#: silently collapsing every following offset in the record.
INDEX_BYTES = 4
#: ``USAGE POINTER``, ``FUNCTION-POINTER`` and ``OBJECT REFERENCE``: one
#: 31-bit address.
POINTER_BYTES = 4
#: ``USAGE PROCEDURE-POINTER`` is *two* words on IBM Enterprise COBOL (the
#: entry address plus a second word the runtime uses), so 8 bytes -- sizing
#: it as a fullword shifted every offset after it by four.
PROCEDURE_POINTER_BYTES = 8
#: ``USAGE POINTER-64`` (Enterprise COBOL 6.x): a 64-bit address, a
#: doubleword.  ``POINTER-32`` is the explicitly 31-bit form, a fullword.
#: Neither spelling was known here, so both were sized from their (absent)
#: PICTURE as zero bytes and every later offset in the record collapsed.
POINTER_64_BYTES = 8

#: Usages that hold an address rather than data.  ``OBJECT REFERENCE`` (OO
#: COBOL) is one too; with no PICTURE it used to be sized as zero bytes,
#: collapsing every following offset in the record.
POINTER_USAGES = frozenset(
    {
        "POINTER",
        "POINTER-32",
        "POINTER-64",
        "PROCEDURE-POINTER",
        "FUNCTION-POINTER",
        "OBJECT REFERENCE",
    }
)
PACKED_USAGES = frozenset({"COMP-3", "COMPUTATIONAL-3", "PACKED-DECIMAL"})
#: Binary usages whose byte order is fixed big-endian, per IBM Enterprise
#: COBOL and GnuCOBOL's default ``binary-byteorder``.
BINARY_FIXED_USAGES = frozenset(
    {"COMP", "COMPUTATIONAL", "COMP-4", "COMPUTATIONAL-4", "BINARY"}
)
#: ``COMP-5``: "native" binary, so its byte order is a choice rather than a
#: fixed property.  Sized identically to ``COMP``.
BINARY_NATIVE_USAGES = frozenset({"COMP-5", "COMPUTATIONAL-5"})
BINARY_USAGES = BINARY_FIXED_USAGES | BINARY_NATIVE_USAGES
SINGLE_FLOAT_USAGES = frozenset({"COMP-1", "COMPUTATIONAL-1"})
DOUBLE_FLOAT_USAGES = frozenset({"COMP-2", "COMPUTATIONAL-2"})
FLOAT_USAGES = SINGLE_FLOAT_USAGES | DOUBLE_FLOAT_USAGES


def binary_byte_length(digits: int) -> int:
    """Bytes a binary (``COMP``/``COMP-4``/``COMP-5``) field of *digits* takes.

    The IBM Enterprise COBOL table: halfword through 4 digits, fullword
    through 9, doubleword through 18, and the extended 16-byte form beyond.
    """
    if digits <= 4:
        return 2
    if digits <= 9:
        return 4
    if digits <= 18:
        return 8
    return 16


def packed_byte_length(digits: int) -> int:
    """Bytes a ``COMP-3`` field of *digits* takes: *digits* digit nibbles
    plus one sign nibble, rounded up to a whole byte."""
    return (digits + 2) // 2


def storage_size(
    usage: str | None,
    *,
    picture_size: int | None,
    total_digits: int | None,
    sign_clause: str | None = None,
    is_signed: bool = False,
    national_picture: bool = False,
) -> int:
    """One occurrence's real storage byte length.

    *picture_size* is the PICTURE's character-position count (``None`` for a
    PICTURE-less item) and *total_digits* its digit count; both come
    straight off a :class:`~.layout.FieldSpec` or a
    :class:`~...models.data_items.PictureClause`.

    Two cases that the per-module copies of this arithmetic used to get
    wrong, and the reason it now lives in one place: ``USAGE INDEX`` has no
    PICTURE to take a size from but still occupies a fullword, and a DISPLAY
    field with ``SIGN IS SEPARATE`` spends a whole byte on the sign that its
    PICTURE's character count does not include.

    ``USAGE NATIONAL`` stores every character position as a two-byte UTF-16
    unit.  An ``N`` picture's size already counts bytes
    (*national_picture*); a numeric or numeric-edited picture's counts
    positions, so ``PIC 9(5) USAGE NATIONAL`` is ten bytes, and a separate
    sign is one more national character (two bytes), not one byte.
    """
    normalized = (usage or "DISPLAY").upper()
    if normalized == "PROCEDURE-POINTER":
        return PROCEDURE_POINTER_BYTES
    if normalized == "POINTER-64":
        return POINTER_64_BYTES
    if normalized in POINTER_USAGES:
        return POINTER_BYTES
    if normalized == "INDEX":
        return INDEX_BYTES
    if normalized in SINGLE_FLOAT_USAGES:
        return 4
    if normalized in DOUBLE_FLOAT_USAGES:
        return 8
    if normalized in PACKED_USAGES:
        return packed_byte_length(total_digits) if total_digits else 0
    if normalized in BINARY_USAGES:
        return binary_byte_length(total_digits) if total_digits else 0
    size = picture_size or 0
    if normalized == "NATIONAL" and not national_picture:
        if size and is_signed and "SEPARATE" in (sign_clause or "").upper():
            size += 1
        return 2 * size
    # DISPLAY only: SIGN IS SEPARATE spends a byte the PICTURE does not
    # count.  A COMP-3/COMP field's sign lives inside its own encoding, so
    # the clause (which COBOL permits but ignores there) adds nothing.
    if size and is_signed and "SEPARATE" in (sign_clause or "").upper():
        size += 1
    return size
