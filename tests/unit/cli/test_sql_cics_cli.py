"""Tests for the `sql-cics-check` subcommand and the `sql-cics-check` lint rule.

The analyzer's own behaviour is covered in
tests/unit/analysis/test_sql_cics_lint.py. What is pinned here is the two
surfaces a consumer actually reads: the subcommand's JSON, and the rule
appearing in `lint` with its severities carried across intact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cobolparser.analysis.lint import RULES, LintAnalyzer
from cobolparser.cli.parse import _build_parser, _cmd_sql_cics_check
from cobolparser.parser import parse_cobol

UNCHECKED_SQL = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ID   PIC X(6).
       01 WS-NAME PIC X(30).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
              SELECT NAME INTO :WS-NAME FROM CUST WHERE ID = :WS-ID
           END-EXEC
           EXEC CICS READ FILE('CUSTFILE') INTO(WS-NAME)
           END-EXEC
           GOBACK.
"""

CHECKED_SQL = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLOK.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ID   PIC X(6).
       01 WS-NAME PIC X(30).
       01 WS-RESP PIC S9(8) COMP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
              SELECT NAME INTO :WS-NAME FROM CUST WHERE ID = :WS-ID
           END-EXEC
           IF SQLCODE NOT = 0
              DISPLAY "SQL FAILED"
           END-IF
           EXEC CICS READ FILE('CUSTFILE') INTO(WS-NAME) RESP(WS-RESP)
           END-EXEC
           GOBACK.
"""


def _args(filepath: str, **kwargs: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "file": filepath,
        "compact": True,
        "free_form": False,
        "source_format": "auto",
        "dialect": "ibm-enterprise",
        "error_recovery": "collect-all",
        "copybook_path": [],
        "program": None,
        "define": [],
        "output": None,
        "profile": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _run(tmp_path: Path, source: str, capsys) -> dict:
    path = tmp_path / "PROG.cbl"
    path.write_text(source, encoding="utf-8")
    _cmd_sql_cics_check(_args(str(path)))
    return json.loads(capsys.readouterr().out)


class TestSubcommand:
    def test_it_is_a_known_subcommand(self):
        parsed = _build_parser().parse_args(["sql-cics-check", "prog.cbl"])

        assert parsed.func is _cmd_sql_cics_check

    def test_an_unchecked_sqlcode_and_a_bare_cics_read_are_both_flagged(
        self, tmp_path, capsys
    ):
        payload = _run(tmp_path, UNCHECKED_SQL, capsys)

        kinds = {v["kind"] for v in payload["violations"]}
        assert kinds == {"SQL_NO_SQLCODE_CHECK", "CICS_NO_RESP_HANDLING"}
        assert payload["sql_statements"] == 1
        assert payload["cics_statements"] == 1

    def test_a_message_names_both_the_failure_and_the_fix(self, tmp_path, capsys):
        payload = _run(tmp_path, UNCHECKED_SQL, capsys)

        cics = next(
            v for v in payload["violations"] if v["kind"] == "CICS_NO_RESP_HANDLING"
        )
        assert "abends the task" in cics["message"]
        assert "RESP" in cics["message"]

    def test_checking_the_status_suppresses_both_findings(self, tmp_path, capsys):
        # The negative case matters more than the positive one: a rule that
        # cannot be satisfied is a rule people turn off.
        payload = _run(tmp_path, CHECKED_SQL, capsys)

        assert payload["violations"] == []
        assert payload["worst_severity"] is None

    def test_the_gap_list_is_always_present(self, tmp_path, capsys):
        payload = _run(tmp_path, UNCHECKED_SQL, capsys)

        # A quiet report must be distinguishable from an unexamined one.
        assert "unchecked" in payload
        assert payload["unchecked_count"] == len(payload["unchecked"])


class TestLintRule:
    def test_sql_cics_is_a_registered_rule(self):
        assert "sql-cics-check" in RULES

    def test_the_rule_reports_the_same_findings_as_the_subcommand(self):
        result = parse_cobol(UNCHECKED_SQL, filename="PROG.cbl")
        assert result.ast is not None

        report = LintAnalyzer(["sql-cics-check"]).analyze(result.ast)

        kinds = {f.kind for f in report.findings}
        assert kinds == {"SQL_NO_SQLCODE_CHECK", "CICS_NO_RESP_HANDLING"}
        assert report.rules_run == ["sql-cics-check"]

    def test_severity_is_carried_across_from_the_analyzer(self):
        result = parse_cobol(UNCHECKED_SQL, filename="PROG.cbl")
        assert result.ast is not None

        report = LintAnalyzer(["sql-cics-check"]).analyze(result.ast)

        assert {f.severity for f in report.findings} == {"warning"}
        assert report.worst_severity() == "warning"

    def test_a_clean_program_produces_no_findings(self):
        result = parse_cobol(CHECKED_SQL, filename="PROG.cbl")
        assert result.ast is not None

        report = LintAnalyzer(["sql-cics-check"]).analyze(result.ast)

        assert report.findings == []
        assert "sql-cics-check" in report.rules_run

    def test_the_rule_runs_as_part_of_the_default_rule_set(self):
        result = parse_cobol(UNCHECKED_SQL, filename="PROG.cbl")
        assert result.ast is not None

        report = LintAnalyzer().analyze(result.ast)

        assert "sql-cics-check" in report.rules_run
        assert any(f.rule == "sql-cics-check" for f in report.findings)
