"""Tests for the `lint` CLI subcommand.

Covers:
- Registered in the argparse parser and in the legacy-syntax `_SUBCOMMANDS`
  set (without the latter, `main()`'s backward-compatibility shim mistakes
  "lint" for a filename and rewrites the call as `parse lint file.cbl`)
- JSON output: standard identification header plus the LintReport shape
- --format text: one compiler-style `file:line:column:` line per finding,
  caveats as notes, and a trailing summary
- --rule and --min-severity narrow what is reported
- --fail-on turns findings into exit code 3, and only at or above the given
  severity; without it findings never change the exit code
- A file that cannot be parsed still exits 1, so a gate can tell "this
  program has problems" (3) from "this run did not work" (1)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser.cli.parse import _SUBCOMMANDS, _build_parser, main

# One unused item, one lossy MOVE (warning), one illegal MOVE (error), one
# paragraph nothing performs -- enough to exercise every severity band.
PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LINTME.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COUNTER        PIC 9(4) VALUE ZERO.
       01  WS-NEVER-USED     PIC X(10).
       01  WS-NAME           PIC X(20).
       01  WS-ALPHA          PIC A(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-NAME TO WS-COUNTER
           MOVE WS-COUNTER TO WS-ALPHA
           PERFORM USED-PARA
           STOP RUN.
       USED-PARA.
           ADD 1 TO WS-COUNTER.
       ORPHAN-PARA.
           DISPLAY 'NEVER PERFORMED'.
"""


@pytest.fixture
def program(tmp_path: Path) -> str:
    path = tmp_path / "LINTME.cbl"
    path.write_text(PROGRAM, encoding="utf-8")
    return str(path)


def _run(*argv: str) -> None:
    with patch("sys.argv", ["cobol-parser", "lint", *argv]):
        main()


class TestSubcommandRegistered:
    def test_in_parser(self) -> None:
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["lint", "--help"])

    def test_in_legacy_subcommand_set(self) -> None:
        assert "lint" in _SUBCOMMANDS


class TestJsonOutput:
    def test_identification_and_report_shape(self, program: str, capsys) -> None:
        _run(program, "--compact")
        data = json.loads(capsys.readouterr().out)
        assert data["source_file"] == program
        assert data["program_id"] == "LINTME"
        assert set(data) >= {
            "findings",
            "rules_run",
            "failed_rules",
            "caveats",
            "summary",
        }

    def test_findings_carry_rule_severity_and_symbol(
        self, program: str, capsys
    ) -> None:
        _run(program, "--compact")
        data = json.loads(capsys.readouterr().out)
        by_symbol = {f["symbol"]: f for f in data["findings"]}
        assert by_symbol["WS-NEVER-USED"]["rule"] == "unused-variables"
        assert by_symbol["ORPHAN-PARA"]["rule"] == "dead-code"
        assert by_symbol["ORPHAN-PARA"]["severity"] == "warning"

    def test_summary_counts_match_the_findings_shown(
        self, program: str, capsys
    ) -> None:
        _run(program, "--compact", "--min-severity", "error")
        data = json.loads(capsys.readouterr().out)
        assert data["summary"]["total"] == len(data["findings"])
        assert data["summary"]["warning"] == 0
        assert {f["severity"] for f in data["findings"]} == {"error"}


class TestTextOutput:
    def test_one_compiler_style_line_per_finding(self, program: str, capsys) -> None:
        _run(program, "--format", "text")
        lines = capsys.readouterr().out.strip().splitlines()
        assert any(
            line.startswith(f"{program}:6:1: warning [unused-variables]")
            for line in lines
        )
        assert lines[-1].endswith("rule(s) ran)")

    def test_summary_line_counts_every_severity(self, program: str, capsys) -> None:
        _run(program, "--format", "text")
        summary = capsys.readouterr().out.strip().splitlines()[-1]
        assert summary.startswith("4 finding(s): 1 error, 3 warning, 0 info")

    def test_output_file(self, program: str, tmp_path: Path) -> None:
        out = tmp_path / "lint.txt"
        _run(program, "--format", "text", "-o", str(out))
        assert "[dead-code]" in out.read_text(encoding="utf-8")


class TestFiltering:
    def test_rule_narrows_the_run(self, program: str, capsys) -> None:
        _run(program, "--compact", "--rule", "dead-code")
        data = json.loads(capsys.readouterr().out)
        assert data["rules_run"] == ["dead-code"]
        assert {f["rule"] for f in data["findings"]} == {"dead-code"}

    def test_repeated_rule_flags_accumulate(self, program: str, capsys) -> None:
        _run(program, "--compact", "--rule", "dead-code", "--rule", "unused-variables")
        data = json.loads(capsys.readouterr().out)
        assert data["rules_run"] == ["dead-code", "unused-variables"]

    def test_unknown_rule_is_rejected_by_argparse(self, program: str) -> None:
        with pytest.raises(SystemExit) as excinfo:
            _run(program, "--rule", "not-a-rule")
        assert excinfo.value.code == 2

    def test_min_severity_drops_lower_findings(self, program: str, capsys) -> None:
        _run(program, "--compact", "--min-severity", "error")
        data = json.loads(capsys.readouterr().out)
        assert [f["severity"] for f in data["findings"]] == ["error"]


class TestExitCodes:
    def test_findings_alone_do_not_fail_the_run(self, program: str) -> None:
        _run(program, "--compact")  # no SystemExit

    def test_fail_on_error_exits_three(self, program: str) -> None:
        with pytest.raises(SystemExit) as excinfo:
            _run(program, "--compact", "--fail-on", "error")
        assert excinfo.value.code == 3

    def test_fail_on_error_ignores_warning_only_programs(self, program: str) -> None:
        # Only the dead-code rule runs, and it reports warnings -- below the
        # gate, so the run must still succeed.
        _run(program, "--compact", "--rule", "dead-code", "--fail-on", "error")

    def test_fail_on_warning_catches_the_same_program(self, program: str) -> None:
        with pytest.raises(SystemExit) as excinfo:
            _run(program, "--compact", "--rule", "dead-code", "--fail-on", "warning")
        assert excinfo.value.code == 3

    def test_fail_on_is_not_reached_by_filtered_out_findings(
        self, program: str
    ) -> None:
        # --min-severity error leaves only the illegal MOVE; a warning gate
        # sees that error and still fails, but a run whose findings were all
        # filtered away must not.
        _run(
            program,
            "--compact",
            "--rule",
            "dead-code",
            "--min-severity",
            "error",
            "--fail-on",
            "error",
        )

    def test_a_run_that_could_not_happen_exits_one_not_three(
        self, tmp_path: Path
    ) -> None:
        # The whole point of reserving 3 for findings: a CI gate must be able
        # to tell "this program has problems" from "lint never ran".
        with pytest.raises(SystemExit) as excinfo:
            _run(str(tmp_path / "NO-SUCH-FILE.cbl"), "--compact", "--fail-on", "error")
        assert excinfo.value.code == 1


class TestCaveats:
    def test_unchecked_move_operands_are_reported_as_a_note(
        self, tmp_path: Path, capsys
    ) -> None:
        path = tmp_path / "UNRESOLVED.cbl"
        path.write_text(
            PROGRAM.replace(
                "           MOVE WS-NAME TO WS-COUNTER",
                "           MOVE UNDECLARED-FIELD TO WS-COUNTER",
            ),
            encoding="utf-8",
        )
        _run(str(path), "--format", "text")
        assert "note: move-type-check skipped" in capsys.readouterr().out


class TestFailedRules:
    def test_a_raising_rule_is_reported_on_stderr_and_in_the_json(
        self, program: str, capsys
    ) -> None:
        from cobolparser.analysis.lint import LintAnalyzer

        with patch.object(LintAnalyzer, "_dead_code", side_effect=RuntimeError("boom")):
            _run(program, "--compact")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["failed_rules"] == [
            {"rule": "dead-code", "error": "RuntimeError: boom"}
        ]
        assert "lint rule dead-code did not run" in captured.err
