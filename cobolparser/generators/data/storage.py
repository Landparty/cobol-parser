"""How many bytes a COBOL data item actually occupies.

Split out from both :mod:`.layout` (which knows a field's PICTURE and
category) and :mod:`.encoding` (which turns a value into those bytes) so the
two cannot drift: a record image whose field widths disagreed with the
offsets ``data-items`` reports would be wrong in a way neither module could
detect on its own.  :mod:`.layout_offsets` defers here too, so every surface
in the package answers this question the same way.

Zero dependencies beyond the standard library, deliberately -- it is
imported by modules on both sides of the layout/encoding split.
"""

from __future__ import annotations

#: ``USAGE INDEX`` occupies a fullword.  It carries no PICTURE, so nothing
#: in the layout can derive this -- before this constant existed an INDEX
#: item was sized from its (absent) picture and came out as zero bytes,
#: silently collapsing every following offset in the record.
INDEX_BYTES = 4
#: ``USAGE POINTER`` and its relatives.
POINTER_BYTES = 4

POINTER_USAGES = frozenset({"POINTER", "PROCEDURE-POINTER", "FUNCTION-POINTER"})
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
    """
    normalized = (usage or "DISPLAY").upper()
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
    # DISPLAY only: SIGN IS SEPARATE spends a byte the PICTURE does not
    # count.  A COMP-3/COMP field's sign lives inside its own encoding, so
    # the clause (which COBOL permits but ignores there) adds nothing.
    if size and is_signed and "SEPARATE" in (sign_clause or "").upper():
        size += 1
    return size
