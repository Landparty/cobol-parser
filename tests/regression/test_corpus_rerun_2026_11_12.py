"""Regression tests from the 2026-11-12 CLI/MCP rerun over a private codebase.

The program names in that report are not in this repo; each test rebuilds
the shape the report describes:

* round trip: gen-data ``--format record`` and decode picked different 01s
  when the first one is an all-FILLER header, and ``decode --list-views``
  gave the chosen 01's length while the file is cut at its FD's LRECL;
* same seed, different values: a CSV that leaves fields out (``--max-occurs``,
  ``--include-redefines``) shifted every value after them;
* recoding: an ASCII record image wrote accented VALUE text as ``?``;
* bundle size: a seed per scenario made every fixture distinct, so a
  version 2 bundle could not share any.
"""

from __future__ import annotations

import csv
import io
import json

from cobolparser.cli.parse import main as cli_main
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions
from cobolparser.generators.data.decoding import RecordDecoder
from cobolparser.generators.data.encoding import Charset, EncodingOptions
from cobolparser.generators.program_fixtures import ProgramFixtureGenerator

HEADER_FIRST = """\
       01  CKN-PROP-HDR.
           05  FILLER              PIC X(2).
       01  CKN-PROP-REC.
           05  CKN-ID              PIC 9(8).
           05  CKN-NAME            PIC X(20).
"""

FD_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CKNPROP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PFILE ASSIGN TO PFILE.
       DATA DIVISION.
       FILE SECTION.
       FD  PFILE
           RECORD CONTAINS 28 CHARACTERS.
       01  P-REC-SHORT             PIC X(2).
       01  P-REC-LONG.
           05  P-ID                PIC 9(8).
           05  P-NAME              PIC X(20).
       PROCEDURE DIVISION.
           STOP RUN.
"""

SKIPPED_FIELDS = """\
       01  MES-REC.
           05  MES-ID              PIC 9(6).
           05  FILLER              PIC X(4).
           05  MES-TAB OCCURS 15 TIMES.
               10 MES-V            PIC 9(3).
           05  MES-CODE            PIC X(3).
           05  MES-ALT REDEFINES MES-CODE PIC 9(3).
           05  MES-AMT             PIC S9(5)V99 COMP-3.
           05  MES-LAST            PIC X(5).
"""


def _run(argv: list[str]) -> None:
    import sys

    saved = sys.argv
    sys.argv = ["cobol-parser", *argv]
    try:
        cli_main()
    except SystemExit as exc:
        assert exc.code in (0, None), argv
    finally:
        sys.argv = saved


def _decoded_rows(image_path, copybook_path, capsys) -> list[dict[str, str]]:
    capsys.readouterr()
    _run(["decode", str(image_path), "--copybook", str(copybook_path)])
    return list(csv.DictReader(io.StringIO(capsys.readouterr().out)))


class TestRoundTripPicksOneRecord:
    def test_record_image_skips_an_all_filler_header_like_decode(
        self, tmp_path, capsys
    ):
        copybook = tmp_path / "CKN.cpy"
        copybook.write_text(HEADER_FIRST)
        image = tmp_path / "ckn.bin"
        _run(
            ["gen-data", str(copybook), "--rows", "5", "--seed", "1"]
            + ["--format", "record", "-o", str(image)]
        )
        assert image.stat().st_size == 5 * 28
        rows = _decoded_rows(image, copybook, capsys)
        assert len(rows) == 5
        assert list(rows[0]) == ["CKN-ID", "CKN-NAME"]

    def test_list_views_reports_the_fd_lrecl_it_frames_at(self, tmp_path, capsys):
        program = tmp_path / "CKNPROP.cbl"
        program.write_text(FD_PROGRAM)
        capsys.readouterr()
        _run(["decode", "--copybook", str(program), "--list-views"])
        views = json.loads(capsys.readouterr().out)
        assert views["record_name"] == "P-REC-SHORT"
        assert views["record_length"] == 2
        assert views["framing_length"] == 28
        assert views["lrecl"] == 28

    def test_list_views_without_an_lrecl_has_no_lrecl_key(self, tmp_path, capsys):
        copybook = tmp_path / "CKN.cpy"
        copybook.write_text(HEADER_FIRST)
        capsys.readouterr()
        _run(["decode", "--copybook", str(copybook), "--list-views"])
        views = json.loads(capsys.readouterr().out)
        assert views["framing_length"] == 28
        assert "lrecl" not in views


class TestSameSeedSameValues:
    def _csv_and_decoded(self, tmp_path, capsys, extra: list[str]):
        copybook = tmp_path / "MES.cpy"
        copybook.write_text(SKIPPED_FIELDS)
        base = ["gen-data", str(copybook), "--rows", "5", "--seed", "7"]
        capsys.readouterr()
        _run(base + extra)
        generated = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
        image = tmp_path / "mes.bin"
        _run(base + extra + ["--format", "record", "-o", str(image)])
        return generated, _decoded_rows(image, copybook, capsys)

    def _assert_shared_columns_agree(self, generated, decoded):
        assert len(generated) == len(decoded) == 5
        shared = [c for c in generated[0] if c in decoded[0]]
        assert "MES-LAST" in shared and "MES-AMT" in shared
        for left, right in zip(generated, decoded, strict=True):
            for column in shared:
                assert left[column].strip() == right[column].strip(), column

    def test_capped_occurs_does_not_shift_later_fields(self, tmp_path, capsys):
        generated, decoded = self._csv_and_decoded(
            tmp_path, capsys, ["--max-occurs", "3"]
        )
        self._assert_shared_columns_agree(generated, decoded)

    def test_included_redefines_does_not_shift_later_fields(self, tmp_path, capsys):
        generated, decoded = self._csv_and_decoded(
            tmp_path, capsys, ["--include-redefines"]
        )
        self._assert_shared_columns_agree(generated, decoded)


class TestAsciiRecordKeepsLatin1Text:
    def test_accented_value_round_trips(self, tmp_path):
        copybook = (
            "       01  W1-REC.\n"
            "           05  W1-CITY  PIC X(10) VALUE 'MONTRÉAL'.\n"
            "           05  W1-NOTE  PIC X(6)  VALUE 'café'.\n"
        )
        opts = DataGeneratorOptions(rows=2, seed=1).for_record_image()
        dataset = CopybookDataGenerator(opts).generate_from_source(copybook)
        encoding = EncodingOptions(charset=Charset.ASCII)
        image = dataset.to_records(encoding)
        assert "MONTRÉAL".encode("latin-1") in image
        decoded = RecordDecoder.from_copybook_source(
            copybook, opts=encoding
        ).decode_bytes(image)
        assert [r.values()["W1-CITY"] for r in decoded.records] == ["MONTRÉAL"] * 2
        assert [r.values()["W1-NOTE"] for r in decoded.records] == ["café"] * 2


BRANCHY = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BRANCHY.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE.
           SELECT REF-FILE ASSIGN TO REFFILE.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-TYPE             PIC X.
           05  IN-AMT              PIC 9(5).
           05  IN-NAME             PIC X(20).
       FD  REF-FILE.
       01  REF-REC.
           05  REF-CODE            PIC X(4).
           05  REF-DESC            PIC X(30).
       WORKING-STORAGE SECTION.
       01  WS-TOTAL                PIC 9(7) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE REF-FILE
           READ REF-FILE
           READ IN-FILE
           IF IN-TYPE = 'A'
               ADD IN-AMT TO WS-TOTAL
           ELSE
               IF IN-AMT > 500
                   MOVE 0 TO WS-TOTAL
               END-IF
           END-IF
           CLOSE IN-FILE REF-FILE
           STOP RUN.
"""


class TestScenariosShareUnpinnedFixtures:
    def _bundle(self, tmp_path):
        program = tmp_path / "BRANCHY.cbl"
        program.write_text(BRANCHY)
        return ProgramFixtureGenerator().generate_with_scenarios_from_file(
            str(program), mode="branches", seed=11
        )

    def test_a_boundary_no_scenario_pins_is_written_once(self, tmp_path):
        bundle = self._bundle(tmp_path)
        assert len(bundle.scenarios) > 2
        table = bundle.to_dict()["fixtures"]
        ref_reads = [k for k in table if k.startswith("READ:REF-FILE")]
        assert ref_reads == ["READ:REF-FILE"]

    def test_unpinned_fields_read_as_in_the_happy_path(self, tmp_path):
        bundle = self._bundle(tmp_path)

        def in_rows(scenario):
            (fixture,) = [
                f
                for f in scenario.fixtures
                if f.ref.key == "IN-FILE" and f.ref.category == "READ"
            ]
            return fixture.sequence

        happy = in_rows(bundle.scenarios[0])
        for scenario in bundle.scenarios[1:]:
            rows = in_rows(scenario)
            for row, base in zip(rows, happy, strict=False):
                # IN-NAME is in no condition: no scenario pins it.
                assert row["IN-NAME"] == base["IN-NAME"], scenario.name
