"""Regression coverage for analyzing a file that holds several PROGRAM-IDs.

A source file can hold more than one program unit -- stacked or nested,
delimited by ``END PROGRAM``. The parser has always kept them
(``CobolProgram.contained_programs``), but every analyzer is program-scoped:
it grades a paragraph against the references it can see, so running it on the
outermost unit reports on that unit alone. Nothing above it said so, and
nothing offered a way to reach the others -- a contained program came back
"clean" because it was never examined.

Three things close that:

* ``CobolProgram.program_units()`` / ``find_program_unit()`` -- the list of
  units in source order, and lookup by PROGRAM-ID.
* ``--program NAME`` on every analyzer subcommand, with the file's whole unit
  list reported as ``program_units`` so a report can say what it did not
  cover.
* ``LintAnalyzer`` runs its rules over *every* unit and merges the findings:
  lint is the file's diagnostics, and a contained program silently skipped is
  the failure mode this whole change is about.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.lint import LintAnalyzer
from cobolparser.cli.parse import main

NESTED_SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTERP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-OUTER-UNUSED PIC X.
       PROCEDURE DIVISION.
       OUTER-MAIN.
           CALL "INNERP".
           GOBACK.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNERP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-INNER-UNUSED PIC X.
       PROCEDURE DIVISION.
       INNER-MAIN.
           GOBACK.
       INNER-DEAD-PARA.
           DISPLAY "never".
       END PROGRAM INNERP.
       END PROGRAM OUTERP.
"""


@pytest.fixture
def nested_ast():
    result = parse_cobol(NESTED_SOURCE, filename="nested.cbl")
    assert result.ast is not None, result.errors
    return result.ast


@pytest.fixture
def nested_file(tmp_path):
    path = tmp_path / "NESTED.cbl"
    path.write_text(NESTED_SOURCE)
    return str(path)


class TestProgramUnits:
    def test_lists_every_unit_outermost_first(self, nested_ast):
        assert [u.program_name for u in nested_ast.program_units()] == [
            "OUTERP",
            "INNERP",
        ]

    def test_a_single_program_is_its_own_only_unit(self):
        result = parse_cobol(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. SOLO.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           GOBACK.\n",
            filename="solo.cbl",
        )
        assert [u.program_name for u in result.ast.program_units()] == ["SOLO"]

    def test_lookup_is_case_insensitive_and_misses_cleanly(self, nested_ast):
        assert nested_ast.find_program_unit("innerp").program_name == "INNERP"
        assert nested_ast.find_program_unit("NOSUCH") is None


class TestLintCoversEveryUnit:
    def test_findings_come_from_both_programs(self, nested_ast):
        report = LintAnalyzer().analyze(nested_ast)
        symbols = {f.symbol for f in report.findings}

        # The outer program's unused item was always reported; the contained
        # program's own unused item and dead paragraph were not.
        assert "WS-OUTER-UNUSED" in symbols
        assert "WS-INNER-UNUSED" in symbols
        assert "INNER-DEAD-PARA" in symbols

    def test_each_rule_is_listed_once_however_many_units_ran_it(self, nested_ast):
        report = LintAnalyzer().analyze(nested_ast)

        assert len(report.rules_run) == len(set(report.rules_run))

    def test_linting_one_unit_reports_only_its_own_problems(self, nested_ast):
        inner = nested_ast.find_program_unit("INNERP")
        symbols = {f.symbol for f in LintAnalyzer().analyze(inner).findings}

        assert "WS-INNER-UNUSED" in symbols
        assert "WS-OUTER-UNUSED" not in symbols


class TestProgramSelectionCLI:
    def _run(self, capsys, *argv):
        with patch("sys.argv", ["cobol-parser", *argv]):
            main()
        return json.loads(capsys.readouterr().out)

    def test_default_reports_the_outermost_unit(self, capsys, nested_file):
        data = self._run(capsys, "dead-code", nested_file, "--compact")

        assert data["program_id"] == "OUTERP"
        assert data["dead_code"] == []

    def test_program_selects_a_contained_unit(self, capsys, nested_file):
        data = self._run(
            capsys, "dead-code", nested_file, "--compact", "--program", "INNERP"
        )

        assert data["program_id"] == "INNERP"
        assert [d["name"] for d in data["dead_code"]] == ["INNER-DEAD-PARA"]

    def test_the_report_names_every_unit_in_the_file(self, capsys, nested_file):
        data = self._run(
            capsys, "dead-code", nested_file, "--compact", "--program", "INNERP"
        )

        assert data["program_units"] == ["OUTERP", "INNERP"]

    def test_a_single_program_file_reports_no_unit_list(self, capsys, tmp_path):
        path = tmp_path / "SOLO.cbl"
        path.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. SOLO.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           GOBACK.\n"
        )
        data = self._run(capsys, "dead-code", str(path), "--compact")

        assert "program_units" not in data

    def test_an_unknown_program_name_fails_and_says_what_is_there(
        self, capsys, nested_file
    ):
        with patch(
            "sys.argv",
            ["cobol-parser", "dead-code", nested_file, "--program", "GHOST"],
        ):
            with pytest.raises(SystemExit):
                main()

        err = capsys.readouterr().err
        assert "GHOST" in err
        assert "OUTERP" in err and "INNERP" in err

    def test_lint_covers_every_unit_by_default(self, capsys, nested_file):
        data = self._run(capsys, "lint", nested_file, "--compact")
        symbols = {f["symbol"] for f in data["findings"]}

        assert {"WS-OUTER-UNUSED", "WS-INNER-UNUSED", "INNER-DEAD-PARA"} <= symbols

    def test_lint_program_narrows_to_one_unit(self, capsys, nested_file):
        data = self._run(
            capsys, "lint", nested_file, "--compact", "--program", "INNERP"
        )
        symbols = {f["symbol"] for f in data["findings"]}

        assert "WS-INNER-UNUSED" in symbols
        assert "WS-OUTER-UNUSED" not in symbols


class TestCopybookProvenanceCoversEveryUnit:
    """A contained program's copybook fields must grade as copybook fields.

    `lint` grades an unused DATA DIVISION item as *info* when it came from an
    expanded COPY and *warning* when the program declares it itself, by
    diffing the declared names of an expanded parse against an unexpanded
    one. That diff is program-scoped; once lint covered every unit, computing
    it for the outermost unit alone left a contained program's copybook
    fields out of the set, so they graded as the program's own.
    """

    COPYBOOK = """      * shared layout
       01  SHARED-REC.
           05  SHARED-UNUSED   PIC X(10).
"""

    SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTERP.
       PROCEDURE DIVISION.
       OUTER-MAIN.
           CALL "INNERP".
           GOBACK.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNERP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY SHARED.
       01  WS-INNER-OWN     PIC X.
       PROCEDURE DIVISION.
       INNER-MAIN.
           GOBACK.
       END PROGRAM INNERP.
       END PROGRAM OUTERP.
"""

    @pytest.fixture
    def library(self, tmp_path):
        (tmp_path / "SHARED.cpy").write_text(self.COPYBOOK)
        (tmp_path / "NESTED.cbl").write_text(self.SOURCE)
        return tmp_path

    def test_a_contained_program_copybook_field_grades_as_info(self, capsys, library):
        with patch(
            "sys.argv",
            [
                "cobol-parser",
                "lint",
                str(library / "NESTED.cbl"),
                "--copybook-path",
                str(library),
                "--compact",
            ],
        ):
            main()
        data = json.loads(capsys.readouterr().out)
        by_symbol = {
            f["symbol"]: f for f in data["findings"] if f["rule"] == "unused-variables"
        }

        # The copybook's own field: info. The contained program's own
        # declaration: warning. Both belong to the CONTAINED unit, which is
        # the whole point.
        assert by_symbol["SHARED-UNUSED"]["severity"] == "info"
        assert by_symbol["WS-INNER-OWN"]["severity"] == "warning"
