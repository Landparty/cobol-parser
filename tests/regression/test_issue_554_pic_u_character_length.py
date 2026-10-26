"""Issue #554: ``PIC U(n)`` is fixed character-length UTF-8 -- n characters,
for which Enterprise COBOL reserves 4 x n bytes.  It was sized n bytes, so
``data-items`` offsets, record lengths and gen-data / decode framing after
such a field were 3n bytes short.  ``PIC U BYTE-LENGTH n`` stays n bytes.
"""

from __future__ import annotations

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions
from cobolparser.generators.data.decoding import RecordDecoder
from cobolparser.generators.data.encoding import EncodingOptions, encoding_caveats
from cobolparser.generators.data.layout_offsets import compute_program_data_items

COPYBOOK = (
    "       01  REC.\n"
    "           05  Q  PIC U(4).\n"
    "           05  Z  PIC X.\n"
    "           05  B  PIC U BYTE-LENGTH 6.\n"
)

PROGRAM = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. UTF8LEN.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n" + COPYBOOK + "       PROCEDURE DIVISION.\n"
    "           STOP RUN.\n"
)


def test_data_items_reserves_four_bytes_per_character() -> None:
    result = parse_cobol(
        PROGRAM, filename="utf8len.cbl", error_recovery=ErrorRecoveryMode.FAIL_FAST
    )
    assert result.ast is not None, result.errors
    by_name = {
        item["name"]: item for item in compute_program_data_items(result.ast)["items"]
    }
    assert by_name["Q"]["byte_length"] == 16
    assert by_name["Z"]["byte_offset"] == 16
    assert by_name["B"]["byte_offset"] == 17
    assert by_name["B"]["byte_length"] == 6
    assert by_name["REC"]["byte_length"] == 23


def test_gen_data_writes_n_characters_padded_to_four_n_bytes() -> None:
    opts = DataGeneratorOptions(rows=3, seed=1).for_record_image()
    dataset = CopybookDataGenerator(opts).generate_from_source(COPYBOOK)
    assert dataset.record_length() == 23
    q = next(spec for spec in dataset.fields if spec.name == "Q")
    assert q.storage_size == 16 and q.character_positions == 4
    b = next(spec for spec in dataset.fields if spec.name == "B")
    assert b.storage_size == 6 and b.character_positions == 6
    columns = [spec.name for spec in dataset.fields]
    q_at, z_at = columns.index("Q"), columns.index("Z")
    for row in dataset.rows:
        assert len(row[q_at]) <= 4
    assert any(
        "PIC U(n)" in c and "REC.Q" in c for c in encoding_caveats(dataset.fields)
    )

    image = dataset.to_records(EncodingOptions())
    assert len(image) == 3 * 23
    decoded = RecordDecoder.from_copybook_source(
        COPYBOOK, opts=EncodingOptions()
    ).decode_bytes(image)
    assert decoded.error_count == 0
    assert [r.values()["Z"] for r in decoded.records] == [
        row[z_at] for row in dataset.rows
    ]
