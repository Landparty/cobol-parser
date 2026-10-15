"""Issue #362: a whole program's FD frames RECFM=F at the file's LRECL.

Every 01 under one FD shares one record area, so a fixed-length file of
that FD holds records of the FD's LRECL -- the largest 01, or ``RECORD
CONTAINS n`` -- whichever 01 is chosen with ``--record``.  ``decode`` and
``compare`` used to split the file at the chosen 01's own length, and
``gen-data`` wrote records that short; a 9-byte header read off a 16-byte
file shredded every record after the first.
"""

from __future__ import annotations

import sys

import pytest

from cobolparser.cli.parse import main
from cobolparser.generators.data.compare import compare_files
from cobolparser.generators.data.copybook import (
    CopybookDataGenerator,
    fd_record_length,
    parse_copybook_records,
    select_record,
)
from cobolparser.generators.data.decoding import RecordDecoder
from cobolparser.generators.data.encoding import Charset, EncodingOptions
from cobolparser.generators.data.options import DataGeneratorOptions

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. P6.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRANS-FILE ASSIGN TO TRANSIN.
       DATA DIVISION.
       FILE SECTION.
       FD TRANS-FILE RECORDING MODE IS F{record_clause}.
       01 HDR-REC.
          05 HDR-TYPE PIC X.
          05 HDR-DATE PIC 9(8).
       01 DTL-REC.
          05 DTL-TYPE PIC X.
          05 DTL-ID PIC 9(6).
          05 DTL-AMT PIC 9(9).
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-A PIC X(3).
       PROCEDURE DIVISION.
           STOP RUN.
"""

SOURCE = PROGRAM.format(record_clause="")
DATA = b"H20261014       D123456000012345D654321000000100"


def _program(record_clause: str = "") -> str:
    # On its own line: appended to the FD line it would run past column 72,
    # where fixed format drops it.
    return PROGRAM.format(record_clause="\n          " + record_clause.strip())


def _lrecl(source: str, record: str) -> int | None:
    records = parse_copybook_records(source, filename="p6.cbl")
    return fd_record_length(records, select_record(records, record))


class TestFdRecordLength:
    def test_shorter_record_takes_the_longest_sibling(self):
        assert _lrecl(SOURCE, "HDR-REC") == 16

    def test_longest_record_needs_no_override(self):
        assert _lrecl(SOURCE, "DTL-REC") is None

    def test_record_contains_wins(self):
        source = _program(" RECORD CONTAINS 20 CHARACTERS")
        assert _lrecl(source, "HDR-REC") == 20
        assert _lrecl(source, "DTL-REC") == 20

    def test_record_contains_never_shrinks_the_record(self):
        assert _lrecl(_program(" RECORD CONTAINS 5 CHARACTERS"), "DTL-REC") is None

    def test_small_record_contains_still_gives_one_lrecl(self):
        # RECORD CONTAINS below the largest 01 does not shrink the record
        # area: every 01 of the FD frames at the same 16 bytes.
        source = _program(" RECORD CONTAINS 10 CHARACTERS")
        assert _lrecl(source, "HDR-REC") == 16
        assert _lrecl(source, "DTL-REC") is None

    def test_range_after_recording_mode_is_not_a_fixed_lrecl(self):
        # RECORD CONTAINS 5 TO 30 after RECORDING MODE is a range, so the
        # largest 01 decides rather than a fixed length of 5 or 30.
        clauses = parse_copybook_records(
            _program(" RECORD CONTAINS 5 TO 30 CHARACTERS")
        )[0].get_metadata("fd_clauses")
        assert clauses["record"]["min"] == 5
        assert clauses["record"]["max"] == 30
        source = _program(" RECORD CONTAINS 5 TO 30 CHARACTERS")
        assert _lrecl(source, "HDR-REC") == 16
        assert _lrecl(source, "DTL-REC") is None

    def test_working_storage_record_has_no_fd(self):
        assert _lrecl(SOURCE, "WS-REC") is None

    def test_bare_copybook_has_no_fd(self):
        copybook = "       01 A-REC.\n          05 A PIC X.\n       01 B-REC.\n          05 B PIC X(9).\n"
        records = parse_copybook_records(copybook)
        assert fd_record_length(records, records[0]) is None


class TestDecodeFraming:
    def test_shorter_record_frames_at_lrecl(self):
        decoder = RecordDecoder.from_copybook_source(SOURCE, record="HDR-REC")
        result = decoder.decode_bytes(DATA)
        assert [r.values() for r in result.records] == [
            {"HDR-TYPE": "H", "HDR-DATE": "20261014"},
            {"HDR-TYPE": "D", "HDR-DATE": "12345600"},
            {"HDR-TYPE": "D", "HDR-DATE": "65432100"},
        ]
        assert result.trailing == b""

    def test_default_record_frames_at_lrecl(self):
        # No --record: the first 01 (HDR-REC) is chosen, and was misframed too.
        decoder = RecordDecoder.from_copybook_source(SOURCE)
        assert len(decoder.decode_bytes(DATA).records) == 3

    def test_explicit_record_length_still_overrides(self):
        decoder = RecordDecoder.from_copybook_source(
            SOURCE, record="HDR-REC", record_length=9
        )
        assert decoder.record_length == 9

    def test_record_contains_frames_the_file(self):
        source = _program(" RECORD CONTAINS 20 CHARACTERS")
        decoder = RecordDecoder.from_copybook_source(source, record="DTL-REC")
        data = b"D123456000012345    D654321000000100    "
        result = decoder.decode_bytes(data)
        assert [r.values()["DTL-ID"] for r in result.records] == [
            "123456",
            "654321",
        ]
        assert result.trailing == b""

    def test_compare_frames_at_lrecl(self, tmp_path):
        expected = tmp_path / "expected.dat"
        actual = tmp_path / "actual.dat"
        expected.write_bytes(DATA)
        actual.write_bytes(DATA)
        decoder = RecordDecoder.from_copybook_source(SOURCE, record="HDR-REC")
        diff = compare_files(decoder, expected, actual)
        assert diff.equal
        assert diff.expected_count == diff.matched_count == 3


class TestGenDataPadsToLrecl:
    def _dataset(self, record: str, source: str = SOURCE):
        options = DataGeneratorOptions(rows=3, seed=7).for_record_image()
        return CopybookDataGenerator(options).generate_from_source(
            source, record=record
        )

    @pytest.mark.parametrize(
        ("charset", "space"), [(Charset.ASCII, b" "), (Charset.EBCDIC, b"\x40")]
    )
    def test_shorter_record_is_space_padded(self, charset, space):
        dataset = self._dataset("HDR-REC")
        opts = EncodingOptions(charset=charset)
        raw = dataset.to_records(opts)
        assert len(raw) == 3 * 16
        assert dataset.record_lengths(opts) == [16, 16, 16]
        for start in range(0, len(raw), 16):
            assert raw[start + 9 : start + 16] == space * 7

    def test_longest_record_is_unchanged(self):
        dataset = self._dataset("DTL-REC")
        assert dataset.lrecl is None
        assert len(dataset.to_records()) == 3 * 16

    def test_round_trip_through_decode(self):
        dataset = self._dataset("HDR-REC")
        decoder = RecordDecoder.from_copybook_source(SOURCE, record="HDR-REC")
        result = decoder.decode_bytes(dataset.to_records())
        assert [list(r.values().values()) for r in result.records] == dataset.rows

    def test_hex_dump_shows_the_slack(self):
        dump = self._dataset("HDR-REC").to_hex_dump()
        assert "* record length: 16 bytes (FD LRECL; the layout is 9)" in dump
        assert "* --- record 1 of 3: 16 bytes ---" in dump
        assert "(FD LRECL slack)" in dump

    def test_variable_format_is_not_padded(self):
        from cobolparser.generators.data.encoding import RecordFormat

        dataset = self._dataset("HDR-REC")
        opts = EncodingOptions(record_format=RecordFormat.VARIABLE)
        assert dataset.record_lengths(opts) == [13, 13, 13]


def test_cli_decode_frames_at_lrecl(tmp_path, capsys):
    program = tmp_path / "p6.cbl"
    data = tmp_path / "p6.dat"
    program.write_text(SOURCE)
    data.write_bytes(DATA)
    saved = sys.argv
    sys.argv = [
        "cobol-parser",
        "decode",
        str(data),
        "--copybook",
        str(program),
        "--record",
        "HDR-REC",
    ]
    try:
        main()
    except SystemExit as exc:
        assert not exc.code
    finally:
        sys.argv = saved
    out, err = capsys.readouterr()
    assert out.splitlines() == [
        "HDR-TYPE,HDR-DATE",
        "H,20261014",
        "D,12345600",
        "D,65432100",
    ]
    assert "trailing" not in err
