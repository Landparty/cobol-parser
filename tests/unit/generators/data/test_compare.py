"""Record compare: two record files, one copybook, field-level differences.

Every fixture here is a real record image built by ``encode_record`` -- the
encoder whose bytes are verified against GnuCOBOL -- so these tests exercise
compare over exactly the bytes a COBOL program would have written, EBCDIC
and packed decimal included, rather than over hand-built decode results.
"""

from __future__ import annotations

import pytest

from cobolparser.generators.data.compare import (
    UNMAPPED_BYTES,
    CompareError,
    compare_files,
    compare_records,
)
from cobolparser.generators.data.copybook import parse_copybook_records
from cobolparser.generators.data.decoding import RecordDecoder
from cobolparser.generators.data.encoding import (
    Charset,
    EncodingOptions,
    RecordFormat,
    encode_record,
)
from cobolparser.generators.data.layout import flatten_record
from cobolparser.generators.data.options import DataGeneratorOptions

CUSTOMER = """
       01  CUST-REC.
           05  CUST-ID     PIC 9(4).
           05  CUST-NAME   PIC X(8).
           05  CUST-BAL    PIC S9(5)V99 COMP-3.
           05  ADDR.
               10  ZIP     PIC 9(5).
               10  CITY    PIC X(6).
           05  ITEMS OCCURS 2 TIMES.
               10  QTY     PIC 9(2).
           05  UPD-TS      PIC X(8).
"""

ORDERS = """
       01  ORDER-REC.
           05  ORD-ID      PIC 9(4).
           05  ORD-COUNT   PIC 9(1).
           05  ORD-LINE OCCURS 1 TO 3 TIMES DEPENDING ON ORD-COUNT.
               10  LINE-QTY PIC 9(3).
"""

DUPLICATE_NAMES = """
       01  PAIR-REC.
           05  LEFT-SIDE.
               10  AMT     PIC 9(3).
           05  RIGHT-SIDE.
               10  AMT     PIC 9(3).
"""

EBCDIC = EncodingOptions(charset=Charset.EBCDIC)

ALICE = ["1", "ALICE", "123.45", "12345", "PARIS", "1", "2", "20260927"]
BOB = ["2", "BOB", "-10.00", "54321", "LYON", "3", "4", "20260927"]
CAROL = ["3", "CAROL", "0.00", "11111", "NICE", "5", "6", "20260927"]


def _image(source: str, rows: list[list[str]], opts: EncodingOptions) -> bytes:
    record = parse_copybook_records(source)[0]
    specs = flatten_record(record, DataGeneratorOptions(rows=1).for_record_image())
    return b"".join(encode_record(specs, row, opts) for row in rows)


def _compare(
    expected_rows: list[list[str]],
    actual_rows: list[list[str]],
    *,
    source: str = CUSTOMER,
    opts: EncodingOptions = EBCDIC,
    **kwargs,
):
    decoder = RecordDecoder.from_copybook_source(source, opts=opts)
    return compare_records(
        decoder.decode_bytes(_image(source, expected_rows, opts)),
        decoder.decode_bytes(_image(source, actual_rows, opts)),
        view=decoder.views.base,
        **kwargs,
    )


def _with(row: list[str], index: int, value: str) -> list[str]:
    changed = list(row)
    changed[index] = value
    return changed


# ---------------------------------------------------------------------------
# Equal and positional
# ---------------------------------------------------------------------------


def test_a_file_equals_itself():
    result = _compare([ALICE, BOB], [ALICE, BOB])
    assert result.equal
    assert result.matched_count == 2
    assert result.differences == []
    assert "files are equal" in result.to_text()


def test_one_changed_field_is_one_difference_with_its_offset():
    result = _compare([ALICE, BOB], [ALICE, _with(BOB, 2, "-10.01")])

    assert not result.equal
    assert (result.matched_count, result.changed_count) == (1, 1)
    [record] = result.differences
    assert record.kind == "changed"
    assert (record.expected_index, record.actual_index) == (1, 1)
    [diff] = record.fields
    assert diff.name == "CUST-BAL"
    assert (diff.offset, diff.length) == (12, 4)  # 4 + 8 bytes in; S9(5)V99 COMP-3
    assert (diff.expected, diff.actual) == ("-10.00", "-10.01")
    assert diff.expected_hex == "00 01 00 0D"  # 0001000, sign D


def test_positional_compare_reports_an_insert_as_a_cascade():
    """The reason keys exist: without one, an insert shifts every record."""
    result = _compare([ALICE, BOB, CAROL], [ALICE, CAROL, BOB, CAROL])
    assert result.changed_count == 2
    assert result.extra_count == 1
    assert result.differences[-1].kind == "extra"
    assert result.differences[-1].actual_index == 3


def test_positional_missing_records_at_the_end():
    result = _compare([ALICE, BOB, CAROL], [ALICE])
    assert (result.matched_count, result.missing_count) == (1, 2)
    assert [d.expected_index for d in result.differences] == [1, 2]


# ---------------------------------------------------------------------------
# Keyed
# ---------------------------------------------------------------------------


def test_keyed_compare_reports_an_insert_once():
    result = _compare([ALICE, CAROL], [ALICE, BOB, CAROL], key=["CUST-ID"])
    assert (result.matched_count, result.changed_count, result.extra_count) == (
        2,
        0,
        1,
    )
    [extra] = result.differences
    assert extra.kind == "extra"
    assert extra.key == ("2",)
    assert extra.actual_index == 1


def test_keyed_compare_pairs_reordered_records():
    result = _compare([ALICE, BOB, CAROL], [CAROL, ALICE, BOB], key=["CUST-ID"])
    assert result.equal


def test_keyed_missing_and_changed_together():
    result = _compare(
        [ALICE, BOB, CAROL], [_with(ALICE, 4, "ROUEN"), CAROL], key=["CUST-ID"]
    )
    assert (result.changed_count, result.missing_count) == (1, 1)
    kinds = [(d.kind, d.key) for d in result.differences]
    assert kinds == [("changed", ("1",)), ("missing", ("2",))]
    assert result.differences[0].fields[0].name == "CITY"


def test_multi_field_key():
    first = _with(ALICE, 3, "22222")
    result = _compare([ALICE, first], [first, ALICE], key=["CUST-ID", "ZIP"])
    assert result.equal
    assert result.key == ["CUST-ID", "ZIP"]


def test_duplicate_keys_pair_in_file_order_and_say_so():
    twin = _with(ALICE, 1, "ALICE2")
    result = _compare([ALICE, twin], [ALICE, twin], key=["CUST-ID"])
    assert result.equal
    assert any("appears 2 times in the expected file" in c for c in result.caveats)


def test_key_by_qualified_name():
    result = _compare([ALICE], [ALICE], key=["CUST-REC.ADDR.ZIP"])
    assert result.key == ["ZIP"]


# ---------------------------------------------------------------------------
# Ignore
# ---------------------------------------------------------------------------


def test_ignoring_a_timestamp_makes_the_files_equal():
    later = _with(ALICE, 7, "20261231")
    assert not _compare([ALICE], [later]).equal
    result = _compare([ALICE], [later], ignore=["UPD-TS"])
    assert result.equal
    assert result.ignored == ["UPD-TS"]


def test_ignoring_a_group_ignores_everything_under_it():
    moved = _with(_with(ALICE, 3, "99999"), 4, "BREST")
    result = _compare([ALICE], [moved], ignore=["ADDR"])
    assert result.equal
    assert result.ignored == ["ZIP", "CITY"]


def test_ignoring_a_table_field_name_covers_every_occurrence():
    result = _compare([ALICE], [_with(_with(ALICE, 5, "9"), 6, "8")], ignore=["QTY"])
    assert result.equal
    assert result.ignored == ["QTY(1)", "QTY(2)"]


def test_ignoring_one_occurrence_leaves_the_other():
    result = _compare([ALICE], [_with(_with(ALICE, 5, "9"), 6, "8")], ignore=["QTY(1)"])
    assert [f.name for f in result.differences[0].fields] == ["QTY(2)"]


# ---------------------------------------------------------------------------
# Names that are not in the layout are errors, never no-ops
# ---------------------------------------------------------------------------


def test_unknown_key_is_an_error_listing_the_columns():
    with pytest.raises(CompareError, match="key field 'CUST-NUM' is not in the layout"):
        _compare([ALICE], [ALICE], key=["CUST-NUM"])


def test_unknown_ignore_is_an_error():
    with pytest.raises(CompareError, match="ignore field 'UPDATE-TS'"):
        _compare([ALICE], [ALICE], ignore=["UPDATE-TS"])


def test_a_key_cannot_also_be_ignored():
    with pytest.raises(CompareError, match="both a key and ignored"):
        _compare([ALICE], [ALICE], key=["CUST-ID"], ignore=["CUST-ID"])


def test_an_ambiguous_key_is_an_error():
    with pytest.raises(CompareError, match="names 2 fields"):
        _compare([["1", "2"]], [["1", "2"]], source=DUPLICATE_NAMES, key=["AMT"])


def test_a_group_is_not_a_key():
    with pytest.raises(CompareError, match="key field 'ADDR' is not in the layout"):
        _compare([ALICE], [ALICE], key=["ADDR"])


def test_results_from_different_views_are_refused():
    decoder = RecordDecoder.from_copybook_source(CUSTOMER, opts=EBCDIC)
    data = decoder.decode_bytes(_image(CUSTOMER, [ALICE], EBCDIC))
    data.view = "SOMETHING-ELSE"
    with pytest.raises(CompareError, match="decoded through view"):
        compare_records(data, data, view=decoder.views.base)


# ---------------------------------------------------------------------------
# Values vs bytes
# ---------------------------------------------------------------------------


def _resigned(image: bytes, offset: int) -> bytes:
    """Flip a positive packed field's sign nibble from C to F."""
    last = image[offset]
    assert last & 0x0F == 0x0C
    return image[:offset] + bytes([(last & 0xF0) | 0x0F]) + image[offset + 1 :]


def test_c_and_f_sign_nibbles_are_equal_by_value_but_not_by_bytes():
    decoder = RecordDecoder.from_copybook_source(CUSTOMER, opts=EBCDIC)
    original = _image(CUSTOMER, [ALICE], EBCDIC)
    resigned = _resigned(original, 15)  # last byte of CUST-BAL (offset 12 + 4)
    expected = decoder.decode_bytes(original)
    actual = decoder.decode_bytes(resigned)

    assert compare_records(expected, actual, view=decoder.views.base).equal
    by_bytes = compare_records(
        expected, actual, view=decoder.views.base, compare_bytes=True
    )
    [diff] = by_bytes.differences[0].fields
    assert diff.name == "CUST-BAL"
    assert diff.expected_hex.endswith("5C") and diff.actual_hex.endswith("5F")


def test_bytes_compare_reports_slack_no_field_covers():
    decoder = RecordDecoder.from_copybook_source(
        CUSTOMER, opts=EBCDIC, record_length=44
    )
    image = _image(CUSTOMER, [ALICE], EBCDIC)  # 39 bytes of layout, 5 of slack
    expected = decoder.decode_bytes(image + b"\x40" * 5)
    actual = decoder.decode_bytes(image + b"\x40\x40\xff\x40\x40")

    assert compare_records(expected, actual, view=decoder.views.base).equal
    by_bytes = compare_records(
        expected, actual, view=decoder.views.base, compare_bytes=True
    )
    [diff] = by_bytes.differences[0].fields
    assert diff.name == UNMAPPED_BYTES
    assert diff.offset == 41
    assert diff.actual_hex == "FF 40 40"


def test_bytes_compare_does_not_report_an_ignored_field_as_unmapped():
    later = _with(ALICE, 7, "20261231")
    result = _compare([ALICE], [later], ignore=["UPD-TS"], compare_bytes=True)
    assert result.equal, result.to_text()


def test_bytes_compare_skips_an_ignored_field_ahead_of_real_slack():
    decoder = RecordDecoder.from_copybook_source(
        CUSTOMER, opts=EBCDIC, record_length=44
    )
    later = _with(ALICE, 7, "20261231")
    expected = decoder.decode_bytes(_image(CUSTOMER, [ALICE], EBCDIC) + b"\x40" * 5)
    actual = decoder.decode_bytes(
        _image(CUSTOMER, [later], EBCDIC) + b"\x40\x40\xff\x40\x40"
    )
    result = compare_records(
        expected,
        actual,
        view=decoder.views.base,
        ignore=["UPD-TS"],
        compare_bytes=True,
    )
    [diff] = result.differences[0].fields
    assert diff.name == UNMAPPED_BYTES
    assert diff.offset == 41


def test_a_field_that_does_not_decode_is_compared_by_its_bytes():
    decoder = RecordDecoder.from_copybook_source(CUSTOMER, opts=EBCDIC)
    image = _image(CUSTOMER, [ALICE], EBCDIC)
    broken = image[:12] + b"\xff\xff\xff\xff" + image[16:]
    result = compare_records(
        decoder.decode_bytes(broken),
        decoder.decode_bytes(image),
        view=decoder.views.base,
    )
    assert result.differences[0].fields[0].name == "CUST-BAL"
    assert any("did not decode cleanly" in c for c in result.caveats)


# ---------------------------------------------------------------------------
# Variable-length records
# ---------------------------------------------------------------------------


def test_variable_records_with_different_occurrence_counts():
    vb = EncodingOptions(charset=Charset.EBCDIC, record_format=RecordFormat.VARIABLE)
    short = ["1", "1", "5", "0", "0"]
    longer = ["1", "2", "5", "7", "0"]
    result = _compare([short], [longer], source=ORDERS, opts=vb, key=["ORD-ID"])

    fields = {f.name: f for f in result.differences[0].fields}
    assert set(fields) == {"ORD-COUNT", "LINE-QTY(2)"}
    assert fields["LINE-QTY(2)"].expected is None  # absent from the short record
    assert fields["LINE-QTY(2)"].actual == "7"
    assert "(absent)" in result.to_text()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_max_differences_caps_the_list_but_not_the_counts():
    expected = [ALICE, BOB, CAROL]
    actual = [_with(row, 7, "19990101") for row in expected]
    result = _compare(expected, actual, max_differences=1)
    assert result.changed_count == 3
    assert len(result.differences) == 1
    assert result.truncated
    assert "2 more differing records not shown" in result.to_text()


def test_trailing_bytes_are_a_caveat():
    decoder = RecordDecoder.from_copybook_source(CUSTOMER, opts=EBCDIC)
    image = _image(CUSTOMER, [ALICE], EBCDIC)
    result = compare_records(
        decoder.decode_bytes(image),
        decoder.decode_bytes(image + b"\x40\x40"),
        view=decoder.views.base,
    )
    assert result.equal
    assert any("the actual file ends with 2 bytes" in c for c in result.caveats)


def test_to_dict_round_trips_the_counts_and_differences():
    result = _compare([ALICE, BOB], [ALICE], key=["CUST-ID"])
    data = result.to_dict()
    assert data["equal"] is False
    assert data["missing_count"] == 1
    assert data["differences"][0]["kind"] == "missing"
    assert data["differences"][0]["key"] == ["2"]
    assert data["key"] == ["CUST-ID"]


def test_text_report_names_records_one_based():
    text = _compare([ALICE, BOB], [ALICE, _with(BOB, 1, "ROBERT")], key=["CUST-ID"])
    report = text.to_text()
    assert "CHANGED  CUST-ID='2'  (expected record 2; actual record 2)" in report
    assert "CUST-NAME  @4+8  expected 'BOB'  actual 'ROBERT'" in report


def test_compare_files_reads_both_paths(tmp_path):
    decoder = RecordDecoder.from_copybook_source(CUSTOMER, opts=EBCDIC)
    expected = tmp_path / "EXPECTED.DAT"
    actual = tmp_path / "ACTUAL.DAT"
    expected.write_bytes(_image(CUSTOMER, [ALICE, BOB], EBCDIC))
    actual.write_bytes(_image(CUSTOMER, [ALICE, _with(BOB, 4, "ARLES")], EBCDIC))
    result = compare_files(decoder, expected, actual, key=["CUST-ID"])
    assert result.changed_count == 1
    assert result.expected_count == result.actual_count == 2
