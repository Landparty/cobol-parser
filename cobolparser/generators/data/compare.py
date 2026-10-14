"""Field-level comparison of two record files read through one copybook.

The check that closes an integration test: the output dataset a batch run
wrote, against the baseline it should match.  A byte compare (``cmp``,
IEBCOMPR) answers the wrong question twice over -- one inserted record makes
every record after it "different", and a timestamp that is *supposed* to
change fails the run.  This compares what a COBOL programmer would compare::

    from cobolparser.generators.data import RecordDecoder
    from cobolparser.generators.data.compare import compare_files

    decoder = RecordDecoder.from_copybook_file("CUSTOMER.cpy", opts=ebcdic)
    result = compare_files(
        decoder, "CUST.EXPECTED", "CUST.ACTUAL",
        key=["CUST-ID"], ignore=["LAST-UPDATE-TS"],
    )
    result.equal                  # False
    result.differences[0].fields  # [FieldDifference(name="CUST-BAL", ...)]

* **Records are paired by key** when one is given, so an inserted or deleted
  record is reported once, as ``extra`` or ``missing``, rather than shifting
  every later record into ``changed``.  Without a key they pair by position.
* **Fields compare by decoded value**, so ``+5`` packed with a ``C`` sign
  nibble equals ``+5`` packed with ``F``: the program cannot tell them apart
  either.  ``compare_bytes=True`` compares the raw bytes instead, for the
  cases where the exact image matters (a file handed to another system).
  Text fields are the exception to "by value": decoded text has trailing
  spaces and NULs stripped alike, but a field left as LOW-VALUES is not the
  space-padded baseline to the program (``IF NAME = SPACES``), so two equal
  text values still differ when their NULs are in different places (#287).
  ``FILLER`` is exempt -- uninitialised FILLER is common and harmless -- and
  only a bytes compare reports it.
  A field whose bytes did not decode cleanly on either side is always
  compared by its bytes -- its best-effort value is not a thing to trust.
* **Nothing is dropped quietly.**  A key or ignore name the layout does not
  have is an error listing the ones it does, not a no-op that makes a real
  difference invisible; duplicate keys, decode errors and trailing bytes on
  either side are carried into :attr:`CompareResult.caveats`.
"""

from __future__ import annotations

import os
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from .decoding import DecodedField, DecodedRecord, DecodeResult, RecordDecoder
from .errors import CopybookLayoutError
from .layout import FieldCategory
from .views import RecordView

DifferenceKind = Literal["changed", "missing", "extra"]

#: The pseudo-field a bytes compare reports when two records differ only in
#: bytes no field of the view covers (FILLER, slack past the layout's end).
UNMAPPED_BYTES = "(unmapped bytes)"

#: How many duplicate keys are named individually before the rest are
#: summarised -- a file keyed on the wrong field duplicates nearly every key,
#: and ten thousand identical caveats would bury the one that says so.
_MAX_NAMED_DUPLICATES = 10


class CompareError(CopybookLayoutError):
    """Raised when a comparison cannot be set up as asked.

    A mistyped key or ignore name, a key that is also ignored, or two results
    read through different views -- each would otherwise produce a
    plausible-looking but wrong answer.
    """


@dataclass(frozen=True)
class FieldDifference:
    """One field whose value differs between the paired records.

    Attributes:
        name: The field's column name (subscript included for a table
            occurrence).
        qualified_name: Dotted path from the record root.
        offset: Byte offset within the record -- the expected record's, or
            the actual one's when the field is absent from the expected.
        length: Bytes the field occupies.
        expected: Decoded value in the expected record, ``None`` when the
            field is not present there (a shorter variable-length record, an
            ``OCCURS ... DEPENDING ON`` occurrence its counter excludes).
        actual: Same, for the actual record.
        expected_hex: The expected bytes as spaced hex pairs.
        actual_hex: The actual bytes as spaced hex pairs.
    """

    name: str
    qualified_name: str
    offset: int
    length: int
    expected: str | None
    actual: str | None
    expected_hex: str
    actual_hex: str

    def to_dict(self) -> dict[str, Any]:
        """Serialise the difference."""
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "offset": self.offset,
            "length": self.length,
            "expected": self.expected,
            "actual": self.actual,
            "expected_hex": self.expected_hex,
            "actual_hex": self.actual_hex,
        }


@dataclass(frozen=True)
class RecordDifference:
    """One record that is not the same in both files.

    Attributes:
        kind: ``changed`` -- paired, some fields differ; ``missing`` -- in the
            expected file only; ``extra`` -- in the actual file only.
        key: The record's key values, in ``key`` order, or ``None`` for a
            positional compare.
        expected_index: 0-based position in the expected file, ``None`` for
            an ``extra`` record.
        actual_index: 0-based position in the actual file, ``None`` for a
            ``missing`` record.
        fields: The differing fields of a ``changed`` record; empty otherwise.
    """

    kind: DifferenceKind
    key: tuple[str, ...] | None
    expected_index: int | None
    actual_index: int | None
    fields: list[FieldDifference] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the difference and its fields."""
        return {
            "kind": self.kind,
            "key": list(self.key) if self.key is not None else None,
            "expected_index": self.expected_index,
            "actual_index": self.actual_index,
            "fields": [item.to_dict() for item in self.fields],
        }


@dataclass
class CompareResult:
    """Everything one comparison found.

    The ``*_count`` attributes are always exact.  :attr:`differences` may be
    cut short by ``max_differences``; :attr:`truncated` says when it was.

    Attributes:
        record_name: The copybook record both files were read through.
        view: The view (base record or ``REDEFINES`` overlay) used.
        key: The key columns records were paired on; empty for positional.
        ignored: Every column left out of the compare, after expanding group
            and base names -- what was *actually* skipped, so a reader can
            check that an ignore did not swallow more than intended.
        compare_bytes: Whether fields were compared by raw bytes.
        expected_count: Records in the expected file.
        actual_count: Records in the actual file.
        matched_count: Paired records with no differing field.
        changed_count: Paired records with at least one differing field.
        missing_count: Expected records with no partner in the actual file.
        extra_count: Actual records with no partner in the expected file.
        differences: The differing records, expected-file order first, then
            the extras in actual-file order.
        truncated: True when :attr:`differences` stops short of the counts.
        trailing_differs: The bytes after the last whole record (a partial
            record, :attr:`DecodeResult.trailing`) differ: both files have
            such a tail and the tails are not the same, or -- under
            ``compare_bytes`` -- only one file has one.  Never decoded, so
            no field can be named; it still makes the files unequal.
        caveats: Reasons the answer may not be the whole story.
    """

    record_name: str
    view: str
    key: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    compare_bytes: bool = False
    expected_count: int = 0
    actual_count: int = 0
    matched_count: int = 0
    changed_count: int = 0
    missing_count: int = 0
    extra_count: int = 0
    differences: list[RecordDifference] = field(default_factory=list)
    truncated: bool = False
    trailing_differs: bool = False
    caveats: list[str] = field(default_factory=list)

    @property
    def equal(self) -> bool:
        """True when every record paired, no paired record differs, and the
        trailing partial records (if any) do not differ."""
        return not (
            self.changed_count
            or self.missing_count
            or self.extra_count
            or self.trailing_differs
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the whole comparison."""
        return {
            "record_name": self.record_name,
            "view": self.view,
            "key": list(self.key),
            "ignored": list(self.ignored),
            "compare_bytes": self.compare_bytes,
            "equal": self.equal,
            "expected_count": self.expected_count,
            "actual_count": self.actual_count,
            "matched_count": self.matched_count,
            "changed_count": self.changed_count,
            "missing_count": self.missing_count,
            "extra_count": self.extra_count,
            "truncated": self.truncated,
            "trailing_differs": self.trailing_differs,
            "caveats": list(self.caveats),
            "differences": [item.to_dict() for item in self.differences],
        }

    def to_text(self) -> str:
        """A report a person reads: summary first, then each difference.

        Record numbers here are 1-based, the way a person counts records in
        a file; :meth:`to_dict` keeps the 0-based indexes a program wants.
        """
        pairing = f"key {', '.join(self.key)}" if self.key else "by position"
        mode = "bytes" if self.compare_bytes else "values"
        lines = [
            f"compare {self.record_name} (view {self.view}), {pairing}, "
            f"comparing {mode}",
            f"expected: {self.expected_count} records, "
            f"actual: {self.actual_count} records",
        ]
        if self.ignored:
            lines.append(f"ignored: {', '.join(self.ignored)}")
        if self.equal:
            lines.append("files are equal")
        else:
            lines.append(
                f"matched {self.matched_count}, changed {self.changed_count}, "
                f"missing {self.missing_count}, extra {self.extra_count}"
            )
            if self.trailing_differs:
                lines.append(
                    "trailing bytes differ (the partial records after the last "
                    "whole record are not the same)"
                )
        for caveat in self.caveats:
            lines.append(f"note: {caveat}")
        for item in self.differences:
            lines.append("")
            lines.append(_describe_record(item, self.key))
            width = max((len(diff.name) for diff in item.fields), default=0)
            for diff in item.fields:
                line = (
                    f"  {diff.name.ljust(width)}  @{diff.offset}+{diff.length}  "
                    f"expected {_show(diff.expected)}  actual {_show(diff.actual)}"
                )
                if diff.expected is not None and diff.expected == diff.actual:
                    # Same value, different bytes (padding, a sign nibble):
                    # the values alone would not show what differs.
                    line += (
                        f"  (bytes x'{diff.expected_hex.replace(' ', '')}' vs "
                        f"x'{diff.actual_hex.replace(' ', '')}')"
                    )
                lines.append(line)
        if self.truncated:
            shown = len(self.differences)
            total = self.changed_count + self.missing_count + self.extra_count
            lines.append("")
            lines.append(f"... {total - shown} more differing records not shown")
        return "\n".join(lines) + "\n"


def _describe_record(item: RecordDifference, key: Sequence[str]) -> str:
    where = []
    if item.expected_index is not None:
        where.append(f"expected record {item.expected_index + 1}")
    if item.actual_index is not None:
        where.append(f"actual record {item.actual_index + 1}")
    label = item.kind.upper().ljust(7)
    if item.key is not None:
        shown = ", ".join(
            f"{name}={value!r}" for name, value in zip(key, item.key, strict=True)
        )
        return f"{label}  {shown}  ({'; '.join(where)})"
    return f"{label}  {'; '.join(where)}"


def _show(value: str | None) -> str:
    return "(absent)" if value is None else repr(value)


# ---------------------------------------------------------------------------
# Name resolution: key and ignore tokens against the view's own columns
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Column:
    column: str
    qualified_name: str

    @property
    def base(self) -> str:
        return self.qualified_name.rsplit(".", 1)[-1]

    @property
    def segments(self) -> tuple[str, ...]:
        return tuple(self.qualified_name.split("."))


def _columns_of(view: RecordView) -> list[_Column]:
    return [
        _Column(placed.spec.column.upper(), placed.spec.qualified_name.upper())
        for placed in view.fields
    ]


def _resolve_key(tokens: Sequence[str], columns: list[_Column]) -> list[str]:
    """Each key token to exactly one elementary column, or an error.

    A key has to name one field: a group or a table name would make "the key"
    several values with no stated order, and a name shared by two fields
    (legal COBOL, qualified with ``OF``) would pair on whichever came first.
    """
    resolved: list[str] = []
    for token in tokens:
        wanted = token.strip().upper()
        for attribute in ("column", "qualified_name", "base"):
            hits = [c for c in columns if getattr(c, attribute) == wanted]
            if hits:
                break
        if not hits:
            raise CompareError(
                f"key field {token!r} is not in the layout; columns: "
                + ", ".join(c.column for c in columns)
            )
        if len(hits) > 1:
            raise CompareError(
                f"key field {token!r} names {len(hits)} fields ("
                + ", ".join(c.column for c in hits)
                + "); a key must name exactly one -- use its column name"
            )
        resolved.append(hits[0].column)
    return resolved


def _resolve_ignore(tokens: Sequence[str], columns: list[_Column]) -> list[str]:
    """Every column an ignore token covers, in layout order.

    A token matches a column name (``QTY(2)``), a field name (``QTY``: every
    occurrence), a qualified name, or any group on the field's path
    (``ADDR-HOME``: everything under it).
    """
    ignored: set[str] = set()
    for token in tokens:
        wanted = token.strip().upper()
        hits = [
            c
            for c in columns
            if wanted in (c.column, c.qualified_name, c.base)
            or wanted in c.segments
            or c.qualified_name.startswith(wanted + ".")
        ]
        if not hits:
            raise CompareError(
                f"ignore field {token!r} is not in the layout; columns: "
                + ", ".join(c.column for c in columns)
            )
        ignored.update(c.column for c in hits)
    return [c.column for c in columns if c.column in ignored]


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def compare_records(
    expected: DecodeResult,
    actual: DecodeResult,
    *,
    view: RecordView,
    key: Sequence[str] = (),
    ignore: Sequence[str] = (),
    compare_bytes: bool = False,
    max_differences: int | None = None,
) -> CompareResult:
    """Compare two decoded files field by field.

    Args:
        expected: The baseline, decoded through *view*.
        actual: The file under test, decoded through the same *view*.
        view: The view both were decoded through -- what key and ignore
            names are resolved against, so a name is checked against the
            layout even when both files are empty.
        key: Fields to pair records on.  Empty pairs them by position.
        ignore: Fields, field names or groups to leave out of the compare.
        compare_bytes: Compare raw bytes rather than decoded values.
        max_differences: Report at most this many differing records.  The
            counts stay exact either way.

    Raises:
        CompareError: when a name is not in the layout, names more than one
            key field, is both a key and ignored, or the two results were
            not read through *view*.
    """
    for label, result in (("expected", expected), ("actual", actual)):
        if result.view.upper() != view.name.upper():
            raise CompareError(
                f"the {label} file was decoded through view {result.view!r}, "
                f"not {view.name!r}; decode both through the same view"
            )
    columns = _columns_of(view)
    key_columns = _resolve_key(key, columns)
    ignored = _resolve_ignore(ignore, columns)
    overlap = sorted(set(key_columns) & set(ignored))
    if overlap:
        raise CompareError(
            f"{', '.join(overlap)} is both a key and ignored; a key field has "
            "to be compared to pair records on it"
        )

    compare = CompareResult(
        record_name=expected.record_name,
        view=view.name,
        key=key_columns,
        ignored=ignored,
        compare_bytes=compare_bytes,
        expected_count=len(expected.records),
        actual_count=len(actual.records),
        caveats=_decode_caveats(expected, actual),
        trailing_differs=_trailing_differs(expected, actual, compare_bytes),
    )
    skip = frozenset(ignored)
    # FILLER is exempt from the LOW-VALUES-vs-spaces check: uninitialised
    # FILLER in an FD record is common and harmless (#287).  A bytes
    # compare still reports it.
    fillers = frozenset(
        placed.spec.column.upper() for placed in view.fields if placed.spec.is_filler
    )

    def record(item: RecordDifference) -> None:
        if max_differences is not None and len(compare.differences) >= max_differences:
            compare.truncated = True
            return
        compare.differences.append(item)

    def pair(
        exp: DecodedRecord, act: DecodedRecord, record_key: tuple[str, ...] | None
    ) -> None:
        fields = _field_differences(exp, act, skip, compare_bytes, fillers)
        if fields:
            compare.changed_count += 1
            record(
                RecordDifference("changed", record_key, exp.index, act.index, fields)
            )
        else:
            compare.matched_count += 1

    if key_columns:
        pending: dict[tuple[str, ...], deque[DecodedRecord]] = {}
        for act in actual.records:
            pending.setdefault(_key_of(act, key_columns), deque()).append(act)
        compare.caveats.extend(_duplicate_key_caveats(expected, actual, key_columns))
        for exp in expected.records:
            record_key = _key_of(exp, key_columns)
            partners = pending.get(record_key)
            if partners:
                pair(exp, partners.popleft(), record_key)
            else:
                compare.missing_count += 1
                record(RecordDifference("missing", record_key, exp.index, None))
        # Extras in the order they appear in the actual file, not grouped by
        # key: that is the order someone scrolling the file will find them in.
        leftover = {id(act) for queue in pending.values() for act in queue}
        for act in actual.records:
            if id(act) in leftover:
                compare.extra_count += 1
                record(
                    RecordDifference(
                        "extra", _key_of(act, key_columns), None, act.index
                    )
                )
    else:
        for exp, act in zip(expected.records, actual.records, strict=False):
            pair(exp, act, None)
        for exp in expected.records[len(actual.records) :]:
            compare.missing_count += 1
            record(RecordDifference("missing", None, exp.index, None))
        for act in actual.records[len(expected.records) :]:
            compare.extra_count += 1
            record(RecordDifference("extra", None, None, act.index))

    return compare


def compare_files(
    decoder: RecordDecoder,
    expected: str | os.PathLike[str],
    actual: str | os.PathLike[str],
    *,
    view: str | None = None,
    key: Sequence[str] = (),
    ignore: Sequence[str] = (),
    compare_bytes: bool = False,
    max_differences: int | None = None,
) -> CompareResult:
    """Decode two files through *decoder* and compare them.

    Both files are read with the decoder's own options (charset, byte order,
    record format, record length): an expected and an actual file of the
    same dataset are the same kind of file.

    Raises:
        CompareError: see :func:`compare_records`.
        RecordDecodingError: when either file cannot be framed into records.
        OSError: when either file cannot be read.
    """
    chosen = decoder.resolve_view(view)
    return compare_records(
        decoder.decode_file(expected, view=view),
        decoder.decode_file(actual, view=view),
        view=chosen,
        key=key,
        ignore=ignore,
        compare_bytes=compare_bytes,
        max_differences=max_differences,
    )


def _key_of(item: DecodedRecord, key_columns: Sequence[str]) -> tuple[str, ...]:
    by_column = {decoded.name.upper(): decoded for decoded in item.fields}
    values = []
    for column in key_columns:
        decoded = by_column.get(column)
        if decoded is None or not decoded.present:
            values.append("")
        elif decoded.error:
            # An undecodable key still has to pair with its twin: its bytes
            # are the one thing both copies are guaranteed to agree on.
            values.append(f"x'{decoded.raw.hex().upper()}'")
        else:
            values.append(decoded.value)
    return tuple(values)


def _field_differences(
    exp: DecodedRecord,
    act: DecodedRecord,
    skip: frozenset[str],
    compare_bytes: bool,
    fillers: frozenset[str] = frozenset(),
) -> list[FieldDifference]:
    differences: list[FieldDifference] = []
    actual_fields = {decoded.name.upper(): decoded for decoded in act.fields}
    for exp_field in exp.fields:
        name = exp_field.name.upper()
        if name in skip:
            continue
        act_field = actual_fields.get(name)
        if act_field is None or not _same(
            exp_field, act_field, compare_bytes, pad_sensitive=name not in fillers
        ):
            differences.append(_difference(exp_field, act_field))
    if compare_bytes and not differences:
        # Every field agrees, yet the images may not: the difference is in
        # bytes no field covers. A bytes compare exists to catch exactly this
        # -- but bytes of an *ignored* field are not "unmapped", so they are
        # blanked out on both sides before the images are compared.
        exp_raw = _without_ignored(exp, skip)
        act_raw = _without_ignored(act, skip)
        if exp_raw != act_raw:
            differences.append(_unmapped(exp, act, exp_raw, act_raw))
    return differences


def _without_ignored(item: DecodedRecord, skip: frozenset[str]) -> bytes:
    """The record image with every ignored field's bytes zeroed."""
    if not skip:
        return item.raw
    image = bytearray(item.raw)
    for decoded in item.fields:
        if decoded.present and decoded.name.upper() in skip:
            end = min(decoded.offset + decoded.length, len(image))
            image[decoded.offset : end] = bytes(max(end - decoded.offset, 0))
    return bytes(image)


def _same(
    exp: DecodedField,
    act: DecodedField,
    compare_bytes: bool,
    *,
    pad_sensitive: bool = True,
) -> bool:
    if exp.present != act.present:
        return False
    if not exp.present:
        return True
    if compare_bytes or exp.error or act.error:
        return exp.raw == act.raw
    if exp.value != act.value:
        return False
    if pad_sensitive and exp.category in _TEXT_CATEGORIES:
        # Decoded text has trailing spaces *and* NULs stripped, so 'ALICE'
        # padded with LOW-VALUES decodes the same as 'ALICE' padded with
        # spaces -- yet ``IF NAME = SPACES`` tells them apart, and a field
        # nobody initialised is what an output check exists to catch (#287).
        # Equal values plus NULs in the same places means the same bytes.
        return _nul_positions(exp.raw) == _nul_positions(act.raw)
    return True


_TEXT_CATEGORIES = frozenset(
    {
        FieldCategory.ALPHANUMERIC.value,
        FieldCategory.ALPHABETIC.value,
        FieldCategory.ALPHANUMERIC_EDITED.value,
        FieldCategory.NUMERIC_EDITED.value,
        FieldCategory.NATIONAL.value,
    }
)


def _nul_positions(raw: bytes) -> tuple[int, ...]:
    return tuple(index for index, byte in enumerate(raw) if byte == 0)


def _difference(exp: DecodedField, act: DecodedField | None) -> FieldDifference:
    anchor = exp if exp.present or act is None else act
    return FieldDifference(
        name=exp.name,
        qualified_name=exp.qualified_name,
        offset=anchor.offset,
        length=max(exp.length, act.length if act is not None else 0),
        expected=exp.value if exp.present else None,
        actual=act.value if act is not None and act.present else None,
        expected_hex=exp.hex,
        actual_hex=act.hex if act is not None else "",
    )


def _unmapped(
    exp: DecodedRecord, act: DecodedRecord, exp_raw: bytes, act_raw: bytes
) -> FieldDifference:
    # The first differing byte is found in the images with ignored fields
    # blanked, so an ignored field ahead of the real difference is skipped.
    start = next(
        (
            index
            for index, (left, right) in enumerate(zip(exp_raw, act_raw, strict=False))
            if left != right
        ),
        min(len(exp_raw), len(act_raw)),
    )
    return FieldDifference(
        name=UNMAPPED_BYTES,
        qualified_name=UNMAPPED_BYTES,
        offset=start,
        length=max(len(exp.raw), len(act.raw)) - start,
        expected=None,
        actual=None,
        expected_hex=" ".join(f"{byte:02X}" for byte in exp.raw[start:]),
        actual_hex=" ".join(f"{byte:02X}" for byte in act.raw[start:]),
    )


def _trailing_differs(
    expected: DecodeResult, actual: DecodeResult, compare_bytes: bool
) -> bool:
    """Whether the bytes after each file's last whole record differ (#250).

    Two different tails always differ.  A tail only one file has differs only
    under ``compare_bytes``: comparing values, a stray partial record is a
    framing caveat rather than data, but a byte compare is about the exact
    image and one file's image is longer.
    """
    if expected.trailing and actual.trailing:
        return expected.trailing != actual.trailing
    return compare_bytes and bool(expected.trailing or actual.trailing)


def _decode_caveats(expected: DecodeResult, actual: DecodeResult) -> list[str]:
    caveats: list[str] = []
    for caveat in [*expected.caveats, *actual.caveats]:
        if caveat not in caveats:
            caveats.append(caveat)
    for label, result in (("expected", expected), ("actual", actual)):
        if result.error_count:
            caveats.append(
                f"{result.error_count} field(s) in the {label} file did not "
                "decode cleanly; those fields were compared by their bytes"
            )
        if result.trailing:
            caveats.append(
                f"the {label} file ends with {len(result.trailing)} bytes that "
                "are not a whole record and were not compared -- check the "
                "record length / record format"
            )
    return caveats


def _duplicate_key_caveats(
    expected: DecodeResult, actual: DecodeResult, key_columns: Sequence[str]
) -> list[str]:
    caveats: list[str] = []
    for label, result in (("expected", expected), ("actual", actual)):
        seen: dict[tuple[str, ...], int] = {}
        for item in result.records:
            record_key = _key_of(item, key_columns)
            seen[record_key] = seen.get(record_key, 0) + 1
        duplicates = [(k, n) for k, n in seen.items() if n > 1]
        for record_key, count in duplicates[:_MAX_NAMED_DUPLICATES]:
            caveats.append(
                f"key {_format_key(key_columns, record_key)} appears {count} "
                f"times in the {label} file; its records were paired in file "
                "order"
            )
        if len(duplicates) > _MAX_NAMED_DUPLICATES:
            caveats.append(
                f"... and {len(duplicates) - _MAX_NAMED_DUPLICATES} more "
                f"duplicate keys in the {label} file -- is {', '.join(key_columns)} "
                "really unique?"
            )
    return caveats


def _format_key(key_columns: Iterable[str], values: tuple[str, ...]) -> str:
    return ", ".join(
        f"{name}={value!r}" for name, value in zip(key_columns, values, strict=True)
    )


__all__ = [
    "UNMAPPED_BYTES",
    "CompareError",
    "CompareResult",
    "FieldDifference",
    "RecordDifference",
    "compare_files",
    "compare_records",
]
