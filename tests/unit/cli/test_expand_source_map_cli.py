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
        # `05` sits in column 12 of the fixed-format copybook (#301).
        assert unused["origin"] == {
            "file": str(library / "CUSTOMER.cpy"),
            "line": 4,
            "column": 12,
        }

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

        assert f"{library / 'CUSTOMER.cpy'}:4:12:" in out

    def test_a_copybook_that_cannot_be_reread_prints_no_column(self, capsys, library):
        # Without the member's text there is no telling its layout, so the
        # analyzer column (7 short for this fixed-format member) is not
        # printed as if it were the real one.
        from pathlib import Path

        from cobolparser.preprocess import copybook_expander

        real_read = copybook_expander.read_program_source

        def read_program_source(path, *args, **kwargs):
            # The column pass re-reads each file; the expansion does not
            # come through here, so only the re-read fails.
            if Path(path).name == "CUSTOMER.cpy":
                raise OSError("gone")
            return real_read(path, *args, **kwargs)

        with patch.object(
            copybook_expander, "read_program_source", read_program_source
        ):
            out = _run_text(
                capsys,
                "lint",
                str(library / "PAYROLL.cbl"),
                "--copybook-path",
                str(library),
                "--format",
                "text",
            )

        assert f"{library / 'CUSTOMER.cpy'}:4: info [unused-variables]" in out

    def test_free_form_copybook_in_a_fixed_program_keeps_its_own_column(
        self, capsys, tmp_path
    ):
        # The expander pads a free-form member by exactly the 7 columns
        # normalization strips again, so its analyzer column is already the
        # one on disk (#301).
        (tmp_path / "FREEMEM.cpy").write_text(
            "*> free member\n"
            "01 FREE-REC.\n"
            "   05 FREE-A PIC X.\n"
            "   05 FREE-B PIC X.\n"
        )
        (tmp_path / "MIX.cbl").write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. MIX.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY FREEMEM.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           DISPLAY FREE-A.\n"
            "           GOBACK.\n"
        )
        out = _run_text(
            capsys,
            "lint",
            str(tmp_path / "MIX.cbl"),
            "--copybook-path",
            str(tmp_path),
            "--format",
            "text",
        )

        assert f"{tmp_path / 'FREEMEM.cpy'}:4:4:" in out

    def test_fixed_format_copybook_in_a_free_form_program(self, capsys, library):
        # A free-form parent keeps the member's indicator column but cuts its
        # 6-column sequence area: an offset of 6, not 7.
        (library / "FREEPAY.cbl").write_text(
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. FREEPAY.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "COPY CUSTOMER.\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-PARA.\n"
            "    DISPLAY CUST-ID.\n"
            "    GOBACK.\n"
        )
        out = _run_text(
            capsys,
            "lint",
            str(library / "FREEPAY.cbl"),
            "--copybook-path",
            str(library),
            "--format",
            "text",
        )

        assert f"{library / 'CUSTOMER.cpy'}:4:12:" in out

    def test_without_expansion_origin_is_the_file_itself(self, capsys, library):
        # No --copybook-path: nothing was expanded, so the origin is this
        # file and the same line. It is still emitted, because it carries the
        # on-disk column that `location.column` (analyzer columns, 7 short on
        # a fixed-format line) does not (#301).
        program = str(library / "PAYROLL.cbl")
        data = _run_json(capsys, "lint", program, "--compact")

        for finding in data["findings"]:
            if finding["location"] is None:
                continue
            assert finding["origin"]["file"] == program
            assert finding["origin"]["line"] == finding["location"]["line"]
            assert finding["origin"]["column"] == finding["location"]["column"] + 7
