"""CLI coverage for `expand --source-map` / `--keep-comments` and lint origins.

The library-level behaviour lives in
``tests/regression/test_expansion_source_map_and_comments.py``; this pins the
command-line surface an external consumer (the VS Code extension) actually
calls: that the flags exist, that their output carries the map and the comment
text, and that a lint finding inside an inlined copybook reports the copybook's
own file and line instead of a line number counted in the expanded text.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from cobolparser.cli.parse import main

COPYBOOK = """      * customer master record
       01  CUST-REC.
           05  CUST-ID     PIC 9(6).
           05  CUST-NAME   PIC X(20).
"""

PROGRAM = """      * payroll driver
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY CUSTOMER.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY CUST-ID.
           GOBACK.
"""


@pytest.fixture
def library(tmp_path):
    (tmp_path / "CUSTOMER.cpy").write_text(COPYBOOK)
    (tmp_path / "PAYROLL.cbl").write_text(PROGRAM)
    return tmp_path


def _run_json(capsys, *argv):
    with patch("sys.argv", ["cobol-parser", *argv]):
        main()
    return json.loads(capsys.readouterr().out)


def _run_text(capsys, *argv):
    with patch("sys.argv", ["cobol-parser", *argv]):
        main()
    return capsys.readouterr().out


class TestExpandSourceMap:
    def test_map_is_absent_without_the_flag(self, capsys, library):
        data = _run_json(
            capsys,
            "expand",
            str(library / "PAYROLL.cbl"),
            "--copybook-path",
            str(library),
            "--compact",
        )

        assert "source_location_map" not in data

    def test_map_names_the_file_and_line_of_every_expanded_line(self, capsys, library):
        program = str(library / "PAYROLL.cbl")
        data = _run_json(
            capsys,
            "expand",
            program,
            "--copybook-path",
            str(library),
            "--source-map",
            "--compact",
        )

        mapping = data["source_location_map"]
        lines = data["expanded_source"].split("\n")
        cust_id = next(i for i, line in enumerate(lines, 1) if "CUST-ID" in line)
        goback = next(i for i, line in enumerate(lines, 1) if "GOBACK" in line)

        assert mapping[str(cust_id)] == {
            "file": str(library / "CUSTOMER.cpy"),
            "line": 3,
        }
        assert mapping[str(goback)] == {"file": program, "line": 10}


class TestExpandKeepComments:
    def test_comments_are_blanked_by_default(self, capsys, library):
        data = _run_json(
            capsys,
            "expand",
            str(library / "PAYROLL.cbl"),
            "--copybook-path",
            str(library),
            "--compact",
        )

        assert "payroll driver" not in data["expanded_source"]

    def test_keep_comments_restores_program_and_copybook_comments(
        self, capsys, library
    ):
        data = _run_json(
            capsys,
            "expand",
            str(library / "PAYROLL.cbl"),
            "--copybook-path",
            str(library),
            "--keep-comments",
            "--compact",
        )

        assert "* payroll driver" in data["expanded_source"]
        assert "* customer master record" in data["expanded_source"]


class TestLintReportsOrigins:
    def test_a_finding_inside_a_copybook_names_the_copybook(self, capsys, library):
        data = _run_json(
            capsys,
            "lint",
            str(library / "PAYROLL.cbl"),
            "--copybook-path",
            str(library),
            "--compact",
        )

        unused = next(f for f in data["findings"] if f["symbol"] == "CUST-NAME")
        assert unused["origin"] == {"file": str(library / "CUSTOMER.cpy"), "line": 4}

    def test_text_output_is_clickable_at_the_real_location(self, capsys, library):
        out = _run_text(
            capsys,
            "lint",
            str(library / "PAYROLL.cbl"),
            "--copybook-path",
            str(library),
            "--format",
            "text",
        )

        assert f"{library / 'CUSTOMER.cpy'}:4:" in out

    def test_without_expansion_there_is_no_origin_to_report(self, capsys, library):
        # No --copybook-path: nothing was expanded, so locations already count
        # lines in the file itself and claiming an origin would add nothing.
        data = _run_json(capsys, "lint", str(library / "PAYROLL.cbl"), "--compact")

        assert all("origin" not in f for f in data["findings"])
