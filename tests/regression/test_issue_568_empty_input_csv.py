"""Issue #568: ``gen-fixtures --format csv-dir`` wrote nothing for the
"empty input" scenario. Its READ fixture -- a file-shaped IN boundary with a
layout and zero records -- got ``csv_path: null`` in MANIFEST.json, exactly
like the STATUS_ONLY OPEN / CLOSE beside it, so a consumer could not tell
"bind an empty dataset here" from "this boundary has no data". It now gets a
header-only CSV (option 1 of the issue).
"""

from __future__ import annotations

import json

from cobolparser.generators import DataGeneratorOptions, ProgramFixtureGenerator

RDR2 = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RDR2.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INDD
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-ID    PIC 9(4).
           05  IN-NAME  PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-FS   PIC XX.
       01  WS-EOF  PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE
           PERFORM UNTIL WS-EOF = 'Y'
               READ IN-FILE
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END DISPLAY IN-ID
               END-READ
           END-PERFORM
           CLOSE IN-FILE
           GOBACK.
"""


def _manifest(tmp_path):
    source = tmp_path / "RDR2.cbl"
    source.write_text(RDR2)
    bundle = ProgramFixtureGenerator(
        DataGeneratorOptions(rows=2)
    ).generate_with_scenarios_from_file(str(source), mode="all", seed=1)
    out = tmp_path / "out"
    bundle.write_csv_dir(str(out))
    return out, json.loads((out / "MANIFEST.json").read_text())


def _fixtures(manifest, scenario_name):
    (scenario,) = [s for s in manifest["scenarios"] if s["name"] == scenario_name]
    return {f["category"]: f for f in scenario["fixtures"]}


def test_empty_input_read_gets_a_header_only_csv(tmp_path) -> None:
    out, manifest = _manifest(tmp_path)
    fixtures = _fixtures(manifest, "empty input")
    read = fixtures["READ"]
    assert read["csv_path"] == "empty-input/IN-FILE.csv"
    assert (out / read["csv_path"]).read_text() == "IN-ID,IN-NAME\n"


def test_status_only_fixtures_still_get_no_csv(tmp_path) -> None:
    _out, manifest = _manifest(tmp_path)
    fixtures = _fixtures(manifest, "empty input")
    assert fixtures["OPEN"]["csv_path"] is None
    assert fixtures["CLOSE"]["csv_path"] is None


def test_happy_path_csv_unchanged(tmp_path) -> None:
    out, manifest = _manifest(tmp_path)
    read = _fixtures(manifest, "happy path")["READ"]
    lines = (out / read["csv_path"]).read_text().splitlines()
    assert lines[0] == "IN-ID,IN-NAME"
    assert len(lines) == 1 + 2
