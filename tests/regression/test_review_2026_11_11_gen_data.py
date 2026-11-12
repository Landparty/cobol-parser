"""gen-data / gen-fixtures findings from a private-checkout run (2026-11-11).

* A6 -- the same seed gave different values in the CSV and in the record
  image: the record image always includes FILLER, and every FILLER drew
  values (which were then never written), shifting every later draw. A
  FILLER whose bytes no value changes now draws nothing, and one that owns
  level-88s draws from a stream of its own.
* A8 -- a PICTURE-less elementary item (``05 JUNK.``, usually a misread
  line) was 0 bytes in ``data-items`` but 9 in gen-data / decode, which
  classified it numeric with nine digits. It is 0 bytes everywhere now, and
  both paths say so.
* A9 -- gen-fixtures bundles ran to 1.5 GB: ``--max-occurs`` had no
  default and the JSON was pretty-printed. It now defaults to 10 (``all``
  lifts it), the bundle is compact unless ``--pretty``, a bundle over
  10 MB draws a warning, and (bundle version 2) a fixture that several
  scenarios use unchanged is written once.
* A14 -- gen-data and decode defaulted to the first 01 even when it had
  no generatable field ("no generatable fields") though later 01s did.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser import parse_cobol
from cobolparser.cli.parse import main
from cobolparser.generators.data.copybook import CopybookDataGenerator
from cobolparser.generators.data.decoding import RecordDecoder
from cobolparser.layout.copybook import parse_copybook_records, wrap_copybook_fragment
from cobolparser.layout.errors import CopybookLayoutError
from cobolparser.layout.offsets import compute_program_data_items
from cobolparser.layout.options import DataGeneratorOptions

_FILLER_COPYBOOK = """\
       01  REC.
           05  A  PIC X(3).
           05  FILLER PIC X(2).
           05  B  PIC 9(4).
           05  FILLER PIC X(2) VALUE SPACES.
           05  C  PIC X(5).
           05  FILLER PIC X.
               88  FLAG-ON VALUE 'Y'.
               88  FLAG-OFF VALUE 'N'.
           05  D  PIC S9(3) COMP-3.
"""


def _rows(csv_text: str) -> list[dict[str, str]]:
    lines = csv_text.strip().splitlines()
    header = lines[0].split(",")
    return [dict(zip(header, line.split(","), strict=True)) for line in lines[1:]]


class TestA6SeedAgreesAcrossOutputs:
    def test_record_image_decodes_to_the_csv_values(self) -> None:
        options = DataGeneratorOptions(rows=5, seed=42)
        csv_rows = _rows(
            CopybookDataGenerator(options)
            .generate_from_source(_FILLER_COPYBOOK)
            .to_csv()
        )
        image = (
            CopybookDataGenerator(options.for_record_image())
            .generate_from_source(_FILLER_COPYBOOK)
            .to_records()
        )
        decoded = _rows(
            RecordDecoder.from_copybook_source(_FILLER_COPYBOOK)
            .decode_bytes(image)
            .to_csv()
        )
        assert len(decoded) == len(csv_rows)
        for want, got in zip(csv_rows, decoded, strict=True):
            assert {k: got[k] for k in want} == want

    def test_include_filler_shows_the_written_fill(self) -> None:
        options = DataGeneratorOptions(rows=3, seed=7, include_filler=True)
        plain = _rows(
            CopybookDataGenerator(DataGeneratorOptions(rows=3, seed=7))
            .generate_from_source(_FILLER_COPYBOOK)
            .to_csv()
        )
        with_filler = _rows(
            CopybookDataGenerator(options)
            .generate_from_source(_FILLER_COPYBOOK)
            .to_csv()
        )
        for want, got in zip(plain, with_filler, strict=True):
            assert {k: got[k] for k in want} == want
            assert got["REC.FILLER"] == "" and got["REC.FILLER_2"] == ""


_JUNK_COPYBOOK = """\
       01  REC.
           05  A     PIC X(3).
           05  JUNK.
           05  IX    USAGE INDEX.
           05  B     PIC 9(2).
"""


class TestA8PicturelessItems:
    def test_gen_data_and_data_items_agree(self) -> None:
        dataset = CopybookDataGenerator(
            DataGeneratorOptions(rows=1, seed=1)
        ).generate_from_source(_JUNK_COPYBOOK)
        sizes = {f.name: f.storage_size for f in dataset.fields}
        assert sizes == {"A": 3, "JUNK": 0, "IX": 4, "B": 2}
        assert any("JUNK" in c and "no PICTURE" in c for c in dataset.caveats)

        ast = parse_cobol(wrap_copybook_fragment(_JUNK_COPYBOOK) or "").ast
        report = compute_program_data_items(ast)
        lengths = {i["name"]: i["byte_length"] for i in report["items"]}
        assert lengths["REC"] == 9 and lengths["JUNK"] == 0
        assert any("JUNK" in u and "no PICTURE" in u for u in report["unresolved"])

    def test_decode_caveat(self) -> None:
        decoder = RecordDecoder.from_copybook_source(_JUNK_COPYBOOK)
        result = decoder.decode_bytes(b"ABC\x00\x00\x00\x0112")
        assert any("no PICTURE" in c for c in result.caveats)


_FILLER_FIRST = """\
       01  HEADER-REC.
           05  FILLER  PIC X(10).
       01  DATA-REC.
           05  D-A  PIC X(4).
       01  OTHER-REC.
           05  O-A  PIC 9(2).
"""


class TestA14DefaultRecord:
    def test_defaults_to_first_generatable_record(self) -> None:
        dataset = CopybookDataGenerator(
            DataGeneratorOptions(rows=1, seed=1)
        ).generate_from_source(_FILLER_FIRST)
        assert dataset.record_name == "DATA-REC"

    def test_decode_defaults_to_the_same_record(self) -> None:
        decoder = RecordDecoder.from_copybook_source(_FILLER_FIRST)
        record = decoder.decode_bytes(b"WXYZ").records[0]
        assert record.view == "DATA-REC"
        assert [(f.name, f.value) for f in record.fields] == [("D-A", "WXYZ")]

    def test_named_empty_record_lists_candidates(self) -> None:
        with pytest.raises(CopybookLayoutError) as exc:
            CopybookDataGenerator().generate_from_source(
                _FILLER_FIRST, record="HEADER-REC"
            )
        assert "DATA-REC, OTHER-REC" in str(exc.value)

    def test_no_generatable_record_names_them(self) -> None:
        source = "       01  H1.\n           05  FILLER PIC X.\n"
        with pytest.raises(CopybookLayoutError, match="no record has generatable"):
            CopybookDataGenerator().generate_from_source(source)
        # Still decodable: decode falls back to the first 01.
        assert parse_copybook_records(source)[0].name == "H1"


_TABLE_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TPTTMA02.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-ROW OCCURS 40 TIMES.
               10  IN-CODE  PIC X(3).
       WORKING-STORAGE SECTION.
       01  WS-EOF  PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           READ IN-FILE AT END MOVE 'Y' TO WS-EOF END-READ
           CLOSE IN-FILE
           GOBACK.
"""


class TestA9BundleSize:
    def _run(self, tmp_path: Path, capsys, *extra: str) -> tuple[str, str]:  # type: ignore[no-untyped-def]
        path = tmp_path / "TPTTMA02.cbl"
        path.write_text(_TABLE_PROGRAM)
        with patch("sys.argv", ["cobol-parser", "gen-fixtures", str(path), *extra]):
            main()
        captured = capsys.readouterr()
        return captured.out, captured.err

    def _in_rec_columns(self, bundle: dict) -> int:  # type: ignore[type-arg]
        return sum(1 for f in bundle["layouts"]["IN-REC"] if f["name"] == "IN-CODE")

    def test_default_cap_and_compact_output(self, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
        out, err = self._run(tmp_path, capsys, "--seed", "1")
        assert "\n" not in out.strip()
        assert self._in_rec_columns(json.loads(out)) == 10
        assert "capped at 10" in err and "IN-ROW" in err

    def test_all_lifts_the_cap(self, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
        out, err = self._run(tmp_path, capsys, "--max-occurs", "all", "--pretty")
        assert out.startswith("{\n")
        assert self._in_rec_columns(json.loads(out)) == 40
        assert "capped" not in err

    def test_size_warning(self, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
        with patch(
            "cobolparser.cli.commands.data.GEN_FIXTURES_SIZE_WARNING_BYTES", 100
        ):
            _, err = self._run(tmp_path, capsys)
        assert "warning: the bundle is" in err


class TestA9SharedFixtures:
    """Bundle version 2: each distinct fixture once, scenarios list ids."""

    def _bundle(self):  # type: ignore[no-untyped-def]
        from cobolparser.generators import ProgramFixtureGenerator

        demo = Path(__file__).parents[2] / "examples" / "fixtures" / "FIXTUREDEMO.cbl"
        return ProgramFixtureGenerator().generate_with_scenarios_from_file(
            str(demo), mode="all", seed=1
        )

    def test_unchanged_fixtures_are_written_once(self) -> None:
        bundle = self._bundle()
        v2 = bundle.to_dict()
        assert v2["bundle_version"] == 2
        used = [i for s in v2["scenarios"] for i in s["fixtures"]]
        assert set(used) == set(v2["fixtures"])
        assert len(used) > len(v2["fixtures"])  # some fixture is shared
        assert len(json.dumps(v2)) < len(json.dumps(bundle.to_dict(bundle_version=1)))

    def test_expanding_gives_back_version_1(self) -> None:
        from cobolparser.generators import expand_shared_fixtures

        bundle = self._bundle()
        v1 = bundle.to_dict(bundle_version=1)
        assert expand_shared_fixtures(bundle.to_dict()) == v1
        assert expand_shared_fixtures(v1) == v1

    def test_ids_are_stable_and_name_variants(self) -> None:
        v2 = self._bundle().to_dict()
        assert v2 == self._bundle().to_dict()
        for fixture_id, fixture in v2["fixtures"].items():
            assert fixture_id.split("#")[0] == f"{fixture['category']}:{fixture['key']}"

    def test_unknown_version_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unsupported bundle_version 3"):
            self._bundle().to_dict(bundle_version=3)
