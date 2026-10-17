"""Issue #552: gen-data honoured a VALUE on an elementary item only.  A
group's VALUE (``05 HDR VALUE 'HDR0001'``, ``05 NUMS VALUE ZEROES``) never
reached its subordinates, so a constant header / trailer group got random
bytes.  The literal is now laid over the group's fields by byte offset.
"""

from __future__ import annotations

from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions
from cobolparser.generators.data.encoding import Charset, EncodingOptions

COPYBOOK = (
    "       01  R.\n"
    "           05  HDR VALUE 'HDR0001'.\n"
    "               10 H-TYPE PIC X(3).\n"
    "               10 H-SEQ  PIC 9(4).\n"
    "           05  BODY PIC X(3).\n"
    "           05  NUMS VALUE ZEROES.\n"
    "               10 N1 PIC 9(2).\n"
    "               10 N2 PIC 9(2).\n"
    "           05  TRL VALUE 'AB'.\n"
    "               10 T1 PIC X(1).\n"
    "               10 T2 PIC X(3).\n"
    "           05  HX VALUE X'C1C2'.\n"
    "               10 X1 PIC X(1).\n"
    "               10 X2 PIC X(1).\n"
    "           05  PK VALUE ZERO.\n"
    "               10 P1 PIC S9(3) COMP-3.\n"
)


def _generate(**kwargs):
    opts = DataGeneratorOptions(rows=4, seed=1, **kwargs).for_record_image()
    return CopybookDataGenerator(opts).generate_from_source(COPYBOOK)


def test_group_value_bytes_are_constant_in_every_record() -> None:
    dataset = _generate()
    image = dataset.to_records(EncodingOptions(charset=Charset.EBCDIC))
    length = dataset.record_length()
    records = [image[i : i + length] for i in range(0, len(image), length)]
    assert len(records) == 4
    for record in records:
        assert record[0:7] == "HDR0001".encode("cp037")
        assert record[10:14] == "0000".encode("cp037")
        assert record[14:18] == "AB  ".encode("cp037")
        assert record[18:20] == b"\xc1\xc2"
        assert record[20:22] == b"\x00\x0c"  # COMP-3 zero
    # BODY is the only field left to vary.
    assert len({record[7:10] for record in records}) > 1


def test_group_value_is_sliced_into_each_field_cell() -> None:
    dataset = _generate()
    columns = [spec.name for spec in dataset.fields]
    for row in dataset.rows:
        cells = dict(zip(columns, row, strict=True))
        assert cells["H-TYPE"] == "HDR"
        assert int(cells["H-SEQ"]) == 1
        assert int(cells["N1"]) == 0 and int(cells["N2"]) == 0
        assert cells["T1"] == "A"
        assert cells["T2"].rstrip() == "B"


def test_respect_values_false_still_ignores_it() -> None:
    dataset = _generate(respect_values=False)
    columns = [spec.name for spec in dataset.fields]
    assert {row[columns.index("H-TYPE")] for row in dataset.rows} != {"HDR"}


def test_numeric_slice_is_read_as_digits_at_the_field_scale() -> None:
    # '00012345' over 9(2)V99 + 9(4): the bytes are the literal's, so A is
    # 00.01 -- taking the slice '0001' as the number 1 wrote '0100'.
    copybook = (
        "       01  R.\n"
        "           05  G VALUE '00012345'.\n"
        "               10 A PIC 9(2)V99.\n"
        "               10 B PIC 9(4).\n"
    )
    opts = DataGeneratorOptions(rows=2, seed=1).for_record_image()
    dataset = CopybookDataGenerator(opts).generate_from_source(copybook)
    assert dataset.to_records(EncodingOptions()) == b"00012345" * 2
    columns = [spec.name for spec in dataset.fields]
    for row in dataset.rows:
        assert row[columns.index("A")] == "0.01"


def test_a_non_digit_slice_does_not_become_a_numeric_value() -> None:
    # 'ABCD' over a 9(4) is no value the encoder can write back as those
    # bytes: the cell said ABCD while the record held 0000.  It is generated.
    copybook = (
        "       01  R.\n"
        "           05  G VALUE 'HDRABCD'.\n"
        "               10 A PIC X(3).\n"
        "               10 B PIC 9(4).\n"
    )
    opts = DataGeneratorOptions(rows=3, seed=1).for_record_image()
    dataset = CopybookDataGenerator(opts).generate_from_source(copybook)
    columns = [spec.name for spec in dataset.fields]
    for row in dataset.rows:
        assert row[columns.index("A")] == "HDR"
        assert row[columns.index("B")].isdigit()
